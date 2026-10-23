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
    lines = render.map_overlay("12 spots", BANDS, None, "global", w)
    equals(f"{w}x{h}: two rows", len(lines), 2)
    equals(f"{w}x{h}: each exactly {w} wide", widths(lines), {w})

print("\nit says what is on the map and which view is showing")
body = text(render.map_overlay("412 spots   39 off this view", BANDS, None,
                               "global", 66))
check("the spot count", "412 spots" in body, body)
check("what the view is hiding", "39 off this view" in body, body)
check("and which view it is", "global" in body, body)

print("\nband keys are the digits the band picker already uses")
body = text(render.map_overlay("12 spots", BANDS, None, "global", 66))
for i, band in enumerate(BANDS):
    check(f"{band} is on key {render.MAP_BAND_KEYS[i]}",
          f"{render.MAP_BAND_KEYS[i]}{band}" in body, body)

print("\nand the key is drawn as a key cap, not run into the band name")
# `180m 240m 330m 420m` is four keys and four bands, and reads as five
# nonsense band names. At eight bands there is no column to spare for a
# separator, so the ATTRIBUTE is the separator: the digit is reverse video
# and the band name is not.
segs = render.map_overlay("12 spots", BANDS, None, "global", 66)[1]
for i, band in enumerate(BANDS):
    key = render.MAP_BAND_KEYS[i]
    pair = [(t, k) for t, k in segs if t.strip() in (key, band)]
    check(f"{band}: the key is its own segment",
          (key, "reverse") in [(t.strip(), k) for t, k in pair], pair)
    check(f"{band}: and the band name is not reverse",
          not any(t.strip() == band and k == "reverse" for t, k in pair),
          pair)
check("and the row is still exactly the panel width",
      sum(len(t) for t, _k in segs) == 66,
      sum(len(t) for t, _k in segs))

print("\na band switched off dims its key too")
segs = render.map_overlay("12 spots", BANDS, {"40m"}, "global", 66)[1]
off = [(t.strip(), k) for t, k in segs if t.strip() == render.MAP_BAND_KEYS[0]]
equals("80m is off, so its key is dim rather than a lit cap",
       off, [(render.MAP_BAND_KEYS[0], "dim")])
on = [(t.strip(), k) for t, k in segs if t.strip() == render.MAP_BAND_KEYS[1]]
equals("40m is on, so its key is a cap",
       on, [(render.MAP_BAND_KEYS[1], "reverse")])

print("\na band switched off is dim, not missing")
# Missing would read as a band with no spots, which is a different fact.
lines = render.map_overlay("12 spots", BANDS, {"40m"}, "global", 66)
flat = text(lines)
check("every band is still listed", all(b in flat for b in BANDS), flat)
lit = [t for ln in lines for t, k in ln if k == "bright"]
check("only the chosen one is bright",
      any("40m" in t for t in lit) and not any("80m" in t for t in lit),
      lit)

print("\nthe direction marks say which shape is which")
dirs = [("heard", "+", True), ("by me", "x", False)]
body = text(render.map_overlay("12 spots", BANDS, None, "wide", 66,
                               directions=dirs))
check("the plus is named", "+heard" in body, body)
check("and the cross", "xby me" in body, body)

print("\na message replaces the key hints rather than overflowing")
body = text(render.map_overlay("12 spots", BANDS, None, "global", 66,
                               message="no framebuffer on this machine"))
check("the message is shown", "no framebuffer" in body, body)
for w, _h in SIZES:
    lines = render.map_overlay("12 spots", BANDS, None, "global", w,
                               message="a very long message " * 5)
    equals(f"{w}: still exactly {w} wide", widths(lines), {w})

print("\nno spots, no bands, nothing breaks")
for w, h in SIZES:
    lines = render.map_overlay("no spots yet", [], None, "focus", w)
    equals(f"{w}x{h}: two rows", len(lines), 2)
    equals(f"{w}x{h}: width holds", widths(lines), {w})

print("\nmore bands than there are keys does not overflow")
many = [f"{n}m" for n in range(2, 40, 2)]
for w, _h in SIZES:
    lines = render.map_overlay("12 spots", many, None, "global", w)
    equals(f"{w}: width holds with {len(many)} bands", widths(lines), {w})

