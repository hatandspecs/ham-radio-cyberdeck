"""The map screens — the overlay, the view cycle, and the band keys.

The picture goes to the framebuffer and the two text rows go through curses,
so what is testable without a panel is the overlay and the state machine
behind it. That is also where the bugs would be: which bands are lit, which
direction is shown, and whether a clipped view admits what it is hiding.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import render
import wsprmap
import colors

SIZES = ((66, 20), (50, 15), (80, 24), (40, 12))
BANDS = ["80m", "40m", "30m", "20m", "17m"]


def text(lines):
    return "\n".join("".join(t for t, _k in ln) for ln in lines)


def widths(lines):
    return {sum(len(t) for t, _k in ln) for ln in lines}


print("the overlay is two rows, whatever the panel size")
for w, h in SIZES:
    lines = render.map_overlay("12 spots", "global", w)
    equals(f"{w}x{h}: two rows", len(lines), 2)
    equals(f"{w}x{h}: each exactly {w} wide", widths(lines), {w})

print("\nit says what is on the map and which view is showing")
body = text(render.map_overlay("412 spots   39 off this view", "global", 66))
check("the spot count", "412 spots" in body, body)
check("what the view is hiding", "39 off this view" in body, body)
check("and which view it is", "global" in body, body)

print("\nand which map it is, so the two are never mistaken")
# A contact map with nothing gridded draws the same empty coastline as a
# WSPR map with no spots. Neither said which it was, and one was read as
# the other on the deck.
body = text(render.map_overlay("0 contacts", "focus", 66, title="Bald Eagle"))
check("the title names the session", "Bald Eagle" in body, body)

print("\none key and Esc, and nothing else")
# The band toggles went with the row they needed: the map is scoped to one
# session, and within a session every band answers the same question. The
# heard / heard-by filter went because the deck has no heard-by data -- its
# log holds what it decoded and what it sent, and who heard IT is on
# wsprnet.
body = text(render.map_overlay("12 spots", "global", 66))
check("the view key", "v view" in body, body)
check("and the way out", "Esc back" in body, body)
check("not clipped to 'Esc bac'", "Esc bac\n" not in body + "\n", body)
for gone in ("t ", "+heard", "by me", "1 80m"):
    check(f"{gone!r} is not on the overlay", gone not in body, body)

print("\na message replaces the key row rather than squeezing in beside it")
body = text(render.map_overlay("12 spots", "global", 66,
                               message="no framebuffer on this machine"))
check("the message is shown", "no framebuffer" in body, body)
check("and the keys stand aside", "v view" not in body, body)

# -- the deck side ----------------------------------------------------------

import curses
import cyberdeck


def deck(screen):
    d = cyberdeck.Deck.__new__(cyberdeck.Deck)
    d.cfg = {"MAP_VIEW": "global", "WSPR_LOG_PATH": "/nonexistent",
             "WSPR_SESSION": "", "WSPR_SESSION_START": "", "ACTIVITY": ""}
    d.screen = screen
    d.map_states = None
    d.map_spots = None
    d._map_cache = None
    d.log_form = None
    d.log_records = []
    d._log_shown = lambda: d.log_records
    d._activity_name = lambda: str(d.cfg.get("ACTIVITY", "") or "")
    d._activity_start = lambda: str(d.cfg.get("ACTIVITY_START", "") or "")
    return d


print("\nthe cached map follows the session, not just the file")
# The map is scoped to a session and starting a new one writes nothing to
# the log -- so a cache keyed on the file's size and mtime did not notice,
# and a brand new session with no spots drew the previous session's few
# thousand. Found on the panel 2026-10-23, after creating a second session
# with the same NAME and a different start.
import os
import tempfile
import wsprlog

_tmp = tempfile.mkdtemp()
_log = os.path.join(_tmp, "wspr.log")
_OLD, _NEW = "2026-10-22T18:00:00Z", "2026-10-23T19:00:00Z"
for i, g in enumerate(("FN67", "EN34", "EM64", "IO94")):
    wsprlog.append(_log, {"kind": "rx", "call": f"K{i}ABC", "grid": g,
                          "band": "40 m", "when": _OLD, "activity": "general",
                          "activity_start": _OLD, "snr": -20})

d = deck(cyberdeck.WSPRMAP)
d.cfg.update({"WSPR_LOG_PATH": _log, "LOCATOR": "FN10",
              "WSPR_SESSION": "general", "WSPR_SESSION_START": _OLD})
equals("the session with spots draws them",
       len(d._build_map(cyberdeck.WSPRMAP).points), 4)
# Same NAME, different start. Nothing is written to the log.
d.cfg["WSPR_SESSION_START"] = _NEW
equals("a new session of the same name draws none of them",
       len(d._build_map(cyberdeck.WSPRMAP).points), 0)
d.cfg["WSPR_SESSION_START"] = _OLD
equals("and going back shows them again",
       len(d._build_map(cyberdeck.WSPRMAP).points), 4)

print("\nand the contact map follows the activity")
# The same hole: switching activity changes which records are shown and
# leaves the whole log's length alone.
d = deck(cyberdeck.LOGMAP)
d.cfg.update({"LOCATOR": "FN10", "ACTIVITY": "Park A", "ACTIVITY_START": "a"})
_all = [{"call": "K2ABC", "band": "20m", "grid": "EM12", "activity": "Park A"},
        {"call": "W1XYZ", "band": "40m", "grid": "FN42", "activity": "Park B"},
        {"call": "N3QE", "band": "20m", "grid": "FM19", "activity": "Park B"}]
d.log_records = _all
d._log_shown = lambda: [r for r in _all if r["activity"] == d.cfg["ACTIVITY"]]
equals("Park A has one", len(d._build_map(cyberdeck.LOGMAP).points), 1)
d.cfg["ACTIVITY"] = "Park B"
equals("Park B has two, not Park A's cached one",
       len(d._build_map(cyberdeck.LOGMAP).points), 2)

print("\nthe log map says how many contacts it cannot plot")
# Contacts carry a grid when the schema has one or the callbook lookup filled
# it, and not otherwise. A map showing eleven of forty contacts with nothing
# on screen saying so reads as a map of a quiet weekend.
d = deck(cyberdeck.LOGMAP)
d.cfg["LOCATOR"] = "FM19"
d.log_records = [
    {"call": "K2ABC", "band": "20m", "grid": "EM12"},
    {"call": "W1XYZ", "band": "40m", "gridsquare": "FN42"},
    {"call": "N3QE", "band": "20m"},                      # no grid at all
    {"call": "VE3QQQ", "band": "20m", "grid": ""},         # nor this
    {"call": "G0MZJ", "band": "20m", "grid": "NOTAGRID"},  # nor this
]
sm = d._build_map(cyberdeck.LOGMAP)
equals("two contacts are on the map", len(sm.points), 2)
equals("three could not be placed", sm.ungridded, 3)
check("and the line under the map says so",
      "3 with no grid" in sm.summary(), sm.summary())

print("\nwhich is a different absence from a clipped one")
# `v` fixes a clipped point. Nothing on this screen fixes a missing grid, so
# conflating the two would send the operator to the wrong key.
d = deck(cyberdeck.LOGMAP)
d.cfg["LOCATOR"] = "FM19"
d.log_records = [{"call": "K2ABC", "band": "20m", "grid": "EM12"},
                 {"call": "N3QE", "band": "20m"}]
sm = d._build_map(cyberdeck.LOGMAP)
line = sm.summary()
check("the gridless one is named as such", "no grid" in line, line)
check("and not as off the view", "off this view" not in line, line)

print("\nthe WSPR map has no such count, because a spot always has a grid")
d = deck(cyberdeck.WSPRMAP)
sm = wsprmap.SpotMap(wsprmap.load(view="global"))
sm.add_grid("EM12", "20m", wsprmap.HEARD)
equals("nothing ungridded", sm.ungridded, 0)
check("so the line does not mention it", "no grid" not in sm.summary(),
      sm.summary())

print("\nan empty map still says it is empty")
sm = wsprmap.SpotMap(wsprmap.load(view="global"))
equals("no spots yet", sm.summary(), "no spots yet")

print("\nEsc and F5 both go back to the screen the map was opened from")
# `F5` both ways: it is the key that opened the map from the screen
# underneath, so pressing it again is the obvious way out. `Esc` still
# works, as it does everywhere on the deck.
for which, home in ((cyberdeck.WSPRMAP, cyberdeck.WSPR),
                    (cyberdeck.LOGMAP, cyberdeck.LOG)):
    for key, label in ((27, "Esc"), (curses.KEY_F5, "F5")):
        d = deck(which)
        d._map_state()
        d._handle_map(which, key)
        equals(f"{which}: {label} returns to {home}", d.screen, home)

print("\nthe log map is reachable from the log screen, and said so")
# F5 rather than a letter: every printable key on that screen types into the
# entry form. The footer has no room for it, so the menu names the key.
import menus
item = [i for i in menus.log_menu(True, 0, "", "", "")["items"]
        if i[0] == "g"]
check("the logging menu lists it", bool(item), item)
check("and names the key, since the footer cannot",
      item and "F5" in item[0][1] if item else False, item)

sys.exit(report())
