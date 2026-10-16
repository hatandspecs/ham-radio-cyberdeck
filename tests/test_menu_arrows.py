"""Arrow-key menu navigation and live menu state, driven through a real pty.

The harness runs with TERM=xterm, where keypad(True) puts the terminal into
application cursor mode: Down is \x1bOB, not \x1b[B. The deck itself runs on
the Linux console, where kcud1 is \x1b[B. ncurses resolves both from terminfo;
the test has to send whatever its own TERM specifies.
"""
import os
import sys

# src/ holds the application; tests/ holds this. Both are addressed from the
# project root so a test can be run from anywhere.
_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_PROJECT, "src")
sys.path.insert(0, _SRC)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import check, equals, report
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_screen import run, show
from fldigi_client import Fldigi
import menus

F1, F3 = "\x1bOP", "\x1bOR"
UP, DOWN, ENTER, ESC = "\x1bOA", "\x1bOB", "\r", "\x1b"

body = show("F1, then Down Down", run(keys=[F1, DOWN, DOWN]))
check("the menu is still open after arrows", "DIGIMODES" in body, body[:200])

print("\n-- Down x2 then Enter should reach the third item, Memories --")
body = show("F1 Down Down Enter", run(keys=[F1, DOWN, DOWN, ENTER]))
check("landed on MEMORIES", "MEMOR" in body.upper(), body[:400])

print("\n-- Enter on the first item reaches Mode --")
body = show("F1 Enter", run(keys=[F1, ENTER]))
check("landed on MODE", "MODE" in body, body[:400])

# Up from the first item wraps to the last, and Enter on it opens that
# submenu. Both halves matter: an entry with no handler still wraps to, and
# then does nothing, which is how the Logging entry was caught.
#
# Derived from the menu rather than named, because F1 opens the menu for the
# area the operator is in and the digimode screen is where the deck starts.
CTRL_O = "\x0f"          # one area back on the ring
# F1 from the digimode screen: Mode, Tune Settings, Memories.
DIGI_MODE, DIGI_TUNE, DIGI_MEM = "1", "2", "3"
# The deck's own settings are an area of their own: ^B ^B gets to its screen,
# F1 opens its menu, then Station, Band, Display, System.
DECK = [CTRL_O, CTRL_O, "\x1bOP"]
DECK_STATION, DECK_BAND, DECK_DISPLAY, DECK_SYSTEM = "1", "2", "3", "4"

_LAST = menus.DIGI["items"][-1][1].upper()
print(f"\n-- Up from the first item wraps to the last, {_LAST.title()} --")
body = show("F1 Up Enter", run(keys=[F1, UP, ENTER]))
check(f"wrapped to {_LAST} and it opened", _LAST in body, body[:400])

print("\n-- tuning menu now shows live state --")
body = show("F1 then 2", run(keys=[F1, DIGI_TUNE]))
check("tuning menu shows AFC state", "AFC" in body and ("ON" in body or "off" in body), body[:400])
check("squelch state shown", "Squelch" in body, body[:400])

print("\n-- arrows still leave the single-key shortcuts working --")
body = show("F3 then 4 (RTTY)", run(keys=[F3, "4"], settle=1.5))
check("fldigi on RTTY", Fldigi().modem() == "RTTY", Fldigi().modem())


print("\n-- message memories are edited in place --")
CTRL_U, ENTER = "\x15", "\r"
body = show("F1 5 opens the list", run(keys=[F1, DIGI_MEM], settle=1.3))
check("the list names every slot", all(f"F{n}" in body for n in range(5, 13)), body[:300])
check("empty slots are marked", "(empty)" in body, body[:300])

body = show("F1 5 3 edits F7", run(keys=[F1, DIGI_MEM, "3"], settle=1.4))
check("the editor opens on the chosen slot", "EDIT  F7" in body, body[:200])
check("and loads its current text", "NAME HR IS" in body, body[:200])

body = show("clear and save leaves it empty",
            run(keys=[F1, DIGI_MEM, "3", CTRL_U, ENTER], settle=1.6))
check("back on the list", "MESSAGE MEMORIES" in body, body[:200])
check("F7 is now empty", "F7  (empty)" in body, body[:400])

body = show("type and save stores it",
            run(keys=[F1, DIGI_MEM, "6", CTRL_U] + list("TEST MEMORY") + [ENTER], settle=1.8))
