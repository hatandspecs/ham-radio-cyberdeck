"""The capture mixer — docs/wspr_design.md §6b.

Every path here runs without a sound card: `Gain` takes an injected runner,
so what is checked is the commands built, the output parsed, and the
save-and-restore discipline that makes this a per-session level rather than
a change to the station.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import wsprgain

# What `amixer -c 1 sget Mic capture` really prints on this codec, from
# docs/wspr_deploy.md §4a. Parsed against the real shape, not a guess.
REAL = """Simple mixer control 'Mic',0
  Capabilities: cvolume cvolume-joined cswitch cswitch-joined
  Capture channels: Mono
  Limits: Capture 0 - 16
  Mono: Capture 10 [62%] [8.00dB] [on]
"""

NO_CONTROL = "amixer: Unable to find simple control 'Mic',0\n"


class Mixer:
    """A stand-in amixer. Records what it was asked and answers as told."""

    def __init__(self, level=62, fail_on=()):
        self.level = level
        self.fail_on = set(fail_on)
        self.seen = []

    def __call__(self, cmd):
        self.seen.append(list(cmd))
        verb = cmd[3] if len(cmd) > 3 else ""
        if verb in self.fail_on:
            return 1, "", NO_CONTROL
        if verb == "sget":
            return 0, REAL.replace("[62%]", f"[{self.level}%]"), ""
        # sset: amixer echoes the control's new state, which the deck
        # ignores. The percentage is argument 5 -- amixer, -c, CARD, sset,
        # CONTROL, PERCENT, capture -- and reading it from 4 got the control
        # name instead, which this file caught on its first run.
        self.level = int(str(cmd[5]).rstrip("%"))
        return 0, REAL.replace("[62%]", f"[{self.level}%]"), ""


print("the card is addressed by NAME, because the index moves")
# Measured on the deck: the C-Media codec was card 1 on 2026-10-17 and card
# 2 after the next reboot, with HDMI taking 1. Every `amixer -c 1` then went
# to the HDMI card and answered "Unable to find simple control 'Mic'", so
# the capture gain silently did nothing -- while the deck reported a
# percentage it had never managed to set. `arecord -D plughw:1,0` failed
# "No such file or directory" at the same time, which is a different fault
# from the codec being busy and is not fixed by stopping fldigi.
equals("the default is the card id, not a number",
       wsprgain.DEFAULT_CARD, "Device")
check("which is what /proc/asound/cards calls it",
      isinstance(wsprgain.DEFAULT_CARD, str), repr(wsprgain.DEFAULT_CARD))

print("\nthe commands name the card, the control and the capture direction")
equals("reading", wsprgain.get_command("Device", "Mic"),
       ["amixer", "-c", "Device", "sget", "Mic", "capture"])
equals("writing, as a percentage", wsprgain.set_command(40, "Device", "Mic"),
       ["amixer", "-c", "Device", "sset", "Mic", "40%", "capture"])
# Percent and not raw steps: this codec's range is 0-16 and another's is not.
check("percent, so the codec's own range does not matter",
      "40%" in wsprgain.set_command(40), str(wsprgain.set_command(40)))

print("\nthe level is read out of amixer's real output")
equals("the percentage", wsprgain.parse_level(REAL), 62)
# None is not zero: a control that cannot be read is not one known silent.
equals("no percentage means None", wsprgain.parse_level(NO_CONTROL), None)
equals("and so does nothing at all", wsprgain.parse_level(""), None)
equals("out-of-range is clamped rather than trusted",
       wsprgain.parse_level("Mono: Capture 10 [620%] [8.00dB] [on]"), 100)

print("\napplying remembers what was there")
m = Mixer(level=62)
g = wsprgain.Gain(run=m)
equals("no previous value before anything is applied", g.previous, None)
equals("applying reports no trouble", g.apply(30), "")
equals("the previous value was captured", g.previous, 62)
equals("and the new one recorded", g.applied, 30)
equals("the mixer really moved", m.level, 30)
# A read came first, so the deck never writes without knowing what it
# overwrote -- which is the whole mechanism of putting it back.
equals("it read before it wrote", m.seen[0][3], "sget")
equals("then wrote", m.seen[1][3], "sset")

print("\nand restoring puts exactly that back")
equals("restoring reports no trouble", g.restore(), "")
equals("the mixer is back where the station had it", m.level, 62)
equals("nothing is left applied", g.applied, None)
equals("and nothing left remembered", g.previous, None)

print("\na gain changed three times still restores to the station's value")
# The previous value is captured ONCE per session. Overwriting it on each
# change would restore to the last WSPR level instead of the operator's.
m = Mixer(level=55)
g = wsprgain.Gain(run=m)
g.apply(20)
g.apply(40)
g.apply(75)
equals("still the value found at the start", g.previous, 55)
g.restore()
equals("which is what it goes back to", m.level, 55)

print("\nrestoring without applying does nothing")
m = Mixer(level=55)
g = wsprgain.Gain(run=m)
equals("it is not an error", g.restore(), "")
equals("and it touched nothing", m.seen, [])

print("\na control this codec does not have is named, not echoed")
# amixer says "Unable to find simple control", which does not say which
# setting to change. The deck's message names it.
m = Mixer(fail_on=("sset", "sget"))
g = wsprgain.Gain(control="Mic", card="Device", run=m)
why = g.apply(30)
check("the failure is reported", bool(why), why)
check("it names the control", "'Mic'" in why or "Mic" in why, why)
check("and the card", "Device" in why, why)
equals("nothing is recorded as applied", g.applied, None)
equals("reading it gives None rather than a number", g.read(), None)

print("\nthe measured level comes off a real capture file")
import struct
import tempfile
import wave
import wspr
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "cap.wav")
    # A half-scale sine: a known amplitude, so the dBFS is checkable rather
    # than merely present.
    import math
    frames = b"".join(
        struct.pack("<h", int(0.5 * 32767 * math.sin(i * 0.1)))
        for i in range(12000))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(12000)
        w.writeframes(frames)
    got = wsprgain.level_of(path)
    check("a level is returned", got is not None, str(got))
    rms, peak, dbfs = got
    check("the peak is about half scale", 0.45 < peak / 32767.0 < 0.55,
          f"peak={peak}")
    # A half-amplitude sine is -9 dBFS RMS: 0.5/sqrt(2) = 0.354.
    check("and the dBFS matches the amplitude", -11.0 < dbfs < -7.0,
          f"dbfs={dbfs}")

    bad = os.path.join(tmp, "nope.wav")
    equals("a file that is not there gives None",
           wsprgain.level_of(bad), None)
    stereo = os.path.join(tmp, "stereo.wav")
    with wave.open(stereo, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(12000)
        w.writeframes(frames)
    # Not a crash and not a wrong number: the deck captures mono and a
    # stereo file means something else wrote it.
    equals("and a file in the wrong format gives None",
           wsprgain.level_of(stereo), None)

print("\nthe AGC is turned off for a session and put back after")
# Measured ON as shipped. WSPR is constant envelope, so compressing it
# discards nothing useful and corrupts the SNR `wsprd` reports -- which is
# then uploaded to wsprnet as though it were a measurement.
class Switch:
    """A stand-in amixer with a boolean control as well as a level."""

    def __init__(self, agc=True):
        self.agc = agc
        self.seen = []

    def __call__(self, cmd):
        self.seen.append(list(cmd))
        name = cmd[4] if len(cmd) > 4 else ""
        state = "[on]" if self.agc else "[off]"
        if cmd[3] == "sget":
            if name == "Auto Gain Control":
                return 0, f"Simple mixer control 'Auto Gain Control',0\n" \
                          f"  Mono: Capture {state}\n", ""
            return 0, REAL, ""
        if name == "Auto Gain Control":
            self.agc = cmd[5] == "on"
            return 0, "", ""
        return 0, REAL, ""


m = Switch(agc=True)
g = wsprgain.Gain(run=m)
equals("silencing it reports no trouble", g.silence_agc(), "")
equals("the AGC is off", m.agc, False)
equals("and that it was on is remembered", g.agc_previous, True)
equals("restoring reports no trouble", g.restore_agc(), "")
equals("the AGC is back on", m.agc, True)
equals("and nothing is left remembered", g.agc_previous, None)

print("\nan AGC that was already off is left off afterwards")
# Putting it back "the way it was" has to mean off, not on.
m = Switch(agc=False)
g = wsprgain.Gain(run=m)
equals("silencing an off AGC is not an error", g.silence_agc(), "")
equals("it is still off", m.agc, False)
equals("restoring leaves it off", g.restore_agc(), "")
equals("still off", m.agc, False)

print("\na codec with no AGC control is not an error")
# A blank name, or a control this card does not have, is normal.
m = Switch()
g = wsprgain.Gain(run=m, agc="")
equals("nothing is attempted", g.silence_agc(), "")
equals("and nothing was run", m.seen, [])
equals("restoring is a no-op too", g.restore_agc(), "")

print("\na switch state is read as on, off, or unknown")
equals("on", wsprgain.parse_switch("  Mono: Capture [on]"), True)
equals("off", wsprgain.parse_switch("  Mono: Capture [off]"), False)
# None is not False: a control that cannot be read is not one known to be
# off, and only the difference says whether there is anything to put back.
equals("unreadable is None", wsprgain.parse_switch("nonsense"), None)
equals("and so is nothing", wsprgain.parse_switch(""), None)

sys.exit(report())
