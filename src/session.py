"""The conversation: transcript, compose buffer, and the shape of an over.

Kept free of curses so the behavior that matters can be tested without a
terminal. The interface in cyberdeck.py renders what is here and does nothing
else with it.

The transmit model is the over-based one settled in docs/digimodes_design.md §5.4, which
is fldigi's norm and HF's norm and is not what intuition suggests:

    compose while receiving  ->  Ctrl-T starts the over  ->  Ctrl-Y hands back

Enter inserts a newline into the buffer. It does not transmit. Sending a line
at a time would key the rig dozens of times per QSO, and every turnaround
costs seconds of settling at both ends.

Once an over is running, characters go out as they are typed. That live
typing, corrections included, is what makes this keyboard-to-keyboard rather
than messaging.
"""

import time
from collections import deque

RX = "rx"      # receiving; the buffer accumulates and nothing is transmitted
TX = "tx"      # an over is running; typing goes straight out


class Entry:
    """One run of text from one station, possibly still being added to."""

    __slots__ = ("when", "who", "text", "closed")

    def __init__(self, who, text="", when=None):
        self.when = when if when is not None else time.time()
        self.who = who
        self.text = text
        self.closed = False

    def __repr__(self):
        return f"<{self.who}: {self.text!r}{' ' if self.closed else ' open'}>"


