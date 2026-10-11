"""Ctrl-N and the log screen, driven through a pty against the real program.

Everything else about the logger is tested as pure functions. This file exists
for the part that cannot be: whether the key actually arrives, whether the
screen actually draws, and whether a contact actually reaches the disk.

**It runs under TERM=linux as well as xterm, and that is the point.** The deck
is a framebuffer console, and the console's terminfo captures control bytes
that xterm passes through — `kspd=^Z` turns Ctrl-Z into KEY_SUSPEND. The
memory-insert undo shipped dead on the panel for exactly that reason, correct
in every xterm test. Ctrl-N is byte 14 and `kspd` is the only such capability
in the linux entry, so it should be unaffected — but "should be" is what the
last one was.
"""
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
from test_screen import run, show

STATION = ("CALLSIGN = KD3CCO\nLOCATOR = FN10cs\nRIG = FTX-1\n"
           "ANTENNA = EFHW\n")


def deck(keys, conf_extra, settle=2.2, term="linux", label=""):
    """Run the application with a configuration of our own. Returns (body, log).

    The log path is a temporary file, so a test can never append to the
    operator's real contact log.
    """
    with tempfile.TemporaryDirectory() as tmp:
        log_path = os.path.join(tmp, "qso.log")
        conf_path = os.path.join(tmp, "cyberdeck.conf")
        with open(conf_path, "w") as fh:
            fh.write(STATION + conf_extra + f"LOG_PATH = {log_path}\n")
        body = show(label or "deck", run(keys=keys, settle=settle, term=term,
                                         conf=conf_path))
        written = []
        if os.path.exists(log_path):
            with open(log_path) as fh:
                written = [l.strip() for l in fh if l.strip()]
        return body, written


print("logging off: Ctrl-N is not a key")
# "Absent when off" has to mean absent. Not a screen that says no, not a
# disabled menu item -- the key falls through to the unhandled branch exactly
# as any unused key does, and no file is created.
for term in ("xterm", "linux"):
    body, written = deck(["\x0e"], "LOGGING = no\n", term=term,
                         label=f"Ctrl-N with logging off ({term})")
    check(f"{term}: it reports an unhandled key",
          "unhandled key 14" in body, body[-200:])
    check(f"{term}: the conversation screen is still up",
          "F1 menu" in body, body[-200:])
    equals(f"{term}: and no log file was created", written, [])

print("\nlogging on: Ctrl-N opens the log screen")
for term in ("xterm", "linux"):
    body, _ = deck(["\x0e"], "LOGGING = yes\nACTIVITY = CONTEST\n"
                   "EXCHANGE_TX = CENT\n", term=term,
                   label=f"Ctrl-N with logging on ({term})")
    check(f"{term}: the log screen is drawn", "LOG" in body, body[:120])
    check(f"{term}: the activity is named", "CONTEST" in body, body[:120])
    check(f"{term}: the form is there", "Call" in body, body[-300:])
    check(f"{term}: the footer says how to move",
          "Tab field" in body and "Esc back" in body, body[-120:])
    check(f"{term}: this station's exchange came from the configuration",
          "CENT" in body, body[-300:])
    check(f"{term}: and is marked sticky", "*" in body, body[-300:])

print("\na contact typed on the panel reaches the disk")
keys = (["\x0e"] + list("W3ABC") + ["\t"] + list("101") + ["\t"]
        + list("MONT") + ["\r"])
body, written = deck(keys, "LOGGING = yes\nACTIVITY = CONTEST\n"
                     "EXCHANGE_TX = CENT\n", label="log a contact")
equals("exactly one line was written", len(written), 1)
line = written[0] if written else ""
for want in ("call=W3ABC", "serial_rx=101", "exchange_rx=MONT",
             "exchange_tx=CENT", "activity=CONTEST", "my_call=KD3CCO"):
    check(f"the record carries {want}", want in line, line)
# Rig and antenna come from the Station menu rather than being typed, so a
# contact logged without touching them still says what made it.
check("and this station's equipment", "my_rig=FTX-1" in line
      and "my_antenna=EFHW" in line, line)
# The serial is this station's, counted from the log rather than from a
# counter held in memory.
check("the sent serial started at one", "serial_tx=1" in line, line)

check("the contact appears in the list above the form",
      "W3ABC" in body and "MONT" in body, body[:400])
check("and the form says so", "logged W3ABC" in body, body[-200:])
check("the next serial advanced", "My nr 2" in body, body[-300:])
check("while the sticky exchange stayed", "CENT" in body, body[-300:])

print("\nthe reports default from the MODE, not from nothing")
# Found on the deck: an SSB contest contact logged rst 599, because the commit
# passed an empty mode to parse_entry and a contest form has no report fields
# to correct it afterwards. 599 is the digital default.
body, written = deck(keys, "LOGGING = yes\nACTIVITY = CONTEST\n"
                     "EXCHANGE_TX = CENT\nOPERATING = voice\n",
                     label="voice contest contact")
line = written[0] if written else ""
check("a voice contact gets 59", "rst_s=59 " in line + " ", line)
check("and not the digital 599", "rst_s=599" not in line, line)

print("\nEnter with nothing typed logs nothing")
body, written = deck(["\x0e", "\r"], "LOGGING = yes\n",
                     label="Enter on an empty form")
equals("no file, no contact", written, [])
check("and it says what is missing", "callsign" in body, body[-200:])