check("F10 holds the new text", "F10  TEST MEMORY" in body, body[:400])

body = show("Esc discards", run(keys=[F1, DIGI_MEM, "2", CTRL_U] + list("XXX") + ["\x1b"], settle=1.8))
check("F6 is untouched", "F6  DE {call} {call} K" in body, body[:400])


print("\n-- the station fields are editable, and show their tokens --")
body = show("F1 6 — station", run(keys=DECK + [DECK_STATION], settle=1.6))
check("every field carries its token",
      all(t in body for t in ("{call}", "{name}", "{qth}", "{grid}", "{rig}",
                              "{ant}", "{power}")), body[:400])
check("and its current value", "KD3CCO" in body, body[:400])

body = show("F1 6 2 — edit Name", run(keys=DECK + [DECK_STATION, "2"], settle=1.6))
check("the editor names the field", "EDIT  Name" in body, body[:200])
check("no memory-token hint here",
      "filled in when inserted" not in body, body[-200:])

body = show("editing a memory does show the token hint",
            run(keys=[F1, DIGI_MEM, "1"], settle=1.4))
check("token hint present for a memory", "{call}" in body, body[-200:])
check("and it says how to make a memory multi-line",
      "\\n" in body, body[-200:])

body = show("change Name and save",
            run(keys=DECK + [DECK_STATION, "2", CTRL_U] + list("DONALD") + [ENTER], settle=2.0))
check("the station list shows the new value", "DONALD" in body, body[:400])

print("\n-- the renamed menu entries --")
body = show("F1 digimode menu", run(keys=[F1], settle=1.2))
check("Tuning is now Tune Settings", "Tune Settings" in body, body[:300])
# Band moved to the deck's own area along with the rest of the rig settings,
# so it is checked on the menu it is on now rather than on this one.
body = show("the deck menu", run(keys=DECK, settle=1.6))
check("Radio is now Band", "Band" in body and "Radio" not in body, body[:300])


print("\n-- the band list runs low to high and marks what the rig cannot do --")
import menus
labels = [lbl for _k, lbl, _d, _h in menus.BANDS]
freqs = [hz for _k, _l, _d, hz in menus.BANDS]
check("eleven bands", len(menus.BANDS) == 11, labels)
check("17 m and 12 m are present", {"17 m", "12 m"} <= set(labels), labels)
check("every band has its own key", len({k for k, *_ in menus.BANDS}) == 11,
      [k for k, *_ in menus.BANDS])
check("ordered low to high", freqs == sorted(freqs), freqs)
check("starts at 80 m", labels[0] == "80 m", labels[0])
check("ends at 70 cm", labels[-1] == "70 cm", labels[-1])
check("VHF and UHF are the PSK31 calling frequencies",
      dict(zip(labels, freqs))["6 m"] == 50_290_000
      and dict(zip(labels, freqs))["2 m"] == 144_144_000
      and dict(zip(labels, freqs))["70 cm"] == 432_200_000,
      dict(zip(labels, freqs)))

hf_bands = {"80 m", "40 m", "30 m", "20 m", "17 m", "15 m", "12 m", "10 m"}
hf_only = menus.band_menu(hf_bands)
marked = [lbl for _k, lbl in hf_only["items"] if "not supported" in lbl]
check("an HF-only rig marks the three VHF/UHF entries", len(marked) == 3, marked)
check("and leaves every HF one unmarked",
      len(hf_only["items"]) - len(marked) == len(hf_bands), hf_only["items"])
check("no radio restriction means nothing is marked",
      not any("not supported" in lbl for _k, lbl in menus.band_menu()["items"]),
      menus.band_menu()["items"])

body = show("F1 3 — the band list", run(keys=DECK + [DECK_BAND], settle=1.6))
check("titled BAND", "BAND" in body, body[:200])
check("shows 70 cm", "432.200" in body, body[:400])


print("\n-- the ^WASD note lives in Tune Settings, not on the main screen --")
body = show("conversation screen", run(keys=[], settle=1.3))
check("the hint line no longer mentions ^WASD", "^WASD" not in body, body[-120:])
# At 66 columns the hint line carries `^O ^P area`, which is the only place
# the ring is taught, and that costs `F5+ memory` -- which the digimode menu
# still lists. `^C abort` keeps its place: a key that stops the transmitter is
# worth more on a footer than one that inserts a macro.
check("but still offers the menu and the areas",
      "F1 menu" in body and "^O ^P area" in body, body[-120:])

