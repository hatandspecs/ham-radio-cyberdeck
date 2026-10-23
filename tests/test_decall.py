"""Pulling a correspondent's callsign out of a transmit line — src/decall.py.

The hotkey this feeds writes a log entry, so the thing that matters is what
it REFUSES. A CQ is not a contact. Somebody else's over decoded into the same
transcript is not our contact. A token that cannot be a callsign must not
become one, for the same reason a corrupt WSPR decode must not become a
distance record.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import decall

ME = "KD3CCO"


class Line:
    def __init__(self, text, who="TX"):
        self.text, self.who = text, who


print("the station worked is the one AFTER DE on a received line")
# A received line is evidence the far end was there and answering. A
# transmitted one only proves we called somebody, which is not a contact.
for line, want in (
        ("KD3CCO DE K2ABC K", "K2ABC"),
        ("KD3CCO DE K2ABC K2ABC K", "K2ABC"),
        ("KD3CCO DE W1AW/4 K", "W1AW/4"),
        ("KD3CCO DE ON5KQ PSE K", "ON5KQ"),
        ("kd3cco de k2abc rr 599", "K2ABC"),
        ("KD3CCO KD3CCO DE K2ABC", "K2ABC")):
    equals(f"{line!r}", decall.worked_station(line, ME), want)

print("\nwhich is the opposite end from a transmitted line")
# Reading this line the old way would have logged our own callsign.
equals("the call before DE is ours, not the contact",
       decall.worked_station("KD3CCO DE K2ABC K", ME), "K2ABC")

print("\na CQ is not a contact with anybody")
for line in ("CQ CQ DE K2ABC K", "CQ DX DE K2ABC K", "QRZ DE K2ABC",
             "CQ TEST DE K2ABC"):
    equals(f"{line!r} names nobody", decall.worked_station(line, ME), "")

print("\ntwo other people working each other is not ours to log")
# Their overs land in the same transcript as everything else.
equals("a line addressed to a third party is refused",
       decall.worked_station("W9XYZ DE K2ABC K", ME), "")
equals("even when both calls are real",
       decall.worked_station("G3ABC DE ON5KQ PSE K", ME), "")
check("without a callsign configured, a CQ is still refused",
      decall.worked_station("CQ CQ DE K2ABC K") == "")
check("but an addressed line is taken at face value",
      decall.worked_station("W9XYZ DE K2ABC K") == "K2ABC")

print("\nno DE, nothing to read")
for line in ("", "   ", "K2ABC K2ABC K", "73 TU", None):
    equals(f"{line!r}", decall.worked_station(line, ME), "")

print("\nwhat cannot be a callsign does not become one")
# Q, 0 and 1 never begin a callsign. The same rule the WSPR work uses to
# throw out corrupt decodes, for the same reason.
for token in ("QD9PDP", "002ADF", "1L2LDQ", "K", "73", "PSE", "TU",
              "ABCDE", "DE"):
    check(f"{token!r} is refused", not decall.is_callsign(token), token)
for token in ("K2ABC", "KD3CCO", "ON5KQ", "W1AW/4", "SQ2WB", "KQ4ADJ",
              "9A1XYZ", "G3JKF", "VK6QS"):
    check(f"{token!r} is a callsign", decall.is_callsign(token), token)

print("\nthe candidates are received lines only, newest first")
entries = [Line("CQ CQ DE K2ABC K", "RX"),
           Line("KD3CCO DE K2ABC K", "RX"),
           Line("K2ABC DE KD3CCO RR 599", "TX"),      # our side
           Line("KD3CCO DE ON5KQ K", "RX"),
           Line("73 TU", "RX")]
got = decall.candidates(entries, ME)
equals("two lines name somebody", len(got), 2)
equals("newest first", [c for _i, c, _t in got], ["ON5KQ", "K2ABC"])
check("the transmitted line is not offered",
      all(entries[i].who == "RX" for i, _c, _t in got), got)
check("and the index points back at the transcript",
      all(entries[i].text == t for i, _c, t in got), got)

print("\nnothing to offer is an empty list, not a guess")
equals("an empty transcript", decall.candidates([], ME), [])
equals("one with no DE lines",
       decall.candidates([Line("73 TU", "RX"), Line("K", "RX")], ME), [])
equals("and one that is all CQ",
       decall.candidates([Line("CQ CQ DE K2ABC K", "RX")], ME), [])

print("\nthe hotkey's three behaviours cycle")
equals("log, then prefill-and-switch",
       decall.next_mode(decall.LOG_NOW), decall.PREFILL_SWITCH)
equals("then prefill-and-stay",
       decall.next_mode(decall.PREFILL_SWITCH), decall.PREFILL_STAY)
equals("then back to log",
       decall.next_mode(decall.PREFILL_STAY), decall.LOG_NOW)
equals("and an unknown mode falls back",
       decall.next_mode("banana"), decall.LOG_NOW)
check("every mode has a label an operator can read",
      all(decall.MODE_LABELS.get(m) for m in decall.MODES),
      decall.MODE_LABELS)

sys.exit(report())
