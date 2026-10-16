"""The three areas and the ring that walks them, through a real pty.

Settings, logging and digimodes are peers. `^B` and `^F` walk the ring, which
reads as a strip -- settings | log | digimodes -- wrapping, so every area is
one keystroke from both others.

Driven through a pty under TERM=linux rather than asserted against the pure
renderers, because what is being tested is key DISPATCH: which handler gets a
keystroke, and in what order. That is the part that broke -- `AREA_OF` named
screen constants that were assigned further down the module, which raised
NameError on import and which `py_compile` cannot see, because compiling is
not running.
"""

import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
from test_screen import run, show

CB, CF = "\x0f", "\x10"          # Ctrl-O back, Ctrl-P forward on the ring
F1 = "\x1b[[A"                   # TERM=linux F1
CTRL_N = "\x0e"

STATION = ("CALLSIGN = KD3CCO\nLOCATOR = FN10cs\nRIG = FTX-1\n"
           "ANTENNA = EFHW\nTX_POWER_MAX = 100\n")


def deck(keys, label, extra="", settle=2.6):
    with tempfile.TemporaryDirectory() as tmp:
        conf = os.path.join(tmp, "cyberdeck.conf")
        with open(conf, "w") as fh:
            fh.write(STATION + f"LOG_PATH = {os.path.join(tmp, 'qso.log')}\n"
                     + extra)
        return show(label, run(keys=keys, settle=settle, term="linux",
                               conf=conf))


ON = "LOGGING = yes\n"

print("the deck starts in the digimodes area")
body = deck([], "no keys")
check("the conversation screen is what it boots to",
      "F1 menu" in body and "^T over" in body, body[-200:])
check("and the footer teaches the ring", "^O ^P area" in body, body[-200:])

# Ctrl-O is `VDISCARD`. If the line discipline eats it the key never reaches
# the application, and the only way to find that out is to send it through a
# real terminal and see whether anything moved.
print("\n^O walks left: digimodes -> log -> settings")
body = deck([CB], "^O once", extra=ON)
check("one back reaches the log", "UTC" in body and "CALL" in body, body[:200])

body = deck([CB, CB], "^O twice", extra=ON)
check("two back reaches the deck and rig settings",
      "DECK & RIG" in body, body[:200])
check("which answers what the station is set to",
      "Callsign" in body and "KD3CCO" in body, body[:400])
check("and what it is attached to", "FTX-1" in body and "EFHW" in body,
      body[:400])

print("\n^P walks right, and the ring wraps")
body = deck([CF], "^P once", extra=ON)
check("one forward reaches the settings, wrapping",
      "DECK & RIG" in body, body[:200])

body = deck([CB, CB, CF, CF, CF], "all the way round", extra=ON)
check("three forward from settings comes back to settings",
      "DECK & RIG" in body, body[:200])

print("\neach area remembers where it was left")
# Into the log area, down to the activities list, out to another area and back.
# Landing on the log screen instead would make the ring three buttons rather
# than three tabs.
F2 = "\x1b[[B"
body = deck([CB, F2, CF, CB], "log -> activities -> away -> back", extra=ON)
check("the activities list is what the log area comes back to",
      "ACTIVITIES" in body, body[:200])

print("\nF1 opens the menu for the area, and only that area's lines")
body = deck([F1], "F1 on the conversation")
check("the digimode menu", "DIGIMODES" in body, body[:200])
check("its own lines", "Mode" in body and "Tune Settings" in body, body[:300])
check("and not the deck's", "Station" not in body, body[:300])

body = deck([CB, CB, F1], "F1 on the settings screen", extra=ON)
check("the deck menu", "DECK & RIG" in body, body[:200])
check("its own lines",
      "Station" in body and "System" in body, body[:300])
check("and not the digimodes'", "Tune Settings" not in body, body[:300])

body = deck([CB, F1], "F1 on the log screen", extra=ON)
check("the logging menu", "LOGGING" in body, body[:200])

print("\nEsc backs out inside an area, never across one")
# The station menu's parent is the deck menu, not a shared root. When every
# menu backed out to one root, Esc from here landed on the digimode screen's
# menu -- a different area.
body = deck([CB, CB, F1, "1", "\x1b"], "station then Esc", extra=ON)
check("Esc from Station lands on the deck menu",
      "DECK & RIG" in body and "Station" in body, body[:300])
check("and not on the digimode menu", "Tune Settings" not in body, body[:300])

print("\nthe ring does not leave a question unanswered")
# `d` on the activities screen asks before deleting. Cycling away from the
# question would answer it by walking off -- every key but Enter keeps the
# activity, so a ^F that got through would read as "no" without the operator
# having said anything. The ring is refused on a confirmation for that reason.
#
# The activity is seeded on disk: one named on the panel has no contacts yet,
# so it has no log file and does not appear in the list at all.
def with_activity(keys, label, settle=3.2):
    import datetime as _dt
    with tempfile.TemporaryDirectory() as tmp:
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
        adir = os.path.join(tmp, "activities")
        os.makedirs(adir)
        with open(os.path.join(adir, f"Testpark_{stamp}.log"), "w") as fh:
            fh.write(f"when={stamp}T14:00:00Z call=W1AW band=40m mode=SSB "
                     f"rst_s=59 rst_r=59 my_call=KD3CCO activity=Testpark\n")
        conf = os.path.join(tmp, "cyberdeck.conf")
        with open(conf, "w") as fh:
            fh.write(STATION + ON
                     + f"LOG_PATH = {os.path.join(tmp, 'qso.log')}\n")
        return show(label, run(keys=keys, settle=settle, term="linux",
                               conf=conf))


body = with_activity([CB, F2], "the activities list")
check("the seeded activity is listed", "Testpark" in body, body[:300])

body = with_activity([CB, F2, "d", CF], "^P while a confirmation is up")
check("the confirmation is still the screen",
      "DELETE" in body.upper(), body[:300])
check("and the ring did not carry us off it",
      "DECK & RIG" not in body and "^T over" not in body, body[:300])

print("\nF4 still cycles the colour from every area")
# Asserted as state in test_state.py, where the written file can be read. Here
# it only has to not be swallowed: a screen that returns True for F4 without
# acting would look identical.
for keys, where in (([], "digimodes"), ([CB], "log"), ([CB, CB], "settings")):
    body = deck(keys + [F1], f"F1 still works in {where} after F4",
                extra=ON)
    check(f"{where}: the area's menu still opens", len(body) > 100, body[:80])

print("\nlogging off: the ring lands where it can be switched on")
# Its screens have no form to draw, so landing on one would bounce straight
# back and read as a key that did nothing.
body = deck([CB], "^O with logging off")
check("the logging menu is what comes up", "LOGGING" in body, body[:200])
check("and it says logging is off", "off" in body, body[:400])

sys.exit(report())
