"""The log screen's layout, at every width the deck has ever run at.

Pure, like the other screen renderers: a list of lines of (text, attr)
segments and nothing about curses, so the thing an operator will stare at
during an activation can be looked at here first.

Three properties are load-bearing and none of them is obvious from the code:

  * **every line is exactly `width` characters.** An unpadded line leaves
    whatever the previous screen drew in those columns, and this screen is
    reached from the transcript, which has text all the way across. The
    pairing screen learned the same lesson with its footer.
  * **a callsign never truncates.** A log you cannot read back is not a log.
    The QTH is what gets cut on a narrow screen, because it is the one field
    nobody checks mid-activation.
  * **the newest contacts are the ones shown.** During an activation the
    question is always "did that last one go in", never "what did I work an
    hour ago".
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import render

plain = render.plain

RECS = [
    {"when": "2026-10-10T16:04:00Z", "call": "W3ABC", "rst_s": "59",
     "rst_r": "57", "park": "US-1234", "name": "Bob", "qth": "Pittsburgh, PA"},
    {"when": "2026-10-10T16:07:00Z", "call": "K2XYZ", "rst_s": "59",
     "rst_r": "59", "name": "Jim", "qth": "Albany, NY"},
    {"when": "2026-10-10T16:09:00Z", "call": "N3QQQ", "rst_s": "59",
     "rst_r": "55", "park": "US-0042"},
    {"when": "2026-10-10T16:11:00Z", "call": "KD8SLG/P", "rst_s": "599",
     "rst_r": "599"},
]
HEAD = {"band": "20m", "mode": "SSB", "freq": "14.250",
        "my_park": "US-5678", "count": 4, "clock": "16:12Z"}


def lines(*a, **kw):
    return [plain(l) for l in render.log_screen(*a, **kw)]


print("a log of ordinary contacts has no trace of the activity fields")
# The general-purpose property, asserted rather than asserted about: a set of
# records with no park produces a screen with no park column and a header with
# no park slot, so the layout is not paying for a feature nobody used.
ORD = [
    {"when": "2026-10-10T16:04:00Z", "call": "W3ABC", "rst_s": "59",
     "rst_r": "57", "name": "Bob", "qth": "Pittsburgh, PA", "comment": "QRP 5W"},
    {"when": "2026-10-10T16:07:00Z", "call": "K2XYZ", "rst_s": "59",
     "rst_r": "59", "comment": "first one on 40m"},
]
ord_rows = lines(ORD, "", 66, 10,
                 header={"band": "40m", "mode": "SSB", "freq": "7.040",
                         "count": 2, "clock": "16:12Z"})
check("no park in the header", "US-" not in ord_rows[0], ord_rows[0])
check("and the header is otherwise full", "40m" in ord_rows[0]
      and "7.040" in ord_rows[0] and "2 QSOs" in ord_rows[0], ord_rows[0])
# Derived from the renderer's own constants rather than written out, so a
# layout change moves the test with the code instead of breaking it.
HEADING = render.LOG_HEADING_ROW
FIRST, SECOND = render.LOG_ROW0, render.LOG_ROW0 + 1
check("the columns are named", "CALL" in ord_rows[HEADING]
      and "UTC" in ord_rows[HEADING], ord_rows[HEADING])
check("and an ordinary log is offered no exchange or serial column",
      "EXCH" not in ord_rows[HEADING] and "MY#" not in ord_rows[HEADING],
      ord_rows[HEADING])
# This replaces an assertion that compared a value to itself and so could
# never fail. What matters is that the call sits UNDER its heading: a heading
# naming a column the rows do not use would be worse than no heading.
equals("the call sits under the CALL heading",
       ord_rows[FIRST].index("W3ABC"), ord_rows[HEADING].index("CALL"))
equals("and the report under RST",
       ord_rows[FIRST].index("59/57"), ord_rows[HEADING].index("RST"))
equals("the comment is on the row", "QRP 5W" in ord_rows[FIRST], True)
equals("a comment with no name is too",
       "first one on 40m" in ord_rows[SECOND], True)
check("and the two trailing texts line up",
      ord_rows[FIRST].index("QRP") > 30
      and ord_rows[SECOND].index("first") > 30,
      "\n".join(ord_rows[FIRST:SECOND + 1]))

my_park_absent = lines(ORD, "", 66, 10, header={"count": 2, "my_park": ""})[0]
check("an empty my_park is dropped, not drawn blank",
      "LOG" in my_park_absent and len(my_park_absent) == 66, my_park_absent)

print("\nshape")
for w, h in ((50, 12), (66, 20), (80, 24), (100, 30)):
    rows = lines(RECS, "W3ABC 59", w, h, header=HEAD)
    equals(f"{w}x{h}: exactly {h} rows", len(rows), h)
    bad = [i for i, r in enumerate(rows) if len(r) != w]
    check(f"{w}x{h}: every row is {w} wide", not bad,
          f"rows {bad[:4]} are {[len(rows[i]) for i in bad[:4]]}")

print("\nthe header says what is about to be read aloud")
top = lines(RECS, "", 66, 20, header=HEAD)[0]
for field in ("20m", "SSB", "14.250", "US-5678"):
    check(f"{field} is on it", field in top, top)
check("and the count", "4 QSOs" in top, top)
check("and the clock", "16:12Z" in top, top)

one = lines(RECS[:1], "", 66, 20, header={"count": 1})[0]
check("one contact is singular", "1 QSO " in one, one)

print("\nnarrow headers shed fields rather than overflow")
for w in (40, 46, 50, 56):
    row = lines(RECS, "", w, 14, header=HEAD)[0]
    equals(f"{w}: still exactly {w}", len(row), w)
    check(f"{w}: still says LOG", "LOG" in row, row)

print("\ncontacts")
body = lines(RECS, "", 66, 20,
             header=HEAD)[render.LOG_ROW0:render.LOG_ROW0 + 4]
check("oldest of those shown first", body[0].strip().startswith("16:04"), body[0])
check("time as HH:MM", "16:04" in body[0], body[0])
check("call", "W3ABC" in body[0], body[0])
check("both reports", "59/57" in body[0], body[0])
check("park", "US-1234" in body[0], body[0])
check("name", "Bob" in body[0], body[0])
check("qth", "Pittsburgh, PA" in body[0], body[0])
check("a comment is truncated before anything else is",
      "W3ABC" in plain(render.log_screen(
          [dict(RECS[0], comment="x" * 200)], "", 66, 8,
          header=HEAD)[render.LOG_ROW0])) 
check("a contact with no park still lines up",
      "K2XYZ" in body[1] and "Jim" in body[1], body[1])
check("a stroke callsign is not truncated", "KD8SLG/P" in body[3], body[3])

print("\nthe newest are the ones shown")
many = [dict(RECS[1], call=f"K{i}ABC", when=f"2026-10-10T16:{i:02d}:00Z")
        for i in range(40)]
small = lines(many, "", 66, 12, header={"count": 40})
joined = "\n".join(small)
check("the last one is there", "K39ABC" in joined, joined)
check("the first one is not", "K0ABC " not in joined, joined)

print("\nno contacts yet")
empty = lines([], "", 66, 20, header={"count": 0})
equals("still a full screen", len(empty), 20)
check("and nothing claims to be a contact",
      not any(":" in r and "QSO" not in r and "LOG" not in r
              and "Esc" not in r for r in empty[2:-3]),
      "\n".join(empty[2:6]))

print("\nthe entry line")
row = lines(RECS, "W3ABC 59 57", 66, 20, header=HEAD)[-3]
check("prompt", row.startswith(" > "), row)
check("what was typed", "W3ABC 59 57" in row, row)
check("a cursor at the end", "█" in row, row)

mid = lines(RECS, "W3ABC", 66, 20, header=HEAD, cursor=2)[-3]
check("a cursor in the middle does not add a block", "█" not in mid, mid)
check("and the text is all still there", "W3ABC" in mid, mid)

blank = lines(RECS, "", 66, 20, header=HEAD)[-3]
check("an empty line still shows the prompt and cursor",
      blank.startswith(" > ") and "█" in blank, blank)

print("\nmessages and the footer")
msg = lines(RECS, "", 66, 20, header=HEAD, message="-- rigctld unreachable")
check("the message is shown", "rigctld unreachable" in msg[-2], msg[-2])
check("the footer says how to leave", "Esc back" in msg[-1], msg[-1])
check("and how to commit", "Enter log" in msg[-1], msg[-1])

quiet = lines(RECS, "", 66, 20, header=HEAD)
equals("no message leaves a blank line, not a missing one",
       len(quiet[-2]), 66)

print("\na very small screen still works")
tiny = lines(RECS, "W3ABC", 40, 8, header=HEAD)
equals("8 rows", len(tiny), 8)
check("entry line survives", " > W3ABC" in tiny[-3], tiny[-3])
check("footer survives", "Esc" in tiny[-1], tiny[-1])

print("\nthe row constant tracks the layout")
equals("LOG_ROW0 is where the first contact is drawn", render.LOG_ROW0, 3)
check("and that is where it actually is",
      "16:04" in lines(RECS, "", 66, 20, header=HEAD)[render.LOG_ROW0])

print("\nan activation reserves what general logging omits")
# There is no `pota` flag any more — POTA is ACTIVITY = POTA, and the header
# carries the activity and this station's reference. Setting a reference is
# what reserves the column: during an activation a column that appeared on the
# first park-to-park would shift every row under it, which is worse than one
# that sits empty.
gen = lines(ORD, "", 66, 10, header={"count": 2})
act = lines(ORD, "", 66, 10,
            header={"count": 2, "activity_type": "POTA",
                         "my_park": "US-5678"})
check("general logging says only LOG", "LOG" in gen[0] and "POTA" not in gen[0],
      gen[0])
check("the activity is named on the header", "POTA" in act[0], act[0])
check("and so is the reference", "US-5678" in act[0], act[0])
check("GENERAL is not printed as though it were an activity",
      "GENERAL" not in lines(ORD, "", 66, 10,
                             header={"count": 2,
                                     "activity_type": "GENERAL"})[0])
check("an activity needing a reference says when none is set",
      "no reference set" in lines(
          ORD, "", 66, 10,
          header={"count": 2, "activity_type": "POTA",
                  "needs_ref": True})[0])
check("the reference column is reserved even with no parks logged",
      act[render.LOG_ROW0].index("Bob") > gen[render.LOG_ROW0].index("Bob"),
      f"general={gen[render.LOG_ROW0]!r} "
      f"activation={act[render.LOG_ROW0]!r}")
for w, h in ((50, 12), (66, 20), (80, 24)):
    rows = lines(ORD, "W3ABC", w, h,
                 header=dict(HEAD, activity="POTA", my_park="US-5678"))
    bad = [i for i, r in enumerate(rows) if len(r) != w]
    check(f"{w}x{h}: an activation still pads every row", not bad, str(bad[:4]))

print("\nthe question asked before something is destroyed")
# Its own screen, not a line on another one: deleting a log deletes contacts,
# and a prompt sharing a screen with the thing it is about gets answered by
# reflex. The pty tests assert the OUTCOME of answering it; this asserts what
# it says, because any key but Enter cancels and the harness's own quit key
# therefore always lands on the screen after the cancel.
conf = [plain(l) for l in render.confirm_screen(
    "DELETE ACTIVITY",
    ["Bald Eagle SP  2026-10-11", "",
     "12 contacts will be permanently deleted.",
     "File: Bald-Eagle-SP_2026-10-11.log"], 66, 12)]
flat = "\n".join(conf)
check("it is titled by what it will do", "DELETE ACTIVITY" in conf[0], conf[0])
check("it names the thing", "Bald Eagle SP" in flat, flat)
check("and the date that tells it from another activation",
      "2026-10-11" in flat, flat)
check("it says how much is lost", "12 contacts" in flat, flat)
check("and that it cannot be undone", "permanently" in flat, flat)
check("Enter is the one key that does it", "Enter delete" in conf[-1], conf[-1])
check("Esc keeps it", "Esc keep" in conf[-1], conf[-1])
check("and so does everything else", "any other key" in conf[-1], conf[-1])
for row in conf:
    equals("every row is padded to the width", len(row), 66)
equals("and it fits the height asked for", len(conf), 12)

one = "\n".join(plain(l) for l in render.confirm_screen(
    "DELETE ACTIVITY", ["Testpark", "", "1 contact will be permanently "
                        "deleted."], 66, 12))
check("one contact is singular", "1 contact will" in one, one)

print("\nactivities, listed to be resumed or deleted")
ROWS = [{"name": "Bald Eagle SP", "date": "2026-10-11", "contacts": 12,
         "path": "/x/Bald-Eagle-SP_2026-10-11.log"},
        {"name": "PAQP", "date": "2026-10-10", "contacts": 1, "path": "/x/p.log"}]
acts = [plain(l) for l in render.activity_screen(ROWS, 0, 66, 14,
                                                 current="PAQP")]
flat = "\n".join(acts)
check("titled", "ACTIVITIES" in acts[0], acts[0])
check("both are listed", "Bald Eagle SP" in flat and "PAQP" in flat, flat)
check("with their dates", "2026-10-11" in flat and "2026-10-10" in flat, flat)
check("and their counts", "12 QSOs" in flat and "1 QSO" in flat, flat)
check("the one in use is marked", "* PAQP" in flat, flat)
check("and the one being pointed at", "\u25b8" in flat, flat)
check("the footer says what the keys do",
      all(w in acts[-1] for w in ("Enter resume", "n new", "d delete")),
      acts[-1])
for row in acts:
    equals("every activity row is padded", len(row), 66)

empty = "\n".join(plain(l) for l in render.activity_screen([], 0, 66, 14))
check("an empty list explains itself rather than looking broken",
      "nothing logged under an activity" in empty, empty)

sys.exit(report())
