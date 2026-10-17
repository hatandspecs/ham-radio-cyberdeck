"""When WSPR captures, when it beacons, and when it stops. Pure.

No clock of its own: the time is handed in. That is what makes a two-hour
band-hopping beacon session testable in milliseconds, and it is the same
reason `session.py` keeps no clock -- the behavior that matters here is
entirely about what happens at 23:58, at midnight, and at the moment a
time-out expires, and none of those can be waited for.

**The slot is two minutes and starts on the even minute.** WSPR puts its
transmission one second after the even minute and runs for 110.6 s, so a
capture covers the window from the even minute and the next slot begins 120 s
later whatever happened in this one.

See `docs/wspr_design.md` §6a for the four toggles and §7 for the time-out.
"""

SLOT_SECONDS = 120
# WSPR transmits from one second after the even minute for 110.6 s. The
# capture is the whole 114 s window `wsprd` expects, which starts at the
# even minute -- a second before the transmission does.
CAPTURE_SECONDS = 114
TX_OFFSET_SECONDS = 1.0
TX_SECONDS = 110.6

# What the operator has switched on. Four independent toggles, not a run
# button -- every composition is a defined state, and the one that looks odd
# is the useful one: `wspr` on with `decode` off is the receive level check.
IDLE = "idle"
LISTENING = "listening"        # capturing, not decoding
RECEIVING = "receiving"        # capturing and decoding
BEACONING = "beaconing"        # capturing, decoding, and transmitting


def slot_start(now):
    """The epoch second the current slot began on."""
    return int(now) - (int(now) % SLOT_SECONDS)


def slot_index(now):
    """Which two-minute slot of the UTC day this is. Counts from midnight.

    Used for band hopping and for choosing transmit slots, so that two decks
    started minutes apart agree about which slot is which -- a counter
    private to each process would not.
    """
    return (int(now) % 86400) // SLOT_SECONDS


def in_capture(now):
    """Whether the current moment is inside the 114 s capture window."""
    return (int(now) - slot_start(now)) < CAPTURE_SECONDS


def seconds_to_next_slot(now):
    """How long until the next even minute. Never negative, never over 120."""
    return SLOT_SECONDS - ((float(now) - slot_start(now)) % SLOT_SECONDS)


def band_for_slot(bands, now):
    """Which band this slot uses, hopping through `bands` in order.

    One band selected means no hopping, which is the common case and is not
    a special case in the code: a one-element cycle is a constant.

    Keyed on the slot index rather than on a counter the process keeps, so a
    deck restarted mid-session lands back on the band the schedule says
    rather than starting the rotation again.
    """
    chosen = [b for b in (bands or []) if b]
    if not chosen:
        return ""
    return chosen[slot_index(now) % len(chosen)]


def transmits_in_slot(now, percent, seed=0):
    """Whether this slot beacons, given a transmit percentage.

    Deterministic for a given slot and seed, so the answer does not change
    when the question is asked twice in one slot -- which it is, once to
    decide and once to display "next: transmit". A coin flipped on each call
    would show one thing and do another.

    Pseudo-random rather than every Nth slot, because a regular pattern makes
    two stations on the same percentage collide in the same slots forever.
    The seed is this station's own, so two decks do not share a sequence.
    """
    try:
        percent = int(percent)
    except (TypeError, ValueError):
        return False
    if percent <= 0:
        return False
    if percent >= 100:
        return True
    # A cheap, stable hash of (slot, seed). Python's `hash` is salted per
    # process and would give a different schedule on every restart.
    n = (slot_index(now) * 2654435761 + int(seed) * 40503) & 0xffffffff
    return (n % 100) < percent


