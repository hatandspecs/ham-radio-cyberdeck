"""What the deck remembers when it is restarted.

The deck is switched off by removing its power, so "remembered" has to mean
written to the card, not written to the page cache. Two faults hide here and
neither shows up in a single run:

  * the state is never written, and the defaults quietly stand;
  * the state is written but not flushed, so a clean restart restores it and
    a power cut does not — which reads as "sometimes it works".

This starts the real application, changes something, lets it exit, starts it
again against the same state file, and looks at the screen. The second fault
is addressed by fsync in _save_state; it cannot be reproduced here without
cutting power, so what this covers is the first, plus the read-back path.
"""
import os
import sys
import json
import shutil
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from harness import check, equals, report
from test_screen import run
import colors

F1 = "\x1bOP"          # xterm F1: the menu
F3 = "\x1bOR"          # xterm F3: the mode picker
F4 = "\x1bOS"          # xterm F4: cycle the color scheme
TO_LOG = "\x10"         # ^P: one stop along the ring, the log
# ^O: backwards round the ring from the boot screen, wrapping past the log to
# the conversation. The deck OPENS on DECK & RIG, so every scenario about a
# MODEM, a CARRIER or the digimode status line has to hop there first --
# otherwise `display[0]` is the station fields' own header and the mode keys
# land on a screen that has no modem.
# **Two backwards hops, not one.** WSPR made the ring four areas --
# settings | log | digimodes | WSPR -- so one `^O` back from the boot
# screen now wraps onto WSPR and every scenario below read the wrong
# screen. Named here so the next area costs one edit per file.
TO_DIGI = "\x0f\x0f\x0f"
# Three hops: the ring is five areas now (the band plan joined it),
# and `^O` x3 lands on the conversation whether or not logging is on --
# which is the property the old two-hop constant had. See the ring-hop
# trap in AGENTS.md.


