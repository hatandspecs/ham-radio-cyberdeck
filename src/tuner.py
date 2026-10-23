"""The antenna tuner sweep: what it visits, and how it is driven.

A sweep steps the VFO across chosen band segments and triggers the tuner at
each stop, so one run fills the tuner's memories for a new antenna. The
alternative is working the VFO and the tune button by hand for an hour.

**Every step is a real transmission and the deck cannot hear the band.** That
is why `^X` aborts, why the abort takes effect before the next key-down rather
than at the end of a segment, and why nothing here starts a run without being
asked twice.

Three things measured on a real FTX-1 Optima and a mAT-30 by the
`ftx1-tuner-sweep` project, all of which shape this:

**The radio cannot report that an external tuner has finished.** The `RI`
status bit never clears for a third-party tuner, because the trigger line is
one way. There is nothing to poll. Each frequency is held for a fixed dwell.

**`AC103` is the trigger** -- antenna tuner, external, start tuning -- which
is the front-panel TUNER button held for two seconds.

**The tuner is left in circuit however a run ends**, finished or aborted or
interrupted. An early version of that project left it bypassed, which is
worse than never having run at all.
"""
import time

# Yaesu CAT, from the FTX-1 CAT Operation Reference Manual (2508-C).
CAT_TUNE_START = "AC103;"      # external tuner, start tuning
CAT_TUNE_IN = "AC101;"         # tuner in circuit, not tuning
CAT_TUNE_OFF = "AC100;"        # tuner bypassed

# Held after setting the VFO, before triggering the tuner, so the radio has
# landed on the frequency before it is asked to match there.
SETTLE_S = 0.3

# A dwell shorter than this is shorter than any tuner's own cycle and
# guarantees memories written from an unconverged match -- silently, since
# there is no completion to check. The floor is a guard against a fat finger
# on the cycling key, not a judgment about any particular tuner.
MIN_DWELL_S = 1.0
MAX_DWELL_S = 15.0

IDLE, RUNNING, DONE, ABORTED, FAILED = "idle", "running", "done", "aborted", "failed"


def clamp_dwell(seconds):
    """Keep a configured dwell inside what can actually work."""
    try:
        v = float(seconds)
    except (TypeError, ValueError):
        return 5.0
    return max(MIN_DWELL_S, min(MAX_DWELL_S, v))


class Sweep:
    """One run, advanced a step at a time from the deck's poll loop.

    Nothing here blocks. `tick` returns promptly whether or not the dwell has
    elapsed, because the key that aborts has to be read while the sweep is
    waiting -- a sweep that slept through its dwell could not be stopped
    during the only part of it that matters.
    """

    def __init__(self, frequencies, rig, dwell_s=5.0, settle_s=SETTLE_S,
                 now=time.monotonic):
        self.freqs = list(frequencies)
        # The operator's frequency, read at `start` and restored by `finish`.
        self.started_at_hz = 0
        self.rig = rig
        self.dwell_s = clamp_dwell(dwell_s)
        self.settle_s = settle_s
        self._now = now
        self.index = -1
        self.state = IDLE
        self.message = ""
        self._next_at = 0.0
        self._phase = "step"

    # -- what the screen reads ---------------------------------------------
    @property
    def total(self):
        return len(self.freqs)

    @property
    def done_count(self):
        return max(0, self.index + (0 if self.state == RUNNING else 1))

    @property
    def frequency(self):
        if 0 <= self.index < len(self.freqs):
            return self.freqs[self.index]
        return 0

    @property
    def running(self):
        return self.state == RUNNING

    def progress(self):
        """`(done, total, hz)` for the screen, or None when not running."""
        if self.state != RUNNING:
            return None
        return (self.index + 1, self.total, self.frequency)

    # -- running it ---------------------------------------------------------
    def start(self):
        if not self.freqs:
            self.state, self.message = FAILED, "nothing selected"
            return False
        if not self._put_tuner_in_circuit():
            return False
        # Where the operator was, so `finish` can put them back. A sweep ends
        # parked on its last memory, which is a frequency nobody chose; an
        # operator who tunes the antenna and goes back to a net finds the
        # radio somewhere else entirely.
        #
        # Read, not assumed. A radio that cannot be read reports 0 and
        # nothing is restored, which is better than setting a frequency that
        # was never the one in use.
        try:
            self.started_at_hz = int(self.rig.frequency() or 0)
        except Exception:                              # noqa: BLE001
            self.started_at_hz = 0
        self.index = -1
        self.state = RUNNING
        self.message = ""
        self._next_at = 0.0
        self._phase = "step"
        return True

    def _put_tuner_in_circuit(self):
        try:
            self.rig.send_cat(CAT_TUNE_IN)
        except Exception as exc:                       # noqa: BLE001
            self.state = FAILED
            self.message = f"no rig control: {exc}"
            return False
        return True

    def tick(self):
        """Advance by at most one action. Call it as often as convenient.

        Two phases per frequency. `set_frequency` lands the VFO, then a
        settle elapses, then the tuner is triggered and the dwell runs. The
        settle matters: triggering a match before the radio has arrived asks
        the tuner to match the previous frequency.

        Neither phase sleeps. A sweep that slept through its dwell could not
        read the key that aborts it, during the only part of the run where
        aborting matters.
        """
        if self.state != RUNNING:
            return self.state
        now = self._now()
        if now < self._next_at:
            return self.state

        if self._phase == "settle":
            # The VFO has arrived. Trigger the tuner and start the dwell.
            try:
                self.rig.send_cat(CAT_TUNE_START)
            except Exception as exc:                   # noqa: BLE001
                return self._fail(f"rig control failed: {exc}")
            self._phase = "dwell"
            self._next_at = now + self.dwell_s
            return self.state

        # Dwell over, or the very first step. Move to the next frequency.
        self.index += 1
        if self.index >= len(self.freqs):
            self.index = len(self.freqs) - 1
            self.state = DONE
            self.message = f"tuner memories set on {self.total} frequencies"
            self.finish()
            return self.state
        try:
            self.rig.set_frequency(self.freqs[self.index])
        except Exception as exc:                       # noqa: BLE001
            return self._fail(f"rig control failed: {exc}")
        self._phase = "settle"
        self._next_at = now + self.settle_s
        return self.state

    def _fail(self, message):
        self.state = FAILED
        self.message = message
        self.finish()
        return self.state

    def abort(self, why="stopped"):
        """`^X`. Takes effect before the next key-down, not at a segment end."""
        if self.state == RUNNING:
            self.state = ABORTED
            self.message = why
        self.finish()
        return self.state

    def finish(self):
        """Leave the tuner in circuit, however this run ended.

        Not bypassed. A run that ends with the tuner out of circuit leaves the
        antenna worse than before it started, and that is true whether the run
        completed, was aborted, or died on a CAT error.
        """
        try:
            self.rig.send_cat(CAT_TUNE_IN)
        except Exception:                              # noqa: BLE001
            # Nothing useful to do: the rig is already unreachable, which is
            # what the message from the failing step will say.
            pass
        # Then back where the operator was. After the tuner is in circuit,
        # not before: the order that matters is the one that cannot leave the
        # antenna unmatched, and a failed frequency restore is a nuisance
        # where a failed tuner-in is a worse antenna.
        if getattr(self, "started_at_hz", 0):
            try:
                self.rig.set_frequency(self.started_at_hz)
            except Exception:                          # noqa: BLE001
                pass
