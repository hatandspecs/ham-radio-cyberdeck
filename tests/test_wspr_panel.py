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

import menus

from harness import check, equals, report
from test_screen import run, show

STATION = ("CALLSIGN = KD3CCO\nLOCATOR = FN10cs\nRIG = FTX-1\n"
           "ANTENNA = EFHW\nTX_POWER_MAX = 10\n")

F1 = {"xterm": "\x1bOP", "linux": "\x1b[[A"}
F2 = {"xterm": "\x1bOQ", "linux": "\x1b[[B"}
F3 = {"xterm": "\x1bOR", "linux": "\x1b[[C"}
CTRL_O, CTRL_P = "\x0f", "\x10"
ESC, ENTER, CTRL_C = "\x1b", "\r", "\x03"

# The deck opens on DECK & RIG. The ring is settings | log | digimodes | wspr,
# so `^O` wraps backwards straight onto WSPR -- which is also the cheapest
# way to get there and the reason the ring order puts it last.
TO_WSPR = CTRL_O * 2
# Three hops: the ring is five areas now (the band plan joined it),
# and `^O` x3 lands on the conversation whether or not logging is on --
# which is the property the old two-hop constant had. See the ring-hop
# trap in AGENTS.md.


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
    # A run always has a name: `_wspr_ensure_session` gives an unnamed one
    # the default before any spot is written, so spots always belong to
    # something the danger zone can clear and an export can scope.
    check(f"{term}: with the default session name",
          "general" in body, body[:120])
    check(f"{term}: the four toggles are shown",
          all(w in body for w in ("DECODE", "TX NEXT")), body)
    check(f"{term}: and the footer offers the menu",
          "F1 menu" in body, body[-200:])

print("\nit is a stop on the ring, so the ring still walks")
# Five areas: settings | log | digimodes | wspr | alloc. With logging off the
# log is not on it, so `^P` from WSPR goes forward onto the BAND PLAN rather
# than wrapping to the settings.
#
# It wrapped to the settings while the ring was four areas and WSPR was last.
# The band plan joined the ring after it, which moved this landing by one --
# the ring-hop trap in AGENTS.md, found here late because a wedged fldigi had
# this whole file red and hid the one check that was genuinely wrong.
body = deck([TO_WSPR, CTRL_P], "^O then ^P leaves WSPR again", settle=3.0)
check("the deck left the WSPR screen", "WSPR" not in body[:120], body[:120])
check("onto the next area along, which is the band plan",
      "BAND PLAN" in body, body[:120])

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
                 "Band", "Transmit percent", "Session ToT",
                 "Upload spots",
                 "Spot log", "Danger zone"):
        check(f"{term}: it offers {want}", want in body, body[:600])
    check(f"{term}: and says the ring locks while running",
          "locked while running" in body, body[-200:])

print("\nthe defaults are the ones the design settled on")
body = deck([TO_WSPR, F1["linux"]], "the menu's defaults", settle=3.0)
check("transmit percent defaults to WSJT-X's 20%", "20%" in body, body)
# `1 h`, not `60 min`: `menus._duration` prints hours once there are
# hours, so a twelve-hour time-out does not read as "720 min". The
# default is still sixty minutes; only the way it is written changed.
check("the time-out to 60 minutes", "1 h" in body, body)
check("decoding starts on", "Decode                       on" in body, body)
check("and transmit starts OFF — beaconing is never a default",
      "Transmit                     off" in body, body)

print("\nF3 picks the band, with the WSPR dial frequencies")
body = deck([TO_WSPR, F3["linux"]], "F3 band picker", settle=3.0)
check("the picker opens", "WSPR BAND" in body, body[:120])
check("40 m at its WSPR dial", "7.038600" in body, body)
check("20 m too", "14.095600" in body, body)
check("and 70 cm, the top of the list", "432.300000" in body, body)
check("and says how to put a band in the rotation",
      "Space hop on/off" in body, body[-200:])

print("\nselecting a band takes effect on the screen behind")
body = deck([TO_WSPR, F3["linux"], "4", ESC], "pick 20 m", settle=3.4)
check("the header names the band", "20 m" in body, body[:140])
# GROUPED, as `render.frequency` writes it and as the deck writes every
# frequency: 14.095.600 and not 14.095600. The band PICKER lists plain
# megahertz because it is a table of figures to compare; the header shows
# what the radio's own display shows.
check("at its dial frequency, grouped as the radio reads it",
      "14.095.600" in body, body[:140])

print("\na number selects that band alone — it does not build a rotation")
body = deck([TO_WSPR, F3["linux"], "4", ESC], "4 selects 20 m only",
            settle=3.4)
