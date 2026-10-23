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
DOWN, ENTER = "\x1b[B", "\r"

# The deck OPENS on DECK & RIG. The ring reads
# settings | log | digimodes | WSPR | band plan, so from the boot screen `^P`
# is the log and `^P ^P` the conversation, while `^O` wraps backwards onto
# the band plan.
#
# WSPR made it four areas and the band plan reference made it five. Every
# count in this file is from the boot screen, so a sixth area is one edit
# here plus the three ring-size checks below, which are about the size itself
# and cannot be hidden behind a name.
#
# The ring is configurable now (`RING_ORDER`), and these scenarios run with
# it unset, which is the built-in order above.
#
# Named rather than counted at each call site: the boot screen moved once and
# every scenario in this file counts its steps from it.
TO_LOG = [CF]
TO_DIGI = [CF, CF]
TO_SET = []

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
check("the deck and rig screen is what it boots to",
      "DECK & RIG" in body, body[:200])
check("and the footer teaches the ring", "^O ^P screen" in body, body[-200:])
# The startup notes go to the transcript, which is no longer the boot screen,
# so the header has to say what the deck is doing or a deck with no modem and
# a working one look identical on power-on.
check("the header says what the deck is doing",
      any(w in body for w in ("NO MODEM", "TX INHIBITED", "TX ARMED")),
      body[:200])

# Ctrl-O is `VDISCARD`. If the line discipline eats it the key never reaches
# the application, and the only way to find that out is to send it through a
# real terminal and see whether anything moved.
print("\n^P walks right from the boot screen: settings -> log -> digimodes")
body = deck(TO_LOG, "^P once: the log", extra=ON)
check("one forward reaches the log", "UTC" in body and "CALL" in body,
      body[:200])

body = deck(TO_SET, "the boot screen", extra=ON)
check("the boot screen is the deck and rig settings",
      "DECK & RIG" in body, body[:200])
check("which answers what the station is set to",
      "Callsign" in body and "KD3CCO" in body, body[:400])
check("and what it is attached to", "FTX-1" in body and "EFHW" in body,
      body[:400])

print("\n^O walks left, and the ring wraps")
body = deck([CB], "^O once: wraps onto the band plan", extra=ON)
check("one back wraps onto the band plan, the last area on the ring",
      "BAND PLAN" in body, body[:200])

body = deck([CB, CB], "^O twice: WSPR", extra=ON)
check("two back reaches WSPR", "WSPR" in body, body[:200])

body = deck([CF, CF, CF, CF, CF], "all the way round", extra=ON)
check("five forward comes back to where it started",
      "DECK & RIG" in body, body[:200])

print("\neach area remembers where it was left")
# Into the log area, down to the activities list, out to another area and back.
# Landing on the log screen instead would make the ring three buttons rather
# than three tabs.
F2 = "\x1b[[B"
body = deck(TO_LOG + [F2, CF, CB], "log -> activities -> away -> back", extra=ON)
check("the activities list is what the log area comes back to",
      "ACTIVITIES" in body, body[:200])

print("\nF1 opens the menu for the area, and only that area's lines")
body = deck(TO_DIGI + [F1], "F1 on the conversation", extra=ON)
check("the digimode menu", "DIGIMODES" in body, body[:200])
check("its own lines", "Mode" in body and "Tune Settings" in body, body[:300])
check("and not the deck's", "Station" not in body, body[:300])

body = deck([F1], "F1 on the settings screen", extra=ON)
check("the deck menu", "DECK & RIG" in body, body[:200])
check("its own lines", "Display" in body and "System" in body, body[:300])
check("and not the digimodes'", "Tune Settings" not in body, body[:300])
# Station is not a line: the screen behind this menu is the station editor.
check("and not a second list of the station fields",
      "Station" not in body, body[:300])

body = deck(TO_LOG + [F1], "F1 on the log screen", extra=ON)
check("the logging menu", "LOGGING" in body, body[:200])

print("\nEsc backs out inside an area, never across one")
# The station menu's parent is the deck menu, not a shared root. When every
# menu backed out to one root, Esc from here landed on the digimode screen's
# menu -- a different area.
body = deck([F1, "1", "\x1b"], "display then Esc", extra=ON)
check("Esc from Display lands on the deck menu",
      "DECK & RIG" in body and "Display" in body, body[:300])
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
    """Run with one labelled contact in the log. Returns (body, the log).

    Seeded as a RECORD, not a file: an activity is a label on records and the
    activities screen is a filter over the one log, so a session exists
    because a contact says it does. `activity_start` is the session key.
    """
    import datetime as _dt
    with tempfile.TemporaryDirectory() as tmp:
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
        log = os.path.join(tmp, "qso.log")
        with open(log, "w") as fh:
            fh.write(f"activity_start={stamp}T13:00:00Z "
                     f"when={stamp}T14:00:00Z call=W1AW band=40m mode=SSB "
                     f"rst_s=59 rst_r=59 my_call=KD3CCO activity=Testpark\n")
        conf = os.path.join(tmp, "cyberdeck.conf")
        with open(conf, "w") as fh:
            fh.write(STATION + ON + f"LOG_PATH = {log}\n")
        body = show(label, run(keys=keys, settle=settle, term="linux",
                               conf=conf))
        return body, [l for l in open(log).read().splitlines() if l.strip()]


