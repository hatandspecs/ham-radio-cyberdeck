"""The danger zone, driven through a pty against the real program.

Three ways to throw contacts away, and the reason this is a pty test rather
than a unit test is that two of them are only correct if the CONFIRMATION
actually appears and actually stops there. A delete that happens on the first
keystroke passes every test of the function it calls.

What each case checks is the count in the question. "Clear the log" and
"delete 37 contacts" are different sentences, and the second one is the only
one that tells the operator what they are about to lose -- so a question with
the wrong number in it is the bug worth catching here.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
from test_log_panel import deck, RING_FWD

F1 = "\x1bOP"
ENTER = "\r"
ESC = "\x1b"

# Three contacts in one activity and one outside it, so "this activity's
# QSOs" and "every QSO" are different numbers. If they were the same, every
# assertion below would pass with the two actions swapped.
SEEDED = (
    "when=2026-10-15T14:00:00Z call=W3ABC band=20m mode=FT8\n"
    "when=2026-10-15T14:05:00Z call=K3XYZ band=20m mode=FT8\n"
    "when=2026-10-15T14:10:00Z call=N3QRP band=40m mode=FT8\n"
)
OUTSIDE = "when=2026-10-15T09:00:00Z call=W1AW band=20m mode=FT8\n"

ON = "LOGGING = yes\nACTIVITY = Bald Eagle SP\n"


def seeded(extra=""):
    """The configuration under test: an activity with a session key."""
    return ON + "ACTIVITY_START = 2026-10-15T13:00:00Z\n" + extra


def log_with_outside(path_body=SEEDED):
    """The activity's contacts plus one belonging to no activity."""
    began = "2026-10-15T13:00:00Z"
    lines = [f"activity_start={began} {l.strip()} activity=Bald Eagle SP"
             for l in path_body.splitlines() if l.strip()]
    return "\n".join(lines) + "\n" + OUTSIDE


print("the logging menu offers the danger zone")
body, _ = deck([RING_FWD, F1], seeded(), log_body=log_with_outside(),
               label="F1 on the log screen", settle=2.6)
check("a danger zone item is listed", "Danger zone" in body, body[-900:])

print("\nz opens it, with the counts")
body, _ = deck([RING_FWD, F1, "z"], seeded(), log_body=log_with_outside(),
               label="F1 z", settle=2.8)
check("the title is there", "DANGER ZONE" in body, body[-900:])
check("the activity's own count is three",
      "3 from Bald Eagle SP" in body, body[-900:])
check("the whole log's count is four",
      "4 in the whole log" in body, body[-900:])
check("and it says every one asks", "each one asks" in body, body[-300:])

print("\nEsc goes back to the logging menu, not out of the application")
body, _ = deck([RING_FWD, F1, "z", ESC], seeded(),
               log_body=log_with_outside(), label="F1 z Esc", settle=2.9)
check("the logging menu is showing again",
      "Danger zone" in body, body[-900:])
check("and the danger zone is not", "DANGER ZONE" not in body, body[-900:])

print("\ns asks before deleting this activity's contacts")
body, written = deck([RING_FWD, F1, "z", "s"], seeded(),
                     log_body=log_with_outside(), label="F1 z s", settle=2.9)
check("the question names the activity",
      "DELETE THIS ACTIVITY'S QSOS" in body, body[-900:])
check("and counts them", "3 contacts from Bald Eagle SP" in body, body[-900:])
check("and says Enter does it", "Enter delete them" in body, body[-300:])
equals("nothing was deleted by the question", len(written), 4)

print("\nany other key keeps them")
body, written = deck([RING_FWD, F1, "z", "s", "q"], seeded(),
                     log_body=log_with_outside(), label="F1 z s q",
                     settle=3.0)
equals("all four contacts are still there", len(written), 4)

print("\nEnter deletes them, and only them")
body, written = deck([RING_FWD, F1, "z", "s", ENTER], seeded(),
                     log_body=log_with_outside(), label="F1 z s Enter",
                     settle=3.1)
equals("one contact is left", len(written), 1)
check("it is the one outside the activity",
      any("W1AW" in l for l in written), written)
check("and the deck says how many went",
      "3 contacts deleted from Bald Eagle SP" in body, body[-300:])

print("\nm asks before emptying the whole log")
body, written = deck([RING_FWD, F1, "z", "m"], seeded(),
                     log_body=log_with_outside(), label="F1 z m", settle=2.9)
check("the question is about every contact",
      "DELETE EVERY QSO" in body, body[-900:])
check("and counts all four", "All 4 contacts in the log" in body, body[-900:])
equals("nothing was deleted by the question", len(written), 4)

print("\nEnter empties it")
body, written = deck([RING_FWD, F1, "z", "m", ENTER], seeded(),
                     log_body=log_with_outside(), label="F1 z m Enter",
                     settle=3.1)
equals("the log is empty", written, [])
check("and the deck says so", "log emptied" in body, body[-300:])

print("\na forgets the activities and keeps every contact")
body, written = deck([RING_FWD, F1, "z", "a"], seeded(),
                     log_body=log_with_outside(), label="F1 z a", settle=2.9)
check("the question says no contact is deleted",
      "No contact is deleted" in body, body[-900:])
check("and says what the log keeps",
      "all 4 contacts" in body, body[-900:])

body, written = deck([RING_FWD, F1, "z", "a", ENTER], seeded(),
                     log_body=log_with_outside(), label="F1 z a Enter",
                     settle=3.2)
equals("every contact survived", len(written), 4)
check("the labels survived too",
      all("activity=Bald Eagle SP" in l for l in written if "W1AW" not in l),
      written)
check("and the header fell back to the master log",
      "master log" in body.lower(), body[:200])

print("\nthe empty cases say so instead of asking")
body, written = deck([RING_FWD, F1, "z", "m"], "LOGGING = yes\n",
                     label="empty log, m", settle=2.9)
check("an empty log is not worth a confirmation",
      "already empty" in body, body[-300:])
check("so no question was raised", "DELETE EVERY QSO" not in body, body[-900:])

body, _ = deck([RING_FWD, F1, "z", "s"], "LOGGING = yes\n",
               log_body=OUTSIDE, label="no activity, s", settle=2.9)
check("with no activity selected, s explains itself",
      "no activity is selected" in body, body[-300:])

report()
