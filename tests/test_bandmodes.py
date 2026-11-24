"""The band-mode walk: `BS` to each band, set the mode, come home.

No radio and no curses. A fake rig records every CAT string, and the clock is
handed in so half a minute of settling costs nothing.
"""
import os
import sys

_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import check, equals, report
import bandmodes


class FakeRig:
    """Band registers, the way the radio actually behaves.

    `send_cat("BS0nn;")` recalls that band's stored frequency, a mode set
    writes into the selected band's register, and `set_frequency` moves the
    VFO without touching any register -- which is the whole reason the walk
    exists.
    """

    def __init__(self, registers=None, cat_ok=True):
        self.registers = dict(registers or {
            "03": [7_070_700, "LSB"],
            "05": [14_240_020, "USB"],
        })
        self.at_hz = 14_240_020
        self.band = "05"
        self.cat = []
        self.freqs_set = []
        self.cat_ok = cat_ok

    def send_cat(self, command):
        self.cat.append(command)
        if not self.cat_ok:
            return False
        if command.startswith("BS0"):
            code = command[3:5]
            self.band = code
            reg = self.registers.setdefault(code, [0, ""])
            if reg[0]:
                self.at_hz = reg[0]
        return True

    def frequency(self):
        return self.at_hz

    def set_frequency(self, hz):
        self.freqs_set.append(int(hz))
        self.at_hz = int(hz)
        return True

    def write_mode(self, name):
        """What `Deck._rig_set_mode` amounts to, from the radio's side."""
        self.registers.setdefault(self.band, [self.at_hz, ""])[1] = name
        return True


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def drive(walk, clock, limit=400):
    """Tick to completion, advancing the clock whenever it is waiting."""
    for _ in range(limit):
        if not walk.running:
            return True
        before = (walk._phase, walk.index)
        walk.tick()
        if walk.running and (walk._phase, walk.index) == before:
            clock.advance(walk.settle_s + 0.01)
    return not walk.running


# -- the band table ----------------------------------------------------------

equals("a data walk covers ten HF bands", len(bandmodes.bands_for("data")), 10)
equals("an SSB walk covers eight", len(bandmodes.bands_for("ssb")), 8)
check("SSB skips 30 m and 60 m",
      [b[2] for b in bandmodes.bands_for("ssb") if b[2] in ("30 m", "60 m")] == [])
check("a data walk includes them",
      {"30 m", "60 m"} <= {b[2] for b in bandmodes.bands_for("data")})

equals("14.074 is inside 20 m", bandmodes.band_for(14_074_000), "05")
equals("7.2 is inside 40 m", bandmodes.band_for(7_200_000), "03")
equals("10.140 is inside 30 m", bandmodes.band_for(10_140_000), "04")
equals("2 m is in none of them", bandmodes.band_for(144_200_000), "")
equals("and 13.000 is in none either", bandmodes.band_for(13_000_000), "")


# -- a data walk -------------------------------------------------------------

rig = FakeRig()
clock = Clock()
seen = []


def set_data(hz):
    seen.append(hz)
    return (rig.write_mode("PKTUSB"), "PKTUSB")


walk = bandmodes.Walk(rig, "data", set_data, clock=clock)
check("it starts", walk.start())
equals("it read where the operator was", walk.started_at_hz, 14_240_020)
equals("and which band that is", walk.start_band, "05")
check("it runs to completion", drive(walk, clock), walk._phase)
equals("it finished rather than failed", walk.state, bandmodes.DONE)

bs = [c for c in rig.cat if c.startswith("BS")]
equals("one BS per band, plus one to come home", len(bs), 11)
equals("every HF band code was selected",
       sorted(set(c[3:5] for c in bs)),
       ["00", "01", "02", "03", "04", "05", "06", "07", "08", "09"])
equals("the last BS is the band it started on", bs[-1], "BS005;")
equals("the mode landed on all ten", len(walk.set_ok), 10)
equals("nothing was reported failed", walk.failed, [])

# The point of the whole exercise: ten registers now hold the data mode.
modes = {code: reg[1] for code, reg in rig.registers.items()}
equals("ten band registers hold PKTUSB",
       sorted(c for c, m in modes.items() if m == "PKTUSB"),
       ["00", "01", "02", "03", "04", "05", "06", "07", "08", "09"])

equals("the operator is put back on their own frequency",
       rig.freqs_set[-1], 14_240_020)
