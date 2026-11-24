"""Starting WSPR puts the radio on the dial -- panel report 2026-11-24.

What the operator saw: several bands selected in the picker, WSPR started,
and the VFO never moved to the WSPR frequency of the band the deck said it
was on.

**`_wspr_preflight_modes` describes this bug exactly, for the mode:** "The
mode was only ever claimed on a band CHANGE... Starting a run on the band
already selected therefore claimed nothing, and the first slot refused with
'not in a data mode' -- two minutes after the operator thought they had
started." The mode half was fixed and the FREQUENCY half was missed.

The dial was only ever set by `_wspr_tune`, which runs on a band change from
the picker or on the scheduler's `tune` action. `wsprsched.tick` emits
actions only within two seconds of a slot boundary, and a WSPR slot is two
minutes -- so a run started on the band already selected left the radio
wherever it was for up to two minutes while the screen reported a live
session. Receiving the wrong frequency and saying so convincingly.

Pure checks against a recording rig: what matters is that starting ASKS the
radio to move, and that the dial is set before the mode, because the radio
keeps a mode per band and being on the band is what makes setting the mode
write the right register.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report

import cyberdeck
import session as session_mod
import wsprbands


class Rig:
    """Records what it was asked, and can refuse to move."""

    def __init__(self, reach=True):
        self.freqs = []
        self.modes = []
        self.reach = reach
        self.hz = 7_000_000

    def set_frequency(self, hz):
        self.freqs.append(int(hz))
        if self.reach:
            self.hz = int(hz)
        return True

    def frequency(self):
        return self.hz

    def mode(self):
        return ("PKTUSB", 3000)

    def set_mode(self, name, passband=0):
        self.modes.append(name)
        return True


def deck(band="20m", bands=("20m", "30m", "40m"), rig=None):
    d = cyberdeck.Deck.__new__(cyberdeck.Deck)
    d.cfg = {"LOCATOR": "FN10cs", "CALLSIGN": "KD3CCO"}
    d.wspr_band = band
    d.session = session_mod.Session(callsign="KD3CCO")
    d.notes = []
    d._wspr_note = d.notes.append
    d._wspr_bands = lambda: list(bands)
    d._log_rig = lambda: rig
    # The real one polls the radio until it reports the new frequency; here
    # the question is only whether the deck asked, and what it did with a no.
    d._rig_goto = lambda r, hz: bool(r.set_frequency(hz)) and r.reach
    return d


def said(d):
    return " | ".join(d.notes)


print("starting on the band already selected still tunes")
rig = Rig()
d = deck(band="20m", rig=rig)
d._wspr_preflight_dial()
equals("the radio was asked to move once", len(rig.freqs), 1)
equals("to 20 m's WSPR dial", rig.freqs[0], wsprbands.dial_hz("20m"))
check("and the operator is told where it went", "20m" in said(d), said(d))

print("\nevery selected band's dial is the one for that band")
for band in ("40m", "30m", "20m", "15m", "10m"):
    rig = Rig()
    d = deck(band=band, bands=(band,), rig=rig)
    d._wspr_preflight_dial()
    equals(f"{band} goes to its own dial", rig.freqs,
           [wsprbands.dial_hz(band)])

print("\nwith no current band, the first selected one is taken")
# Reachable: the picker stores an explicit "none" and `_open_wspr` is what
# fills `wspr_band` in. Starting from a path that skipped it must not key
# the clock with no band and report "WSPR started on ".
rig = Rig()
d = deck(band="", bands=("30m", "40m"), rig=rig)
d._wspr_preflight_dial()
equals("the band is filled in", d.wspr_band, "30m")
equals("and the radio went to it", rig.freqs,
       [wsprbands.dial_hz("30m")])

print("\nnothing selected at all asks nothing of the radio")
rig = Rig()
d = deck(band="", bands=(), rig=rig)
d._wspr_preflight_dial()
equals("the radio is left alone", rig.freqs, [])
equals("and no band was invented", d.wspr_band, "")

print("\na radio that will not move says so rather than passing silently")
rig = Rig(reach=False)
d = deck(band="20m", rig=rig)
d._wspr_preflight_dial()
equals("it was still asked", len(rig.freqs), 1)
check("and the failure is on the screen",
      "did not reach" in said(d), said(d))
check("naming the frequency to set by hand",
      "14.0" in said(d), said(d))

print("\nand no rig control is reported, not treated as success")
d = deck(band="20m", rig=None)
d._wspr_preflight_dial()
check("the operator is told to set the dial by hand",
      "no rig control" in said(d), said(d))
check("with the frequency in the message", "14.0" in said(d), said(d))
check("and the band named", "20m" in said(d), said(d))

print("\nthe dial is set before the mode")
# The radio keeps a mode per band -- see `bandmodes` -- so setting the mode
# while on the wrong band writes the wrong band's register. `_wspr_start`
# calls the dial preflight first for that reason; this pins the order so a
# later tidy-up cannot quietly swap them.
import inspect
src = inspect.getsource(cyberdeck.Deck._wspr_start)
check("_wspr_start calls the dial preflight",
      "_wspr_preflight_dial()" in src, src[-400:])
check("and the mode preflight",
      "_wspr_preflight_modes()" in src, src[-400:])
check("in that order",
      src.index("_wspr_preflight_dial()") < src.index("_wspr_preflight_modes()"),
      "the dial must be set before the mode")

sys.exit(report())