class Session:
    def __init__(self, callsign="", scrollback=2000, tx_timeout=180,
                 clock=time.monotonic):
        self.callsign = callsign or "LOCAL"
        self.entries = deque(maxlen=scrollback)
        self.compose = ""
        self.cursor = 0
        self.history = []          # previously sent overs, newest first
        self._recall = None        # position while browsing history
        self._undo = []            # (compose, cursor) before each insert
        self._pending = ""         # what was being typed before browsing
        self.state = RX
        self.tx_timeout = tx_timeout
        self._clock = clock
        self._tx_started = None
        self.notices = deque(maxlen=50)
        # Transmit inhibit. Enforced here rather than by asking fldigi to
        # enforce it: fldigi's main.rx_only was observed not to stop
        # main.tune, and a safety property that depends on another process
        # behaving as documented is not a safety property. Nothing downstream
        # is asked to key unless this is False.
        self.inhibited = False

    # -- transcript -------------------------------------------------------

    def _append(self, who, text):
        """Add text attributed to `who`, continuing an open entry from the
        same station rather than starting a new one for every character."""
        if not text:
            return
        for i, part in enumerate(text.split("\n")):
            if i:
                # A newline closes whatever was open.
                if self.entries and not self.entries[-1].closed:
                    self.entries[-1].closed = True
            if not part:
                continue
            last = self.entries[-1] if self.entries else None
            if last is not None and not last.closed and last.who == who:
                last.text += part
            else:
                self.entries.append(Entry(who, part))

    def receive(self, text):
        """Text decoded off the air. Attributed to the far end, which is not
        identified — the transcript shows who is not this station, and the
        callsign of the other operator is whatever they type."""
        self._append("RX", text)

    @property
    def last_note(self):
        """The most recent marker, for screens that do not show the transcript.

        The tuning screen reports what a search did — found a signal, found
        nothing — and those notes were invisible there, because notes live in
        the transcript and that screen hides it. The one screen where a tuning
        message matters was the one screen that could not show it.
        """
        return self.notices[-1] if self.notices else ""

    def note(self, text):
        """A marker in the transcript: a mode change, a warning. Closed
        immediately, so nothing else joins it."""
        entry = Entry("--", text)
        entry.closed = True
        self.entries.append(entry)
        self.notices.append(text)

    # -- composing --------------------------------------------------------

    def type(self, char):
        """A printable character or a newline from the keyboard.

        Returns the text that should go on the air right now: everything while
        an over is running, nothing while receiving.

        While receiving, the character is inserted at the cursor, so the line
        can be edited like any other terminal input. Mid-over there is no
        cursor to speak of — characters go out as they are typed and cannot be
        recalled — so it appends and sends.
        """
        if self.state == TX:
            out, self.compose, self.cursor = self.compose + char, "", 0
            self._append(self.callsign, out)
            return out
        self.compose = self.compose[:self.cursor] + char + self.compose[self.cursor:]
        self.cursor += len(char)
        return ""

    def backspace(self):
        """Correct the composed buffer, deleting before the cursor.

        Only meaningful while receiving. Mid-over the characters have already
        been sent, and the far end has seen them — which is how RTTY chat has
        always worked, and is not a bug to be hidden.
        """
        if self.state == RX and self.cursor > 0:
            self.compose = (self.compose[:self.cursor - 1]
                            + self.compose[self.cursor:])
            self.cursor -= 1
            return True
        return False

    # -- line editing ------------------------------------------------------

    def insert(self, text):
        """Put text in at the cursor, as a message memory does.

        Mid-over there is no cursor and nothing can be taken back: the text is
        appended and sent, exactly as typing does. While receiving it goes in
        at the cursor and the previous state is remembered, so undo() can take
        it back out.
        """
        if not text:
            return ""
        if self.state == TX:
            out, self.compose, self.cursor = self.compose + text, "", 0
            self._append(self.callsign, out)
            return out
        self._undo.append((self.compose, self.cursor))
        del self._undo[:-20]
        self.compose = self.compose[:self.cursor] + text + self.compose[self.cursor:]
        self.cursor += len(text)
        return ""

    def undo(self):
        """Take back the last insert. Only meaningful while receiving — once
        an over is running the far end has already seen it."""
        if self.state != RX or not self._undo:
            return False
        self.compose, self.cursor = self._undo.pop()
        return True

    def move(self, delta):
        """Move the cursor within the composed line. True if it moved."""
        if self.state != RX:
            return False
        was = self.cursor
        self.cursor = max(0, min(len(self.compose), self.cursor + delta))
        return self.cursor != was

    def home(self):
        self.cursor = 0

    def end(self):
        self.cursor = len(self.compose)

    def recall(self, delta):
        """Step through previously sent overs, newest first.

        delta -1 goes back in time, +1 forward. Stepping forward past the most
        recent entry restores whatever was being typed before the first
        recall, so browsing the history and coming back costs nothing.
        """
        if self.state != RX or not self.history:
            return False
        # history[0] is the most recent, so going back in time means moving
        # UP the list by index. _recall is the entry currently shown, or None
        # while the draft is being edited.
        if self._recall is None:
            if delta > 0:
                return False               # already at the newest: the draft
            self._pending = self.compose
            at = 0
        else:
            at = self._recall - delta      # delta -1 (older) -> index + 1

        if at < 0:                         # forward past the newest entry
            self._recall = None
            self.compose = self._pending
            self.cursor = len(self.compose)
            return True
        at = min(at, len(self.history) - 1)
        self._recall = at
        self.compose = self.history[at]
        self.cursor = len(self.compose)
        return True

    # -- the over ---------------------------------------------------------

    def inhibit(self, on=True):
        """Refuse to transmit at all. Survives a hand-back and an abort;
        only an explicit call clears it."""
        self.inhibited = bool(on)
        self.note("transmit inhibited" if self.inhibited else "transmit enabled")
        return self.inhibited

    def start_over(self):
        """Begin transmitting. Returns the buffered text to send, or None if
        no over was started — already transmitting, or inhibited."""
        if self.inhibited:
            self.note("transmit inhibited — nothing sent")
            return None
        if self.state == TX:
            # Say so. This returned None in silence, which is indistinguishable
            # from a dead key — and it is reachable whenever the session's idea
            # of transmitting has drifted from fldigi's, so the operator gets a
            # Ctrl-T that does nothing and no reason why. See Deck.poll(),
            # which reconciles the drift this note reports.
            self.note("already transmitting — Ctrl-Y to hand back, Ctrl-C to abort")
            return None
        text, self.compose, self.cursor = self.compose, "", 0
        self._recall = None
        if text.strip():
            self.history.insert(0, text.rstrip("\n"))
            del self.history[40:]      # a session's worth, not a logbook
        self.state = TX
        self._tx_started = self._clock()
        # This is the over as intended. What fldigi actually puts on the air
        # is shown separately and transiently while sending — see the
        # transmit-progress note in docs/digimodes_design.md §5.5.
        if text:
            self._append(self.callsign, text)
        return text

    def hand_back(self):
        """End the over. fldigi drops to receive once the buffer drains.

        The transmit timer is deliberately left running. Handing back does not
        unkey the radio — it appends fldigi's "receive after the buffer" mark,
        and the radio stays keyed until everything already composed has gone
        out, which at 31 baud can be minutes. Clearing the timer here, as this
        did, disarmed the only software backstop for exactly the window in
        which the transmitter is running unattended. It is cleared when fldigi
        confirms it has stopped: see confirm_receive().
        """
        if self.state != TX:
            return False
        self.state = RX
        if self.entries and not self.entries[-1].closed:
            self.entries[-1].closed = True
        return True

    def confirm_receive(self):
        """fldigi has actually stopped transmitting. Disarms the timer.

        The only thing entitled to do so: the operator's keys say what should
        happen, and the radio says what did."""
        self._tx_started = None

    def resync_to_receive(self):
        """Drop to receive because fldigi is not transmitting after all.

        The session's state is set by the operator's keys and fldigi's is set
        by the radio, and they can part company: a start_over() whose XML-RPC
        call failed leaves this side transmitting and the radio idle, and from
        then on every Ctrl-T is refused for a reason the operator cannot see.
        Distinct from abort() because nothing is being stopped — the discovery
        is that nothing was running.
        """
        if self.state != TX:
            return False
        self.state = RX
        self._tx_started = None
        if self.entries and not self.entries[-1].closed:
            self.entries[-1].closed = True
        return True

    def abort(self):
        """Stop transmitting immediately, mid-word if necessary."""
        was = self.state == TX or self._tx_started is not None
        self.state = RX
        self._tx_started = None
        if was:
            self.note("transmit aborted")
        return was

    def tx_elapsed(self):
        if self._tx_started is None:
            return 0.0
        return self._clock() - self._tx_started

    def tx_timed_out(self):
        """True when an over has run past TX_TIMEOUT and must be stopped.

        The radio's own timer is the real backstop; this is the software one,
        and it exists because a host that hangs holds PTT asserted.
        """
        # Armed whenever the radio may be keyed, which is not the same as
        # the operator still composing: after hand_back() the session is in RX
        # and the transmitter is still draining. Keying on state here let a
        # stuck transmission run with nothing watching it.
        if self._tx_started is None or not self.tx_timeout:
            return False
        return self.tx_elapsed() >= self.tx_timeout

    # -- what the interface shows -----------------------------------------

    def buffer_indicator(self):
        if self.state == TX:
            return "[TX]"
        return f"[RX {len(self.compose)}]" if self.compose else "[RX]"
