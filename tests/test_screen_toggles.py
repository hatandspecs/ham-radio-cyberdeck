"""F2 and F3 as screen toggles, from wherever the operator happens to be.

The three views — conversation, tuning, mode — are a flat set, not a tree.
Identifying an unknown signal means going tune, mode, tune, mode, and a
navigation that requires Esc between each is the wrong shape for it. So both
keys reach every screen, and each is its own way back out.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from harness import check, report
from test_screen import run

F2 = "\x1bOQ"
F3 = "\x1bOR"

# The deck OPENS on DECK & RIG, not on the conversation. `^O` steps backwards
# round the ring -- settings | log | digimodes -- and the log is not on it
# while logging is off, which it is in these fixtures, so one `^O` wraps
# straight to the conversation.
#
# Every scenario below starts there, because what is being tested is F2 and
# F3 as toggles BETWEEN the digimode screens and not as a way into them.
# Without this each one read the settings screen, where F2 and F3 are the
# Display and System menus, and all five "from the conversation" checks
# failed on a screen they were never meant to be looking at.
# **Two backwards hops, not one.** WSPR made the ring four areas --
# settings | log | digimodes | WSPR -- so one `^O` back from the boot
# screen now wraps onto WSPR and every scenario below read the wrong
# screen. Named here so the next area costs one edit per file.
TO_CHAT = "\x0f\x0f"


def body(scr):
    return "\n".join(scr.display)


def is_tune(b):
    return "TUNING" in b or "quality" in b


def is_mode(b):
    return "MODE" in b and "AUTO (RSID)" in b


def is_chat(b):
    return "F1 menu" in b and not is_tune(b) and not is_mode(b)


if __name__ == "__main__":
    print("Screen toggles")

    check("F2 from the conversation reaches tuning", is_tune(body(run(keys=[TO_CHAT, F2]))))
    check("F2 again returns to the conversation", is_chat(body(run(keys=[TO_CHAT, F2, F2]))))

    check("F3 from the conversation reaches the mode picker",
          is_mode(body(run(keys=[TO_CHAT, F3]))))
    check("F3 again returns to the conversation",
          is_chat(body(run(keys=[TO_CHAT, F3, F3]))))

    # The two asked for: straight across, without passing through the middle.
    check("F3 from the tuning screen reaches the mode picker",
          is_mode(body(run(keys=[TO_CHAT, F2, F3]))))
    check("F2 from the mode picker reaches the tuning screen",
          is_tune(body(run(keys=[TO_CHAT, F3, F2]))))

    # And back and forth repeatedly, which is the actual use.
    check("tune, mode, tune, mode holds up",
          is_mode(body(run(keys=[TO_CHAT, F2, F3, F2, F3]))))
    check("and ends on the conversation when F3 closes it",
          is_chat(body(run(keys=[TO_CHAT, F2, F3, F2, F3, F3]))))

    # The full mode list is still the mode picker as far as F3 is concerned.
    check("F3 closes the full mode list too",
          is_chat(body(run(keys=[TO_CHAT, F3, "m", F3]))))

    sys.exit(report())
