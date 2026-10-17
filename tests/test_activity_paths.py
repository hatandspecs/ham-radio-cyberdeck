"""The routes an operator takes through activities and schemas — §7i.

Driven through a pty against the real program, because every one of these is
a question about which handler gets a keystroke and what the NEXT screen
shows. The pure halves are in `test_activity_follow.py` (the log file) and
`test_logform.py` (`LogForm.typed`).

Assertions are on the screen the deck ends up on, or on the log file. Never
on a confirmation: the harness ends every run with Ctrl-Q and any key but
Enter cancels one, so a question is never the last thing drawn.
"""
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
from test_screen import run, show

STATION = ("CALLSIGN = KD3CCO\nLOCATOR = FN10cs\nRIG = FTX-1\n"
           "ANTENNA = EFHW\n")

RING_FWD = "\x10"                # ^P: the boot screen is DECK & RIG; the log
F1 = "\x1b[[A"                   # TERM=linux
F2 = "\x1b[[B"
F3 = "\x1b[[C"
DOWN = "\x1b[B"
ENTER, ESC, CTRL_X = "\r", "\x1b", "\x18"
CTRL_U = "\x15"          # clears the editor; Ctrl-X does not

BEGAN = "2026-10-15T13:00:00Z"
# A park activation with a reference, and one contact outside any activity.
POTA = (f'activity_start={BEGAN} when=2026-10-15T14:00:00Z call=W3ABC '
        f'band=20m mode=SSB rst_s=59 rst_r=59 activity="Bald Eagle SP" '
        f'activity_type=POTA my_park=US-5678 park=US-1234\n'
        f'when=2026-10-15T09:00:00Z call=W1AW band=20m mode=SSB\n')


def deck(keys, label, extra="", log_body=POTA, settle=3.0):
    """Run with a seeded log. Returns (screen text, records left)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "qso.log")
        if log_body:
            with open(path, "w") as fh:
                fh.write(log_body)
        conf = os.path.join(tmp, "cyberdeck.conf")
        with open(conf, "w") as fh:
            fh.write(STATION + "LOGGING = yes\n" + extra
                     + f"LOG_PATH = {path}\n")
        body = show(label, run(keys=keys, settle=settle, term="linux",
                               conf=conf))
        left = []
        if os.path.exists(path):
            with open(path) as fh:
                left = [l.strip() for l in fh if l.strip()]
        return body, left


# -- the schema follows the activity -------------------------------------

print("resuming a session applies the schema it was logged under")
# Boot on the master log under general logging, then resume the POTA session
# from the list. Row 0 is the master log, so one Down reaches it.
body, _ = deck([RING_FWD, F2, DOWN, ENTER], "resume the POTA session",
               settle=3.4)
check("the header names the activity", "Bald Eagle SP" in body, body[:120])
check("and says which schema came with it", "POTA" in body, body[:120])
check("the park column is there, so the schema really changed",
      "REF" in body, body[:300])
check("and this station's reference came back too",
      "US-5678" in body, body[:400])

print("\nthe activities list says which schema each session will resume in")
body, _ = deck([RING_FWD, F2], "the list names the schema", settle=3.0)
check("the session's schema is on its row", "pota" in body, body[:300])
check("the master log is given none", "master log" in body, body[:300])

print("\nswitching to the master log keeps the schema and drops the reference")
# The master log spans every schema, so it has none of its own to restore --
# but the reference has to go, or contacts made after the activation ends go
# on claiming the park.
body, _ = deck([RING_FWD, F2, DOWN, ENTER, F2, ENTER],
               "POTA session, then the master log", settle=3.8)
check("the header is the master log", "master log" in body, body[:120])
check("the reference is gone from the form",
      "US-5678" not in body, body[-500:])

print("\nand resuming the activity brings both back")
body, _ = deck([RING_FWD, F2, DOWN, ENTER, F2, ENTER, F2, DOWN, ENTER],
               "there and back again", settle=4.2)
check("the activity is named again", "Bald Eagle SP" in body, body[:120])
check("the reference is back", "US-5678" in body, body[-500:])
check("and the park column with it", "REF" in body, body[:300])


# -- keep the current schema when naming a new activity ------------------

print("\nnaming an activity opens the picker; Esc keeps the schema")
body, _ = deck([RING_FWD, F3, "g", F2, "n"] + list("Field Day") + [ENTER, ESC],
               "name one, then Esc out of the picker", settle=4.0)
check("the new activity is named on the header", "Field Day" in body,
      body[:120])
check("the schema is still general logging — no schema word on the header",
      "POTA" not in body[:120], body[:120])
check("and Esc landed on the LOG screen, not a menu",
      "←→ field" in body, body[-200:])
check("so the form is there to type into", "Call" in body, body[-400:])

print("\nthe picker says Esc keeps it")
body, _ = deck([RING_FWD, F3], "the schema picker", settle=3.0)
check("the footer says so", "Esc keep" in body, body[-200:])
check("and advertises the edit key", "e+n edit" in body, body[-200:])


# -- switching schema is refused over a part-typed contact ---------------

print("\na part-typed contact blocks a schema change")
body, _ = deck([RING_FWD] + list("W3ABC") + [F3, "g"],
               "type a callsign, then try to change schema", settle=3.6)
check("the deck says what is in the way", "still typed" in body, body[-400:])
check("and how to get past it", "^X to clear" in body, body[-400:])
check("the callsign is still on the form", "W3ABC" in body, body[-500:])

print("\nclearing it first lets the change through")
body, _ = deck([RING_FWD] + list("W3ABC") + [CTRL_X, F3, "g"],
               "clear it, then change schema", settle=3.8)
check("nothing is in the way now", "still typed" not in body, body[-400:])
check("and the schema change was reported", "schema" in body, body[-400:])

print("\nwhat the DECK prefilled does not block it")
# The reports, the frequency, the mode and the rig are all filled in without
# being typed, and a form the operator has not touched must not refuse.
body, _ = deck([RING_FWD, F3, "g"], "change schema on an untouched form",
               settle=3.4)
check("the change went through", "still typed" not in body, body[-400:])


# -- renaming a session --------------------------------------------------

print("\nr renames the selected session")
keys = [RING_FWD, F2, DOWN, "r", CTRL_U] + list("Black Moshannon") + [ENTER]
body, left = deck(keys, "rename the session", settle=4.0)
check("the deck says what moved", "relabeled" in body, body[-300:])
labelled = [l for l in left if "Black Moshannon" in l]
equals("the contact carries the new name", len(labelled), 1)
check("and kept its session start", f"activity_start={BEGAN}" in labelled[0],
      labelled[0])
check("and its schema", "activity_type=POTA" in labelled[0], labelled[0])
check("the contact outside the activity is untouched",
      any("W1AW" in l and "activity=" not in l for l in left), str(left))

print("\nthe master log cannot be renamed")
body, left = deck([RING_FWD, F2, "r"], "r on the master row", settle=3.2)
check("it says so", "cannot be renamed" in body, body[-300:])
check("and no contact changed",
      any("Bald Eagle SP" in l for l in left), str(left))

print("\na nameless rename is refused")
keys = [RING_FWD, F2, DOWN, "r", CTRL_U, ENTER]
body, left = deck(keys, "rename to nothing", settle=3.6)
check("the contact keeps its name",
      any("Bald Eagle SP" in l for l in left), str(left))

sys.exit(report())
