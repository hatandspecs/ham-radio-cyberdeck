"""Setting one mode on every HF band, a band at a time.

**Why this exists.** The deck changes bands by setting a frequency, and on
the FTX-1 that recalls nothing: mode is global as far as `FA` can see, which
is what made "set every HF band to Data-U" look impossible. It is not. `BS`
-- BAND SELECT in the CAT manual, set-only, the CAT equivalent of pressing a
band button -- recalls the band's stacking register, frequency and mode
together, and a mode set while that band is selected is remembered in it.

Measured on the radio 2026-11-23, with a dummy load attached and nothing
transmitting::

    BS003;  MD01;   ->  40 m, LSB
    BS005;  MD0C;   ->  20 m, DATA-U
    BS003;          ->  reads 7070700 and MD01

So per-band modes ARE reachable over CAT. They are reachable through `BS`
and not through frequency, and the deck had only ever used frequency.

**Why it is a state machine rather than a loop.** A band change takes about
2.4 seconds to read back; ten bands is better than half a minute, and the
deck's poll loop is single-threaded with no worker threads anywhere in it.
`tick()` is called from that loop and waits on deadlines rather than
sleeping. `tuner.py` is the same shape for the same reason, and this follows
it deliberately. See `Walk.tick` for the one place that can still block.
"""
import time

IDLE, RUNNING, DONE, FAILED = "idle", "running", "done", "failed"

# `BS` band codes from the FTX-1 CAT manual (BS + side + two digits), with
# one frequency inside each band beside them.
#
# **The frequency is not where the radio is put.** `BS` recalls whatever the
# band's own register holds, which is the entire point. It is carried here so
# the sideband rule has something to ask about when a band's register cannot
# be read back, and so the walk can name the band it is on.
BANDS = (
    ("00",  1_840_000, "160 m"),
    ("01",  3_573_000, "80 m"),
    ("02",  5_357_000, "60 m"),
    ("03",  7_074_000, "40 m"),
    ("04", 10_136_000, "30 m"),
    ("05", 14_074_000, "20 m"),
    ("06", 18_100_000, "17 m"),
    ("07", 21_074_000, "15 m"),
    ("08", 24_915_000, "12 m"),
    ("09", 28_074_000, "10 m"),
)

# Band codes a sideband mode is not set on. No SSB on 30 m at all, and 60 m
# is channelized with upper sideband only -- setting LSB/USB across those two
# would be setting a mode for an operating style neither band has. Data modes
# go on all ten.
NO_SSB = ("02", "04")

# Measured at 2.38 s to read back, so this is that with room. Shorter and the
# mode lands while the radio is still moving, which is the mistake that made
# the first probe of this conclude the opposite of the truth.
BAND_SETTLE_S = 3.0


def band_for(hz):
    """The `BS` code whose band contains `hz`, or "" for none of them.

    Edges from the band plan rather than from the table's spot frequencies:
    the walk has to put the operator back on the band they started on, and
    "near 14.074" is not the question -- "inside 20 m" is.
    """
    edges = (
        ("00",  1_800_000,  2_000_000),
        ("01",  3_500_000,  4_000_000),
        ("02",  5_250_000,  5_450_000),
        ("03",  7_000_000,  7_300_000),
        ("04", 10_100_000, 10_150_000),
        ("05", 14_000_000, 14_350_000),
        ("06", 18_068_000, 18_168_000),
        ("07", 21_000_000, 21_450_000),
        ("08", 24_890_000, 24_990_000),
        ("09", 28_000_000, 29_700_000),
    )
    for code, lo, hi in edges:
        if lo <= int(hz) <= hi:
            return code
    return ""


def bands_for(kind):
    """The bands a walk of this kind visits."""
    if kind == "ssb":
        return tuple(b for b in BANDS if b[0] not in NO_SSB)
    return BANDS


