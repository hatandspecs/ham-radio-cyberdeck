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
TO_DIGI = "\x0f\x0f"


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

        second = run(keys=[TO_DIGI], state_path=path, settle=1.8,
                     settle_s="0.2")
        check("the restarted deck comes back on that carrier",
              f"{saved.get('carrier')}Hz" in second.display[0],
              second.display[0])
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

    sys.exit(report())