class Schedule:
    """The run state of a WSPR session, advanced by being told the time.

    Holds no clock, no subprocess and no audio. `tick(now)` returns the
    actions a caller should take, so the caller owns every side effect and
    this owns every decision.
    """

    def __init__(self, bands=(), tx_percent=0, timeout_minutes=60, seed=0):
        self.bands = [b for b in bands if b]
        self.tx_percent = tx_percent
        self.timeout_minutes = timeout_minutes
        self.seed = seed
        self.wspr = False
        self.decode = True
        self.transmit = False
        self.tx_next = False
        self.started_at = None
        self._slot = None
        # The slot the one-shot armed, so it can be cleared when that slot
        # has passed rather than when the next tick happens to arrive.
        self._tx_next_slot = None
        # The slot a transmission last went out in, so the next one can be
        # kept clear. None until something has been sent.
        self._last_tx_slot = None

    # -- state ------------------------------------------------------------

    @property
    def state(self):
        if not self.wspr:
            return IDLE
        if not self.decode:
            return LISTENING
        return BEACONING if self.transmit else RECEIVING

    def start(self, now):
        """Begin a session. The time-out counts from here."""
        self.wspr = True
        self.started_at = float(now)
        self._slot = None

    def stop(self):
        """End it. Everything the caller must undo is the caller's to undo."""
        self.wspr = False
        self.transmit = False
        self.tx_next = False
        self.started_at = None
        self._slot = None
        self._tx_next_slot = None
        self._last_tx_slot = None

    def set_transmit(self, on, now):
        """Arm or disarm transmit. **Arming restarts the time-out.**

        Through a method rather than by assigning `transmit`, because the
        timer has to be restarted with it: an operator re-arming after a
        time-out has just said "keep going", and that is what the clock is
        measuring. Disarming also spends the one-shot, which would otherwise
        fire on the next slot after transmit was switched off.
        """
        self.transmit = bool(on)
        if self.transmit:
            self.started_at = float(now)
        else:
            self.tx_next = False
            self._tx_next_slot = None

    def arm_tx_next(self, now):
        """Beacon on the next slot, whatever the percentage says."""
        self.tx_next = True
        self._tx_next_slot = slot_index(now) + 1

    # -- the time-out -----------------------------------------------------

    def timeout_remaining(self, now):
        """Seconds left before the time-out stops the session, or None.

        None when nothing is running or the time-out is off. A time-out of
        zero means off -- a session that stops immediately is not a thing
        anyone wants, and it is the natural reading of "no limit".
        """
        if self.started_at is None or not self.timeout_minutes:
            return None
        spent = float(now) - self.started_at
        return max(0.0, self.timeout_minutes * 60 - spent)

    def timed_out(self, now):
        remaining = self.timeout_remaining(now)
        return remaining is not None and remaining <= 0

    # -- the decision -----------------------------------------------------

    def will_transmit(self, now):
        """Whether the slot containing `now` beacons.

        The one-shot wins over the percentage, and the percentage only
        applies when transmit is switched on at all. Asked for the display as
        well as for the decision, so it must not change between the two.
        """
        if not self.wspr or not self.transmit:
            return False
        here = slot_index(now)
        # **The one-shot wins over everything, including the guard below.**
        # It is a deliberate act: an operator who asks for the next slot has
        # asked for it.
        if self.tx_next and self._tx_next_slot == here:
            return True
        # **Never two slots in a row from the RANDOM choice.** Observed on
        # the air: `tx next` fired, and the percentage independently chose
        # the slot straight after it, so the deck beaconed twice running --
        # two transmissions back to back, no listening between them, and a
        # receiver hearing the same station twice for no gain.
        #
        # Only the random choice is suppressed, which is what makes this a
        # guard rather than a cap: the one-shot above still fires.
        if self._last_tx_slot is not None and here == self._last_tx_slot + 1:
            return False
        return transmits_in_slot(now, self.tx_percent, self.seed)

    def tick(self, now):
        """What to do at `now`. Returns a list of actions, possibly empty.

        Actions are `("stop", reason)`, `("tune", band)`,
        `("capture", band)` and `("transmit", band)`. The caller performs
        them; nothing here touches a radio, a file or a process.

        A new slot is recognised by its index changing, not by arithmetic on
        the previous call -- so a tick that arrives late, or twice, or after
        the process was asleep, still produces exactly one slot's worth of
        actions.
        """
        if not self.wspr:
            return []
        if self.timed_out(now):
            # **The time-out disarms TRANSMIT. It does not end the session.**
            # The timer exists for an unattended transmitter, and receiving
            # carries no on-air risk -- so stopping everything gave up the
            # part that was still doing something useful, and handed the
            # codec back and restarted fldigi, which is a lot of machinery
            # to fire because a clock ran out.
            #
            # `started_at` is cleared, so `timeout_remaining` answers None
            # and this cannot fire twice. Arming transmit again restarts it,
            # which makes the guarantee "no transmitting for longer than
            # this without being told again".
            self.transmit = False
            self.tx_next = False
            self._tx_next_slot = None
            self.started_at = None
            return [("tx_off", "time-out")]

        here = slot_index(now)
        if here == self._slot:
            return []
        # Only at the top of a slot. A tick arriving 40 s in has missed the
        # window, and starting a capture then would hand `wsprd` a truncated
        # file that decodes nothing -- worse than skipping the slot, because
        # it looks like a dead band.
        if (int(now) - slot_start(now)) > 2:
            self._slot = here
            return []
        self._slot = here

        band = band_for_slot(self.bands, now) or (self.bands[0]
                                                  if self.bands else "")
        actions = []
        if band:
            actions.append(("tune", band))
        if self.will_transmit(now):
            actions.append(("transmit", band))
            # Recorded here, where the transmission is actually handed to
            # the caller -- not in `will_transmit`, which the display calls
            # every draw and which must stay free of side effects.
            self._last_tx_slot = here
            # The one-shot is spent. Cleared on the slot it fired in rather
            # than on the next tick, so a tick that never comes does not
            # leave it armed for an hour.
            if self.tx_next and self._tx_next_slot == here:
                self.tx_next = False
                self._tx_next_slot = None
        else:
            actions.append(("capture", band))
        return actions