check("the message names the mode and the count",
      "PKTUSB" in walk.message and "10" in walk.message, walk.message)


# -- an SSB walk picks the sideband from where each band register sits -------

rig = FakeRig()
clock = Clock()
asked = []


def set_ssb(hz):
    name = "LSB" if hz < 10_000_000 else "USB"
    asked.append((hz, name))
    return (rig.write_mode(name), name)


walk = bandmodes.Walk(rig, "ssb", set_ssb, clock=clock)
walk.start()
check("the SSB walk completes", drive(walk, clock), walk._phase)
equals("it visited eight bands", len(asked), 8)
check("everything below 10 MHz got LSB",
      all(n == "LSB" for hz, n in asked if hz < 10_000_000), asked)
check("everything above got USB",
      all(n == "USB" for hz, n in asked if hz >= 10_000_000), asked)
check("30 m and 60 m were never asked about",
      all(bandmodes.band_for(hz) not in ("02", "04") for hz, _n in asked),
      asked)

# 40 m's register holds 7.0707, so the sideband question is asked about the
# radio's own answer rather than about the table's spot frequency.
check("the frequency asked about is the register's",
      (7_070_700, "LSB") in asked, asked)


# -- a radio that cannot be reached ------------------------------------------

rig = FakeRig(cat_ok=False)
clock = Clock()
walk = bandmodes.Walk(rig, "data", lambda hz: (True, "PKTUSB"), clock=clock)
walk.start()
walk.tick()
equals("a BS that does not go stops the walk", walk.state, bandmodes.FAILED)
check("and says why", "rigctld" in walk.message, walk.message)


# -- a mode the radio will not take ------------------------------------------

rig = FakeRig()
clock = Clock()
calls = {"n": 0}


def set_flaky(hz):
    calls["n"] += 1
    ok = calls["n"] % 2 == 0          # every other band refuses
    return (ok and rig.write_mode("PKTUSB"), "PKTUSB")


walk = bandmodes.Walk(rig, "data", set_flaky, clock=clock)
walk.start()
drive(walk, clock)
equals("the ones that took it are counted", len(walk.set_ok), 5)
equals("and so are the ones that did not", len(walk.failed), 5)
check("the message names the bands that refused",
      "would not take it" in walk.message, walk.message)
check("it still came home", rig.freqs_set[-1] == 14_240_020, rig.freqs_set)


# -- an abort still puts the radio back --------------------------------------

rig = FakeRig()
clock = Clock()
walk = bandmodes.Walk(rig, "data", lambda hz: (rig.write_mode("PKTUSB"),
                                               "PKTUSB"), clock=clock)
walk.start()
for _ in range(6):                     # a few bands in
    walk.tick()
    clock.advance(walk.settle_s + 0.01)
part = len(walk.set_ok)
check("some bands were set before the abort", 0 < part < 10, part)
walk.abort("stopped by hand")
drive(walk, clock)
check("the walk ended", not walk.running)
equals("the operator is back on their frequency",
       rig.freqs_set[-1], 14_240_020)
equals("the last BS homed them", [c for c in rig.cat
                                  if c.startswith("BS")][-1], "BS005;")
check("the message says it was stopped",
      "stopped by hand" in walk.message, walk.message)


# -- started somewhere with no band register ---------------------------------

rig = FakeRig()
rig.at_hz = 144_200_000                # 2 m: no HF register to come back to
clock = Clock()
walk = bandmodes.Walk(rig, "data", lambda hz: (True, "PKTUSB"), clock=clock)
walk.start()
equals("no start band is found", walk.start_band, "")
drive(walk, clock)
equals("it still goes back by frequency", rig.freqs_set[-1], 144_200_000)
check("and sent no BS for a band it could not name",
      [c for c in rig.cat if c.startswith("BS")][-1] != "BS0;",
      rig.cat[-3:])


# -- a radio whose frequency cannot be read at all ---------------------------

class DeafRig(FakeRig):
    def frequency(self):
        raise OSError("no answer")


rig = DeafRig()
clock = Clock()
walk = bandmodes.Walk(rig, "data", lambda hz: (True, "PKTUSB"), clock=clock)
walk.start()
equals("nothing was read to come back to", walk.started_at_hz, 0)
drive(walk, clock)
check("so no frequency is guessed on the way home", rig.freqs_set == [],
      rig.freqs_set)
equals("and the walk still finished", walk.state, bandmodes.DONE)

report()
