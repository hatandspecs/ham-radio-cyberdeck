"""F2 and F3 from inside a menu belong to the area the menu was opened from.

Found by an operator on deck & rig: `F1` `6` to the rig-mode menu, then `F2`
by accident, and the deck left the area entirely and drew the digimode tuner.
`_handle_menu` ran the digimodes pair from inside EVERY menu, because the
block predates the other three areas.

The rule the codebase already states, in `_handle_log`'s own comment: "on
every area, F2 and F3 are that area's two main sub-views."
"""
import os
import sys

_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import check, report
from test_screen import run, show

F1, F2, F3 = "\x1bOP", "\x1bOQ", "\x1bOR"
CTRL_O, CTRL_P = "\x0f", "\x10"

# The ring, as the rest of the suite counts it: the deck boots on DECK & RIG,
# `^P` once reaches the log, `^O` twice reaches WSPR and three times the
# conversation.
TO_SET = []
TO_LOG = [CTRL_P]
TO_WSPR = [CTRL_O, CTRL_O]
TO_DIGI = [CTRL_O, CTRL_O, CTRL_O]

# The tuning screen's own rows, used to prove the deck did NOT land there.
TUNER_MARK = "quality"


# -- deck & rig: the reported bug ---------------------------------------------

# `F1` `6` opens the rig-mode menu, and `F2` from there used to close it and
# draw the digimode tuner.
body = show("F2 from the rig-mode menu",
            run(keys=TO_SET + [F1, "6", F2]))
check("it does not leave for the digimode tuner", TUNER_MARK not in body,
      body[:400])
check("it opens this area's first sub-view, DISPLAY", "DISPLAY" in body,
      body[:400])

body = show("F3 from the rig-mode menu",
            run(keys=TO_SET + [F1, "6", F3]))
check("F3 does not leave for the digimode tuner either",
      TUNER_MARK not in body, body[:400])
check("it opens this area's second sub-view, SYSTEM", "SYSTEM" in body,
      body[:400])

# The same two keys from the area's top menu, not only from a sub-menu.
body = show("F2 from the deck menu", run(keys=TO_SET + [F1, F2]))
check("F2 on the deck menu opens DISPLAY",
      "DISPLAY" in body and TUNER_MARK not in body, body[:400])


# -- digimodes: the behavior the old block was written for, still intact ------

body = show("F2 from the digimode menu", run(keys=TO_DIGI + [F1, F2]))
check("F2 still reaches the tuner from a digimode menu",
      TUNER_MARK in body, body[:400])

body = show("F3 from the digimode menu", run(keys=TO_DIGI + [F1, F3]))
check("F3 still opens the mode picker", "MODE" in body.upper(), body[:400])

# F3 out of the mode picker is the way back to the conversation: tune, mode,
# tune, mode without climbing a tree.
body = show("F3 twice from the digimode menu",
            run(keys=TO_DIGI + [F1, F3, F3]))
check("a second F3 closes the mode picker rather than reopening it",
      "Tune Settings" not in body, body[:400])


# -- logging and WSPR: the other two areas, same rule ------------------------

body = show("F2 from the logging menu", run(keys=TO_LOG + [F1, F2]))
check("F2 on a logging menu opens the activities list",
      "ACTIVITIES" in body and TUNER_MARK not in body, body[:400])

body = show("F3 from the logging menu", run(keys=TO_LOG + [F1, F3]))
check("F3 on a logging menu does not reach the digimode tuner",
      TUNER_MARK not in body, body[:400])

body = show("F2 from the WSPR menu", run(keys=TO_WSPR + [F1, F2]))
check("F2 on a WSPR menu opens the session list",
      "WSPR SESSIONS" in body and TUNER_MARK not in body, body[:400])

body = show("F3 from the WSPR menu", run(keys=TO_WSPR + [F1, F3]))
check("F3 on a WSPR menu does not reach the digimode tuner",
      TUNER_MARK not in body, body[:400])

report()
