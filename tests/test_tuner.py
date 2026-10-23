"""The antenna tuner sweep — src/tuner.py.

Every step of a sweep is a real transmission, so the properties asserted here
are the ones that keep that safe rather than the ones that make it convenient:

**The abort takes effect before the next key-down.** Not at the end of a
segment, not after the current dwell. The reason `^X` exists is to stop
transmitting on top of somebody already using the frequency.

**The tuner is left in circuit however a run ends.** Finished, aborted, or
dead on a CAT error. A run that ends bypassed leaves the antenna worse than
before it started.

**Nothing blocks.** A sweep that slept through its dwell could not read the
key that stops it.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import tuner


class FakeRig:
    """Records what was sent, and can be told to fail."""

    def __init__(self, fail_on=None, at_hz=14_074_000):
        self.freqs = []
        self.cat = []
        # Both, in the order they arrived. `freqs` and `cat` are separate
        # lists and so cannot show whether a frequency was set before or
        # after a CAT command -- which is exactly what the end of a sweep
        # has to get right, since restoring the dial before putting the
        # tuner back in circuit would leave the antenna unmatched on the
        # frequency the operator returns to.
        self.sent = []
        self.fail_on = fail_on
        # Where the operator was when the sweep started, which `finish` is
        # supposed to put back.
        self.at_hz = at_hz

    def frequency(self):
        if self.fail_on == "read":
            raise OSError("no rig")
        return self.at_hz

    def set_frequency(self, hz):
        if self.fail_on == "freq":
            raise OSError("no rig")
        self.freqs.append(hz)
        self.sent.append(("freq", hz))
        return True

    def send_cat(self, cmd):
        if self.fail_on == "cat" and cmd == tuner.CAT_TUNE_START:
            raise OSError("no rig")
        self.cat.append(cmd)
        self.sent.append(("cat", cmd))
        return True


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, by):
        self.t += by


def run_to_end(sw, clock, limit=10000):
    """Drive a sweep to completion the way the poll loop would."""
    for _ in range(limit):
        if not sw.running:
            return
        before = sw.state
        sw.tick()
        if sw.state == before and sw.running:
            clock.advance(0.05)
    raise AssertionError("sweep did not finish")


FREQS = [7_176_000, 7_180_000, 7_190_000]

print("the CAT commands are the ones measured on the radio")
equals("start tuning is AC103", tuner.CAT_TUNE_START, "AC103;")
equals("in circuit is AC101", tuner.CAT_TUNE_IN, "AC101;")
equals("bypassed is AC100", tuner.CAT_TUNE_OFF, "AC100;")

print("\na run visits every frequency, in order, and tunes at each")
clock = Clock()
rig = FakeRig()
sw = tuner.Sweep(FREQS, rig, dwell_s=5, now=clock)
check("it starts", sw.start())
run_to_end(sw, clock)
equals("the state is done", sw.state, tuner.DONE)
equals("every frequency was visited, ascending",
       rig.freqs[:len(FREQS)], FREQS)
equals("and the tuner was triggered once per frequency",
       rig.cat.count(tuner.CAT_TUNE_START), len(FREQS))

print("\nand then puts the operator's frequency back")
# A sweep ends parked on its last memory, which is a frequency nobody chose.
# An operator who tunes the antenna and goes back to a net would otherwise
# find the radio somewhere else entirely.
equals("the last frequency set is the one it started on",
       rig.freqs[-1], rig.at_hz)
equals("which is one more set than there were memories",
       len(rig.freqs), len(FREQS) + 1)
equals("and it happens after the tuner is back in circuit, not before",
       rig.sent[-2:], [("cat", tuner.CAT_TUNE_IN), ("freq", rig.at_hz)])

print("\na radio that cannot be read has nothing to put back")
clock2 = Clock()
blind = FakeRig(fail_on="read")
sw2 = tuner.Sweep(FREQS, blind, dwell_s=5, now=clock2)
check("the sweep still starts", sw2.start())
run_to_end(sw2, clock2)
equals("it ran", sw2.state, tuner.DONE)
equals("and set exactly the memories, inventing no frequency",
       blind.freqs, FREQS)

print("\nan aborted run puts it back too")
clock3 = Clock()
rig3 = FakeRig(at_hz=7_074_000)
sw3 = tuner.Sweep(FREQS, rig3, dwell_s=5, now=clock3)
sw3.start()
sw3.tick()
clock3.advance(tuner.SETTLE_S + 0.01)
sw3.tick()
sw3.abort()
equals("back where the operator was, mid-sweep", rig3.freqs[-1], 7_074_000)
equals("with the tuner put back in circuit first",
       rig3.sent[-2:], [("cat", tuner.CAT_TUNE_IN), ("freq", 7_074_000)])

print("\nthe tuner goes in circuit before anything is keyed")
equals("the first command is in-circuit, not a tune",
       rig.cat[0], tuner.CAT_TUNE_IN)

print("\nand is left in circuit when the run finishes")
equals("the last command puts it in circuit", rig.cat[-1], tuner.CAT_TUNE_IN)
check("it is never bypassed", tuner.CAT_TUNE_OFF not in rig.cat, rig.cat)

print("\nthe frequency is set before the tuner is triggered")
# Triggering before the VFO has arrived asks the tuner to match the previous
# frequency, which is a bad memory written silently.
clock = Clock()
rig = FakeRig()
sw = tuner.Sweep([14_025_000], rig, dwell_s=5, now=clock)
sw.start()
sw.tick()
equals("one frequency set", rig.freqs, [14_025_000])
check("and no tune yet", tuner.CAT_TUNE_START not in rig.cat, rig.cat)

# **Ticking again WITHOUT advancing the clock.** This is what tests the
# settle at all: tick does one action per call either way, so a version with
# no settle delay looks identical to one with it until the clock is held
# still. An earlier form of this check advanced the clock first and passed
# against a mutant that triggered the tuner the instant the VFO was set.
for _ in range(20):
    sw.tick()
check("and still none, because the settle has not elapsed",
      tuner.CAT_TUNE_START not in rig.cat,
      f"tuner fired {rig.cat.count(tuner.CAT_TUNE_START)} times during settle")

clock.advance(tuner.SETTLE_S + 0.01)
sw.tick()
check("after the settle, the tuner is triggered",
      tuner.CAT_TUNE_START in rig.cat, rig.cat)

print("\nnothing blocks: a tick during the dwell returns at once")
clock = Clock()
rig = FakeRig()
sw = tuner.Sweep(FREQS, rig, dwell_s=5, now=clock)
sw.start()
sw.tick()
clock.advance(tuner.SETTLE_S + 0.01)
sw.tick()
before = len(rig.freqs)
for _ in range(50):
    sw.tick()                      # mid-dwell, clock not advanced
equals("fifty ticks inside the dwell changed nothing", len(rig.freqs), before)
check("and the sweep is still running", sw.running)

print("\nthe abort stops it before the next key-down")
clock = Clock()
rig = FakeRig()
sw = tuner.Sweep(FREQS, rig, dwell_s=5, now=clock)
sw.start()
sw.tick()
clock.advance(tuner.SETTLE_S + 0.01)
sw.tick()
tuned_before = rig.cat.count(tuner.CAT_TUNE_START)
sw.abort()
equals("the state is aborted", sw.state, tuner.ABORTED)
clock.advance(600)
for _ in range(20):
    sw.tick()
# One memory, then the restore. The restore is `finish`'s work and happens
# once, on the abort, not on every tick afterwards.
equals("no further frequency was set", len(rig.freqs), 2)
equals("and the extra one is the restore, not another memory",
       rig.freqs[-1], rig.at_hz)
equals("and nothing more was tuned",
       rig.cat.count(tuner.CAT_TUNE_START), tuned_before)

print("\nan aborted run still leaves the tuner in circuit")
equals("the last command is in-circuit", rig.cat[-1], tuner.CAT_TUNE_IN)

print("\na CAT failure stops the run and says so")
clock = Clock()
rig = FakeRig(fail_on="cat")
sw = tuner.Sweep(FREQS, rig, dwell_s=5, now=clock)
sw.start()
sw.tick()
clock.advance(tuner.SETTLE_S + 0.01)
sw.tick()
equals("the state is failed", sw.state, tuner.FAILED)
check("with a reason", "rig control" in sw.message, sw.message)
equals("and the tuner is still left in circuit",
       rig.cat[-1], tuner.CAT_TUNE_IN)

print("\na run that cannot reach the radio at all never keys it")
rig = FakeRig()
rig.send_cat = lambda cmd: (_ for _ in ()).throw(OSError("no rigctld"))
sw = tuner.Sweep(FREQS, rig, dwell_s=5)
check("start refuses", not sw.start())
equals("the state is failed", sw.state, tuner.FAILED)
check("and it says why", "no rig" in sw.message, sw.message)

print("\nan empty selection is refused rather than run")
sw = tuner.Sweep([], FakeRig(), dwell_s=5)
check("start refuses", not sw.start())
check("and says nothing is selected", "nothing" in sw.message, sw.message)

print("\nthe dwell is clamped to what can actually work")
# Too short fails silently -- the radio cannot report that an external tuner
# finished -- so a fat finger on the cycling key must not produce a sweep
# that writes unconverged memories.
equals("a sane value passes through", tuner.clamp_dwell(2.5), 2.5)
equals("1.5 seconds is allowed", tuner.clamp_dwell(1.5), 1.5)
equals("zero is raised to the floor", tuner.clamp_dwell(0),
       tuner.MIN_DWELL_S)
equals("a negative too", tuner.clamp_dwell(-5), tuner.MIN_DWELL_S)
equals("and an absurd value is capped", tuner.clamp_dwell(900),
       tuner.MAX_DWELL_S)
equals("nonsense falls back to the default", tuner.clamp_dwell("soon"), 5.0)
equals("and so does None", tuner.clamp_dwell(None), 5.0)

print("\nthe dwell is honored, not approximated")
clock = Clock()
rig = FakeRig()
sw = tuner.Sweep([1_800_000, 1_810_000], rig, dwell_s=3.0, now=clock)
sw.start()
sw.tick()
clock.advance(tuner.SETTLE_S + 0.01)
sw.tick()
clock.advance(2.5)                 # less than the dwell
sw.tick()
equals("it has not moved on early", len(rig.freqs), 1)
clock.advance(0.6)                 # now past it
sw.tick()
equals("and moves on once the dwell has elapsed", len(rig.freqs), 2)

print("\nprogress is what the screen needs, and nothing while idle")
clock = Clock()
sw = tuner.Sweep(FREQS, FakeRig(), dwell_s=5, now=clock)
equals("idle has no progress", sw.progress(), None)
sw.start()
sw.tick()
done, total, hz = sw.progress()
equals("the total is the frequency count", total, len(FREQS))
equals("the current frequency is reported", hz, FREQS[0])
check("and the count is one-based for display", done == 1, done)
sw.abort()
equals("an aborted sweep reports no progress", sw.progress(), None)

print("\na running sweep holds the ring, as WSPR does")
# Every key on the tuner screen is already swallowed while a sweep runs,
# including Esc. `^O` and `^P` are read BEFORE the per-screen handlers, so
# they were the one way to walk away from a deck that is transmitting for
# the better part of an hour with nothing outside that screen saying so.
import cyberdeck
import session as session_mod


def deck_sweeping(running=True):
    d = cyberdeck.Deck.__new__(cyberdeck.Deck)
    d.cfg = {"RING_ORDER": ""}
    d.log_on = True
    d.wspr = None            # `wspr_running` is a property reading this
    d.screen = cyberdeck.TUNER
    d.area_screen = {}
    d.menu = None
    d.tuner_message = ""
    d.session = session_mod.Session(callsign="KD3CCO")
    d._close_menu = lambda: None
    d.log_form = None
    if running:
        clk = Clock()
        d.tuner_run = tuner.Sweep(FREQS, FakeRig(), dwell_s=5, now=clk)
        d.tuner_run.start()
    else:
        d.tuner_run = None
    return d


d = deck_sweeping()
check("the sweep is running", d.tuner_run.running)
d._ring(1)
equals("^P does not leave the tuner screen", d.screen, cyberdeck.TUNER)
check("and it says what is in the way", "sweep is running" in d.tuner_message,
      d.tuner_message)
check("naming the key that clears it", "^X" in d.tuner_message,
      d.tuner_message)
d._ring(-1)
equals("nor does ^O", d.screen, cyberdeck.TUNER)

print("\nand releases it the moment the sweep ends")
d.tuner_run.abort()
check("the sweep has stopped", not d.tuner_run.running)
d._ring(1)
check("the ring moves again", d.screen != cyberdeck.TUNER, d.screen)

print("\nwith no sweep the ring was never locked")
d = deck_sweeping(running=False)
d._ring(1)
check("it leaves the tuner screen", d.screen != cyberdeck.TUNER, d.screen)
equals("with nothing to explain", d.tuner_message, "")

sys.exit(report())
