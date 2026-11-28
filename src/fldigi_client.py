"""The XML-RPC boundary between the terminal and fldigi.

fldigi does the modem work and is never seen: it runs against a virtual X
server with no display attached (docs/platform_design.md §4.1). Everything the terminal
needs of it passes through the twenty-odd methods below, out of the 176 fldigi
exposes.

Two properties matter more than the API surface:

* **No call may block the interface.** Every request carries a timeout, and a
  dead fldigi surfaces as ``connected == False`` rather than as an exception
  reaching the keyboard loop. A terminal that freezes is worse than one that
  says what is missing (§12).
* **Received text is a stream, not a snapshot.** fldigi keeps an ever-growing
  RX buffer; ``poll_rx`` remembers how much of it has been read and returns
  only what is new.
"""

import socket
import time
import xmlrpc.client

DEFAULT_URL = "http://127.0.0.1:7362/"
DEFAULT_TIMEOUT = 2.0

# How hard `stop_transmit` tries before it admits the radio may still be
# keyed. Three rounds of (abort, clear, rx) with a read-back between them,
# which at a 0.15 s verify poll is under a second of the interface's time --
# acceptable for the one action whose whole job is to stop a transmitter.
STOP_TRIES = 3
STOP_VERIFY_S = 0.45
STOP_VERIFY_STEP_S = 0.15

# fldigi's inline control for "return to receive once the buffer has drained".
# Appending this rather than calling main.rx() is what lets an over finish
# sending instead of being cut off mid-word (§5.4).
RX_AFTER_BUFFER = "^r"


class _TimeoutTransport(xmlrpc.client.Transport):
    """xmlrpc.client has no timeout parameter; this supplies one."""

    def __init__(self, timeout):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


# Control characters removed from received text. A noisy channel, or one
# being decoded by a modem that is not listening for it, produces these; the
# screen cannot draw them and a NUL crashes `curses.addstr` outright.
_RX_STRIP = {i: None for i in range(32) if chr(i) not in "\n\r\t"}
_RX_STRIP[0x7f] = None


class FldigiError(Exception):
    pass