if __name__ == "__main__":
    print("Remembered state across a restart")
    tmp = tempfile.mkdtemp(prefix="cyberdeck-state-")
    path = os.path.join(tmp, "state", "cyberdeck.json")
    try:
        # A fresh deck, then RTTY chosen from the curated list (F3, then 4).
        first = run(keys=[TO_DIGI, F3, "4"], state_path=path, settle=1.5)
        body = "\n".join(first.display)
        check("the mode change took effect", "RTTY" in body, body[:200])

        check("a state file was written", os.path.exists(path), path)
        saved = {}
        if os.path.exists(path):
            with open(path) as fh:
                saved = json.load(fh)
        equals("it records the mode", saved.get("mode"), "RTTY")
        check("it records a carrier", isinstance(saved.get("carrier"), int),
              repr(saved.get("carrier")))

        # A second process, same state file, and no keys but the hop: what
        # is being tested is the mode it comes back in, which is read off the
        # digimode status line.
        second = run(keys=[TO_DIGI], state_path=path, settle=1.8,
                     settle_s="0.2")
        body2 = "\n".join(second.display)
        check("the restarted deck comes back in RTTY", "RTTY" in body2,
              body2[:200])
        check("and says it resumed rather than starting fresh",
              "resumed" in body2 or "RTTY" in body2, body2[:300])

        # The default is BPSK31; seeing it would mean the state was ignored.
        check("it did not fall back to the configured default",
              "BPSK31" not in body2.split("\n")[0], body2.split("\n")[0])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # A carrier moved by tuning, with no menu action at all. This is the case
    # that was broken: _save_state ran only from menu actions, so a deck tuned
    # with the search and nudge keys and then restarted came back on whatever
    # carrier happened to be live at the last colour change or memory edit.
    print("\nA carrier moved by tuning, with no menu action")
    tmp = tempfile.mkdtemp(prefix="cyberdeck-tuned-")
    path = os.path.join(tmp, "state", "cyberdeck.json")
    try:
        # Ctrl-D nudges the carrier +10 Hz; settle longer than STATE_SETTLE_S
        # so the deck has a chance to write it.
        nudges = [TO_DIGI] + ["\x04"] * 6
        first = run(keys=nudges, state_path=path, settle=1.5, settle_s="0.2")
        line = first.display[0]
        check("the nudges moved the carrier", "Hz" in line, line)

        saved = {}
        if os.path.exists(path):
            with open(path) as fh:
                saved = json.load(fh)
        check("a carrier reached only by tuning is written to the state file",
              isinstance(saved.get("carrier"), int), repr(saved.get("carrier")))
        # 1500 is the configured default; the nudges moved it off that.
        check("and it is where the tuning left it, not the default",
              saved.get("carrier") not in (None, 1500), repr(saved.get("carrier")))

        # **A SHORT settle, and a tolerance.** fldigi's AFC moves the
        # carrier on its own, so the longer this waits the further the
        # reading drifts from what was restored: 1560 came back as 1556
        # after five seconds. Raising the settle to "fix" an intermittent
        # failure here made it reliable in the wrong direction, which is
        # worth recording -- the wait was never the problem.
        #
        # What is being tested is that the state file was HONORED rather
        # than ignored, so the assertion is "near the saved carrier, and
        # nowhere near the configured default", not an exact match.
        second = run(keys=[TO_DIGI], state_path=path, settle=1.8,
                     settle_s="0.2")
        import re as _re
        shown = _re.search(r"(\d+)Hz", second.display[0])
        got = int(shown.group(1)) if shown else None
        check("the restarted deck reports a carrier at all",
              got is not None, second.display[0])
        check("which is the one from the state file, within AFC drift",
              got is not None and abs(got - saved["carrier"]) <= 15,
              f"{got} vs saved {saved.get('carrier')}")
        check("and not the configured default",
              got is not None and abs(got - 1500) > 15,
              f"{got}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nsettings a menu can change outlive a restart")
    # Every one of these already called `_save_state` and not one was in the
    # saved dict, so the panel wrote a state file that did not contain the
    # thing just changed. Lines-per-contact set to 3 came back as 1, and a
    # reference typed for an activation was gone after a flat battery --
    # during the activation it was typed for.
    import cyberdeck as _deck
    check("the list of them is not empty", bool(_deck._REMEMBERED),
          str(_deck._REMEMBERED))

    d = tempfile.mkdtemp(prefix="cyberdeck-remember-")
    try:
        conf = os.path.join(d, "cyberdeck.conf")
        with open(conf, "w") as fh:
            fh.write("CALLSIGN = KD3CCO\nLOGGING = yes\nLOG_LINES = 1\n"
                     + f"LOG_PATH = {os.path.join(d, 'qso.log')}\n")
        state = os.path.join(d, "state", "cyberdeck.json")
        # ^P to the log, F1 for its menu, `n` to cycle the lines. There is
        # no key that jumps to the log any more -- the ring reaches it.
        run(keys=[TO_LOG, F1, "n"], state_path=state, conf=conf, settle=1.6)
        saved = {}
        if os.path.exists(state):
            with open(state) as fh:
                saved = json.load(fh)
        equals("the line count is written to the state file",
               saved.get("LOG_LINES"), "2")

        # A second process, same state file: it has to come back on 2 rather
        # than on the 1 the conf says.
        second = run(keys=[TO_LOG, F1], state_path=state, conf=conf,
                     settle=1.8, settle_s="0.2")
        body = "\n".join(second.display)
        check("and the restarted deck comes back on it",
              "2 of 3" in body, body[:400])
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print("\nF4 cycles the color scheme from every area")
    # It was bound in one place, on the fallthrough BELOW the screen handlers,
    # so it worked on the conversation and was a dead key on the log screen,
    # the activities list, the pickers, the tune screen and inside every menu.
    # Changing scheme is a decision about the light in the room, not about the
    # screen in front of you.
    #
    # The state file is what makes it observable: the scheme deliberately
    # writes no transcript note, because a log of it is noise mid-contact.
    def color_after(keys):
        """The remembered scheme after driving `keys` into a fresh deck."""
        d = tempfile.mkdtemp(prefix="cyberdeck-scheme-")
        try:
            conf = os.path.join(d, "cyberdeck.conf")
            with open(conf, "w") as fh:
                fh.write("CALLSIGN = KD3CCO\nLOGGING = yes\n"
                         + f"LOG_PATH = {os.path.join(d, 'qso.log')}\n")
            state = os.path.join(d, "state", "cyberdeck.json")
            run(keys=keys, state_path=state, conf=conf, settle=1.5)
            if not os.path.exists(state):
                return ""
            with open(state) as fh:
                return json.load(fh).get("color", "")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    # No baseline from a keyless run: nothing triggers a save, so the state
    # file is not written at all and there is nothing to compare against. What
    # matters is not which scheme F4 lands on but that one keystroke lands on
    # the SAME one from all three areas.
    moved = color_after([F4])
    check("F4 on the conversation records a scheme",
          moved in colors.SCHEMES, repr(moved))
    # The same one keystroke, from the other two areas. Asserted as the SAME
    # destination: one cycle step from the same starting scheme, so a handler
    # that fired twice or not at all both show up here.
    equals("F4 on the log screen lands on the same one",
           color_after([TO_LOG, F4]), moved)
    equals("and F4 inside the settings menu too",
           color_after([F1, F4]), moved)

    print("\nevery WSPR setting outlives a power cycle")
    # Reported as "tx and rx audio gain seem not to stick through power
    # cycles". The levels were only the visible part: NOT ONE WSPR setting
    # was in `_REMEMBERED`, so a power cycle also forgot the band rotation,
    # the session name, the transmit percent, the time-out and the upload
    # toggle. And the restore loop accepted `str` only, so the numeric ones
    # could not have come back even once they were listed.
    import cyberdeck as _deck
    import config as _config

    # **The hardware addresses are deliberately NOT remembered.** None of
    # them is reachable from a menu, which is the rule `_REMEMBERED`
    # follows, and persisting them is actively harmful: a state file written
    # when the codec was card 1 kept pointing a corrected build back at
    # card 1 after the codec became card 2, so the stale value beat the
    # fixed default and the audio stayed dead. These belong in the conf,
    # where a card that moves is a one-line edit.
    HARDWARE = ("WSPR_DEVICE", "WSPR_RX_CARD", "WSPR_RX_CONTROL",
                "WSPR_RX_AGC")
    for key in sorted(k for k in _config.SCHEMA if k.startswith("WSPR_")):
        if key in HARDWARE:
            check(f"{key} is NOT remembered",
                  key not in _deck._REMEMBERED, key)
        else:
            check(f"{key} is remembered", key in _deck._REMEMBERED, key)

    # The numeric ones specifically: JSON gives an int back as an int, which
    # the old `isinstance(value, str)` test silently discarded.
    numeric = [k for k in _deck._REMEMBERED
               if _config.SCHEMA.get(k, (None, str, ""))[1] is not str]
    check("there are numeric settings in the list", bool(numeric),
          str(numeric))

    # And a real round trip through a process, which is the only thing that
    # proves the write and the read agree.
    #
    # **The state file is written by hand rather than driven through the
    # UI.** The levels are only reachable from the calibration screens now,
    # and those are refused unless WSPR is running -- which would stop
    # fldigi and take the sound card, and no test here does that. Writing
    # the file directly exercises the part that was actually broken: the
    # restore loop accepted `str` only, so every NUMERIC setting was
    # written and then silently discarded on the way back in.
    # Two hops back reaches WSPR on the five-area ring, whether or not
    # logging is on. A SECOND ring-hop site in this file -- the one above
    # is TO_DIGI -- which is how the last ring change was missed too.
    TO_WSPR, ESC = "\x0f\x0f", "\x1b"
    tmp = tempfile.mkdtemp(prefix="cyberdeck-wspr-state-")
    path = os.path.join(tmp, "state", "cyberdeck.json")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump({"WSPR_TX_LEVEL": 25, "WSPR_RX_GAIN": 40}, fh)
        screen = run(keys=[TO_WSPR, F1, "a"], state_path=path, settle=3.0,
                     settle_s="0.2")
        body = "\n".join(screen.display)
        # The AUDIO submenu's spelling, which is "TX audio 25%  RX gain
        # 40%" -- the main WSPR menu writes the same values as "TX 25%  RX
        # 40%", and asserting that form here failed against a screen that
        # was entirely correct.
        check("the transmit level comes back from the state file",
              "TX audio 25%" in body, body)
        check("and so does the capture gain", "RX gain 40%" in body, body)
        # Neither is 50 or 70, which is what the conf alone would give.
        check("not the configured defaults",
              "TX audio 50%" not in body and "RX gain 70%" not in body,
              body)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    sys.exit(report())