print("\nthe view cycle is a loop with no dead end")
seen, view = [], wsprmap.DEFAULT_VIEW
for _ in range(len(wsprmap.VIEWS)):
    seen.append(view)
    view = wsprmap.next_view(view)
equals("it returns to where it started", view, wsprmap.DEFAULT_VIEW)
equals("having visited every view", sorted(seen), sorted(wsprmap.VIEWS))

print("\nevery scheme gives the map a dim outline and bright spots")
for scheme in ("matrix", "deckard", "hal", "tron", "ripley"):
    dim, bright = colors.map_colors(scheme)
    check(f"{scheme}: both are colours", 0 <= dim <= 0xFFFFFF
          and 0 <= bright <= 0xFFFFFF, (dim, bright))
    def lum(c):
        return ((c >> 16) & 255) * 0.3 + ((c >> 8) & 255) * 0.6 + (c & 255) * 0.1
    check(f"{scheme}: the outline is dimmer than the spots",
          lum(dim) < lum(bright), (hex(dim), hex(bright)))

print("\nan unknown scheme falls back rather than raising")
dim, bright = colors.map_colors("banana")
check("it still returns a pair", bright > 0, (dim, bright))

# -- the two maps are not the same map --------------------------------------
#
# The WSPR map answers "who hears me, and who do I hear" -- the two are
# different questions and the gap between them is the whole point of the
# direction filter. A worked contact answers both at once: a QSO that only
# went one way is not a QSO. So the log map carries one legend, and the
# direction key says why it does nothing rather than appearing dead.
import curses
import cyberdeck


def deck(screen):
    d = cyberdeck.Deck.__new__(cyberdeck.Deck)
    d.cfg = {"MAP_VIEW": "global"}
    d.screen = screen
    d.map_state = None
    d.map_spots = None
    d.log_form = None
    return d


print("\nthe log map offers one direction, the WSPR map two")
d = deck(cyberdeck.LOGMAP)
state = d._map_state()
log_dirs = d._map_dirs(cyberdeck.LOGMAP, state)
wspr_dirs = d._map_dirs(cyberdeck.WSPRMAP, state)
equals("one legend on the log map", len(log_dirs), 1)
equals("and it says 'worked', not 'heard'", log_dirs[0][0], "worked")
check("lit, because there is nothing to switch off", log_dirs[0][2])
equals("two on the WSPR map", len(wspr_dirs), 2)
equals("asking the two questions", [d_[0] for d_ in wspr_dirs],
       ["heard", "by me"])

print("\n`t` on the log map explains itself instead of going dead")
d = deck(cyberdeck.LOGMAP)
d._map_state()
d._handle_map(cyberdeck.LOGMAP, ord("t"))
check("it says why", "two-way" in d.map_state["msg"], d.map_state["msg"])
check("and filters nothing", d.map_state["dirs"] is None, d.map_state["dirs"])

print("\nand on the WSPR map it still cycles")
d = deck(cyberdeck.WSPRMAP)
d._map_state()
d._handle_map(cyberdeck.WSPRMAP, ord("t"))
check("the filter moved off 'both'", d.map_state["dirs"] is not None,
      d.map_state["dirs"])
equals("with nothing to explain", d.map_state["msg"], "")

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
sm.add_grid("EM12", "20m", wsprmap.HEARD_BY)
equals("nothing ungridded", sm.ungridded, 0)
check("so the line does not mention it", "no grid" not in sm.summary(),
      sm.summary())

print("\nan empty map still says it is empty")
sm = wsprmap.SpotMap(wsprmap.load(view="global"))
equals("no spots yet", sm.summary(), "no spots yet")

print("\nEsc goes back to the screen the map was opened from")
for which, home in ((cyberdeck.WSPRMAP, cyberdeck.WSPR),
                    (cyberdeck.LOGMAP, cyberdeck.LOG)):
    d = deck(which)
    d._map_state()
    d._handle_map(which, 27)
    equals(f"{which} returns to {home}", d.screen, home)

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