# **Hopping is not in the header at all now.** It is a toggle on the switch
# row, beside DECODE and TX, because saying it in both places left the
# header repeating an answer from the row below. So the header is asserted
# to be free of it, and the toggle is checked where it lives.
check("the header says nothing about hopping",
      "hop" not in body[:140].lower(), body[:140])
check("and the toggle row is where it is answered", "HOP" in body, body)

print("\nSpace builds a rotation; the header counts it")
# **Not `"hop" in body`** -- the header says "no hop" when hopping is off,
# so that assertion passed on the off state. It also drove `4 + 2`, the
# removed prefix idiom, which under the Space rules selects 40 m alone and
# so asserted hopping against a screen that showed none.
#
# 40 m is configured; Space on row 0 adds 80 m beside it.
body = deck([TO_WSPR, F3["linux"], " ", ESC], "80 m beside 40 m",
            settle=3.8)
# The rotation is reported in the message line and on the toggle, not in
# the header.
check("a rotation is reported", "hop" in body.lower(), body[-300:])
check("and HOP is on the toggle row", "HOP" in body, body)
check("and + is gone rather than silently meaning something else",
      "+n" not in body, body[-200:])

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
# Named as the SESSION's: the slot, the decode and the session all have
# clocks, and "Time-out" alone said which of them not at all.
check("the time-out moved", "Session ToT" in body, body)

print("\nthe upload toggle says what arming it means")
body = deck([TO_WSPR, F1["linux"], "u"], "u toggles upload", settle=3.2)
check("it reports the three conditions rather than just 'on'",
      "wsprnet" in body or "upload" in body.lower(), body[-400:])

print("\nCtrl-C on a stopped WSPR says so rather than doing nothing")
# **Ctrl-C, not Ctrl-X.** Ctrl-C aborts an over on the conversation screen,
# and Ctrl-X means CLEAR everywhere on the deck -- the transcript and the
# entry form -- so using it for "stop" in one application only was an
# inconsistency to pay for under pressure.
body = deck([TO_WSPR, CTRL_C], "^C with WSPR stopped", settle=3.0)
check("it says it is not running", "not running" in body, body[-300:])
check("and the footer teaches the keys",
      "^B inhibit" in body and ("^C stop" in body or "^O ^P" in body),
      body[-200:])

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

print("\nthe band picker is a checkbox, not a two-key prefix")
# `+n` was the first idiom and was reported undiscoverable in those words.
body = deck([TO_WSPR, F3["linux"]], "F3 opens the band picker", settle=3.0)
check("it opens", "WSPR BAND" in body, body[:120])
check("the footer teaches Space", "Space hop on/off" in body, body[-200:])
check("and Enter for a single band", "Enter use this one" in body,
      body[-200:])
check("+n is gone from it", "+n" not in body, body[-200:])
check("membership is drawn as a checkbox", "[*]" in body or "[ ]" in body,
      body)

print("\na band number selects that band and tunes to it")
# It set the band and waited for the scheduler, so with WSPR stopped the
# label moved and the radio did not.
body = deck([TO_WSPR, F3["linux"], "4", ESC], "4 picks 20 m", settle=3.2)
check("the deck reports the band it went to", "20 m" in body, body)
check("and the dial frequency it tuned to",
      "14.095.600" in body or "14.095600" in body, body)

print("\nSpace adds a band to the rotation")
body = deck([TO_WSPR, F3["linux"], " ", ESC],
            "Space on 80 m adds it beside 40 m", settle=3.4)
check("the deck reports a rotation rather than a single band",
      "hop" in body.lower(), body[-300:])

print("\nthe only selected band cannot be unselected")
# Something has to be selected; an empty rotation has nothing to tune to.
# The cursor opens on 80 m, row 0, while the only selected band is the
# configured 40 m -- so this walks to 40 m first. Space on 80 m would ADD
# it, which is the first version of this case and tested nothing.
body = deck([TO_WSPR, F3["linux"], "\x1b[B", " ", ESC],
            "Space on 40 m, the only selected band", settle=3.4)
check("it says why it refused", "only band" in body, body[-300:])

print("\nband hopping is a toggle, highlighted when it is on")
body = deck([TO_WSPR], "one band, no hopping", settle=3.0)
check("the toggle is there with one band", "HOP" in body, body)
check("and the header does not mention it",
      "hop" not in body[:140].lower(), body[:140])
body = deck([TO_WSPR], "three bands", settle=3.0,
            extra="WSPR_BANDS = 40 m,30 m,20 m\n")
check("and it is still the toggle that says so, with three bands",
      "HOP" in body, body)

print("\nthe slot clock is on the screen")
body = deck([TO_WSPR], "stopped: no stale clock", settle=3.0)
check("stopped, it says so rather than showing a clock",
      "not running" in body, body)

print("\nthe hop check is offered, and refuses without rig control")
# The mode check moved to the band picker; its case is below.