class Fldigi:
    """A connection to one fldigi instance.

    Every public method returns a usable value even when fldigi is unreachable,
    so callers can render a screen without wrapping each field in try/except.
    Whether the last call succeeded is in ``connected``.
    """

    def __init__(self, url=DEFAULT_URL, timeout=DEFAULT_TIMEOUT):
        self.url = url
        self.timeout = timeout
        self.connected = False
        self.last_error = ""
        self._rx_pos = 0
        self._proxy = None
        # The modem and carrier put aside while the decoder is parked. See
        # `park_decoder`.
        self._parked_modem = ""
        self._parked_carrier = 0
        self._null_modem = None
        self._connect()
        # Probe once, so `connected` describes reality from the moment the
        # object exists rather than from the first call a caller happens to
        # make. Without this the interface shows "no modem" for one poll
        # interval every time it starts.
        self.version()

    # -- plumbing ---------------------------------------------------------

    def _connect(self):
        self._proxy = xmlrpc.client.ServerProxy(
            self.url, transport=_TimeoutTransport(self.timeout), allow_none=True)

    def _call(self, name, *args, default=None):
        """One XML-RPC call. Never raises; records the failure instead."""
        try:
            method = self._proxy
            for part in name.split("."):
                method = getattr(method, part)
            result = method(*args)
            self.connected = True
            self.last_error = ""
            return result
        except (OSError, socket.timeout, xmlrpc.client.Error) as exc:
            self.connected = False
            self.last_error = f"{type(exc).__name__}: {exc}"
            # A fresh proxy on the next attempt: a socket that failed once
            # tends to keep failing, and reconnecting is free.
            self._connect()
            return default

    def version(self):
        return self._call("fldigi.name_version", default="")

    # -- received text ----------------------------------------------------

    def poll_rx(self):
        """New received characters since the last poll, as a string.

        fldigi returns the RX buffer as base64 (XML-RPC type '6'), so it
        arrives as xmlrpc.client.Binary and has to be decoded. Characters
        outside ASCII do occur on a noisy channel and must not crash the feed.
        """
        length = self._call("text.get_rx_length", default=None)
        if length is None:
            return ""
        if length < self._rx_pos:
            # The buffer was cleared underneath us; start again rather than
            # reading from a position that no longer exists.
            self._rx_pos = 0
        if length == self._rx_pos:
            return ""
        chunk = self._call("text.get_rx", self._rx_pos, length - self._rx_pos,
                           default=None)
        if chunk is None:
            return ""
        raw = chunk.data if isinstance(chunk, xmlrpc.client.Binary) else bytes(chunk)
        self._rx_pos = length
        text = raw.decode("utf-8", errors="replace")
        # **Control characters are stripped here, not at the screen.**
        # `errors="replace"` handles bytes that are not valid UTF-8; it does
        # nothing about bytes that are. NUL is valid UTF-8, decodes to
        # "\x00", and makes curses' `addstr` raise ValueError -- which took
        # the deck down on 2026-10-18 while the decoder was parked on the
        # NULL modem during an SSB session.
        #
        # Newline and tab are kept: the transcript is line-based and they
        # carry meaning. Everything else below space, and DEL, is noise from
        # a channel being decoded by a modem that is not listening for it.
        return text.translate(_RX_STRIP)

    def clear_rx(self):
        self._call("text.clear_rx")
        self._rx_pos = 0

    # -- transmitting -----------------------------------------------------

    def start_over(self, text):
        """Send the composed buffer and key the transmitter.

        Order matters: the text goes into fldigi's TX widget first, so that
        keying and sending are one action from the operator's point of view.

        **Keying is conditional on the text having landed, and that is the
        whole point.** `main.tx` used to go out unconditionally. `_call`
        swallows every error and builds a fresh proxy for the next attempt,
        so one timed-out `text.add_tx` followed by a successful `main.tx` put
        the radio on the air with an empty TX widget: carrier up, nothing
        modulated, and -- because nothing was draining -- no completion event
        to end the over. Reported from the panel 2026-11-24.

        Empty text is refused for the same reason rather than keying on a
        buffer with nothing in it.

        Returns whether the radio was asked to key, so the caller can tell
        the operator when it was not.
        """
        if not text:
            return False
        self._call("text.add_tx", text)
        if not self.connected:
            return False
        self._call("main.tx")
        return self.connected

    def send_more(self, text):
        """Append to what is already going out, mid-over."""
        if text:
            self._call("text.add_tx", text)

    def hand_back(self):
        """Finish the over: drop to receive once the buffer has drained.

        Returns whether fldigi actually took the instruction. This was
        fire-and-forget, and a failed call is the exact thing that leaves the
        radio keyed with the terminal showing receive: the mark never arrives,
        nothing unkeys, and no one is told.
        """
        self._call("text.add_tx", RX_AFTER_BUFFER)
        return self.connected

    def receive_now(self):
        """Unconditional return to receive, without waiting for the buffer.

        The escalation from hand_back(): where `^r` is a mark placed in a
        stream that may not be moving, this acts on the modem directly."""
        self._call("main.rx")
        return self.connected

    def tune(self):
        """Start fldigi's tune carrier. Returns whether the call went out.

        A steady carrier at 100% duty cycle, which is what setting a
        transmit drive against the radio's power meter needs: a varying
        envelope would have the operator comparing the loudest moment of
        one reading against the quietest of the next. It is also why PSK31
        then reads lower than the drive was set at -- PSK31's envelope
        drops to zero on every phase reversal, so its average runs 1 to
        3 dB under a steady tone.

        **Stop it with `stop_transmit`, not `abort`.** Tune is not a
        transmission with a buffer behind it, so `main.abort` has nothing
        to end and PTT stays asserted -- the 2026-11-24 stuck-transmitter
        case exactly. `stop_transmit` reads the state back and says whether
        the radio actually unkeyed.

        **This is not gated by fldigi's `rx_only`.** `main.tune` was
        observed to key the radio with receive-only set, which
        `docs/digimodes_design.md` §7 records as the reason that flag is
        set but never relied on. So every caller must ask the deck's own
        interlock first; `Deck._digi_tx_preflight` is the only gate there
        is.
        """
        self._call("main.tune")
        return self.connected

    def abort(self):
        """Drop the carrier now, and throw away what had not gone out yet.

        **`main.abort` alone leaves the TX widget holding the remainder.**
        `start_over` and `send_more` both `text.add_tx`, which APPENDS, so
        the next over went out behind whatever the aborted one had not
        reached -- the operator saw their new message sent after a fragment
        of the old one. Reported from the panel 2026-10-23.

        Clearing after the abort rather than before: the order that matters
        is the one that stops the transmitter first.

        **Prefer `stop_transmit`.** This is the first two thirds of it: it
        asks fldigi to stop and never checks that it did, which is how a
        transmitter stayed keyed through a dozen Ctrl-Cs on 2026-11-24. Kept
        because the order it establishes is tested and worth keeping, and
        because `stop_transmit` is built out of it.
        """
        self._call("main.abort")
        self._call("text.clear_tx")

    def stop_transmit(self, tries=STOP_TRIES):
        """Stop transmitting, then CONFIRM the radio has unkeyed.

        Returns `(stopped, detail)` -- `stopped` is True only when fldigi has
        been read back and said it is in receive. The caller is expected to
        treat False as "the transmitter may still be running" and say so:
        nothing else in the deck can tell.

        **Why this exists.** `abort()` sent `main.abort` and `text.clear_tx`
        and returned None, and nothing checked it. `main.abort` ends a
        transmission *in progress*; with an empty or stalled TX widget there
        is nothing for it to end, and PTT stayed asserted. The call that
        unconditionally returns the modem to receive is `main.rx` -- written
        here as `receive_now` and, until now, never called from anywhere in
        the deck. So the escalation is:

            main.abort      stop the transmission
            text.clear_tx   drop the tail, so the next over is its own
            main.rx         return to receive whether or not there was one
            main.get_trx_state   and then ASK, rather than assume

        and the whole thing repeats while fldigi still says it is keyed,
        because a single round that failed on a timeout should not be the
        last word on a live transmitter.
        """
        detail = "not asked"
        for attempt in range(max(1, tries)):
            self._call("main.abort")
            self._call("text.clear_tx")
            self._call("main.rx")
            if not self.connected:
                detail = f"fldigi did not answer ({self.last_error})"
                continue
            waited = 0.0
            while waited < STOP_VERIFY_S:
                state = str(self.trx_state()).upper()
                if state.startswith("R"):
                    return True, f"confirmed in receive after {attempt + 1}"
                if not self.connected:
                    break
                time.sleep(STOP_VERIFY_STEP_S)
                waited += STOP_VERIFY_STEP_S
            detail = f"fldigi still reports {str(self.trx_state()).strip()}"
        return False, detail

    def receive_only(self, on=True):
        """Inhibit transmit entirely (§9)."""
        self._call("main.rx_only" if on else "main.rx_tx")

    def clear_tx(self):
        self._call("text.clear_tx")

    def trx_state(self):
        return self._call("main.get_trx_state", default="?")

    def transmitting(self):
        return str(self.trx_state()).upper().startswith("T")

    # -- modem ------------------------------------------------------------

    def modem_names(self):
        return self._call("modem.get_names", default=[]) or []

    def modem(self):
        """The modem the OPERATOR is working in.

        While the decoder is parked this is the modem put aside, not the
        `NULL` actually loaded -- see `park_decoder`. Every caller wants the
        first answer: the panel shows what the operator chose, the mode picker
        marks it current, and the log records what a contact was made on.
        `modem_loaded` is the raw question, for the one place that asks it.
        """
        return self._parked_modem or self.modem_loaded()

    def modem_loaded(self):
        """The modem fldigi actually has loaded, parked or not."""
        return self._call("modem.get_name", default="?")

    def set_modem(self, name):
        """Load a modem, or change the one to come back to while parked.

        Applying it while parked would start the decoder the park exists to
        stop, and the next poll would park it again -- so the choice is
        recorded and takes effect when the radio comes back to a data mode.
        The caller is what tells the operator that; this only has to not
        contradict itself.
        """
        if self._parked_modem:
            self._parked_modem = str(name)
            return None
        return self._call("modem.set_by_name", name, default=None)

    # -- parking the decoder ----------------------------------------------
    #
    # fldigi decodes whatever is on its sound card whether or not the radio is
    # in a mode that could be carrying it. On a Pi 3A+ that is real work --
    # the DSP is the deck's largest continuous cost -- and it buys nothing
    # when the radio is in SSB or FM: anything decoded is noise, and transmit
    # is interlocked off anyway.
    #
    # fldigi has no "stop decoding" call. Loading the `NULL` modem is the
    # nearest thing and does the job, because NULL has no decoder to run.

    def park_decoder(self):
        """Stop decoding, remembering the modem and carrier to come back to.

        Returns True when the decoder is parked, so a caller can tell the
        operator. False when fldigi offers no `NULL` modem -- older builds and
        unusual ones -- in which case nothing is changed: a park that cannot
        be undone cleanly is worse than a decoder left running.
        """
        if self._parked_modem:
            return True
        if self._null_modem is None:
            names = [str(n) for n in (self.modem_names() or [])]
            self._null_modem = next(
                (n for n in names if n.upper() == "NULL"), "")
        if not self._null_modem:
            return False
        current = self.modem_loaded()
        if not current or current == "?" or current == self._null_modem:
            return False
        # The carrier goes with it. fldigi moves the carrier to the new
        # modem's own sweet spot when a modem is loaded, so coming back
        # without this would land the operator somewhere other than the
        # signal they had tuned onto -- the same trap `_set_mode` works
        # around when the operator changes modem deliberately.
        self._parked_carrier = self.carrier()
        self._parked_modem = current
        self._call("modem.set_by_name", self._null_modem)
        return True

    def unpark_decoder(self):
        """Load the remembered modem again. Returns its name, or "".

        Nothing happens, and "" comes back, when the decoder was not parked --
        so this is safe to call on every poll, which is how it is called.

        **The park is forgotten only once fldigi confirms the modem is back,
        and that ordering is the whole fix.** This used to clear
        `_parked_modem` BEFORE the `modem.set_by_name` it depends on. `_call`
        swallows every error, so a failed unpark left fldigi on `NULL`,
        returned the modem's name as though it had worked -- the deck said
        "rig back in a data mode, decoding PSK31 again" -- and, with the
        bookkeeping already cleared, never retried. From then on `modem()`
        reported `NULL`, `_digi_mode_ok` kept passing because it reads the
        RIG's mode and not the modem, and `Ctrl-T` keyed the radio into a
        modem with nothing to modulate.

        That is the 2026-11-24 stuck-transmitter report, from the bottom up.
        Reading the modem back costs one call per poll while parked, and only
        while parked.
        """
        name = self._parked_modem
        if not name:
            return ""
        self._call("modem.set_by_name", name)
        if not self.connected:
            return ""          # still parked; the next poll tries again
        back = str(self.modem_loaded() or "")
        if not back or back == "?" or back.upper() == "NULL":
            return ""          # fldigi did not take it; stay parked
        self._parked_modem = ""
        if self._parked_carrier:
            self._call("modem.set_carrier", int(self._parked_carrier))
        self._parked_carrier = 0
        return back

    def modem_is_null(self):
        """Whether fldigi actually has the NULL modem loaded.

        The question `modem()` deliberately cannot answer: it reports what the
        operator chose, which while parked is the modem put aside rather than
        the `NULL` in use. Transmitting into NULL keys the radio and
        modulates nothing, so the paths that key ask this directly.
        """
        name = str(self.modem_loaded() or "")
        return bool(name) and name.upper() == "NULL"

    def force_unpark(self, fallback=""):
        """Get a real modem loaded, whatever the park bookkeeping says.

        The reset path. `unpark_decoder` is careful and conditional by
        design; this is for the operator who has decided the digimode side is
        wrong and wants it put back. Tries the parked modem, then `fallback`,
        then the first modem fldigi offers that is not NULL. Returns the name
        loaded, or "".
        """
        wanted = [n for n in (self._parked_modem, fallback) if n]
        if not wanted or self.modem_is_null():
            for n in (self.modem_names() or []):
                if str(n).upper() != "NULL":
                    wanted.append(str(n))
                    break
        for name in wanted:
            self._call("modem.set_by_name", name)
            if not self.connected:
                continue
            back = str(self.modem_loaded() or "")
            if back and back != "?" and back.upper() != "NULL":
                self._parked_modem = ""
                if self._parked_carrier:
                    self._call("modem.set_carrier", int(self._parked_carrier))
                self._parked_carrier = 0
                return back
        return ""

    @property
    def decoder_parked(self):
        return bool(self._parked_modem)

    def carrier(self):
        return self._call("modem.get_carrier", default=0)

    def set_carrier(self, hz):
        return self._call("modem.set_carrier", int(hz), default=None)

    def nudge_carrier(self, delta):
        return self._call("modem.inc_carrier", int(delta), default=None)

    def search_up(self):
        self._call("modem.search_up")

    def search_down(self):
        self._call("modem.search_down")

    def quality(self):
        q = self._call("modem.get_quality", default=0.0)
        try:
            return float(q)
        except (TypeError, ValueError):
            return 0.0

    def bandwidth(self):
        """Modem bandwidth in Hz, or 0 where fldigi does not report one.

        Olivia is the notable case: it answers 0 here and keeps its real
        bandwidth behind modem.olivia.get_bandwidth. Callers display what they
        get rather than inventing a number.
        """
        return self._call("modem.get_bandwidth", default=0)

    # -- receiver settings ------------------------------------------------

    def afc(self):
        return bool(self._call("main.get_afc", default=False))

    def set_afc(self, on):
        self._call("main.set_afc", bool(on))

    def squelch(self):
        return bool(self._call("main.get_squelch", default=False))

    def set_squelch(self, on):
        self._call("main.set_squelch", bool(on))

    def squelch_level(self):
        return self._call("main.get_squelch_level", default=0.0)

    def set_squelch_level(self, level):
        self._call("main.set_squelch_level", float(level))

    def rsid(self):
        """Act on a Reed-Solomon Identifier received from another station.

        RSID is the closest fldigi has to automatic mode detection: a station
        sends a short identifier burst ahead of its over encoding the mode and
        the audio frequency, and a receiver with this on switches to match. It
        is not blind detection — nothing is deduced from the signal itself, so
        a station that does not send one is not followed.
        """
        return bool(self._call("main.get_rsid", default=False))

    def set_rsid(self, on):
        self._call("main.set_rsid", bool(on))

    def reverse(self):
        """Mark/space sense. RTTY on the air is conventionally lower sideband;
        running AFSK through the radio's DATA-U path is upper, so the tones
        arrive swapped and decode as steady, word-free garbage until this is
        flipped."""
        return bool(self._call("main.get_reverse", default=False))

    def set_reverse(self, on):
        self._call("main.set_reverse", bool(on))

    def txid(self):
        """Send an identifier ahead of our own overs, so others can follow us.

        Separate from rsid in fldigi, and worth having on for the same reason
        one leaves RSID on: a deck that relies on other people's identifiers
        while sending none is taking without giving.
        """
        return bool(self._call("main.get_txid", default=False))

    def set_txid(self, on):
        self._call("main.set_txid", bool(on))

    # -- readouts ---------------------------------------------------------

    def signal_to_noise(self):
        return self._call("main.get_status1", default="")

    def imd(self):
        return self._call("main.get_status2", default="")

    # -- rig --------------------------------------------------------------
    #
    # fldigi exposes two rig families and they point in opposite directions:
    #
    #   rig.*   is how an EXTERNAL rig-control program (flrig) tells fldigi
    #           what the radio is doing. rig.set_frequency updates fldigi's
    #           own display and commands nothing.
    #   main.*  goes the other way: main.set_frequency and main.set_rig_mode
    #           command the radio through whatever rig control fldigi holds,
    #           which here is rigctld over Hamlib NET.
    #
    # Reads work either way, which is what made this hard to spot: the deck
    # showed the right frequency while none of its setters reached the radio.

    def frequency(self):
        f = self._call("main.get_frequency", default=0.0)
        try:
            return float(f)
        except (TypeError, ValueError):
            return 0.0

    def set_frequency(self, hz):
        return self._call("main.set_frequency", float(hz), default=None)

    def rig_mode(self):
        return self._call("main.get_rig_mode", default="")

    def rig_modes(self):
        """The mode names this rig accepts, as Hamlib reports them."""
        return self._call("main.get_rig_modes", default=[]) or []

    def set_rig_mode(self, name):
        return self._call("main.set_rig_mode", str(name), default=None)