body = show("F1 2 — tune settings", run(keys=[F1, DIGI_TUNE], settle=1.4))
check("the note is here instead", "Ctrl-A / Ctrl-D" in body, body[:500])
check("and names the search keys", "Ctrl-W / Ctrl-S" in body, body[:500])

tune = menus.tuning_menu(True, True, 30, True, False, False)
note_rows = [i for i, (key, _lbl) in enumerate(tune["items"]) if not key.strip()]
# Two rows, and the count matters: the renderer splits a menu of more than
# height-6 items into two columns that truncate every label at 27 characters,
# which mangles this menu. Adding a row here costs a selectable one.
check("the note rows exist", len(note_rows) >= 2, note_rows)
check("the menu still fits one column at 66x20",
      len(tune["items"]) <= 20 - 6, f'{len(tune["items"])} items')
check("and none of them can be selected",
      not set(note_rows) & set(menus.selectable(tune)),
      (note_rows, menus.selectable(tune)))


print("\n-- Ctrl-Y hands back, not Ctrl-K --")
body = show("hint line", run(keys=[], settle=1.2))
check("the hint offers ^Y", "^Y hand" in body, body[-120:])
check("and no longer ^K", "^K hand" not in body, body[-120:])


print("\n-- system hotkeys work outside the menu, and are advertised in it --")
CTRL_X, CTRL_I = "\x18", "\x09"
body = show("F1 7 — system", run(keys=DECK + [DECK_SYSTEM], settle=1.6))
check("the inhibit hotkey is shown", "Ctrl-I" in body, body[:400])
check("the Tab collision is named", "also Tab" in body, body[:400])
check("the clear hotkey is shown", "Ctrl-X" in body, body[:400])
check("quit too", "Ctrl-Q" in body, body[:400])

# after=2.5, longer than the fldigi client's two-second timeout: Ctrl-X calls
# text.clear_rx before it writes its note, so a slow fldigi delays the note
# rather than preventing it.
body = show("Ctrl-X clears", run(keys=[CTRL_X], settle=1.6, after=2.5))
check("the transcript is emptied", "transcript cleared" in body, body[:300])
check("and the startup notes are gone", "fldigi 4.2" not in body, body[:300])

body = show("Ctrl-I arms transmit", run(keys=[CTRL_I], settle=1.4))
check("INH clears from the status line", " INH " not in body, body[:120])
check("and it is recorded", "transmit enabled" in body, body[:400])


print("\n-- The RX hold after an over is adjustable from Tune Settings --")
body = show("F1 2", run(keys=[F1, DIGI_TUNE], settle=1.4))
check("both bounds are listed with their values",
      "RX hold least" in body and "RX hold most" in body, body[:700])
check("the default window is 1000 to 4000 ms",
      "(1000 ms)" in body and "(4000 ms)" in body, body[:700])

body = show("] raises the lower bound twice",
            run(keys=[F1, "2", "]", "]"], settle=1.7))
check("stepped up by 250 ms each press", "(1500 ms)" in body, body[:700])
body = show("[ lowers it to zero",
            run(keys=[F1, "2", "[", "[", "[", "["], settle=1.9))
check("and down again", "(0 ms)" in body, body[:700])

body = show("} raises the upper bound",
            run(keys=[F1, "2", "}", "}"], settle=1.7))
check("the upper bound steps too", "(4500 ms)" in body, body[:700])

# The pair must never describe an impossible window: a lower bound above the
# upper one would blank for longer than the gate is allowed to wait, which is
# not a state the operator can reason about. Raising one carries the other.
body = show("lower bound pushed past the upper one",
            run(keys=[F1, "2"] + ["{"] * 14 + ["]"] * 2, settle=3.0))
check("raising least past most carries most up with it",
      body.count("(1000 ms)") >= 2 or body.count("(1250 ms)") >= 2,
      body[:700])

# 0 is not a duration here: it turns the quality gate off and leaves the
# fixed window, so the menu says so rather than printing "0 ms".
body = show("upper bound at zero",
            run(keys=[F1, "2"] + ["{"] * 16, settle=3.2))
check("an upper bound of zero reads as off", "RX hold most   down   (off)" in body,
      body[:700])

sys.exit(report())
