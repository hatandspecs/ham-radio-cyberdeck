"""`^G` on the conversation screen — `Deck._log_from_transcript`.

The hotkey reads the last RECEIVED line, takes the station named after `DE`,
and does one of three things with it. What matters, and what this file checks:

**It logs the other station, never this one.** A transmitted line names this
station after `DE`. Logging that would log ourselves, with the correspondent's
callsign nowhere in the record.

**"Log it" writes the file.** Not just the form. A commit without an append
clears the entry and throws the contact away, which is the one failure that
cannot be noticed until the log is read back.

**The other two behaviours leave the contact recoverable.** The callsign goes
in as a PREFILL, so `Ctrl-Z` offers to replace a misdecoded one, and only
`prefill` moves the screen.

The commit path is the real `_log_commit` — the same one the log screen's
Enter takes — against a log file in a temporary directory. Only the radio
accessors are stubbed, because the point is the record that lands on disk.
"""
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import time

import cyberdeck
import decall
import logform
import activities
import qsolog
import session as session_mod

MYCALL = "KD3CCO"


def deck(mode=decall.PREFILL_SWITCH, log_on=True, heard=(), sent=(),
         schema="", tmpdir=None):
    """A Deck with just enough attached to run the hotkey and the commit."""
    d = cyberdeck.Deck.__new__(cyberdeck.Deck)
    d.cfg = {"LOG_HOTKEY": mode, "CALLSIGN": MYCALL, "LOCATOR": "FM19",
             "ACTIVITY": "", "ACTIVITY_START": "", "ACTIVITY_TYPE": schema,
             "RIG": "FTX-1", "ANTENNA": "EFHW", "TX_POWER": 5,
             "ACTIVITY_TYPE": schema}
    d.log_on = log_on
    d.screen = cyberdeck.CHAT
    d.session = session_mod.Session(callsign=MYCALL)
    for text in heard:
        d.session.receive(text + "\n")
    for text in sent:
        d.session._append(MYCALL, text)

    act = activities.get(schema, activities.load())
    d.log_form = logform.LogForm(act)
    d.log_records = []
    d._looked_up = ""
    d._rig = None
    d.log_message = ""
    d.picker_message = ""
    d.acts_message = ""

    # No radio. `_radio_now` is a cache in front of three CAT round trips;
    # priming the cache is how the real deck avoids them on a draw path, and
    # it is how this avoids them with no radio attached.
    d._radio_cache = ("14.074000", "FT8", 5)
    d._radio_at = time.monotonic()
    d._log_rig = lambda: None

    d._logfile = os.path.join(tmpdir or tempfile.mkdtemp(), "test.adi")
    d._log_path = lambda: d._logfile
    return d


def logged(d):
    return qsolog.read(d._logfile)


print("the station taken off the transcript is the other one")
d = deck(heard=["KD3CCO DE K2ABC K"])
check("the hotkey reports success", d._log_from_transcript() is not False)
equals("the form holds their call", d.log_form.value("call"), "K2ABC")

print("\nand never this one, however the lines fall")
# Our own outgoing line names us after DE. Reading it would log ourselves.
d = deck(sent=["K2ABC DE KD3CCO K"])
check("a transmitted line alone is not a source",
      d._log_from_transcript() is False)
equals("nothing reached the form", d.log_form.value("call"), "")
check("and it says why",
      "received" in d.session.last_note, d.session.last_note)

d = deck(heard=["KD3CCO DE K2ABC K"], sent=["K2ABC DE KD3CCO K"])
d._log_from_transcript()
equals("with both present it is still theirs",
       d.log_form.value("call"), "K2ABC")

# The side of the transcript is checked on its own, not left to the shape of
# the text. A transmitted line normally reads "THEIRS DE MINE", so refusing
# it falls out of who is named before `DE` -- but an operator who types a
# decode back to ask for a repeat, or a loopback that echoes our own transmit
# into the receive pane, puts a line of the RECEIVED shape on the transmit
# side. Without the `who` filter that reads as having heard them.
d = deck(sent=["KD3CCO DE W1XYZ K"])
check("a line we sent is not a source whatever shape it has",
      d._log_from_transcript() is False)
equals("so nothing is filled in", d.log_form.value("call"), "")

print("\nthe newest received line wins")
d = deck(heard=["KD3CCO DE K2ABC K", "KD3CCO DE W1XYZ K"])
d._log_from_transcript()
equals("the second station, not the first",
       d.log_form.value("call"), "W1XYZ")

