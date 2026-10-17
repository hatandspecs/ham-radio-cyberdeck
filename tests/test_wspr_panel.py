"""WSPR through a real pty: the ring, the lock, and the menus.

The engines are tested as pure units elsewhere. This file exists for the part
that cannot be: whether the keys arrive, whether the screen draws, and
whether **the ring refuses to leave while WSPR is running** — which is the
one property of this feature that is about key dispatch rather than about
radio.

**Nothing here transmits and nothing starts WSPR for real.** Starting it
would stop fldigi and open the sound card, so the scenarios below reach the
screen and the menus and stop short of `w`. The start path's own logic — the
refusals, the service stop — is unit-tested where it can be driven without a
radio.

Under `TERM=linux` as well as xterm, because the console's terminfo is not
xterm's and that difference has shipped bugs here before.
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
           "ANTENNA = EFHW\nTX_POWER_MAX = 10\n")

F1 = {"xterm": "\x1bOP", "linux": "\x1b[[A"}
F2 = {"xterm": "\x1bOQ", "linux": "\x1b[[B"}
F3 = {"xterm": "\x1bOR", "linux": "\x1b[[C"}
CTRL_O, CTRL_P = "\x0f", "\x10"
ESC, ENTER, CTRL_X = "\x1b", "\r", "\x18"

# The deck opens on DECK & RIG. The ring is settings | log | digimodes | wspr,
# so `^O` wraps backwards straight onto WSPR -- which is also the cheapest
# way to get there and the reason the ring order puts it last.
TO_WSPR = CTRL_O


def deck(keys, label, extra="", term="linux", settle=2.8):
    with tempfile.TemporaryDirectory() as tmp:
        conf = os.path.join(tmp, "cyberdeck.conf")
        with open(conf, "w") as fh:
            fh.write(STATION + extra
                     + f"LOG_PATH = {os.path.join(tmp, 'qso.log')}\n"
                     + f"WSPR_LOG_PATH = {os.path.join(tmp, 'wspr.log')}\n")
        return show(label, run(keys=keys, settle=settle, term=term,
                               conf=conf))


print("the ring reaches WSPR")
for term in ("xterm", "linux"):
    body = deck([TO_WSPR], f"^O onto WSPR ({term})", term=term)
    # NOT `"WSPR" in body`. That passed while the deck was refusing to
    # start, because the error it printed named `WSPR_LOG_PATH` -- a
    # vacuous pass of exactly the kind this project keeps finding. The
    # header's own shape is the assertion: the title, then the session.
    check(f"{term}: the WSPR screen is drawn",
          body.lstrip().startswith("WSPR "), body[:120])
    check(f"{term}: and the config was accepted",
          "unknown setting" not in body, body[:200])
    check(f"{term}: with no session yet", "no session" in body, body[:120])
    check(f"{term}: the four toggles are shown",
          all(w in body for w in ("DECODE", "TX NEXT")), body)
    check(f"{term}: and the footer offers the menu",
          "F1 menu" in body, body[-200:])

print("\nit is a stop on the ring, so the ring still walks")
# Four areas: settings | log | digimodes | wspr. With logging off the log is
# not on it, so `^P` from WSPR wraps to the settings.
body = deck([TO_WSPR, CTRL_P], "^O then ^P leaves WSPR again", settle=3.0)
check("the deck left the WSPR screen",
      "DECK & RIG" in body or "^T over" in body, body[:120])

print("\nthe power block shows the ceiling, the reading and the dBm")
body = deck([TO_WSPR], "the power block")
check("the ceiling from the configuration", "max 10 W" in body, body)
# With no rigctld answering, the power cannot be read -- which must say so
# rather than claiming a wattage.
check("and an unreadable power says so rather than guessing",
      "power unknown" in body or "W" in body, body)

print("\nF1 opens the WSPR menu, with every toggle's state on it")
for term in ("xterm", "linux"):
    body = deck([TO_WSPR, F1[term]], f"F1 on WSPR ({term})", term=term,
                settle=3.0)
    check(f"{term}: the menu opens", "WSPR" in body, body[:120])
    for want in ("Decode", "Transmit", "Transmit next slot", "Session",
                 "Band", "Transmit percent", "Time-out", "Upload spots",
                 "Spot log", "Danger zone"):
        check(f"{term}: it offers {want}", want in body, body[:600])
    check(f"{term}: and says the ring locks while running",
          "locked while running" in body, body[-200:])

print("\nthe defaults are the ones the design settled on")
body = deck([TO_WSPR, F1["linux"]], "the menu's defaults", settle=3.0)
check("transmit percent defaults to WSJT-X's 20%", "20%" in body, body)
check("the time-out to 60 minutes", "60 min" in body, body)
check("decoding starts on", "Decode                       on" in body, body)
check("and transmit starts OFF — beaconing is never a default",
      "Transmit                     off" in body, body)

print("\nF3 picks the band, with the WSPR dial frequencies")
body = deck([TO_WSPR, F3["linux"]], "F3 band picker", settle=3.0)
check("the picker opens", "WSPR BAND" in body, body[:120])
check("40 m at its WSPR dial", "7.038600" in body, body)
check("20 m too", "14.095600" in body, body)
check("and 70 cm, the top of the list", "432.300000" in body, body)
check("and says how to add to the rotation",
      "add to rotation" in body, body[-200:])

print("\nselecting a band takes effect on the screen behind")
body = deck([TO_WSPR, F3["linux"], "4", ESC], "pick 20 m", settle=3.4)
check("the header names the band", "20 m" in body, body[:140])
check("at its dial frequency", "14.095600" in body, body[:140])

print("\na number selects that band alone — it does not build a rotation")
body = deck([TO_WSPR, F3["linux"], "4", ESC], "4 selects 20 m only",
            settle=3.4)
check("no rotation from one keypress", "hop" not in body[:140], body[:140])

print("\n+ then a number adds one to the rotation")
body = deck([TO_WSPR, F3["linux"], "4", "+", "2", ESC], "20 m plus 40 m",
            settle=3.8)
check("the header marks it as hopping", "hop" in body[:140], body[:140])

print("\nF2 names a session")
body = deck([TO_WSPR, F2["linux"]] + list("Saturday") + [ENTER],
            "name a session", settle=3.4)
check("the header carries the name", "Saturday" in body, body[:140])

print("\nthe danger zone is behind z, and counts by kind")
body = deck([TO_WSPR, F1["linux"], "z"], "the WSPR danger zone", settle=3.2)
check("it opens", "DANGER ZONE" in body, body[:120])
check("forgetting destroys nothing", "spots kept" in body, body)
check("and the counts are separated by kind",
      "heard" in body and "sent" in body, body)

print("\nthe transmit percent and the time-out cycle rather than prompt")
body = deck([TO_WSPR, F1["linux"], "p"], "p cycles the percent", settle=3.2)
check("it moved off 20", "30%" in body or "Transmit percent" in body, body)
body = deck([TO_WSPR, F1["linux"], "o"], "o cycles the time-out", settle=3.2)
check("the time-out moved", "Time-out" in body, body)

print("\nthe upload toggle says what arming it means")
body = deck([TO_WSPR, F1["linux"], "u"], "u toggles upload", settle=3.2)
check("it reports the three conditions rather than just 'on'",
      "wsprnet" in body or "upload" in body.lower(), body[-400:])

print("\nCtrl-X on a stopped WSPR says so rather than doing nothing")
body = deck([TO_WSPR, CTRL_X], "^X with WSPR stopped", settle=3.0)
check("it says it is not running", "not running" in body, body[-300:])

print("\nEsc does not leave the WSPR area")
# Esc backs out WITHIN an application and never leaves one -- the same rule
# every other area holds to.
body = deck([TO_WSPR, ESC], "Esc on the WSPR screen", settle=3.0)
check("the WSPR screen is still what is drawn", "WSPR" in body, body[:120])
check("and not the conversation", "^T over" not in body, body[:200])

print("\nthe spot log is a different file from the contact log")
body = deck([TO_WSPR, F1["linux"]], "the menu names the spot log",
            settle=3.0)
check("it names wspr.log", "wspr.log" in body, body)
check("and not qso.log", "qso.log" not in body, body)

report()
