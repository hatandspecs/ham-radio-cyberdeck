"""The danger zone: the three ways to throw contacts away.

Two halves, for the reason every destructive path on this deck is tested in
two halves. What the question SAYS is checked against the pure renderers,
because that is where the counts are built. What the keys DO is checked
through a pty against the real program, because a confirmation that is drawn
but whose Enter goes to the wrong handler looks correct in every unit test --
which is a mistake this project has already made (see `_ask_confirm`).

The pty half asserts OUTCOMES, never the question on the last screen. The
harness ends every run with Ctrl-Q, a confirmation is cancelled by any key
except Enter, and so the question is never what is left on screen.
"""
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
from test_screen import run, show

import menus
import qsolog

STATION = ("CALLSIGN = KD3CCO\nLOCATOR = FN10cs\nRIG = FTX-1\n"
           "ANTENNA = EFHW\n")

F1 = "\x1b[[A"                   # TERM=linux F1
RING_FWD = "\x10"                # Ctrl-P: the log is one stop from the boot
ENTER, ESC = "\r", "\x1b"

# Three contacts in one session and one belonging to no activity, so "this
# activity's QSOs" and "every QSO" are different numbers. Were they the same,
# every assertion below would pass with the two actions swapped.
BEGAN = "2026-10-15T13:00:00Z"
IN_SESSION = [
    f"activity_start={BEGAN} when=2026-10-15T14:00:00Z call=W3ABC band=20m "
    f'mode=FT8 activity="Bald Eagle SP"',
    f"activity_start={BEGAN} when=2026-10-15T14:05:00Z call=K3XYZ band=20m "
    f'mode=FT8 activity="Bald Eagle SP"',
    f"activity_start={BEGAN} when=2026-10-15T14:10:00Z call=N3QRP band=40m "
    f'mode=FT8 activity="Bald Eagle SP"',
]
OUTSIDE = "when=2026-10-15T09:00:00Z call=W1AW band=20m mode=FT8"
SEEDED = "\n".join(IN_SESSION + [OUTSIDE]) + "\n"

ON = ("LOGGING = yes\nACTIVITY = Bald Eagle SP\n"
      f"ACTIVITY_START = {BEGAN}\n")


def deck(keys, label, conf_extra=ON, log_body=SEEDED, settle=2.8):
    """Run the program with a log of our own. Returns (screen text, records).

    The log is a temporary file, so a test can never touch the operator's own
    contact log -- and LOG_PATH is written after `conf_extra` so a scenario
    cannot set it by hand and have it silently overridden.
    """
    with tempfile.TemporaryDirectory() as tmp:
        log_path = os.path.join(tmp, "qso.log")
        if log_body:
            with open(log_path, "w") as fh:
                fh.write(log_body)
        conf_path = os.path.join(tmp, "cyberdeck.conf")
        with open(conf_path, "w") as fh:
            fh.write(STATION + conf_extra + f"LOG_PATH = {log_path}\n")
        body = show(label, run(keys=keys, settle=settle, term="linux",
                               conf=conf_path))
        left = []
        if os.path.exists(log_path):
            with open(log_path) as fh:
                left = [l.strip() for l in fh if l.strip()]
        return body, left


# -- what the question says ---------------------------------------------

print("the danger zone names its actions and counts each one")
m = menus.danger_menu(activity="Bald Eagle SP", contacts=412, session=37,
                      sessions=4)
equals("it is titled as what it is", m["title"], "DANGER ZONE")
keys = [k for k, _label in m["items"]]
# `f` fills gaps from HamQTH and is the one line here that destroys
# nothing. It is on this menu because it rewrites the whole log in one
# pass, which is the property the rest of this screen shares.
equals("three that destroy, and one that fills", keys, ["a", "s", "m", "f"])
labels = dict(m["items"])
check("and the filling one says so",
      labels["f"].startswith("Fill in"), labels["f"])
text = "\n".join(label for _k, label in m["items"])
check("the one that destroys nothing is first",
      m["items"][0][1].startswith("Forget all activities"), m["items"][0][1])
