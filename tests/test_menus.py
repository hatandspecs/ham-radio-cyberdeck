"""Menus render inside every grid the panel can produce."""
import os
import sys

# src/ holds the application; tests/ holds this. Both are addressed from the
# project root so a test can be run from anywhere.
_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_PROJECT, "src")
sys.path.insert(0, _SRC)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import check, equals, report
import menus, render
import activities
from render import plain
from fldigi_client import Fldigi


GRIDS = [(66, 20), (80, 24), (50, 15), (100, 30)]

print("-- every menu fits every grid --")
for name, menu in [("root", menus.ROOT), ("display", menus.DISPLAY),
                   ("tuning", menus.tuning_menu(True, False, 5.0, True, True)),
                   ("radio", menus.band_menu()),
                   ("system", menus.SYSTEM),
                   ("station", menus.station_menu({"CALLSIGN": "KD3CCO", "NAME": "Don"})),
                   ("mode", menus.mode_menu("BPSK31"))]:
    for w, h in GRIDS:
        lines = menus.render(menu, w, h)
        too_wide = [plain(l) for l in lines if len(plain(l)) > w]
        check(f"{name} at {w}x{h}", len(lines) == h and not too_wide,
              f"lines={len(lines)} over={too_wide[:1]}")

print("\n-- the mode menu marks the mode in use --")
m = menus.mode_menu("RTTY")
labels = [lbl for _, lbl in m["items"]]
check("current mode flagged", any(l.startswith("RTTY") and l.endswith("<") for l in labels), labels[:5])
check("'more' offered", any("more" in l for l in labels))

print("\n-- the conversational subset of a real fldigi modem list --")
f = Fldigi()
names = f.modem_names()
kb = menus.keyboard_modes(names)
check("fldigi answered", len(names) > 100, len(names))
check("subset is smaller than the whole", 0 < len(kb) < len(names), f"{len(kb)} of {len(names)}")
check("every tier-1 mode exists in fldigi", all(n in names for _, n in menus.MODE_TIER1),
      [n for _, n in menus.MODE_TIER1 if n not in names])
print(f"    {len(kb)} conversational modems, first few: {', '.join(kb[:6])}")

print("\n-- paging the long list --")
for w, h in GRIDS:
    menu, page, pages, keymap = menus.paged_menu("ALL MODES", kb, 0, w, h)
    lines = menus.render(menu, w, h)
    over = [plain(l) for l in lines if len(plain(l)) > w]
    check(f"page 1 of {pages} at {w}x{h}", len(lines) == h and not over, over[:1])
    check(f"  keys map to modems at {w}", all(v in kb for v in keymap.values()))

menu, page, pages, keymap = menus.paged_menu("ALL MODES", kb, 99, 66, 20)
check("page number clamped to the last page", page == pages - 1, f"{page}/{pages}")

print("\n-- a two-column page at 66x20 --")
menu, *_ = menus.paged_menu("ALL MODES", kb, 0, 66, 20)
for l in menus.render(menu, 66, 20):
    t = plain(l)
    if t.strip(): print(f"    |{t}|")

print()
print("\nthe logging menu")
off = menus.log_menu(on=False)
equals("off is one item and nothing else", len(off["items"]), 1)
check("and it says off", "off" in off["items"][0][1], off["items"][0][1])

on = menus.log_menu(on=True, count=14, lookup=True)
keys = [k for k, _ in on["items"]]
# General items only, and in that order. Everything here applies to every
# contact; the activity is last because it is the one that changes what the
# other items mean.
equals("on opens the rest", keys, ["l", "a", "m", "d", "c", "v", "n"])
check("the count is on the toggle",
      "14 QSOs" in on["items"][0][1], on["items"][0][1])
check("lookup state is shown",
      "on" in dict(on["items"])["c"], dict(on["items"])["c"])

activating = menus.log_menu(on=True, count=14, lookup=True, activity="POTA",
                            park="US-5678")
check("the reference is shown once an activity needs one",
      "US-5678" in dict(activating["items"])["p"],
      dict(activating["items"])["p"])

one = menus.log_menu(on=True, count=1)
check("one contact is singular", "1 QSO" in one["items"][0][1]
      and "QSOs" not in one["items"][0][1], one["items"][0][1])
# No activity reads as "general logging", not as a blank waiting to be filled.
check("no activity reads as general logging",
      "general logging" in dict(one["items"])["v"]
      and "—" not in dict(one["items"])["v"],
      dict(one["items"])["v"])

# An item whose only possible answer is "this is not set up" occupies a line,
# invites a keystroke and teaches nothing. Absent is better than greyed.
check("no QRZ item without a key",
      "u" not in [k for k, _ in menus.log_menu(on=True)["items"]])
withkey = menus.log_menu(on=True, has_qrz_key=True, qrz_pending=14)
check("and one with a key", "u" in [k for k, _ in withkey["items"]])
check("carrying the backlog",
      any("14 waiting" in label for _, label in withkey["items"]),
      str(withkey["items"]))

print("\nit is reachable from the root menu")
# The entry and its handler went in together, which is the rule: a root item
# whose Enter does nothing is worse than an absent one. test_menu_arrows
# catches the dead case, because Up-Enter from the first item lands on
# whatever is last -- which is now this.
equals("one line, in the root menu",
       [l for _, l in menus.ROOT["items"] if l == "Logging"], ["Logging"])
check("and the menu it opens is built", 
      menus.log_menu(on=False)["title"] == "LOGGING")

