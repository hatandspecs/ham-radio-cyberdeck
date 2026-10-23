"""Pulling a correspondent's callsign out of a received line.

A digimode over names both stations either side of `DE`:

    KD3CCO DE K2ABC K           what arrives
    K2ABC DE KD3CCO K           what goes out

**The received line is the one to read.** On receive, `DE` separates who is
being called -- this station -- from who is calling, which is the station
worked. Taking it from a transmitted line instead would log a contact on the
strength of having called someone, which is not a contact; a received line is
evidence that they were actually there and answering.

Checking the call BEFORE `DE` against this station is what keeps somebody
else's over out of the log. Two stations working each other land in the same
transcript as everything else, and `W9XYZ DE K2ABC` is a contact between two
other people.

This exists so that logging does not mean retyping a callsign already on the
screen, which is the most common thing typed twice in a session.
"""
import re

# A callsign: a prefix, a separating digit, a suffix, and optionally a
# portable or SDR tail. **Q, 0 and 1 are never the first character** -- Q is
# reserved for Q-codes and 0 and 1 are unallocated -- which is the same rule
# the WSPR analysis uses to throw out corrupt decodes, and the same reason:
# a thing that cannot be a callsign should not become a log entry.
# **Q is barred only as the FIRST character.** Anywhere else it is ordinary:
# SQ2WB is Polish and KQ4ADJ is American. An earlier form of this pattern
# excluded Q from the second position too and threw both away -- the same
# mistake made once already in the WSPR corrupt-decode filter, where it also
# discarded every compound call and every SDR reporter.
CALLSIGN = re.compile(
    r"^(?:[A-PR-Z][A-Z0-9]?|[2-9][A-Z])[0-9][A-Z]{1,4}"
    r"(?:/[A-Z0-9]{1,5})?$")

DE = "DE"


def is_callsign(token):
    return bool(CALLSIGN.match((token or "").strip().upper()))


def worked_station(line, my_call=""):
    """The station calling in a RECEIVED line, or "".

    `KD3CCO DE K2ABC K` gives `K2ABC`: on receive, what follows `DE` is the
    far end. When `my_call` is given, the call before `DE` must be this
    station -- otherwise the line is two other people working each other,
    which lands in the same transcript and is not ours to log.

    A CQ is deliberately refused. `CQ CQ DE K2ABC` is somebody calling into
    the air, not a contact, and logging it would invent a QSO that has not
    happened yet.
    """
    if not line:
        return ""
    words = str(line).upper().replace(",", " ").split()
    try:
        i = words.index(DE)
    except ValueError:
        return ""
    before = [w for w in words[:i] if w]
    if my_call:
        mine = my_call.strip().upper()
        if not before or not any(w == mine for w in before):
            return ""
    elif not any(is_callsign(w) for w in before):
        # No callsign at all before DE is a CQ or a QRZ. Without a station
        # of our own to check against, that is the only signal available
        # that the line was not addressed to anybody.
        return ""
    for token in words[i + 1:]:
        if is_callsign(token):
            return token
    return ""


def candidates(entries, my_call="", who="RX"):
    """Received lines that name a correspondent, newest first.

    Returns `(index, callsign, text)` so the screen can offer a choice: the
    most recent is the default and the arrows reach the ones before it.
    """
    out = []
    for i, entry in enumerate(entries):
        if getattr(entry, "who", "") != who:
            continue
        call = worked_station(getattr(entry, "text", ""), my_call)
        if call:
            out.append((i, call, getattr(entry, "text", "")))
    out.reverse()
    return out


# What the hotkey does, cycled from the digimodes menu.
LOG_NOW, PREFILL_SWITCH, PREFILL_STAY = "log", "prefill", "prefill_stay"
MODES = (LOG_NOW, PREFILL_SWITCH, PREFILL_STAY)
MODE_LABELS = {
    LOG_NOW: "log it, stay here",
    PREFILL_SWITCH: "prefill and switch to the log",
    PREFILL_STAY: "prefill, stay here",
}


def next_mode(mode):
    try:
        return MODES[(MODES.index(mode) + 1) % len(MODES)]
    except ValueError:
        return MODES[0]