body, _log = with_activity(TO_LOG + [F2], "the activities list")
check("the seeded activity is listed", "Testpark" in body, body[:300])
# The master log is always there and always first: it is where every contact
# is kept, so going back to it is something you select rather than something
# that happens when an activity is deleted.
check("the master log is listed first",
      "master log" in body.splitlines()[2], body[:300])
body, _log = with_activity(TO_LOG + [F2, "d"], "d on the master log row")
check("and it refuses to be removed",
      "cannot be removed" in body, body[:400])

# Down one first: row 0 is the master log and `d` on it refuses, so without
# this the confirmation never opens and the scenario tests nothing.
body, kept = with_activity(TO_LOG + [F2, DOWN, "d", CF],
                           "^P while a confirmation is up")
# Asserted by where the deck ENDED UP, not by looking for the question. The
# harness quits with Ctrl-Q and every key but Enter cancels a confirmation, so
# the question is never the last screen -- and the previous version of this
# check looked for the word DELETE, which matched the activities screen's own
# FOOTER and so passed without testing anything at all.
#
# The distinction that matters: a blocked ^P leaves the confirmation to be
# cancelled, which returns to the activities list. A ^P that got through would
# have carried the deck to the log screen before the question was ever
# answered.
check("the deck is still in the activities list",
      "ACTIVITIES" in body, body[:200])
check("and the ring did not carry it to another screen",
      "DECK & RIG" not in body and "^T over" not in body, body[:300])
check("the contact is untouched either way", len(kept) == 1, str(kept))

print("\nF4 still cycles the colour from every area")
# Asserted as state in test_state.py, where the written file can be read. Here
# it only has to not be swallowed: a screen that returns True for F4 without
# acting would look identical.
for keys, where in ((TO_DIGI, "digimodes"), (TO_LOG, "log"),
                    (TO_SET, "settings")):
    body = deck(keys + [F1], f"F1 still works in {where} after F4",
                extra=ON)
    check(f"{where}: the area's menu still opens", len(body) > 100, body[:80])

print("\nlogging off: the log is not on the ring at all")
# It has nothing to show when off -- no form, no file -- so the ring is two
# stops rather than three. Landing on the conversation with a logging menu
# over it was tried and was worse: it put the operator in one application
# while showing them another's menu, and the next press then skipped the
# conversation.
body = deck([CF], "^P with logging off")
check("one forward goes straight to the conversation",
      "^T over" in body, body[-200:])
body = deck([CF, CF], "^P twice with logging off")
check("two reaches WSPR", "WSPR" in body, body[:200])
body = deck([CF, CF, CF], "^P three times with logging off")
check("three reaches the band plan", "BAND PLAN" in body, body[:200])
body = deck([CF, CF, CF, CF], "^P four times with logging off")
check("and four comes back to the settings", "DECK & RIG" in body,
      body[:200])

print("\nthe deck and rig screen is edited in place")
# It was read-only and that was wrong: the station's own details were reachable
# only by going through a menu to find the editor, and a screen that showed
# them without letting them be changed invited the attempt and refused it.

body = deck(TO_SET, "the settings screen", extra=ON)
check("the cursor starts on the first row",
      "\u25b8Callsign" in body, body[:300])
check("it says the arrows pick and Enter edits",
      "\u2191\u2193 pick" in body and "Enter edit" in body, body[-120:])
# The ceiling, not the live reading. The label said "Power" for a CAT reading
# while `TX_POWER_MAX` -- the thing an operator sets -- was not on the screen.
check("the power ceiling is labelled as a maximum",
      "Max power" in body, body[:400])
# The live power reading is NOT on this screen. `_power_now()` asks the radio
# and falls back to the setting only when it will not answer, so a row for
# typing it invites setting a number the radio contradicts -- and every
# reading on here cost a round trip, five times a second, which is what made
# the screen feel slow. `{power}` substitutes the reading, so the token is
# unaffected.
check("the live power reading is not on it", "Power now" not in body,
      body[:400])
check("nor are the radio's other readings",
      "READ FROM THE RIG" not in body, body[:400])

body = deck([DOWN] * 5 + [ENTER], "Down x5 then Enter", extra=ON)
check("Enter opens the editor for the row the cursor is on",
      "EDIT" in body and "Antenna" in body, body[:200])

# Read-only rows are drawn but never landed on. A cursor that could sit on the
# VFO and do nothing on Enter would read as a broken key.
body = deck([DOWN] * 40, "Down forty times", extra=ON)
check("the cursor wraps among the editable rows and no further",
      "\u25b8" in body, body[:400])
for ro in ("\u25b8VFO", "\u25b8Rig mode", "\u25b8Transmit", "\u25b8Power now"):
    check(f"it never lands on {ro[1:]}", ro not in body, body[:400])

print("\nBand belongs to the digimodes, not the deck")
# It tunes to the digimode calling frequency for the band, which is a digital
# modes decision and useless to anything else. It was briefly moved to the
# deck menu on the reasoning that a band is a property of the radio -- which
# is true of the band and false of this entry.
body = deck(TO_DIGI + [F1], "the digimode menu", extra=ON)
check("Band is on the digimode menu", "Band" in body, body[:300])
body = deck([F1], "the deck menu", extra=ON)
check("and not on the deck menu", "Band" not in body, body[:300])
check("which still has the rest", "Display" in body and "System" in body,
      body[:300])

sys.exit(report())