check("and says so", "contacts kept" in m["items"][0][1], m["items"][0][1])
check("the session count is the session's", "37 from Bald Eagle SP" in text,
      text)
check("the whole-log count is the whole log's", "412 in the whole log" in text,
      text)
check("and the footer says every one asks", "each one asks" in m["footer"],
      m["footer"])

print("\nwith no activity the session line says so rather than naming nothing")
m = menus.danger_menu(activity="", contacts=5, session=0, sessions=0)
check("it reads as an absence", "(no activity)" in m["items"][1][1],
      m["items"][1][1])

print("\nthe logging menu offers it, and offers it last")
log = menus.log_menu(True, count=4, activity="Bald Eagle SP")
items = [k for k, _l in log["items"] if k]
check("z is the key", "z" in items, str(items))
equals("and it is the last item", items[-1], "z")
text = "\n".join(l for _k, l in log["items"])
check("it is named as a danger zone", "Danger zone" in text, text)

print("\nEsc out of it returns to the logging menu")
equals("the parent is the logging menu", menus.MENU_PARENT.get("danger"),
       "logging")


# -- what the keys do ----------------------------------------------------

print("\nz reaches the screen, with this log's own counts on it")
body, left = deck([RING_FWD, F1, "z"], "F1 z")
check("the title is on screen", "DANGER ZONE" in body, body[-900:])
check("the session's three are counted", "3 from Bald Eagle SP" in body,
      body[-900:])
check("the log's four are counted", "4 in the whole log" in body, body[-900:])
equals("and opening it destroyed nothing", len(left), 4)

print("\nEsc goes back to the logging menu, not out of the application")
body, _left = deck([RING_FWD, F1, "z", ESC], "F1 z Esc", settle=2.9)
check("the logging menu is showing again", "Danger zone" in body, body[-900:])
check("and the danger zone is not", "DANGER ZONE" not in body, body[-900:])

print("\ns: any key but Enter keeps this activity's contacts")
# `q` cancels the question; the harness's own Ctrl-Q then asks to quit.
body, left = deck([RING_FWD, F1, "z", "s", "q"], "F1 z s q", settle=3.0)
equals("all four are still there", len(left), 4)

print("\ns then Enter deletes this activity's contacts and only those")
body, left = deck([RING_FWD, F1, "z", "s", ENTER], "F1 z s Enter", settle=3.1)
equals("one contact is left", len(left), 1)
check("it is the one outside the activity", "W1AW" in (left[0] if left else ""),
      str(left))
check("and the deck says how many went",
      "3 contacts deleted from Bald Eagle SP" in body, body[-400:])

print("\nm: any key but Enter keeps the whole log")
body, left = deck([RING_FWD, F1, "z", "m", "q"], "F1 z m q", settle=3.0)
equals("all four are still there", len(left), 4)

print("\nm then Enter empties the log, and leaves the file in place")
body, left = deck([RING_FWD, F1, "z", "m", ENTER], "F1 z m Enter", settle=3.1)
equals("no contacts are left", left, [])
check("and the deck says so", "log emptied" in body, body[-400:])

print("\na then Enter forgets the activities and keeps every contact")
body, left = deck([RING_FWD, F1, "z", "a", ENTER], "F1 z a Enter", settle=3.2)
equals("every contact survived", len(left), 4)
check("the labels survived too",
      sum("Bald Eagle SP" in l for l in left) == 3, str(left))
check("and the header fell back to the master log",
      "master log" in "\n".join(body.splitlines()[:4]).lower(), body[:300])

print("\nthe empty cases say so instead of asking")
body, left = deck([RING_FWD, F1, "z", "m"], "empty log, m",
                  conf_extra="LOGGING = yes\n", log_body="", settle=3.0)
check("an empty log is not worth a confirmation",
      "already empty" in body, body[-400:])

body, left = deck([RING_FWD, F1, "z", "s"], "no activity, s",
                  conf_extra="LOGGING = yes\n",
                  log_body=OUTSIDE + "\n", settle=3.0)
check("with no activity selected, s explains itself",
      "no activity selected" in body, body[-400:])
equals("and the one contact is untouched", len(left), 1)

sys.exit(report())
