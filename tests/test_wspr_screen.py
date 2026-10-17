"""The WSPR screen and its menus — docs/wspr_design.md §10.

Pure renderers: a list of lines, each a list of `(text, attr)` segments, and
nothing about curses. So every case here runs at any width with no terminal.

**Two properties carry most of the value.** Every row must be exactly the
screen's width, because a row wider than the screen is one curses refuses to
draw and a short one leaves whatever the previous screen left in those
columns. And nothing may be cut mid-word — the fault that produced
`QTH        COM` in the log columns and `from Satu` in this menu's first
draft.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import menus
import render

GRIDS = ((66, 20), (50, 15), (80, 24), (40, 12))

SPOTS = [
    {"when": "2026-10-17T02:08:00Z", "snr": -25, "call": "WW0WWV",
     "grid": "DN70", "dbm": 30, "km": 2410},
    {"when": "2026-10-17T02:08:00Z", "snr": -26, "call": "KC0MVF",
     "grid": "EN13", "dbm": 30, "km": 1680},
]
STATE = dict(session="Saturday night", band="40 m", dial_hz=7_038_600,
             hopping=True, next_tx=False, clock="0210Z", wspr=True,
             decode=True, transmit=True, tx_next=False, watts="0.5",
             dbm=27, dbm_exact=True, ceiling=10, heard=2, sent=1,
             upload="on", timeout_left=3240, decoding=True)


def plain(rows):
    return ["".join(t for t, _a in r) for r in rows]


print("every row is exactly the screen's width, at every size")
for w, h in GRIDS:
    rows = render.wspr_screen(SPOTS, w, h, state=STATE, message="beaconing",
                              footer=" F1 menu")
    equals(f"{w}x{h}: the right number of rows", len(rows), h)
    wrong = [i for i, r in enumerate(rows)
             if sum(len(t) for t, _a in r) != w]
    equals(f"{w}x{h}: every row is {w} wide", wrong, [])

print("\nthe header says what the deck is doing")
head = plain(render.wspr_screen(SPOTS, 66, 20, state=STATE))[0]
check("the session", "Saturday night" in head, head)
check("the band", "40 m" in head, head)
check("the dial, grouped as the radio reads it", "7.038.600" in head, head)
check("that it is hopping", "hop" in head, head)
check("what the next slot does", "next: RX" in head, head)
check("and the clock", "0210Z" in head, head)
tx_next = dict(STATE, next_tx=True)
check("which says TX when the next slot transmits",
      "next: TX" in plain(render.wspr_screen(SPOTS, 66, 20,
                                             state=tx_next))[0], "")

print("\nthe spots are newest first, which is the opposite of the contact log")
# A WSPR session accumulates hundreds and the question is always "what is
# coming in now", never "what came in an hour ago".
body = plain(render.wspr_screen(SPOTS, 66, 20, state=STATE))
rows = [r for r in body if "WW0WWV" in r or "KC0MVF" in r]
equals("both are shown", len(rows), 2)
check("in the order given, newest first",
      rows[0].find("WW0WWV") >= 0, rows[0])
check("with the SNR", "-25" in rows[0], rows[0])
check("the grid", "DN70" in rows[0], rows[0])
check("the claimed power", "30" in rows[0], rows[0])
check("and the distance when it is known", "2410" in rows[0], rows[0])

print("\na spot with no grid shows a dash, not an empty column")
# A type 2 compound-call message carries no grid at all.
no_grid = [{"when": "2026-10-17T02:08:00Z", "snr": -5, "call": "KD3CCO/P",
            "dbm": 37}]
row = [r for r in plain(render.wspr_screen(no_grid, 66, 20, state=STATE))
       if "KD3CCO/P" in r][0]
check("the call is there", "KD3CCO/P" in row, row)
check("and the missing grid reads as absent", "-" in row, row)

print("\nthe four toggles read from their shape, not from four words")
on = render.wspr_toggles(dict(wspr=True, decode=True, transmit=False,
                              tx_next=False))
labels = {t.strip(): a for t, a in on if t.strip()}
equals("WSPR on is highlighted", labels["WSPR"], "reverse")
equals("DECODE on is highlighted", labels["DECODE"], "reverse")
equals("TX off is dim", labels["TX"], "dim")
equals("TX NEXT off is dim", labels["TX NEXT"], "dim")
all_off = render.wspr_toggles({})
check("nothing on means nothing highlighted",
      all(a == "dim" for t, a in all_off if t.strip()), str(all_off))

print("\nthe power block highlights an exactly encodable dBm")
# The whole point of showing three numbers together: an operator adjusting
# the power control watches for the highlight.
seg = render.wspr_power("5", 37, True, ceiling=10)
flat = "".join(t for t, _a in seg)
check("the ceiling", "max 10 W" in flat, flat)
check("the reading", "5 W" in flat, flat)
check("and the dBm", "37 dBm" in flat, flat)
equals("which is highlighted when exact",
       [a for t, a in seg if "dBm" in t], ["reverse"])

seg = render.wspr_power("3", 33, False, ceiling=10)
flat = "".join(t for t, _a in seg)
check("an inexact dBm is not highlighted",
      "reverse" not in [a for t, a in seg if "dBm" in t], str(seg))
check("and is marked as snapped", "snapped" in flat, flat)

print("\na power that had to fall back says so")
# A beacon announcing a wattage the radio is not making is worse than one
# announcing nothing.
flat = "".join(t for t, _a in
               render.wspr_power("5", 37, True, 10, fallback=True))
check("it is marked configured", "configured" in flat, flat)
flat = "".join(t for t, _a in render.wspr_power(None, None, False, 10))
check("and an unknown power says unknown", "unknown" in flat, flat)

print("\nthe counters and the timer")
line = [r for r in plain(render.wspr_screen(SPOTS, 66, 20, state=STATE))
        if "heard" in r][0]
check("what was heard", "heard 2" in line, line)
check("what was sent", "sent 1" in line, line)
check("the upload state", "upload on" in line, line)
check("the time remaining, as minutes and seconds", "54:00" in line, line)
check("and that a decode is still running", "decoding" in line, line)
quiet = plain(render.wspr_screen(SPOTS, 66, 20,
                                 state=dict(STATE, decoding=False,
                                            timeout_left=None)))
line = [r for r in quiet if "heard" in r][0]
check("no timer when there is none", "left" not in line, line)
check("and no decoding when nothing is", "decoding" not in line, line)

print("\nan empty screen still draws, and is still the right shape")
for w, h in GRIDS:
    rows = render.wspr_screen([], w, h, state={})
    equals(f"{w}x{h}: rows", len(rows), h)
    wrong = [i for i, r in enumerate(rows)
             if sum(len(t) for t, _a in r) != w]
    equals(f"{w}x{h}: all {w} wide", wrong, [])
head = plain(render.wspr_screen([], 66, 20, state={}))[0]
check("and says there is no session", "no session" in head, head)


# -- the menus ----------------------------------------------------------

print("\nthe menu carries each toggle's state on its own line")
m = menus.wspr_menu(dict(wspr=True, decode=True, transmit=False,
                         tx_next=False, session="Saturday night",
                         band="40 m", hopping=True, hop_count=3,
                         tx_percent=20, timeout_minutes=60, upload="on",
                         heard=2, sent=1))
text = "\n".join(l for _k, l in m["items"])
keys = [k for k, _l in m["items"]]
equals("the four toggles come first", keys[:4], ["w", "d", "t", "n"])
check("WSPR shows on", "WSPR" in text and "on" in text, text[:80])
check("Transmit shows off", "Transmit                     off" in text, text)
check("the session is named", "Saturday night" in text, text)
check("the band, and that it is hopping", "hopping 3 bands" in text, text)
check("the transmit percent", "20%" in text, text)
check("the time-out", "60 min" in text, text)
check("the upload state", "Upload spots                 on" in text, text)
check("the calibration tone is offered", "Calibrate" in text, text)
equals("and the danger zone is last", keys[-1], "z")
check("the footer says the ring is locked",
      "locked while running" in m["footer"], m["footer"])
equals("a time-out of zero reads as off",
       "off" in dict(menus.wspr_menu({"timeout_minutes": 0})["items"])["o"],
       True)

print("\nthe menu fits the panel at every size")
for w, h in GRIDS:
    lines = plain(menus.render(m, w, h))
    over = [l for l in lines if len(l.rstrip()) > w]
    equals(f"{w}x{h}: nothing overflows", over, [])

print("\nthe danger zone counts by kind, and never cuts a name")
# "473 records" hides which: losing a night of received data and clearing
# one's own transmissions are different losses.
for name in ("Saturday night", "A very long session name indeed", ""):
    d = menus.wspr_danger_menu(name, 412, 61, 998, 140, 4)
    body = "\n".join(l for _k, l in d["items"])
    check(f"{name[:12]!r}: heard and sent are separate",
          "412 heard + 61 sent" in body, body)
    check(f"{name[:12]!r}: the whole log too",
          "998 heard + 140 sent" in body, body)
    check(f"{name[:12]!r}: forgetting destroys nothing",
          "spots kept" in body, body)
    for w, h in GRIDS:
        lines = plain(menus.render(d, w, h))
        over = [l for l in lines if len(l.rstrip()) > w]
        equals(f"{name[:12]!r} at {w}x{h}: nothing overflows", over, [])
check("the session is named in the footer, where there is room",
      "Saturday night" in menus.wspr_danger_menu("Saturday night")["footer"],
      menus.wspr_danger_menu("Saturday night")["footer"])
check("and no session reads as none",
      "no session" in menus.wspr_danger_menu("")["footer"],
      menus.wspr_danger_menu("")["footer"])

print("\nthe keys do not collide with the deck's reserved ones")
# F4 is the colour toggle and F1 the menu on every screen, so a menu key
# that duplicated a screen key would be ambiguous to an operator.
equals("every menu key is unique", len(keys), len(set(keys)))
equals("and the danger zone's too",
       len([k for k, _l in menus.wspr_danger_menu()["items"]]), 3)

report()
