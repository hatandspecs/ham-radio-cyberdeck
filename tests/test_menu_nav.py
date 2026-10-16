"""Menu navigation, driven through a real pty, with fldigi checked afterwards."""
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

F1, F2, F3, F4 = "\x1bOP", "\x1bOQ", "\x1bOR", "\x1bOS"

f = Fldigi()
f.set_modem("BPSK31")

# F1 opens the menu for the AREA the operator is in. On the digimode screen
# that is the digimode settings: the deck's own settings are their own area,
# one ^B away, and mixing the two is what made this screen the deck's home.
body = show("F1 digimode menu", run(keys=[F1]))
check("the digimode menu opens", "DIGIMODES" in body)
check("its items are listed",
      all(w in body for w in ("Mode", "Tune Settings", "Memories")))
check("and the deck's own settings are not among them",
      "Station" not in body and "System" not in body, body[:400])
check("it says how to reach the other areas", "^O ^P" in body, body[-200:])

# Ctrl-O from the digimode screen reaches the log, and again the deck's own
# settings -- the ring order read as a strip: settings | log | digimodes.
body = show("^B ^B -> the settings screen", run(keys=["\x0f", "\x0f"]))
check("the settings screen is its own screen", "DECK & RIG" in body, body[:200])
check("and it answers what the station is set to",
      "Callsign" in body and "Rig" in body, body[:400])

body = show("^B ^B then F1 -> the deck menu", run(keys=["\x0f", "\x0f", F1]))
check("F1 there opens the deck menu", "DECK & RIG" in body, body[:200])
# Station is NOT on it: the screen behind the menu edits those fields in
# place, every one with its substitution token beside it. A menu offering a
# second list of the same eight settings was the same information twice.
check("it offers the panel's own settings", "Display" in body
      and "System" in body, body[:400])
check("and not a second list of the station fields",
      "Station" not in body, body[:400])

# The station fields are edited on the screen itself, not through a menu.
body = show("^O ^O -> the station fields", run(keys=["\x0f", "\x0f"]))
check("the callsign is on the screen", "Callsign" in body, body[:400])
check("with the token a memory substitutes it into",
      "{call}" in body, body[:400])
check("and Enter edits the row the cursor is on",
      "Enter edit" in body, body[-120:])

body = show("F1 then 2 -> Tune Settings", run(keys=[F1, "2"]))
check("tuning menu reached", "TUNING" in body or "AFC" in body, body[:300])

# Display moved to the deck's own area with the rest of what the panel does,
# so it is reached through that area now: ^B ^B to its screen, F1, then 3.
body = show("the deck menu then 1 -> Display",
            run(keys=["\x0f", "\x0f", F1, "1"], settle=1.6))
check("display menu reached", "DISPLAY" in body, body[:200])
check("all four schemes offered",
      all(w in body for w in ("Matrix", "Deckard", "Hal", "Tron")), body[:400])

body = show("F3 mode picker", run(keys=[F3]))
check("mode menu opens", "MODE" in body)
check("current mode is marked", "BPSK31  <" in body, [l for l in body.splitlines() if "BPSK31" in l])
check("'more modes' offered", "more modes" in body)

body = show("F3 then m -> the full list", run(keys=[F3, "m"]))
check("paged list reached", "ALL MODES" in body and "page 1/" in body)
check("single-key selection shown", " a " in body and " b " in body)

print("\n-- selecting RTTY actually changes fldigi's modem --")
run(keys=[F3, "4"], settle=1.5)
after = f.modem()
check("fldigi is now on RTTY", after == "RTTY", after)

# Each run starts a fresh Deck, which applies DEFAULT_MODE from the config on
# startup — so a mode set in one run is deliberately overridden in the next.
# The marking has to be checked inside a single session: pick RTTY, reopen the
# menu, and look.
body = show("select RTTY then reopen the menu, one session",
            run(keys=[F3, "4", F3]))
check("RTTY marked as current", "RTTY  <" in body,
      [l for l in body.splitlines() if "RTTY" in l])
f.set_modem("BPSK31")

print("\n-- the radio menu sets the VFO --")
before = f.frequency()
run(keys=[F1, "3", "1"], settle=1.5)          # menu -> Radio -> 14.070
after = f.frequency()
check("VFO moved to 14.070", abs(after - 14_070_000) < 1000, f"{before} -> {after}")

print()
sys.exit(report())