print("\ncalibration is refused with a reason while WSPR is off")
# **Both calibrations open the sound card, and fldigi holds it while WSPR is
# off** -- so with WSPR off they produced a capture-device error from inside
# a screen that looked ready. The menu item now says why before it is
# entered, which is the only part this file can drive: starting WSPR for
# real stops fldigi and takes the codec, which no test here does.
for key, what in (("c", "transmit"), ("m", "receive")):
    body = deck([TO_WSPR, F1["linux"], "a", key],
                f"{key} with WSPR off ({what})", settle=3.6)
    check(f"{what}: it is refused rather than opened",
          "WSPR CALIBRATE" not in body, body[:140])
    check(f"{what}: and says WSPR must be on",
          "WSPR must be on" in body, body[-300:])
    # The menu is closed first, or the message lands underneath it -- the
    # fault that made "calibrate transmit audio" read as doing nothing.
    check(f"{what}: with the menu closed so it can be read",
          "Calibrate transmit" not in body, body)

print("\nthe arrows select and scroll the spot list")
body = deck([TO_WSPR, "\x1b[B"], "down arrow on an empty list", settle=3.0)
check("an empty list does not crash or mark a row",
      "WSPR" in body[:120] and "Traceback" not in body, body[:200])

print("\nthe spot heading has a band column")
body = deck([TO_WSPR], "the heading", settle=3.0)
check("BAND is a column", "BAND" in body, body)

print("\nthe WSPR menu stays in ONE column, so the values stay on it")
# `menus.render` goes two-column above `height - 6` items, which on the
# panel is 14 -- and the second column has no room for the current values,
# which is the one thing this menu exists to show. Adding the two audio
# levels and the mode check as separate rows took it to 16 and silently
# dropped every value; five checks in this file caught it. The item count is
# a design constraint, so it is asserted directly.
d = menus.wspr_menu({"tx_level": 25, "rx_gain": 70, "timeout_minutes": 60})
equals("13 items, with one to spare under the threshold",
       len(d["items"]) <= 14, True)
body = deck([TO_WSPR, F1["linux"]], "the menu keeps its values", settle=3.0)
# The deck under test runs on its own defaults, so these are the configured
# levels rather than the ones handed to `wspr_menu` above.
for want in ("20%", "1 h", "wspr.log", "TX 50%  RX 70%"):
    check(f"the menu still shows {want!r}", want in body, body)

print("\nthe audio levels are one submenu, which is one job")
body = deck([TO_WSPR, F1["linux"], "a"], "a opens the audio menu",
            settle=3.2)
check("it opens", "WSPR AUDIO" in body, body[:120])
# Both levels on one line, with the measured dBFS beside the gain it judges.
check("the transmit level is there", "TX audio 50%" in body, body)
check("and the capture gain", "RX gain 70%" in body, body)
check("and no reading until something has been captured",
      "no reading yet" in body, body)
check("and the two calibration screens that set them",
      "Calibrate transmit" in body and "Calibrate receive" in body, body)
check("which is where the levels are set, not here",
      "the levels are set in those" in body, body[-200:])

print("\nboth levels cycle from that menu, and the menu line shows it")
# `t` and `r` step the levels. They are not advertised on the menu, which
# offers the calibration screens instead -- the level belongs next to a
# meter. They work, and the line above reports the new value immediately.
body = deck([TO_WSPR, F1["linux"], "a", "t"], "t cycles the TX level",
            settle=3.4)
check("the transmit level moved off 50", "TX audio 60%" in body, body)
check("and the capture gain did not move with it",
      "RX gain 70%" in body, body)
body = deck([TO_WSPR, F1["linux"], "a", "r"], "r cycles the RX gain",
            settle=3.4)
check("the capture gain moved off 70", "RX gain 75%" in body, body)
check("and the transmit level did not move with it",
      "TX audio 50%" in body, body)

print("\nEsc from the audio menu goes back to the WSPR menu, not out")
body = deck([TO_WSPR, F1["linux"], "a", ESC], "Esc from the audio menu",
            settle=3.4)
check("the WSPR menu is what is drawn", "Transmit percent" in body, body)

print("\nthe band picker offers the bands and the rotation, and says so")
body = deck([TO_WSPR, F3["linux"]], "the picker", settle=3.0)
check("it opens", "WSPR BAND" in body, body[:120])
check("a band is chosen with Enter", "Enter use this one" in body, body[-200:])
# The rotation is a checkbox on the row the arrows are already on. `+` then a
# number came first and was reported undiscoverable, which it was.
check("and the rotation is toggled with Space",
      "Space hop on/off" in body, body[-200:])
check("with a mark for the bands in it", "[*] in rotation" in body, body[-200:])

sys.exit(report())
