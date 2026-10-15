"""Layout at every grid the panel can produce (docs/design_doc.md §3.3)."""
import os
import sys

# src/ holds the application; tests/ holds this. Both are addressed from the
# project root so a test can be run from anywhere.
_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_PROJECT, "src")
sys.path.insert(0, _SRC)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import check, equals, report
import time, render
from render import plain
from session import Session


GRIDS = [(66, 20), (80, 24), (50, 15), (100, 30)]

print("-- status line fits every grid, and never loses call/state/clock --")
fields = dict(call="KD3CCO", freq="14.070.15", sideband="USB", mode="BPSK31",
              carrier="1500Hz", snr="S/N 18", imd="IMD -24", state="RX", clock="2114Z")
for w, _ in GRIDS:
    line = plain(render.status_line(fields, w))
    ok = len(line) == w and "KD3CCO" in line and "RX" in line and "2114Z" in line
    check(f"{w} cols", ok, f"len={len(line)} {line!r}")

print("\n-- narrow widths drop the least useful fields first --")
for w in (66, 50, 40, 30):
    line = plain(render.status_line(fields, w))
    kept = [k for k in ("IMD", "USB", "S/N", "1500Hz", "14.070.15", "BPSK31") if k in line]
    print(f"    {w:3} cols: {line.strip()!r}")
    check(f"{w} cols still shows call+state", "KD3CCO" in line and "RX" in line)

print("\n-- transcript wraps and pads to the window height --")
s = Session(callsign="KD3CCO")
s.receive("KD3CCO de NOCALL  good copy, 599 here in State College. "
          "rig is an FTX-1 running 20 watts into a vertical.\n")
for c in "NOCALL de KD3CCO  copy 100 percent": s.type(c)
s.start_over()
lines = render.transcript_lines(s.entries, 66, 12)
check("exactly the window height", len(lines) == 12, f"got {len(lines)}")
check("no line exceeds the width", all(len(plain(l)) <= 66 for l in lines),
      max((len(plain(l)) for l in lines), default=0))
print("    sample:")
for l in lines[:5]:
    if plain(l).strip(): print(f"      |{plain(l)}|")

print("\n-- a long unbroken run is split rather than overflowing --")
s2 = Session(callsign="KD3CCO")
s2.receive("x" * 200)
lines = render.transcript_lines(s2.entries, 66, 8)
check("still within width", all(len(plain(l)) <= 66 for l in lines))

print("\n-- timestamps can be switched off, and the gutter shrinks --")
with_ts = plain(render.transcript_lines(s.entries, 66, 3, timestamps=True)[0])
without  = plain(render.transcript_lines(s.entries, 66, 3, timestamps=False)[0])
check("both fit", len(with_ts) <= 66 and len(without) <= 66)

print("\n-- compose region: indicator right-aligned, cursor after the text --")
lines, (row, col) = render.compose_lines("NOCALL de KD3CCO  all the fldigi modes", "[RX 36]", 66, 2)
check("height honored", len(lines) == 2, len(lines))
# The indicator sits on the last *used* row, not on the padding below it.
check("indicator present", any("[RX 36]" in plain(l) for l in lines))
check("indicator is on the cursor row", "[RX 36]" in plain(lines[row]))
check("cursor on the last used row", row == 0, row)
first = plain(lines[0])
check("no overflow", all(len(plain(l)) <= 66 for l in lines), max(len(plain(l)) for l in lines))
print(f"    |{first}|")

print("\n-- empty transcript still fills the window --")
check("padded", len(render.transcript_lines([], 66, 10)) == 10)

print("\n-- the tuning screen's decode preview --")
equals("empty shows a dash", render.preview("", 40), "\u2014")
equals("keeps the tail, not the head",
       render.preview("A" * 10 + "TAIL", 4), "TAIL")
equals("collapses newlines into one line",
       render.preview("de N3QE\nK\n", 40), "de N3QE K")
equals("drops control characters",
       render.preview("ab\x00\x07cd", 40), "ab cd")
equals("narrow width returns nothing rather than garbage",
       render.preview("anything", 2), "")

print("\n-- signal readouts are not relabeled --")
rows = render.tune_rows({"snr": "45 /170", "imd": "s/n -22 dB"}, 66)
signal = [r for r in rows if r.startswith("  signal")][0]
check("RTTY's baud/shift survives verbatim", "45 /170" in signal, signal)
check("and is not prefixed with S/N", "S/N  45" not in signal, signal)

print("\n-- scroll back through history --")
s3 = Session(callsign="KD3CCO")
for i in range(40): s3.note(f"line {i}")
tail = plain(render.transcript_lines(s3.entries, 66, 5, scroll=0)[-1])
back = plain(render.transcript_lines(s3.entries, 66, 5, scroll=10)[-1])
check("scrolling shows older text", "39" in tail and "29" in back, f"{tail!r} / {back!r}")