print("\n`^G` again steps back to an earlier received line")
# The specification gave this to the arrows. On the conversation screen the
# arrows recall previous overs, which is used far more often, so the key
# already in the operator's hand cycles instead.
d = deck(heard=["KD3CCO DE K2ABC K", "KD3CCO DE W1XYZ K",
                "KD3CCO DE VE3QQQ K"])
d._log_from_transcript()
equals("the first press takes the newest", d.log_form.value("call"), "VE3QQQ")
check("and numbers it from the newest",
      "1 of 3" in d.session.last_note, d.session.last_note)
d._log_from_transcript()
equals("the second press steps back", d.log_form.value("call"), "W1XYZ")
d._log_from_transcript()
equals("and the third", d.log_form.value("call"), "K2ABC")
d._log_from_transcript()
equals("then it wraps to the newest again",
       d.log_form.value("call"), "VE3QQQ")

print("\nbut typing over it starts from the newest")
# No state of its own: the form IS the state. A callsign the operator typed
# is not a position in the candidate list, so the next press offers the
# newest rather than resuming a walk they have abandoned.
d = deck(heard=["KD3CCO DE K2ABC K", "KD3CCO DE W1XYZ K"])
d._log_from_transcript()
d._log_from_transcript()
equals("stepped back to the older one", d.log_form.value("call"), "K2ABC")
d.log_form.set("call", "N3QE", touch=True)
d._log_from_transcript()
equals("and after typing, back to the newest",
       d.log_form.value("call"), "W1XYZ")

print("\nwith one candidate there is nowhere to step")
d = deck(heard=["KD3CCO DE K2ABC K"])
d._log_from_transcript()
d._log_from_transcript()
equals("it stays on the only station", d.log_form.value("call"), "K2ABC")
check("and does not claim a position in a list of one",
      "of 1" not in d.session.last_note, d.session.last_note)

print("\n'log it' does not step back — it logs the newest, every time")
# Stepping would make a repeated press log a DIFFERENT station each time,
# which is the opposite of what a key that writes the file should do.
d = deck(mode=decall.LOG_NOW, heard=["KD3CCO DE K2ABC K",
                                     "KD3CCO DE W1XYZ K"])
d._log_from_transcript()
d._log_from_transcript()
equals("both entries are the newest station",
       [r.get("call") for r in logged(d)], ["W1XYZ", "W1XYZ"])

# The case that makes the guard load-bearing rather than belt-and-braces.
# A successful commit clears the form, so nothing matches on the next press
# and the newest is offered anyway. A commit that FAILS leaves the callsign
# sitting there -- and without the guard the retry would quietly log a
# different station than the one that just failed to write.
d = deck(mode=decall.LOG_NOW, heard=["KD3CCO DE K2ABC K",
                                     "KD3CCO DE W1XYZ K"])
# Under a regular FILE, so `os.makedirs` raises NotADirectoryError. A
# merely absent directory is not a failure: `_log_commit` creates the
# parent, because an activity's log lives in a directory of its own that
# may not exist yet.
blocker = os.path.join(os.path.dirname(d._logfile), "blocker")
with open(blocker, "w", encoding="utf-8") as fh:
    fh.write("not a directory\n")
d._logfile = os.path.join(blocker, "qso.adi")
d._log_path = lambda: d._logfile
check("the write fails", d._log_from_transcript() is False)
equals("and the callsign is still on the form",
       d.log_form.value("call"), "W1XYZ")
d._log_from_transcript()
equals("so the retry is the same station, not the one before it",
       d.log_form.value("call"), "W1XYZ")

print("\nthe callsign goes in as a prefill, not as typing")
d = deck(heard=["KD3CCO DE K2ABC K"])
d._log_from_transcript()
f = d.log_form.field("call")
equals("the prefill is recorded", f.prefill, "K2ABC")
check("the field is not marked touched", not f.touched)
check("so it is not in what the operator typed",
      "call" not in d.log_form.typed(), d.log_form.typed())

print("\nthe radio fields come along, so the entry is ready to commit")
d = deck(heard=["KD3CCO DE K2ABC K"])
d._log_from_transcript()
equals("the frequency", d.log_form.value("freq"), "14.074000")
equals("the mode", d.log_form.value("mode"), "FT8")
check("and the form is ready to log", d.log_form.ready())

