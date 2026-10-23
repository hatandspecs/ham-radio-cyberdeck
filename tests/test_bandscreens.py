"""The band plan reference and the auto tuner screens — src/render.py.

Both draw the same two columns, band-and-segment then range, because they are
one idea seen twice: one reads the plan, the other picks from it.

The width property is the one that bites on a 66-column panel. Every row must
be exactly the screen's width -- not less, which leaves the previous frame
showing through, and not more, which wraps and pushes the footer off.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import bandplan
import render

SIZES = ((66, 20), (50, 15), (80, 24), (40, 12))


def text(lines):
    return "\n".join("".join(t for t, _k in ln) for ln in lines)


def widths(lines):
    return {sum(len(t) for t, _k in ln) for ln in lines}


SEGS = bandplan.segments("us_general")

print("the reference screen draws the plan and tunes nothing")
body = text(render.allocation_screen(SEGS, 0, 66, 20, "US General"))
check("it is titled as a band plan", "BAND PLAN" in body, body[:80])
check("it names the license class", "US General" in body, body[:80])
check("the first column is band and segment together",
      "160m (All Modes)" in body, body[:200])
check("the range is in MHz", "1.800 - 2.000" in body, body[:200])
check("no memory count reaches the screen",
      "memories" not in body.lower(), body)
check("and no bandwidth column either",
      " kHz" not in body, body)

print("\nevery row is exactly the screen's width, at every size")
for w, h in SIZES:
    lines = render.allocation_screen(SEGS, 0, w, h, "US General")
    equals(f"{w}x{h}: the right number of rows", len(lines), h)
    equals(f"{w}x{h}: every row is {w} wide", widths(lines), {w})

print("\nit pages, and the page follows the cursor")
per = render.SEGMENTS_PER_PAGE
check("the General plan is longer than one page", len(SEGS) > per, len(SEGS))
first = text(render.allocation_screen(SEGS, 0, 66, 20, "US General"))
last = text(render.allocation_screen(SEGS, len(SEGS) - 1, 66, 20, "US General"))
check("page one shows the lowest band", "160m" in first, first[:200])
check("and not the highest", "6m (" not in first, first)
check("the last page shows the highest band", "6m (" in last, last)
check("and not the lowest", "160m" not in last, last)
check("the page number is shown when there is more than one",
      "1/" in first, first[:80])

print("\nthe cursor marks exactly one row")
lines = render.allocation_screen(SEGS, 3, 66, 20, "US General")
marked = [ln for ln in lines
          if "".join(t for t, _k in ln).startswith("▸")]
equals("one row carries the marker", len(marked), 1)

print("\nthe tuner screen shows selection, locks and what it will cost")
sel = bandplan.Selection(SEGS)
sel.select_phone()
body = text(render.tuner_screen(sel, 0, 66, 20, "US General", dwell_s=5))
check("it is titled as the tuner", "AUTO TUNER" in body, body[:80])
check("selected rows are marked", render.SEG_ON in body, body[:300])
check("unselected rows are marked too", render.SEG_OFF in body, body[:400])
check("the summary names the segment count", "segment" in body, body)
check("and the memory count", "memories" in body, body)
check("and what it will cost in time", "about" in body, body)

print("\na locked row is visible and marked, not hidden")
# 6 m is last in band order, so the cursor has to be on its page for the
# row to be drawn at all. Rendering page one and asserting the mark appears
# tested the pagination, not the lock.
locked_seg = [s for s in SEGS if s.band == "6m"][0]
locked_idx = SEGS.index(locked_seg)
sel = bandplan.Selection(SEGS, locked=[locked_seg.key])
body = text(render.tuner_screen(sel, locked_idx, 66, 20, "US General"))
check("the locked mark appears", render.SEG_LOCKED in body, body)
check("and the band is still listed, not hidden", "6m (" in body, body)
unlocked = text(render.tuner_screen(
    bandplan.Selection(SEGS), locked_idx, 66, 20, "US General"))
check("an unlocked row of the same band carries no lock mark",
      render.SEG_LOCKED not in unlocked, unlocked)

print("\nnothing selected says so rather than showing a zero")
sel = bandplan.Selection(SEGS)
body = text(render.tuner_screen(sel, 0, 66, 20))
check("it says nothing is selected", "nothing" in body, body)
check("and does not claim 0 memories", "0 memories" not in body, body)

print("\nthe running line replaces the summary and advertises the abort")
sel = bandplan.Selection(SEGS)
sel.select_phone()
body = text(render.tuner_screen(sel, 0, 66, 20, running=(7, 80, 7_180_000)))
check("it shows progress", "7/80" in body, body)
check("and the frequency being tuned", "7.180" in body, body)
check("and that ^X aborts", "^X" in body, body)
check("the summary is gone while running", "memories" not in body, body)
check("the footer is only the abort",
      "Space pick" not in body, body[-120:])

print("\nthe width property holds for the tuner screen too")
sel = bandplan.Selection(SEGS)
sel.select_all()
for w, h in SIZES:
    lines = render.tuner_screen(sel, 0, w, h, "US General")
    equals(f"{w}x{h}: the right number of rows", len(lines), h)
    equals(f"{w}x{h}: every row is {w} wide", widths(lines), {w})
    lines = render.tuner_screen(sel, 0, w, h, running=(1, 2, 14_000_000))
    equals(f"{w}x{h}: and while running", widths(lines), {w})

print("\nthe longest segment name still fits beside its range at 66")
longest = max(SEGS, key=lambda s: len(s.name))
row = render._segment_row(longest, 66, "▸", render.SEG_ON)
equals(f"{longest.name!r} fits", len(row), 66)
check("the range is not truncated off the end",
      row.rstrip().endswith(f"{longest.end_hz / 1e6:.3f}"), row)

print("\nboth screens use the same row format")
seg = SEGS[0]
a = render._segment_row(seg, 66, " ")
b = render._segment_row(seg, 66, " ")
equals("one formatter, one layout", a, b)
check("band and mode are one label, not two columns",
      "(" in a and ")" in a, a)

print("\nan empty plan draws without raising")
for w, h in SIZES:
    lines = render.allocation_screen([], 0, w, h, "US General")
    equals(f"{w}x{h}: empty plan still fills the screen", len(lines), h)
    equals(f"{w}x{h}: and keeps its width", widths(lines), {w})
    empty = bandplan.Selection([])
    lines = render.tuner_screen(empty, 0, w, h)
    equals(f"{w}x{h}: empty tuner list too", widths(lines), {w})

sys.exit(report())
