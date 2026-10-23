"""The ring editor — `Deck._handle_ring_editor` and `render.ring_screen`.

The screen that writes `RING_ORDER`. `test_ring_order.py` covers what the
deck does with that string; this covers how the string gets written, and the
three things that make the screen honest rather than merely functional:

**Deck & rig cannot leave the ring.** It holds the system menu, including the
way out of a deck configured into a corner. The row says so before the key is
pressed, and the key says so when it is.

**Esc discards.** The editor works on a copy. An editor that wrote through as
the arrows moved would reorder the ring under the operator mid-decision.

**Logging off is not the same as off the ring.** The log leaves the ring when
logging is switched off, by a different mechanism. An order edited while it is
off must come back with logging still in it.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import curses

import cyberdeck
import render
import menus
import session as session_mod

A = cyberdeck
SPACE, ENTER = 32, 10


def deck(order="", log_on=True):
    d = cyberdeck.Deck.__new__(cyberdeck.Deck)
    d.cfg = {"RING_ORDER": order}
    d.log_on = log_on
    d.screen = A.SET
    d.menu = None
    d.session = session_mod.Session(callsign="KD3CCO")
    d._save_state = lambda: None
    d._close_menu = lambda: None
    d._open_ring_editor()
    return d


def on_ring(d):
    return [a for a, on in d.ring_rows if on]


def labels(d):
    return [lab for _n, _a, lab, on, _f in d._ring_screen_rows() if on]


def press(d, *keys):
    for k in keys:
        d._handle_ring_editor(k)
    return d


def sel(d, area):
    """Put the cursor on an area, whatever order the rows are in."""
    d.ring_sel = [a for a, _on in d.ring_rows].index(area)
    return d


print("it opens on the ring as configured")
d = deck("")
equals("the default order, with nothing set", on_ring(d), list(A.RING))
equals("and every area is on it", len(d.ring_rows), len(A.RING_AREAS))

d = deck("wspr,settings,digimodes")
equals("a configured order comes back as it was",
       on_ring(d), [A.AREA_WSPR, A.AREA_SETTINGS, A.AREA_DIGI])
equals("with the areas left off listed after it",
       [a for a, on in d.ring_rows if not on],
       [A.AREA_LOG, A.AREA_ALLOC])

print("\nonly what is on the ring is numbered")
rows = d._ring_screen_rows()
equals("three numbers, 1 to 3", [n for n, _a, _l, on, _f in rows if on],
       [1, 2, 3])
check("and none on the areas left off",
      all(n == 0 for n, _a, _l, on, _f in rows if not on), rows)

print("\nSpace puts an area on the ring and takes it off again")
d = deck("settings,digimodes")
sel(d, A.AREA_WSPR)
press(d, SPACE)
check("WSPR joined", A.AREA_WSPR in on_ring(d), on_ring(d))
equals("at the end, which is where the numbering puts it",
       on_ring(d)[-1], A.AREA_WSPR)
check("and the cursor stayed on it",
      d.ring_rows[d.ring_sel][0] == A.AREA_WSPR, d.ring_sel)
press(d, SPACE)
check("Space again takes it off", A.AREA_WSPR not in on_ring(d), on_ring(d))

print("\ndeck & rig cannot be taken off, and the key says why")
d = deck("")
sel(d, A.RING_FIXED)
press(d, SPACE)
check("it is still on the ring", A.RING_FIXED in on_ring(d), on_ring(d))
check("and the screen says why, rather than the key going dead",
      "cannot leave" in d.ring_message, d.ring_message)
check("the row says so too, before the key is pressed",
      any(fixed for _n, a, _l, _on, fixed in d._ring_screen_rows()
          if a == A.RING_FIXED), d._ring_screen_rows())

print("\na number moves the selected area to that position")
d = deck("settings,logging,digimodes,wspr")
sel(d, A.AREA_WSPR)
press(d, ord("1"))
equals("WSPR to the front", on_ring(d)[0], A.AREA_WSPR)
check("the cursor followed it", d.ring_rows[d.ring_sel][0] == A.AREA_WSPR,
      d.ring_sel)
press(d, ord("3"))
equals("and a second number keeps working on the same area",
       on_ring(d).index(A.AREA_WSPR), 2)

print("\nout of range is clamped, not refused")
d = deck("settings,logging,digimodes")
sel(d, A.AREA_SETTINGS)
press(d, ord("9"))
equals("9 at a list of three means last", on_ring(d)[-1], A.AREA_SETTINGS)
equals("and the list is still three long", len(on_ring(d)), 3)

print("\n0 and a number on an area that is off both explain themselves")
d = deck("")
press(d, ord("0"))
check("0 is not a position", "starts at 1" in d.ring_message, d.ring_message)
d = deck("settings,digimodes")
sel(d, A.AREA_WSPR)
press(d, ord("1"))
check("a number cannot place what is not on the ring",
      "not on the ring" in d.ring_message, d.ring_message)
check("and it names the key that would fix that",
      "Space" in d.ring_message, d.ring_message)
equals("nothing moved", on_ring(d), [A.AREA_SETTINGS, A.AREA_DIGI])

print("\nEnter writes the order and Esc discards it")
d = deck("settings,logging,digimodes,wspr,alloc")
sel(d, A.AREA_ALLOC)
press(d, ord("1"), ENTER)
equals("the config holds the new order", d.cfg["RING_ORDER"],
       "alloc,settings,logging,digimodes,wspr")
equals("and the screen went back to deck & rig", d.screen, A.SET)
# On the screen's own message line, NOT the transcript: the ring is deck
# configuration and has nothing to do with what went over the air.
check("the screen says what the ring is now",
      "Band plan" in d.ring_message, d.ring_message)
check("and the transcript is left alone",
      "Band plan" not in d.session.last_note, d.session.last_note)

d = deck("settings,logging,digimodes")
sel(d, A.AREA_DIGI)
press(d, ord("1"), 27)
equals("Esc leaves the config alone", d.cfg["RING_ORDER"],
       "settings,logging,digimodes")
equals("and also goes back", d.screen, A.SET)

print("\nlogging off is not the same as off the ring")
d = deck("settings,logging,digimodes", log_on=False)
check("the editor still shows logging on the ring",
      A.AREA_LOG in on_ring(d), on_ring(d))
press(d, ENTER)
check("and saving keeps it there", "logging" in d.cfg["RING_ORDER"],
      d.cfg["RING_ORDER"])
equals("though the live ring leaves it out while logging is off",
       d._ring_areas(), [A.AREA_SETTINGS, A.AREA_DIGI])
d.log_on = True
equals("and it rejoins when logging comes back on",
       d._ring_areas(), [A.AREA_SETTINGS, A.AREA_LOG, A.AREA_DIGI])

print("\nwhat it saves is what the deck walks")
for order in ("", "wspr,alloc", "alloc,wspr,digimodes,logging,settings",
              "digimodes"):
    d = deck(order)
    press(d, ENTER)
    equals(f"{order or '(default)'}: round-trips through the config",
           d._ring_areas(), on_ring(d))

print("\nthe screen fits every panel size, with every row on it")
for w, h in ((66, 20), (50, 15), (80, 24), (40, 12)):
    d = deck("")
    lines = render.ring_screen(d._ring_screen_rows(), 0, w, h)
    equals(f"{w}x{h}: exactly {h} rows", len(lines), h)
    equals(f"{w}x{h}: each exactly {w} wide",
           {sum(len(t) for t, _k in ln) for ln in lines}, {w})

print("\nevery area it offers has a name an operator would recognize")
for area in A.RING_AREAS:
    label = A.AREA_LABELS.get(area, "")
    check(f"{area} is called something", bool(label), label)
    check(f"{label} is not the config key", label != area, label)

print("\nit is reached from the one area that cannot leave the ring")
item = [i for i in menus.DECK["items"] if "ring" in i[1].lower()]
check("the deck & rig menu lists it", bool(item), menus.DECK["items"])
d = deck("")
d.screen = A.SET
d.menu = "deck"
d.menu_sel = 0
d.menu_page = 0
d.fldigi = None
d.scr = type("S", (), {"getmaxyx": lambda _s: (20, 66)})()
d._handle_menu(ord(item[0][0]) if item else 0)
equals("and the key opens it", d.screen, A.RINGED)

print("\nthe editor belongs to deck & rig, so ^O out of it lands there")
equals("its area", A.AREA_OF[A.RINGED], A.AREA_SETTINGS)

sys.exit(report())