print("\nprefill-and-switch is the only behaviour that moves the screen")
d = deck(mode=decall.PREFILL_SWITCH, heard=["KD3CCO DE K2ABC K"])
d._log_from_transcript()
equals("prefill goes to the log screen", d.screen, cyberdeck.LOG)
check("with the cursor on the callsign, to correct a bad decode",
      d.log_form.current.name == "call", d.log_form.current)

d = deck(mode=decall.PREFILL_STAY, heard=["KD3CCO DE K2ABC K"])
d._log_from_transcript()
equals("prefill_stay stays on the conversation", d.screen, cyberdeck.CHAT)
equals("and still fills the form", d.log_form.value("call"), "K2ABC")

print("\n'log it' writes the file and stays put")
d = deck(mode=decall.LOG_NOW, heard=["KD3CCO DE K2ABC K"])
check("it reports success", d._log_from_transcript())
equals("it does not leave the conversation", d.screen, cyberdeck.CHAT)
recs = logged(d)
equals("one contact is on disk", len(recs), 1)
equals("and it is theirs", recs[0].get("call"), "K2ABC")
equals("with our callsign as the station", recs[0].get("my_call"),
       MYCALL)
check("the band came from the frequency",
      recs[0].get("band") == "20m", recs[0].get("band"))

print("\nand it clears the form, ready for the next station")
equals("the callsign is gone", d.log_form.value("call"), "")
check("the transcript says what happened",
      "K2ABC" in d.session.last_note, d.session.last_note)

print("\ntwo presses on the same line log it twice, not zero times")
# The dupe question belongs to the log screen, which has a dupe check. What
# must not happen here is the second press silently doing nothing.
d = deck(mode=decall.LOG_NOW, heard=["KD3CCO DE K2ABC K"])
d._log_from_transcript()
d._log_from_transcript()
equals("both reached the file", len(logged(d)), 2)

print("\nnothing to log is said, not guessed at")
d = deck(heard=["CQ CQ DE K2ABC K2ABC K"])
check("a CQ names nobody we are talking to",
      d._log_from_transcript() is False)
d = deck(heard=[])
check("an empty transcript", d._log_from_transcript() is False)
check("and it says so", "no received line" in d.session.last_note,
      d.session.last_note)

print("\nlogging switched off refuses, and says where the switch is")
d = deck(log_on=False, heard=["KD3CCO DE K2ABC K"])
check("the hotkey refuses", d._log_from_transcript() is False)
check("nothing was written", not os.path.exists(d._logfile))
check("and it names the menu", "F1" in d.session.last_note,
      d.session.last_note)

print("\nan unknown mode falls back rather than doing nothing")
d = deck(mode="whatever-the-conf-file-said", heard=["KD3CCO DE K2ABC K"])
d._log_from_transcript()
equals("it prefills", d.log_form.value("call"), "K2ABC")
equals("and switches, which is the default", d.screen, cyberdeck.LOG)

print("\nevery mode is reachable from the digimode menu")
import menus
for mode in decall.MODES:
    item = menus.digi_menu(mode)["items"][-1]
    equals(f"{mode} is on key 5", item[0], "5")
    check(f"{mode} is spelled out, not named",
          decall.MODE_LABELS[mode] in item[1], item[1])
check("and ^G is named there, since no footer has room for it",
      "^G" in menus.digi_menu(decall.LOG_NOW)["items"][-1][1])

print("\nF5 on the log screen opens the map of the contacts")
# Checked here rather than in test_mapscreen because this file is the one
# with a working entry form attached: the point of a function key is that it
# does NOT reach the form, and that only means something with a form there.
import curses
d = deck(heard=["KD3CCO DE K2ABC K"])
d.log_sel = None
d.log_scroll = 0
d._handle_log(curses.KEY_F5)
equals("it reaches the map", d.screen, cyberdeck.LOGMAP)

d = deck(heard=["KD3CCO DE K2ABC K"])
d.log_sel = None
d.log_scroll = 0
d._handle_log(ord("g"))
equals("while the letter still types into the form",
       d.log_form.value("call"), "G")
check("which is why the map is on a function key",
      d.screen == cyberdeck.CHAT, d.screen)

print("\nthe setting outlives a restart")
check("LOG_HOTKEY is in the config schema", "LOG_HOTKEY" in
      __import__("config").SCHEMA)
check("and in what the state file remembers",
      "LOG_HOTKEY" in cyberdeck._REMEMBERED, cyberdeck._REMEMBERED)

sys.exit(report())