class Walk:
    """One mode onto every HF band, stepped from the deck's poll loop.

    `rig` needs `send_cat`, `frequency` and `set_frequency`. `set_mode_for`
    is called with the frequency the radio reports on each band and returns
    `(ok, mode_name)`; keeping it a callable leaves the sideband rule, the
    passband and the mode verification where they already live rather than
    duplicating them here.
    """

    def __init__(self, rig, kind, set_mode_for,
                 settle_s=BAND_SETTLE_S, clock=time.monotonic):
        self.rig = rig
        self.kind = kind
        self.set_mode_for = set_mode_for
        self.settle_s = float(settle_s)
        self.clock = clock
        self.bands = bands_for(kind)
        self.state = IDLE
        self.message = ""
        self.index = -1
        self.started_at_hz = 0
        self.start_band = ""
        self.set_ok = []
        self.failed = []
        self.mode_name = ""
        self._phase = ""
        self._next_at = 0.0

    # -- what the screen asks ----------------------------------------------
    @property
    def running(self):
        return self.state == RUNNING

    def progress(self):
        """`(done, total, label)` while running, else None."""
        if self.state != RUNNING:
            return None
        at = max(0, min(self.index, len(self.bands) - 1))
        label = self.bands[at][2] if self.bands else ""
        if self._phase in ("home", "restore"):
            label = "back to %s" % (self._band_label(self.start_band) or "where it was")
        return (len(self.set_ok) + len(self.failed), len(self.bands), label)

    def _band_label(self, code):
        for c, _hz, label in BANDS:
            if c == code:
                return label
        return ""

    # -- running it ---------------------------------------------------------
    def start(self):
        """Read where the operator is, then begin. False if it cannot.

        **The starting frequency is read, not assumed.** A walk ends on
        whichever band `BS` was last given, and an operator who sets the
        modes and goes back to a net would otherwise find the radio on a
        different band entirely. A radio that cannot be read reports 0 and
        nothing is restored, which is better than setting a frequency that
        was never in use -- the same call `tuner.start` makes.
        """
        if not self.bands:
            self.state, self.message = FAILED, "no bands to set"
            return False
        try:
            self.started_at_hz = int(self.rig.frequency() or 0)
        except Exception:                              # noqa: BLE001
            self.started_at_hz = 0
        self.start_band = band_for(self.started_at_hz) if self.started_at_hz else ""
        self.index = 0
        self.set_ok = []
        self.failed = []
        self.state = RUNNING
        self.message = ""
        self._phase = "select"
        self._next_at = 0.0
        return True

    def abort(self, why="stopped"):
        """Stop where it stands, and still put the operator back.

        Half the bands set and the radio parked on whichever one the abort
        landed in is the worst of both, so an abort runs the same homing the
        end of a walk does.
        """
        if self.state != RUNNING:
            return
        self.message = why
        self._phase = "home"
        self._next_at = 0.0

    def tick(self):
        """One step.

        **This method never sleeps; `set_mode_for` can.** The settling
        between bands is a deadline rather than a sleep, which is the whole
        point of the state machine -- but the callable handed in is
        `Deck._rig_set_mode`, which polls the radio for up to
        `RIG_MODE_SETTLE_S` before giving up on a mode. A mode that lands
        normally costs about a quarter second of that; a radio refusing the
        mode costs the full three seconds per band, and the panel is
        unresponsive for it. Tolerated rather than solved: the same call
        already blocks the same way from `_digi_claim_mode` and the WSPR
        preflight, and a radio refusing every mode is a bigger problem than
        a sluggish panel. The fix, if it is ever worth it, is to split the
        mode verification into phases of its own here.
        """
        if self.state != RUNNING:
            return
        now = self.clock()
        if now < self._next_at:
            return

        if self._phase == "select":
            code = self.bands[self.index][0]
            if not self._cat("BS0%s;" % code):
                self.state = FAILED
                self.message = "no rig control — is rigctld running?"
                return
            self._phase = "mode"
            self._next_at = now + self.settle_s
            return

        if self._phase == "mode":
            code, spot_hz, label = self.bands[self.index]
            # The radio's own answer, so the sideband rule asks about where
            # the band register actually left us rather than about a spot
            # frequency nobody is on. The table's frequency is the fallback,
            # and a band whose register cannot be read is still inside its
            # own band.
            try:
                hz = int(self.rig.frequency() or 0)
            except Exception:                          # noqa: BLE001
                hz = 0
            if band_for(hz) != code:
                hz = spot_hz
            ok, name = False, ""
            try:
                ok, name = self.set_mode_for(hz)
            except Exception:                          # noqa: BLE001
                ok, name = False, ""
            if name:
                self.mode_name = name
            (self.set_ok if ok else self.failed).append(label)
            self.index += 1
            if self.index >= len(self.bands):
                self._phase = "home"
                self._next_at = 0.0
            else:
                self._phase = "select"
                self._next_at = 0.0
            return

        if self._phase == "home":
            # Nothing read at the start means nothing to go back to, and a
            # guessed frequency would be worse than none.
            if not self.started_at_hz:
                self._finish()
                return
            if self.start_band:
                self._cat("BS0%s;" % self.start_band)
                self._phase = "restore"
                self._next_at = now + self.settle_s
            else:
                # Started outside the HF bands -- on 2 m, say. There is no
                # register to recall, so go straight back by frequency.
                self._phase = "restore"
                self._next_at = 0.0
            return

        if self._phase == "restore":
            # **The frequency is set even though `BS` just recalled one.**
            # The deck tunes with `set_frequency`, which does not touch the
            # band register, so the register very often holds a different
            # frequency than the one the operator was actually on.
            try:
                self.rig.set_frequency(self.started_at_hz)
            except Exception:                          # noqa: BLE001
                pass
            self._finish()
            return

    def _finish(self):
        self.state = DONE
        if self.failed and self.set_ok:
            self.message = "%s on %d bands; %s would not take it" % (
                self.mode_name or "the mode", len(self.set_ok),
                ", ".join(self.failed))
        elif self.failed:
            self.message = "no band would take %s" % (self.mode_name or "it")
            self.state = FAILED
        elif self.message:
            self.message = "%s — %s set on %d bands" % (
                self.message, self.mode_name or "the mode", len(self.set_ok))
        else:
            self.message = "%s set on %d bands" % (
                self.mode_name or "the mode", len(self.set_ok))

    def _cat(self, command):
        """Send one CAT string and say whether it went.

        **The return value is checked**, for the reason `tuner._cat` records:
        `send_cat` answers False when rigctld cannot be reached, and a walk
        that swallowed that would count ten bands up on the panel while
        nothing at all reached the radio.
        """
        try:
            return bool(self.rig.send_cat(command))
        except Exception:                              # noqa: BLE001
            return False
