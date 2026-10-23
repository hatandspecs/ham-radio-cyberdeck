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
for name, menu in [("digi", menus.DIGI), ("deck", menus.DECK),
                   ("display", menus.DISPLAY),
                   ("tuning", menus.tuning_menu(True, False, 5.0, True, True)),
                   ("radio", menus.band_menu()),
                   ("system", menus.SYSTEM),
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
# `e` is the ACTIVITY -- the session being logged -- and `v` the TYPE it
# uses. Two lines because they are two things: an operator could previously
# choose POTA but not say which activation it was.
# `n` is no longer "new type" -- creating a type moved onto the picker that
# lists them, where what already exists is in front of the operator making the
# decision. It is now the lines-per-contact setting, which belongs on this menu
# because it is about reading the log rather than about one activity.
# Four groups, in the order an operator meets them: the state of logging,
# then this session, then what a contact looks like, then the file and what
# comes out of it. The danger zone is last and apart, because everything on
# it destroys something.
# `g` is the contact map, between the session group and the entry group: it
# is a way of READING the log, which is what that boundary separates. It
# names the key that opens it from the log screen as well, because that
# screen's footer is 61 of 66 columns already and has no room for it.
equals("on opens the rest", keys,
       ["l", "e", "v", "g", "d", "c", "m", "n", "f", "a", "z"])
# `x` exports the activity in progress and is offered ONLY when there is one.
# Without an activity it would export the same records as `a` under a
# different name -- two menu items for one action, and the reader left
# wondering what the difference is.
check("exporting an activity is not offered without one",
      "x" not in keys, str(keys))
with_act = menus.log_menu(on=True, count=14, activity="Bald Eagle SP")
check("and is offered with one, naming it",
      "Bald Eagle SP" in dict(with_act["items"])["x"],
      dict(with_act["items"])["x"])
check("while `a` names the whole log either way",
      "the whole log" in dict(on["items"])["a"],
      dict(on["items"])["a"])
check("creating a type is not offered here",
      not any("New type" in label for _k, label in on["items"]),
      str(on["items"]))
check("and `n` sets the line count", "Lines per contact" in
      dict(on["items"])["n"], dict(on["items"])["n"])
# It states the number and NOTHING about what the extra rows show. What they
# show is the activity type's own field order, carrying on from where the
# first row stops, so it differs with every type -- a county-hunting type puts
# county there and a satellite type puts the bird there. Any description here
# would be wrong for most of them, which is why there is none.
for n in (1, 2, 3):
    shown = dict(menus.log_menu(on=True, log_lines=n)["items"])["n"]
    check(f"{n} is shown as the setting", f"{n} of 3" in shown, shown)
    check(f"and {n} does not claim what the rows contain",
          not any(w in shown.lower() for w in
                  ("where", "station", "contact's", "grid", "power")),
          shown)
equals("the activity comes before its schema",
       keys.index("e") < keys.index("v"), True)
# Last, and named so nobody arrives in it by accident.
equals("the danger zone is last", keys[-1], "z")
# The log file sits with the export rather than under the toggle. There is
# one log now and an activity is a label on its records, so which file is in
# use stopped being a question asked per session and became part of "where
# does this end up".
equals("the activity is second", keys[1], "e")
check("and the file sits with the export",
      keys.index("f") == keys.index("a") - 1, str(keys))
check("and names the default when none is set",
      "qso.log" in dict(on["items"])["f"], dict(on["items"])["f"])
check("or the one in use",
      "paqp.log" in dict(menus.log_menu(on=True, log_name="paqp.log")
                         ["items"])["f"], "")
check("the count is on the toggle",
      "14 QSOs" in on["items"][0][1], on["items"][0][1])
check("lookup state is shown",
      "on" in dict(on["items"])["c"], dict(on["items"])["c"])

# The reference follows the TYPE, not the activity's name: whether this
# station puts a reference on every contact is a property of the template.
activating = menus.log_menu(on=True, count=14, lookup=True,
                            activity="Bald Eagle SP", activity_type="POTA",
                            park="US-5678")
check("the reference is shown once the type needs one",
      "US-5678" in dict(activating["items"])["p"],
      dict(activating["items"])["p"])
check("the activity's own name is shown too",
      "Bald Eagle SP" in dict(activating["items"])["e"],
      dict(activating["items"])["e"])
check("and the type beside it",
      "POTA" in dict(activating["items"])["v"],
      dict(activating["items"])["v"])
# A named activity whose type wants no reference is not asked for one.
# Not named `plain`: that is render.plain, imported at the top, and
# shadowing it broke the width checks further down with a TypeError.
no_ref = menus.log_menu(on=True, count=14, activity="Morning on 40",
                        activity_type="")
check("a general type is asked for no reference",
      "p" not in dict(no_ref["items"]), str(no_ref["items"]))

one = menus.log_menu(on=True, count=1)
check("one contact is singular", "1 QSO" in one["items"][0][1]
      and "QSOs" not in one["items"][0][1], one["items"][0][1])
# No activity reads as "general logging", not as a blank waiting to be filled.
check("no activity reads as general logging",
      "general logging" in dict(one["items"])["v"]
      and "—" not in dict(one["items"])["v"],
      dict(one["items"])["v"])

# There is no QRZ upload item, with a key or without one. Uploading is a
# manual action taken on the laptop; see the end of this file for why that is
# pinned rather than merely intended.
check("no QRZ item without a key",
      "u" not in [k for k, _ in menus.log_menu(on=True)["items"]])
withkey = menus.log_menu(on=True, has_qrz_key=True, qrz_pending=14)
check("and none with one either",
      "u" not in [k for k, _ in withkey["items"]],
      str(withkey["items"]))
check("and no backlog is advertised",
      not any("waiting" in label for _, label in withkey["items"]),
      str(withkey["items"]))

print("\nit is reachable from the root menu")
# The entry and its handler went in together, which is the rule: a root item
# whose Enter does nothing is worse than an absent one. test_menu_arrows
# catches the dead case, because Up-Enter from the first item lands on
# whatever is last -- which is now this.
check("logging is not a line on either area menu",
      not any(l == "Logging"
              for _k, l in menus.DIGI["items"] + menus.DECK["items"]),
      str(menus.DIGI["items"] + menus.DECK["items"]))
check("and the menu it opens is still built",
      menus.log_menu(on=False)["title"] == "LOGGING")
# The two area menus carry what belongs to their own area and nothing else.
equals("the digimode menu is the digimode settings",
       [l for _k, l in menus.DIGI["items"]],
       ["Mode", "Tune Settings", "Band", "Memories"])
# Band is NOT here: it tunes to the digimode calling frequencies, which is a
# digital-modes decision. It was on this menu briefly, on the reasoning that a
# band is a property of the radio -- true of the band, false of this entry.
# No Station line: the deck-and-rig SCREEN is the station editor now, every
# field with its substitution token beside it. A menu opening a second list of
# the same eight settings was the same information twice.
# The three screens added 2026-10-22 are here rather than on an area menu,
# each for its own reason. The auto tuner keys the transmitter for an hour,
# so it is not one `^O` from everything else. The ring editor configures the
# ring, and deck & rig is the one area that cannot leave it -- so it is
# reachable from a deck configured into a corner. The export offers files
# from every area at once and so belongs to none of them.
equals("the deck menu is the deck and the panel",
       [l for _k, l in menus.DECK["items"]],
       ["Display", "System", "Auto tuner", "Function ring order",
        "Send files to a phone"])
check("and the station is not a menu line",
      not any(l == "Station" for _k, l in menus.DECK["items"]),
      str(menus.DECK["items"]))
# Every station field still has to be reachable, which is now the screen's
# job -- so the screen is built from this and the tokens come with it.
check("every station field carries a label",
      all(l for _k, l, _t in menus.STATION_FIELDS),
      str(menus.STATION_FIELDS))
check("and all but the power ceiling carry a token",
      [k for k, _l, t in menus.STATION_FIELDS if not t] == ["TX_POWER_MAX"],
      str([(k, t) for k, _l, t in menus.STATION_FIELDS]))
check("and the band picker is not on it",
      not any(l == "Band" for _k, l in menus.DECK["items"]),
      str(menus.DECK["items"]))
# Every menu with a parent backs out INSIDE its own area, so Esc can never
# cross from one area's menus into another's.
import render as _r
for _child, _parent in menus.MENU_PARENT.items():
    check(f"{_child} backs out to {_parent}", bool(_parent), _child)
check("both area menus say how to reach the others",
      "^O ^P" in menus.DIGI["footer"] and "^O ^P" in menus.DECK["footer"],
      menus.DIGI["footer"] + " / " + menus.DECK["footer"])

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

on_pota = menus.log_menu(on=True, count=5, activity_type="POTA",
                         park="US-5678")
check("an activity with a reference adds the item",
      "p" in [k for k, _ in on_pota["items"]], str(on_pota["items"]))
check("showing the reference",
      any("US-5678" in l for _, l in on_pota["items"]), str(on_pota["items"]))
check("an unset reference reads 'not set' — the activity is selected",
      any("not set" in l for _, l in
          menus.log_menu(on=True, activity_type="POTA")["items"]),
      str(menus.log_menu(on=True, activity_type="POTA")["items"]))
check("a contest activity needs no reference item",
      "p" not in [k for k, _ in
                  menus.log_menu(on=True, activity_type="CONTEST")["items"]],
      str(menus.log_menu(on=True, activity="CONTEST")["items"]))

print("\nthree default activities, and the rest are examples to copy")
equals("exactly three are built in", sorted(activities.BUILTIN),
       ["CONTEST", "GENERAL", "POTA"])
picker = menus.activity_type_menu(sorted(activities.BUILTIN), "POTA")
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
# It used to say "Sign and upload to LoTW", which reads like a key that
# sends. It exports a file and prints the tqsl command; the label says that.
check("and it says it prints the command, because that is all it does",
      any("print" in l.lower() for _, l in
          menus.log_menu(on=True, has_tqsl=True)["items"]))
check("and does not read like a key that sends",
      not any("upload to LoTW" in l for _, l in
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

print("\nnothing in the panel uploads a contact anywhere")
# The operator's rule, 2026-10-11: uploading is always a manual action, never
# automatic. A deck being tested is full of contacts that must not reach
# anyone's permanent record, and "I did not press anything" has to be a
# complete defense.
#
# Pinned as a property of the source rather than as a comment, because a
# comment does not fail when someone wires a key to an uploader.
_PANEL = os.path.join(_SRC, "cyberdeck.py")
_panel_src = open(_PANEL).read()

check("the panel never imports qrzlog",
      "qrzlog" not in _panel_src,
      "cyberdeck.py mentions qrzlog")
# lotw IS imported -- for `available()` and to PRINT a command. What must not
# appear is a call to the function that actually sends.
for call in ("lotw.upload(", "lotwmod.upload(", "qrzlog.upload("):
    check(f"and never calls {call})", call not in _panel_src,
          f"cyberdeck.py calls {call}")

menu = menus.log_menu(True, count=3, has_qrz_key=True, qrz_pending=7, has_tqsl=True)
labels = " ".join(label for _k, label in menu["items"])
check("the menu offers no QRZ upload, even with a key configured",
      "QRZ" not in labels, labels)
check("and no count of contacts 'waiting' to be sent",
      "waiting" not in labels, labels)
check("the LoTW item says it exports and prints rather than sends",
      "print" in labels.lower(), labels)
# Named for WHAT is exported rather than for the format. There is one log and
# one activity-filtered export of it, and "Export ADIF" twice over said
# nothing about which was which. The file extension is on the line anyway.
check("ADIF export is still offered — it writes a local file",
      "Export the whole log" in labels and ".adi" in labels, labels)

# The parameters stay accepted so no caller breaks, and passing them changes
# nothing: that is what makes reinstating an upload item a deliberate edit.
equals("has_qrz_key no longer changes the menu",
       [k for k, _l in menus.log_menu(True, count=3, has_qrz_key=True)["items"]],
       [k for k, _l in menus.log_menu(True, count=3, has_qrz_key=False)["items"]])

print("\na time-out is printed as an operator reads it")
# Minutes all the way up read badly past an hour: a twelve hour time-out
# printed as "720 min" is arithmetic the reader has to do.
for mins, want in ((0, "off"), (15, "15 min"), (30, "30 min"),
                   (60, "1 h"), (90, "1 h 30 min"), (120, "2 h"),
                   (240, "4 h"), (480, "8 h"), (720, "12 h")):
    equals(f"{mins} min reads {want!r}", menus._duration(mins), want)
equals("and nonsense reads off", menus._duration("x"), "off")
equals("as does a negative", menus._duration(-5), "off")

# The menu row itself, so the label and the value stay together.
row = dict(menus.wspr_menu({"timeout_minutes": 720})["items"])["o"]
check("the WSPR menu shows twelve hours", "12 h" in row, row)
check("and still names it the session's", "Session ToT" in row, row)

print("\nthe WSPR menu reaches the session list, as F2 does")
# It went straight to the name editor, which can only START a session -- so
# the menu offered no way back into an earlier one, and the list was
# reachable from `F2` alone. An operator looking for it looked at the menu.
_st = {"session": "general", "band": "20 m", "wspr": True, "decode": True,
       "transmit": False, "tx_next": False, "hopping": False, "hop_count": 1,
       "tx_percent": 20, "timeout_minutes": 60, "upload": "on",
       "log_name": "wspr.log", "heard": 455, "sent": 1, "tx_level": 35,
       "rx_gain": 100, "dbfs": -37.0}
_items = dict(menus.wspr_menu(_st)["items"])
check("the line is there", "e" in _items, sorted(_items))
check("named as a list, like the logging menu's activities",
      _items["e"].startswith("Sessions"), _items["e"])
check("and it shows the one in use", "general" in _items["e"], _items["e"])

sys.exit(report())