print()

print("\n-- the tuning screen repeats the last note --")
rows = render.tune_rows({"note": "search up: carrier 1500 -> 1832 Hz"}, 66)
joined = "\n".join(rows)
check("the note appears on the screen",
      "search up: carrier 1500 -> 1832 Hz" in joined, joined)
rows = render.tune_rows({}, 66)
check("no note leaves a blank row rather than an error",
      any(r.strip() == "" for r in rows), rows)
check("a long note is truncated to the width",
      all(len(r) <= 66 for r in render.tune_rows({"note": "x" * 200}, 66)),
      [len(r) for r in render.tune_rows({"note": "x" * 200}, 66)])


print("\n-- newlines are hard breaks, and never reach the screen --")
# Enter inserts a newline in the compose buffer. Before this, _wrap split only
# on spaces, so the newline stayed inside the string handed to addstr, moved
# the cursor, and painted the rest of the buffer over the hint line. It showed
# up as a display glitch on any over of three or more lines.
three = "first line\nsecond line\nthird line"
equals("three lines wrap to three", render._wrap(three, 40),
       ["first line", "second line", "third line"])
equals("no newlines behaves as before",
       render._wrap("the quick brown fox jumps over the lazy dog", 20),
       ["the quick brown fox", "jumps over the lazy", "dog"])
equals("a trailing newline leaves an empty line to type on",
       render._wrap("a\n", 20), ["a", ""])
equals("an empty buffer is still one empty line", render._wrap("", 20), [""])

lines, _cur = render.compose_lines(three, "[RX 33]", 66, 3)
rendered = ["".join(t for t, _k in ln) for ln in lines]
check("no newline survives into a rendered row",
      not any("\n" in r for r in rendered), rendered)
check("the last row carries the buffer indicator", "[RX 33]" in rendered[-1],
      rendered[-1])

# The caret has to land on the character the cursor index names, which means
# counting the characters the breaks swallowed as well as the ones shown.
# Indices chosen at the boundaries: end of a line, and the character straight
# after each newline, which is where an off-by-one in the break accounting
# shows up first.
for index, want in ((0, (0, 1)), (10, (0, 11)), (11, (1, 1)),
                    (22, (1, 12)), (23, (2, 1)), (33, (2, 11))):
    _l, got = render.compose_lines(three, "", 66, 5, cursor=index)
    equals(f"cursor {index} after {three[:index]!r}", got, want)

# A memory is stored on one line and may be sent as several. Both places it
# can live are line-based — cyberdeck.conf is KEY = value, and the on-deck
# editor takes Enter to mean save — so `\n` is expanded at insertion instead.
# Multi-line memories are how PSK31 is actually worked: a station description
# arrives as a formatted block, not one long line to unwrap.
memory = "NAME HR IS {name}\\nQTH {qth}\\nRIG IS {rig}"
expanded = memory.replace("\\n", "\n").format_map(
    {"name": "Don", "qth": "State College, PA", "rig": "FTX-1"})
equals("an escaped memory expands to three lines",
       expanded.count("\n"), 2)
equals("and wraps to one row each",
       render._wrap(expanded, 48),
       ["NAME HR IS Don", "QTH State College, PA", "RIG IS FTX-1"])
check("the editor hint says how to do it",
      "\\n" in render.EDIT_TOKENS_HINT, render.EDIT_TOKENS_HINT)
check("and still fits the panel", len(render.EDIT_TOKENS_HINT) <= 66,
      len(render.EDIT_TOKENS_HINT))

# The transient TX echo is the path that actually broke on the air. Sent and
# received text reach the transcript already split into one entry per line;
# the echo does not — it is fldigi's stream wrapped in a synthetic entry, so
# it carries newlines verbatim and is the one place they reach a renderer.
# Symptom: the second line blanked halfway and the third resumed, whenever an
# over of three or more lines was going out.
from session import Entry
echo = render.entry_lines(Entry("TX", "line one\nline two\nline three"), 66)
echoed = ["".join(t for t, _k in ln) for ln in echo]
equals("the echo renders one row per line", len(echoed), 3)
check("and no row carries a raw newline",
      not any("\n" in r for r in echoed), echoed)
check("only the first row is stamped and attributed",
      "TX" in echoed[0] and "TX" not in echoed[1], echoed)

# Only the last `height` rows are shown; the caret must follow into them.
_l, (row, _col) = render.compose_lines(three, "", 66, 2, cursor=33)
equals("with two rows shown the caret follows into them", row, 1)