print("\nand it renders at every width")
for w in (50, 66, 80, 100):
    for menu in (menus.log_menu(on=False),
                 menus.log_menu(on=True, count=14, park="US-5678",
                                has_qrz_key=True, qrz_pending=3)):
        rows = menus.render(menu, w, 16)
        equals(f"{w}: 16 rows", len(rows), 16)
        over = [plain(r) for r in rows if len(plain(r)) > w]
        check(f"{w}: nothing overflows", not over, str(over[:2]))

print("\nPOTA is an activity, not a separate mode")
# The merge: a POTA toggle and an ACTIVITY that both mean "show the park
# fields" are two controls for one thing. There is only the activity now.
plain_menu = menus.log_menu(on=True, count=5)
keys = [k for k, _ in plain_menu["items"]]
check("general logging offers no reference item", "p" not in keys, str(keys))
check("but the activity is always selectable", "v" in keys, str(keys))
check("and no item mentions a POTA mode",
      not any("POTA mode" in l for _, l in plain_menu["items"]),
      str(plain_menu["items"]))

on_pota = menus.log_menu(on=True, count=5, activity="POTA", park="US-5678")
check("an activity with a reference adds the item",
      "p" in [k for k, _ in on_pota["items"]], str(on_pota["items"]))
check("showing the reference",
      any("US-5678" in l for _, l in on_pota["items"]), str(on_pota["items"]))
check("an unset reference reads 'not set' — the activity is selected",
      any("not set" in l for _, l in
          menus.log_menu(on=True, activity="POTA")["items"]),
      str(menus.log_menu(on=True, activity="POTA")["items"]))
check("a contest activity needs no reference item",
      "p" not in [k for k, _ in
                  menus.log_menu(on=True, activity="CONTEST")["items"]],
      str(menus.log_menu(on=True, activity="CONTEST")["items"]))

print("\nthree default activities, and the rest are examples to copy")
equals("exactly three are built in", sorted(activities.BUILTIN),
       ["CONTEST", "GENERAL", "POTA"])
picker = menus.activity_menu(sorted(activities.BUILTIN), "POTA")
check("the picker offers general logging first",
      "General" in picker["items"][0][1], str(picker["items"]))
check("and marks the one in use",
      any("*" in l for _, l in picker["items"]), str(picker["items"]))

print("\nwhere the mode comes from is selectable")
for value, want in (("auto", "auto"), ("digital", "fldigi"), ("voice", "rig")):
    m = menus.log_menu(on=True, operating=value)
    row = [l for k, l in m["items"] if k == "m"][0]
    check(f"{value} is named on the panel", want in row, row)
check("an unknown value is shown rather than hidden",
      "sideways" in [l for k, l in
                     menus.log_menu(on=True, operating="sideways")["items"]
                     if k == "m"][0])

print("\nLoTW appears only with tqsl present")
check("absent without it", "t" not in
      [k for k, _ in menus.log_menu(on=True)["items"]])
check("present with it", "t" in
      [k for k, _ in menus.log_menu(on=True, has_tqsl=True)["items"]])
check("and it says sign, because that is what tqsl does",
      any("Sign" in l for _, l in
          menus.log_menu(on=True, has_tqsl=True)["items"]))

print("\nand the fullest menu still fits the panel")
full = menus.log_menu(on=True, count=14, lookup=True, activity="POTA",
                      park="US-5678", has_qrz_key=True, qrz_pending=3,
                      has_tqsl=True, operating="auto")
# More than height-6 items makes the renderer split into two columns that
# truncate every label at 27 characters, which mangles this menu.
check("it stays inside one column at 66x20", len(full["items"]) <= 20 - 6,
      f'{len(full["items"])} items')
for w in (50, 66, 80, 100):
    rows = menus.render(full, w, 20)
    over = [plain(r) for r in rows if len(plain(r)) > w]
    check(f"{w}: nothing overflows", not over, str(over[:2]))

print("\nevery advertised memory token is actually provided")
# The failure this catches is silent and ugly: a token in the hint or the
# station menu that the deck does not substitute is inserted *literally*, so
# a memory sends "RUNNING {power} TO" over the air. The three lists have to
# agree, and they live in three different files.
import re as _re
import pathlib as _pathlib

_src = _pathlib.Path(__file__).resolve().parent.parent / "src" / "cyberdeck.py"
_text = _src.read_text()
_block = _text[_text.index("text = raw.replace"):
               _text.index("out = self.session.insert")]
_provided = set(_re.findall(r'"(\w+)":', _block))

_hint = set(_re.findall(r"\{(\w+)\}", render.EDIT_TOKENS_HINT))
equals("the hint advertises nothing the deck cannot fill in",
       sorted(_hint - _provided), [])

# A station field may legitimately have no token — TX_POWER_MAX scales a CAT
# reading and is never inserted into a message — so empty ones are skipped
# rather than counted as a missing substitution.
_menu_tokens = {t.strip("{}") for _k, _l, t in menus.STATION_FIELDS if t}
equals("and neither does the station menu",
       sorted(_menu_tokens - _provided), [])
check("a station field without a token is allowed",
      any(not t for _k, _l, t in menus.STATION_FIELDS),
      str(menus.STATION_FIELDS))

check("the hint still fits the 66-column panel",
      len(render.EDIT_TOKENS_HINT) <= 66,
      f"{len(render.EDIT_TOKENS_HINT)} chars: {render.EDIT_TOKENS_HINT}")

# Rig and antenna are read from the Station menu rather than being logger
# settings of their own, because a second place to set them is a second place
# for them to be wrong.
for key in ("RIG", "ANTENNA", "TX_POWER"):
    check(f"{key} is a station field", key in
          [k for k, _l, _t in menus.STATION_FIELDS],
          str([k for k, _l, _t in menus.STATION_FIELDS]))

sys.exit(report())
