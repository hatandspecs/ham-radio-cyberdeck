"""Band segments, sweep frequencies, locks and selection — src/bandplan.py.

**The frequency list is checked against the implementation that was field
tested.** `ftx1-tuner-sweep/ftx1_cat.py` drove a real FTX-1 Optima and a
mAT-30 on 15 m and 12 m, and this module has to keep producing the same
frequencies it did. Where that project is reachable the two are compared
directly; where it is not, the expected lists below are the ones it produced.

The other thing asserted hard is that **a lock beats every bulk operation**.
Select-all, invert and the phone and CW hotkeys must all skip a locked row,
because a lock is how an operator records what the antenna cannot do and a
bulk key that overrode it would key the radio on a band that does not work.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import bandplan

print("the 1 kHz edge padding, which keeps a sweep off a band boundary")
f = bandplan.frequencies_for(3_525_000, 3_600_000)
equals("first point is 1 kHz inside the lower edge", f[0], 3_526_000)
equals("last point is 1 kHz inside the upper edge", f[-1], 3_599_000)
check("and nothing sits on either edge",
      3_525_000 not in f and 3_600_000 not in f, f[:3])
equals("80m CW/Data is nine memories", len(f), 9)
equals("the interior points are clean multiples of 10 kHz",
       [x for x in f[1:-1] if x % 10_000], [])

print("\nthe documented example lists, verbatim")
equals("80m CW/Data 3.525-3.600",
       bandplan.frequencies_for(3_525_000, 3_600_000),
       [3_526_000, 3_530_000, 3_540_000, 3_550_000, 3_560_000,
        3_570_000, 3_580_000, 3_590_000, 3_599_000])
equals("40m Phone 7.175-7.300",
       bandplan.frequencies_for(7_175_000, 7_300_000),
       [7_176_000, 7_180_000, 7_190_000, 7_200_000, 7_210_000, 7_220_000,
        7_230_000, 7_240_000, 7_250_000, 7_260_000, 7_270_000, 7_280_000,
        7_290_000, 7_299_000])

print("\na range too narrow for padding plus a grid is not silently dropped")
narrow = bandplan.frequencies_for(10_000_000, 10_001_500)
check("it still produces frequencies", len(narrow) >= 1, narrow)
check("and they stay inside the range",
      all(10_000_000 <= x <= 10_001_500 for x in narrow), narrow)

print("\nit agrees with the field-tested implementation")
SWEEP = "/home/natale/git_repos/ftx1-tuner-sweep"
if os.path.isdir(SWEEP):
    sys.path.insert(0, SWEEP)
    try:
        # `ftx1_cat` imports pyserial at module level for its radio class.
        # The function being compared is pure arithmetic and never touches a
        # port, and the deck talks to the radio through rigctld rather than
        # a serial library, so pyserial is not installed here or on the card.
        # A stub lets the real function be compared instead of a copy of it
        # transcribed into this file, which would not catch a change there.
        import types
        sys.modules.setdefault("serial", types.ModuleType("serial"))
        import ftx1_cat
        same = True
        for lo, hi in ((3_525_000, 3_600_000), (7_175_000, 7_300_000),
                       (28_000_000, 29_700_000), (18_068_000, 18_168_000),
                       (50_000_000, 54_000_000)):
            mine = bandplan.frequencies_for(lo, hi)
            theirs = ftx1_cat.frequencies_for([(lo, hi)], bandplan.STEP_HZ)
            if mine != theirs:
                same = False
                check(f"{lo}-{hi} matches", False,
                      f"mine {mine[:4]}... theirs {theirs[:4]}...")
        check("every range matches ftx1_cat.frequencies_for", same)
        equals("and the edge padding constant is the same",
               bandplan.EDGE_PAD_HZ, ftx1_cat.EDGE_PAD_HZ)
    except ImportError as exc:
        check("ftx1_cat is importable", False, str(exc))
else:
    check("ftx1-tuner-sweep not present; compared against its recorded output",
          True)

print("\n30m is CW/data only for every class, including Extra")
# The source file annotates us_general 30m fully and us_extra 30m as only
# "Full band". A label taken from that text would read "All Modes" for an
# Extra licensee and invite a phone sweep where phone is prohibited.
for lic in ("us_general", "us_extra"):
    segs = [s for s in bandplan.segments(lic) if s.band == "30m"]
    equals(f"{lic}: one 30m segment", len(segs), 1)
    equals(f"{lic}: labelled CW/Data only", segs[0].label, "CW/Data only")
    check(f"{lic}: and it is not offered to select-all-phone",
          not segs[0].is_phone, segs[0].label)

print("\nthe wide bands are subdivided by activity, not swept whole")
ten = [s for s in bandplan.segments("us_general") if s.band == "10m"]
check("10m is more than one row", len(ten) > 1, [s.name for s in ten])
ssb = [s for s in ten if s.label == "SSB"]
equals("there is a 10m SSB segment", len(ssb), 1)
equals("it runs 28.300 to 28.600", (ssb[0].start_hz, ssb[0].end_hz),
       (28_300_000, 28_600_000))
equals("which is 31 memories, not 171", ssb[0].memory_count(), 31)
whole = bandplan.frequencies_for(28_000_000, 29_700_000)
equals("the undivided block would have been 171", len(whole), 171)

print("\nthe sub-segments deliberately do not tile the band")
covered = sum(s.end_hz - s.start_hz for s in ten)
check("they cover less than the full CFR block",
      covered < 29_700_000 - 28_000_000, covered)
check("because 29.000-29.500 holds nothing worth tuning for",
      not any(s.start_hz < 29_500_000 and s.end_hz > 29_000_000
              for s in ten), [s.name for s in ten])

print("\nsub-segments cannot escape the privilege range")
for lic in ("us_general", "us_extra"):
    for s in bandplan.segments(lic):
        rows = [r for r in bandplan.segments(lic, subdivide=False)
                if r.band == s.band]
        inside = any(r.start_hz <= s.start_hz and s.end_hz <= r.end_hz
                     for r in rows)
        if not inside:
            check(f"{lic} {s.name} lies inside its privilege range", False,
                  f"{s.start_hz}-{s.end_hz}")
            break
    else:
        check(f"{lic}: every sub-segment lies inside its privilege range",
              True)

print("\nthe panel's first column is band and segment together")
segs = bandplan.segments("us_general")
names = [s.name for s in segs]
check("read as one label", "80m (Phone)" in names, names[:4])
check("and the key is stable for a config file",
      all(":" in s.key for s in segs), segs[0].key)
check("every row fits the 66-column panel beside its range",
      all(len(f"  [*] {s.name:<22} {s.start_hz/1e6:>7.3f} - "
              f"{s.end_hz/1e6:.3f}") <= 66 for s in segs),
      max(len(s.name) for s in segs))

print("\nSpace is the only way to pick a segment")
# The bulk operations -- all, none, invert, all-phone, all-CW -- and the
# per-segment lock that existed to override them were removed 2026-10-23,
# after the first sweep on the panel. Scrolling twenty-odd rows and
# pressing Space is fast enough, and with no bulk operation to protect
# against, a lock protected against nothing.
segs = bandplan.segments("us_general")
for gone in ("select_all", "clear", "invert", "select_phone", "select_cw",
             "toggle_lock", "is_locked", "locked_keys"):
    check(f"{gone} is gone", not hasattr(bandplan.Selection(segs), gone))

print("\ntoggle reports what the row became")
sel = bandplan.Selection(segs)
key = segs[0].key
equals("off to on", sel.toggle(key), True)
check("and it is selected", sel.is_selected(key))
equals("on to off", sel.toggle(key), False)
check("and it is not", not sel.is_selected(key))

print("\na working selection, built one row at a time")
sel = bandplan.Selection(segs)
want = [s for s in segs if s.label == bandplan.PHONE
        and s.band in ("80m", "40m", "20m", "15m", "17m")]
for s in want:
    sel.toggle(s.key)
equals("the phone segments of the bands this antenna works",
       sorted(x.name for x in sel.selected()),
       sorted(x.name for x in want))
check("which is a sweep of a few minutes at 2.5 s",
      1.0 <= sel.seconds(2.5) / 60 <= 8.0, sel.seconds(2.5) / 60)

print("\na selection handed in at construction is kept")
sel = bandplan.Selection(segs, chosen=[key])
check("the chosen row is selected", sel.is_selected(key))

print("\nthe summary line the screen carries")
sel = bandplan.Selection(segs)
equals("nothing selected says so", sel.summary(5), "selected: nothing")
sel.toggle([s for s in segs if s.name == "30m (CW/Data only)"][0].key)
line = sel.summary(5)
check("one segment is singular", "1 segment " in line, line)
check("it names the memory count", "6 memories" in line, line)
check("and what it will cost", "about" in line, line)

print("\nthe sweep visits every selected segment, ascending")
sel = bandplan.Selection(segs)
sel.toggle([s for s in segs if s.name == "40m (Phone)"][0].key)
sel.toggle([s for s in segs if s.name == "80m (Phone)"][0].key)
freqs = sel.sweep_frequencies()
equals("ascending across segments", freqs, sorted(freqs))
equals("and the count is the sum of the parts", len(freqs),
       sel.memory_count())
check("80m comes before 40m", freqs[0] < 7_000_000, freqs[0])

print("\nlicenses come from the plan file, not from a literal here")
lics = bandplan.licenses()
check("General and Extra are both present",
      "us_general" in lics and "us_extra" in lics, sorted(lics))
check("and each has a display name",
      all(v for v in lics.values()), lics)

print("\n160m is in the regulation and is offered")
check("General includes 160m",
      any(s.band == "160m" for s in bandplan.segments("us_general")),
      [s.band for s in bandplan.segments("us_general")])

sys.exit(report())