print("\nF1 from the log screen configures the logger")
# The function keys were dead on this screen, which is what made them the
# right place for it. F1 means "menu" everywhere else on the deck, so here it
# opens the LOGGING menu rather than the root one -- that is what is being
# configured from this screen.
#
# F1 is NOT the same bytes under both terminals: xterm sends \EOP and the
# linux console sends \E[[A. Reading it from terminfo is the only way a test
# can be honest about whether the panel gets the key -- the same class of
# fault as kspd=^Z eating Ctrl-Z.
F1 = {"xterm": "\x1bOP", "linux": "\x1b[[A"}

for term in ("xterm", "linux"):
    body, _ = deck(["\x0e", F1[term]],
                   "LOGGING = yes\nACTIVITY = CONTEST\nEXCHANGE_TX = CENT\n",
                   term=term, label=f"Ctrl-N then F1 ({term})")
    check(f"{term}: the LOGGING menu opens", "LOGGING" in body, body[:120])
    check(f"{term}: it offers the activity", "Activity" in body, body[:400])
    check(f"{term}: showing which one is selected", "CONTEST" in body,
          body[:400])
    check(f"{term}: and the way back to the log", "^N the log screen" in body,
          body[-120:])

for term in ("xterm", "linux"):
    body, _ = deck(["\x0e", F1[term], "v"],
                   "LOGGING = yes\nACTIVITY = CONTEST\n", term=term,
                   label=f"into the activity picker ({term})")
    check(f"{term}: the picker opens", "ACTIVITY" in body, body[:120])
    check(f"{term}: general logging is offered first",
          "General logging" in body, body[:300])
    check(f"{term}: and the one in use is marked", "*" in body, body[:300])

print("\nchoosing an activity changes the form")
# A contest form has a serial and an exchange; a general one has reports, a
# name and a QTH. Switching has to rebuild it, or the fields on screen belong
# to the activity that was just left.
# Esc from the logging menu goes UP to the root menu rather than out, so
# leaving takes two of them before Ctrl-N can reach the log screen again.
body, _ = deck(["\x0e", F1["linux"], "v", "g", "\x1b", "\x1b", "\x0e"],
               "LOGGING = yes\nACTIVITY = CONTEST\n",
               label="switch to general logging")
check("the form now has reports", "Sent" in body and "Rcvd" in body,
      body[-400:])
check("and no contest serial", "My nr" not in body, body[-400:])
check("the header stops naming an activity", "CONTEST" not in body,
      body[:120])

print("\nbuilding an activity on the panel")
# Copy an existing one, change which fields it has, put them in order, name
# it, save it. The file written is the same INI an operator edits over SSH,
# so a definition made on the panel can be read and corrected by hand.
DOWN = "\x1b[B"

def build(keys, label):
    """Run with an activities.conf of our own, and return (body, its text)."""
    import tempfile as _tf
    with _tf.TemporaryDirectory() as tmp:
        acts = os.path.join(tmp, "activities.conf")
        log_path = os.path.join(tmp, "qso.log")
        conf_path = os.path.join(tmp, "cyberdeck.conf")
        with open(conf_path, "w") as fh:
            fh.write(STATION + "LOGGING = yes\nACTIVITY = CONTEST\n"
                     + f"LOG_PATH = {log_path}\n")
        os.environ["CYBERDECK_ACTIVITIES"] = acts
        try:
            body = show(label, run(keys=keys, settle=3.2, term="linux",
                                   conf=conf_path))
        finally:
            os.environ.pop("CYBERDECK_ACTIVITIES", None)
        written = open(acts).read() if os.path.exists(acts) else ""
        return body, written

body, _ = build(["\x0e", F1["linux"], "n"], "copy the activity in use")
check("the selection screen opens", "SELECT FIELDS" in body, body[:120])
check("naming what it was copied from", "CONTEST" in body, body[:120])
check("the copied fields are on", "\u2588" in body, body[:400])
check("and the others are off", "\u00b7" in body, body[:400])
check("it says how to toggle", "Space toggle" in body, body[-120:])

body, _ = build(["\x0e", F1["linux"], "n", "6", "\r"], "choose fields, then order")
check("Enter moves on to the ordering screen", "ORDER FIELDS" in body,
      body[:120])
check("the chosen fields are numbered", "1." in body and "2." in body,
      body[:300])
check("and it says a number moves a row", "renumber" in body, body[-120:])

# Toggle Name on, go to it, type 1 to make it first, name it, save it.
keys = (["\x0e", F1["linux"], "n", "6", "\r", DOWN, DOWN, "1", "\r"]
        + list("PAQP") + ["\r"])
body, written = build(keys, "name it and save")
check("the file was written", "[PAQP]" in written, written or "(empty)")
check("with the field that was added", "name" in written, written)
check("in the order it was put into", "entry = name," in written, written)
check("carrying what the copy inherited", "serial = yes" in written, written)
check("and the renamed label", "label_exchange_rx" in written, written)

check("the deck switched to it", "LOG  PAQP" in body, body[:120])
check("and the form rebuilt in the new order",
      body.index("Name") < body.index("Nr"), body[-400:])

# load() and save() have to agree on the path. When they did not, an activity
# built on the panel was written to one file and looked for in another: it
# saved without error and then was not there.
import activities as _acts
os.environ["CYBERDECK_ACTIVITIES"] = "/tmp/somewhere/activities.conf"
try:
    equals("load and save resolve the same path",
           _acts.config_path(), "/tmp/somewhere/activities.conf")
finally:
    os.environ.pop("CYBERDECK_ACTIVITIES", None)

print("\nEsc returns to the conversation")
body, _ = deck(["\x0e", "\x1b"], "LOGGING = yes\n", label="Ctrl-N then Esc")
check("back on the conversation screen", "F1 menu" in body, body[-200:])
check("and the log screen is gone", "Tab field" not in body, body[-200:])

sys.exit(report())