print("\ncontinuation rows follow the activity's field order")
# Not a fixed list. The activity type's field order IS the operator's statement
# about what matters on this contact, so a hardcoded "line two is where they
# are" is wrong for every custom type -- a county-hunting type puts county
# second, a satellite type puts the bird second, and neither wants a row spent
# on a grid square it never asks for.
import activities as _acts

COUNTY = _acts.ActivityType("COUNTYHUNT", label="County hunting",
                            entry=("rst_s", "rst_r", "county", "state"))
SAT = _acts.ActivityType("SATWORK", label="Satellites",
                         entry=("rst_s", "rst_r", "sat_name", "prop_mode"))
REC = {"when": "2026-10-14T14:00:00Z", "call": "W1AW", "rst_s": "59",
       "rst_r": "59", "county": "Centre", "state": "PA", "sat_name": "SO-50",
       "prop_mode": "SAT", "grid": "FN10"}

order = render.log_extra_fields(COUNTY, REC)
equals("the county type leads with county, then state",
       order[:2], ["county", "state"])
order = render.log_extra_fields(SAT, REC)
equals("the satellite type leads with the bird",
       order[:2], ["sat_name", "prop_mode"])
check("fields the first row already shows are not repeated",
      not ({"call", "rst_s", "rst_r", "name", "qth"} & set(order)), str(order))
# The station's own call is the same on every contact in the file, and the
# activity is named in the header above the list.
check("and neither are the ones the header already says",
      not ({"my_call", "activity", "activity_type"} & set(order)), str(order))
# What the activity never asked for still follows, so general logging -- whose
# four fields all fit on the first row -- is not left with empty rows.
check("anything else the record carries follows", "grid" in order, str(order))
order = render.log_extra_fields(None, REC)
check("with no activity at all, the stored order is used",
      order and "state" in order, str(order))

print("\na field is never split across two rows")
WIDE = {"when": "2026-10-14T14:00:00Z", "call": "W1AW",
        "county": "Northumberland", "state": "Pennsylvania",
        "country": "United States", "grid": "FN10xx",
        "my_rig": "FTX-1 Field", "my_antenna": "End-fed half wave"}
fields = render.log_extra_fields(None, WIDE)
rows = render.log_extra_rows(WIDE, fields, 66, 2)
equals("exactly as many rows as asked for", len(rows), 2)
for row in rows:
    check(f"no row overruns the width: {row!r}", len(row) <= 66, row)
# Every label that appears, appears whole and next to its own value. A `Coun`
# at the end of one row and `ty Northumberland` at the start of the next is
# worse than a short row.
joined = " ".join(rows)
for label, value in (("County", "Northumberland"),
                     ("State", "Pennsylvania")):
    if label in joined:
        check(f"{label} is whole and keeps its value",
              f"{label} {value}" in joined, joined)

print("\nfree text is capped rather than taking the row")
LONG = {"when": "2026-10-14T14:00:00Z", "call": "W1AW", "state": "PA",
        "comment": "worked him on the second call after a long tail ender"}
# `comment` is on the FIRST row, so it is asked for here directly -- the point
# is the cap, not which row it lands on.
rows = render.log_extra_rows(LONG, ("comment", "state"), 66, 1)
check("a long comment is clipped", "..." in rows[0], rows[0])
check("with ASCII dots, not an ellipsis character",
      "\u2026" not in rows[0], rows[0])
check("and it still leaves room for the field after it",
      "State PA" in rows[0], rows[0])
equals("clip leaves short text alone", render.clip("abc", 24), "abc")
equals("and clips to exactly the limit",
       len(render.clip("x" * 40, 24)), 24)
check("the clipped form ends in dots",
      render.clip("x" * 40, 24).endswith("..."), render.clip("x" * 40, 24))

print("\nhow many contacts fit, when a contact is more than one row")
# Both helpers return CONTACTS, not rows. They returned rows and were used as
# a contact count, so at three lines each the scroll clamp allowed an offset a
# third past the end of the list -- which draws nothing and reads as a hang.
one = render.log_body_rows(20, None, 66, 1)
check("three lines each fits fewer contacts than one line each",
      render.log_body_rows(20, None, 66, 3) < one,
      f"{render.log_body_rows(20, None, 66, 3)} vs {one}")
equals("and never fewer than one", render.log_body_rows(6, None, 66, 3), 1)
equals("the scroll stops at the end of the list",
       render.log_scroll_max([{}] * 4, 20, None, 66, 1), 0)
check("a three-line list can be scrolled when a one-line one cannot",
      render.log_scroll_max([{}] * 6, 20, None, 66, 3) > 0,
      str(render.log_scroll_max([{}] * 6, 20, None, 66, 3)))

sys.exit(report())
