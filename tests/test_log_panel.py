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

# One stop along the ring from the boot screen: settings | log | digimodes.
# The deck opens on the settings, so `^P` is the log. There is no key that
# jumps straight to it -- the ring is how every application is reached.
RING_FWD = "\x10"
import activities
import menus
import render

STATION = ("CALLSIGN = KD3CCO\nLOCATOR = FN10cs\nRIG = FTX-1\n"
           "ANTENNA = EFHW\n")


def deck(keys, conf_extra, settle=2.2, term="linux", label="",
         log_name="qso.log", log_body="", activity_log=""):
    """Run the application with a configuration of our own. Returns (body, log).

    The log path is a temporary file, so a test can never append to the
    operator's real contact log. `log_name` names that file, because "qso.log"
    is the default the header deliberately does not print; `log_body` seeds it
    with contacts already made.

    LOG_PATH is written last, after `conf_extra`, so a test cannot set it by
    hand and silently have it overridden -- which is what happened when this
    was first written.
    """
    with tempfile.TemporaryDirectory() as tmp:
        log_path = os.path.join(tmp, log_name)
        # One log. `activity_log` used to seed an ACTIVITY's own file; an
        # activity is a label on records now, so the same seeding writes the
        # same contacts into the one log with `activity=` on each -- which is
        # what makes the session exist at all.
        if log_body and activity_log:
            import datetime as _dt
            stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
            began = f"{stamp}T00:00:00Z"
            with open(log_path, "w") as fh:
                for line in log_body.splitlines():
                    if not line.strip():
                        continue
                    fh.write(f"activity_start={began} {line.strip()} "
                             f"activity={activity_log}\n")
        elif log_body:
            with open(log_path, "w") as fh:
                fh.write(log_body)
        conf_path = os.path.join(tmp, "cyberdeck.conf")
        with open(conf_path, "w") as fh:
            fh.write(STATION + conf_extra + f"LOG_PATH = {log_path}\n")
        body = show(label or "deck", run(keys=keys, settle=settle, term=term,
                                         conf=conf_path))
        # One log, so one place to read. The harness used to collect from the
        # default log AND every activity file beside it, because a named
        # activity's contacts lived in their own.
        written = []
        if os.path.exists(log_path):
            with open(log_path) as fh:
                written = [l.strip() for l in fh if l.strip()]
        return body, written


print("logging off: Ctrl-N is not a key")
# "Absent when off" has to mean absent. Not a screen that says no, not a
# disabled menu item -- the log is not a stop on the ring at all, so `^O` and
# `^P` walk two applications instead of three, and no file is created.
#
# There is no longer a key that jumps to the log, so "the key is absent" is
# not what this can test. What it tests is that the ring skips it: one `^P`
# from the boot screen reaches the CONVERSATION rather than the log.
for term in ("xterm", "linux"):
    body, written = deck([RING_FWD], "LOGGING = no\n", term=term,
                         label=f"^P with logging off ({term})")
    check(f"{term}: the ring skips the log and reaches the conversation",
          "^T over" in body, body[-200:])
    check(f"{term}: so the log screen is not drawn",
          "\u2190\u2192 field" not in body, body[-200:])
    equals(f"{term}: and no log file was created", written, [])

print("\nlogging on: the ring reaches the log screen")
for term in ("xterm", "linux"):
    body, _ = deck([RING_FWD], "LOGGING = yes\nACTIVITY_TYPE = CONTEST\n"
                   "EXCHANGE_TX = CENT\n", term=term,
                   label=f"Ctrl-N with logging on ({term})")
    check(f"{term}: the log screen is drawn", "LOG" in body, body[:120])
    check(f"{term}: the activity is named", "CONTEST" in body, body[:120])
    check(f"{term}: the form is there", "Call" in body, body[-300:])
    check(f"{term}: the footer says how to move between fields",
          "\u2190\u2192 field" in body, body[-120:])
    check(f"{term}: and how to reach the contacts above",
          "\u2191\u2193 pick" in body, body[-120:])
    check(f"{term}: and how to reach the other areas",
          "^O ^P screen" in body, body[-120:])
    # Not guessable, so it has to be on the footer. Esc is, and came off it to
    # make room -- all seven keys do not fit in 66 columns.
    check(f"{term}: and how to clear the entry", "^X clear" in body,
          body[-120:])
    check(f"{term}: this station's exchange came from the configuration",
          "CENT" in body, body[-300:])
    check(f"{term}: and is marked sticky", "*" in body, body[-300:])

print("\na contact typed on the panel reaches the disk")
keys = ([RING_FWD] + list("W3ABC") + ["\t"] + list("101") + ["\t"]
        + list("MONT") + ["\r"])
body, written = deck(keys, "LOGGING = yes\nACTIVITY_TYPE = CONTEST\n"
                     "EXCHANGE_TX = CENT\n", label="log a contact")
equals("exactly one line was written", len(written), 1)
line = written[0] if written else ""
for want in ("call=W3ABC", "serial_rx=101", "exchange_rx=MONT",
             "exchange_tx=CENT", "activity_type=CONTEST", "my_call=KD3CCO"):
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
body, written = deck(keys, "LOGGING = yes\nACTIVITY_TYPE = CONTEST\n"
                     "EXCHANGE_TX = CENT\nOPERATING = voice\n",
                     label="voice contest contact")
line = written[0] if written else ""
check("a voice contact gets 59", "rst_s=59 " in line + " ", line)
check("and not the digital 599", "rst_s=599" not in line, line)

print("\nEnter with nothing typed logs nothing")
body, written = deck([RING_FWD, "\r"], "LOGGING = yes\n",
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
    body, _ = deck([RING_FWD, F1[term]],
                   "LOGGING = yes\nACTIVITY_TYPE = CONTEST\nEXCHANGE_TX = CENT\n",
                   term=term, label=f"Ctrl-N then F1 ({term})")
    check(f"{term}: the LOGGING menu opens", "LOGGING" in body, body[:120])
    check(f"{term}: it offers the activity", "Activity" in body, body[:400])
    check(f"{term}: showing which one is selected", "CONTEST" in body,
          body[:400])
    check(f"{term}: and the way out", "^O ^P areas" in body, body[-120:])

for term in ("xterm", "linux"):
    body, _ = deck([RING_FWD, F1[term], "v"],
                   "LOGGING = yes\nACTIVITY_TYPE = CONTEST\n", term=term,
                   label=f"into the activity picker ({term})")
    check(f"{term}: the picker opens", "LOG SCHEMA" in body, body[:120])
    check(f"{term}: general logging is offered first",
          "General logging" in body, body[:300])
    check(f"{term}: and the one in use is marked", "*" in body, body[:300])

print("\nchoosing an activity changes the form")
# A contest form has a serial and an exchange; a general one has reports, a
# name and a QTH. Switching has to rebuild it, or the fields on screen belong
# to the activity that was just left.
# No Esc and no second ^P: the schema picker has ONE exit and it closes to
# the log screen however it was reached, so choosing general logging lands
# back on the form. The old sequence added two Escs and another ring step and
# so read the DIGIMODE screen while asserting about the entry form.
body, _ = deck([RING_FWD, F1["linux"], "v", "g"],
               "LOGGING = yes\nACTIVITY_TYPE = CONTEST\n",
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
#
# The copy starts from the type picker -- `v` to open it, then `c` and the
# number of the type to copy. It used to start from a line on the logging
# menu; that line is gone, because choosing what to copy without seeing the
# list of what exists is the wrong order to decide in.
DOWN = "\x1b[B"
RIGHT = "\x1b[C"
COPY_CONTEST = ["v", "c", "1"]


# Derived, never counted by hand. Both the page a field is on and the key
# printed beside it move when ENTRY_FIELDS is reordered, and a hard-coded "6"
# is how a test ends up toggling whatever slid into that row -- it was "6" for
# `name` until page one became QRZ's entry panel, and then it was `grid`.
# `type_key` above exists for exactly the same reason.
def field_keys(name):
    """The keystrokes that toggle `name`, starting from page one."""
    names = [f for f, _l, _k in activities.field_choices()]
    page, row = divmod(names.index(name), render.FIELDS_PER_PAGE)
    return [RIGHT] * page + [activities.pick_key(row)]

def build(keys, label):
    """Run with an activities.conf of our own, and return (body, its text)."""
    import tempfile as _tf
    with _tf.TemporaryDirectory() as tmp:
        acts = os.path.join(tmp, "activities.conf")
        log_path = os.path.join(tmp, "qso.log")
        conf_path = os.path.join(tmp, "cyberdeck.conf")
        with open(conf_path, "w") as fh:
            fh.write(STATION + "LOGGING = yes\nACTIVITY_TYPE = CONTEST\n"
                     + f"LOG_PATH = {log_path}\n")
        os.environ["CYBERDECK_ACTIVITIES"] = acts
        try:
            body = show(label, run(keys=keys, settle=3.2, term="linux",
                                   conf=conf_path))
        finally:
            os.environ.pop("CYBERDECK_ACTIVITIES", None)
        written = open(acts).read() if os.path.exists(acts) else ""
        return body, written

body, _ = build([RING_FWD, F1["linux"]] + COPY_CONTEST,
                "copy the activity in use")
check("the selection screen opens", "SELECT FIELDS" in body, body[:120])
check("naming what it was copied from", "CONTEST" in body, body[:120])
check("the fields not copied are off", "\u00b7" in body, body[:400])
check("it says how to toggle", "Space toggle" in body, body[-120:])
check("and that the list pages", "page" in body, body[-120:])

# CONTEST is a serial and an exchange, and anything strictly contest-related
# is on page two: page one is general and POTA logging. So the copy shows its
# fields on from the page they are on, not from the first one.
body, _ = build([RING_FWD, F1["linux"]] + COPY_CONTEST + [RIGHT],
                "the copied fields are on, on their own page")
check("the copied fields are on", "\u2588" in body, body[:400])
check("and the heading says which page", "2/2" in body, body[:80])

body, _ = build([RING_FWD, F1["linux"]] + COPY_CONTEST
                + field_keys("name") + ["\r"],
                "choose fields, then order")
check("Enter moves on to the ordering screen", "ORDER FIELDS" in body,
      body[:120])
check("the chosen fields are numbered", "1." in body and "2." in body,
      body[:300])
check("and it says a number moves a row", "renumber" in body, body[-120:])

# Toggle Name on, go to it, type 1 to make it first, name it, save it.
keys = ([RING_FWD, F1["linux"]] + COPY_CONTEST + field_keys("name")
        + ["\r", DOWN, DOWN, "1", "\r"] + list("PAQP") + ["\r"])
body, written = build(keys, "name it and save")
check("the file was written", "[PAQP]" in written, written or "(empty)")
check("with the field that was added", "name" in written, written)
check("in the order it was put into", "entry = name," in written, written)
check("carrying what the copy inherited", "serial = yes" in written, written)
check("and the renamed label", "label_exchange_rx" in written, written)

check("the deck switched to it", "PAQP" in body.splitlines()[0], body[:120])
check("and the header still says what the log is for",
      "master log" in body.splitlines()[0], body[:120])
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

print("\nthe log screen says F1 opens its menu")
# The function keys were dead on this screen, so F1 was given the logging
# menu -- and then the one screen on the deck with a menu of its own was the
# one screen whose footer did not mention F1.
body, _ = deck([RING_FWD], "LOGGING = yes\n", label="the footer names F1")
check("F1 is named in the footer", "F1 menu" in body, body[-140:])
check("and so is the clear key", "^X clear" in body, body[-140:])

print("\nCtrl-X clears the staged contact on the panel")
# Byte 24. The linux console's terminfo captures control bytes as keys in
# exactly one place -- kspd=^Z -- so ^X arrives as 24 under both terminals;
# it is already the transcript's clear key on this panel. Checked under both
# anyway, because that is the assumption that was wrong last time.
for term in ("xterm", "linux"):
    keys = ([RING_FWD] + list("W3ABC") + ["\t"] + list("101") + ["\x18"])
    body, written = deck(keys, "LOGGING = yes\nACTIVITY_TYPE = CONTEST\n"
                         "EXCHANGE_TX = CENT\n", term=term,
                         label=f"type then Ctrl-X ({term})")
    check(f"{term}: it says the entry was cleared",
          "entry cleared" in body, body[-200:])
    check(f"{term}: the callsign is gone from the form",
          "W3ABC" not in body, body[-400:])
    equals(f"{term}: and nothing was logged", written, [])
    # Sticky fields describe the session, not the station, and survive it.
    check(f"{term}: this station's exchange stayed", "CENT" in body,
          body[-400:])

# Pressed on a form holding nothing, it says so rather than looking dead.
body, _ = deck([RING_FWD, "\x18"], "LOGGING = yes\n",
               label="Ctrl-X on an empty form")
check("nothing staged is reported, not ignored",
      "nothing staged" in body, body[-200:])

print("\nthe log file is named, and switching it switches the log")
SEEDED = ("when=2026-10-11T14:00:00Z call=W1AW band=40m mode=SSB "
          "rst_s=59 rst_r=59 my_call=KD3CCO\n"
          "when=2026-10-11T14:01:00Z call=K2XYZ band=40m mode=SSB "
          "rst_s=59 rst_r=57 my_call=KD3CCO\n")

body, _ = deck([RING_FWD], "LOGGING = yes\n", log_name="paqp.log",
               log_body=SEEDED, label="a named log is named on the header")
check("the header names the log", "LOG:paqp.log" in body, body[:120])
check("and the contacts in it are listed",
      "W1AW" in body and "K2XYZ" in body, body[:400])
check("with the count", "2 QSO" in body, body[:120])

# The default log is NOT named, so an ordinary deck's header is unchanged.
body, _ = deck([RING_FWD], "LOGGING = yes\n", label="the default log is unnamed")
check("the default log name is left off the header",
      "LOG:" not in body, body[:120])
check("the header is still the log screen", "LOG" in body, body[:120])

print("\nthe logging menu offers the log file, and no uploader")
body, _ = deck([RING_FWD, F1["linux"]], "LOGGING = yes\n", term="linux",
               label="the logging menu")
# "Default log" was the name when there were per-activity files beside a
# default one. There is one log now, so the line is just the file.
check("the log file is offered", "Log file" in body, body[:400])
check("and no QRZ upload", "QRZ" not in body, body[:400])
check("and nothing claims contacts are waiting to be sent",
      "waiting" not in body, body[:400])

print("\nan activity filters the one log; the master log does not")
# One log, and an activity is a LABEL on its records -- §7f. Selecting an
# activity filters the list to that session; selecting the master log shows
# everything, because every contact ever made is in it whatever activity made
# it. The seeded log holds one labeled contact and one belonging to no
# activity, so the two cases are different lists and not the same one twice.
MIXED = ("when=2026-10-11T14:00:00Z call=W1AW band=40m mode=SSB "
         "rst_s=59 rst_r=59 my_call=KD3CCO\n"
         "when=2026-10-11T18:31:00Z call=K3PP band=40m mode=SSB rst_s=59 "
         "rst_r=59 serial_tx=55 serial_rx=101 exchange_rx=MONT "
         "activity=CONTEST my_call=KD3CCO\n")

# No `activity_log=`: the label is already on the one line that should carry
# it. Passing it relabeled EVERY line, so both contacts ended up inside the
# activity and "the one outside it is not listed" was testing a log that had
# no outside.
body, _ = deck([RING_FWD], "LOGGING = yes\nACTIVITY = CONTEST\n",
               log_body=MIXED,
               label="a named activity lists its own contacts")
check("the contact in that activity is listed", "K3PP" in body, body[:400])
check("the one outside it is not", "W1AW" not in body, body[:400])
check("and the count is this activity's", "1 QSO" in body, body[:120])

body, _ = deck([RING_FWD], "LOGGING = yes\n", log_body=MIXED,
               label="the master log lists everything")
# BOTH, which is the point of the master log and the opposite of what this
# checked when every activity had a file of its own.
check("the master log lists the unlabeled contact", "W1AW" in body,
      body[:400])
check("and the one inside an activity too", "K3PP" in body, body[:400])
check("with the whole log's count", "2 QSO" in body, body[:120])

print("\nthe columns say what is being filled in")
# The SCHEMA decides them -- §7g. A contest schema asks for a serial and an
# exchange and for neither report, because in a contest the report is 59
# every time, so there is no RST column and a column of bare `/` down the
# screen is not drawn. RST used to be in this list and unconditional in the
# renderer.
body, _ = deck([RING_FWD], "LOGGING = yes\nACTIVITY_TYPE = CONTEST\n",
               log_body=MIXED, label="contest column headings")
for want in ("UTC", "CALL", "MY#", "NR", "EXCH"):
    check(f"the {want} column is named", want in body, body[:300])
check("and no RST column, which the schema does not ask for",
      "RST" not in body, body[:300])

# The other half of the same rule, so this cannot pass by the renderer having
# dropped RST everywhere: general logging DOES ask for the reports.
body, _ = deck([RING_FWD], "LOGGING = yes\n", log_body=MIXED,
               label="general column headings")
check("general logging names the RST column", "RST" in body, body[:300])
check("and no serial column, which it does not ask for",
      "NR" not in body and "MY#" not in body, body[:300])

# On an EMPTY log the columns still have to appear, or the operator cannot see
# which fields they are about to fill until the first contact is already in.
body, _ = deck([RING_FWD], "LOGGING = yes\nACTIVITY_TYPE = CONTEST\n",
               label="contest columns on an empty log")
check("the serial column is there before the first contact",
      "NR" in body, body[:300])
check("and the exchange column with it", "EXCH" in body, body[:300])

# A general activity has no serial and no exchange, so naming those columns
# would be naming fields that do not exist on its form.
body, _ = deck([RING_FWD], "LOGGING = yes\n", label="general column headings")
check("general logging names a name column", "NAME" in body, body[:300])
check("and no exchange column", "EXCH" not in body, body[:300])
check("and no serial column", "MY#" not in body, body[:300])

print("\nthe callsign goes in upper case")
body, written = deck([RING_FWD] + list("w3abc") + ["\r"], "LOGGING = yes\n",
                     label="lower-case callsign typed")
check("the form shows it upper", "W3ABC" in body, body[-400:])
check("and never lower", "w3abc" not in body, body[-400:])
line = written[0] if written else ""
check("and the log records it upper", "call=W3ABC" in line, line)

print("\nan activity has a name, a type and a log file of its own")
body, _ = deck([RING_FWD], "LOGGING = yes\nACTIVITY = Bald Eagle SP\n"
               "ACTIVITY_TYPE = POTA\n", label="a named activity")
check("the header names the activity", "Bald Eagle SP" in body, body[:120])
check("and the type it uses", "POTA" in body, body[:120])
check("the reference column is reserved", "REF" in body, body[:300])

# ACTIVITY naming a TYPE is how it was spelled before the two were different
# things. It is read as both rather than refused.
body, _ = deck([RING_FWD], "LOGGING = yes\nACTIVITY = POTA\n",
               label="the old spelling still works")
check("an old ACTIVITY = POTA still gives a POTA form",
      "Park" in body or "Ref" in body, body[-400:])

print("\nF2 opens the activities list")
F2 = {"xterm": "\x1bOQ", "linux": "\x1b[[B"}
F3 = {"xterm": "\x1bOR", "linux": "\x1b[[C"}
for term in ("xterm", "linux"):
    body, _ = deck([RING_FWD, F2[term]], "LOGGING = yes\n", term=term,
                   label=f"Ctrl-N then F2 ({term})")
    check(f"{term}: the activities screen opens", "ACTIVITIES" in body,
          body[:120])
    check(f"{term}: it says how to start one", "n new" in body, body[-120:])
    check(f"{term}: and how to forget one", "d forget" in body, body[-120:])

# The list is never empty: the MASTER LOG is always on it, always first and
# not deletable, because it is where every contact ever made is kept whatever
# activity made it. So "nothing logged yet" is not a state this screen can be
# in, and the message that used to say so is unreachable.
body, _ = deck([RING_FWD, F2["linux"]], "LOGGING = yes\n",
               label="no activities yet")
check("the master log is on the list", "master log" in body, body[:200])
check("with its count", "0 QSOs" in body, body[:200])
check("and it is the only row", body.count("QSO") == 1, body[:300])

print("\ndeleting an activity asks first, then does it")
#
# These assert OUTCOMES, not the final screen. The harness ends every run
# with Ctrl-Q, and the confirmation is cancelled by any key except Enter --
# deliberately, since the operator who hit `d` by accident is who it is for.
# So the last screen is always the screen AFTER cancelling, and a test that
# looked for "DELETE ACTIVITY" on it could never pass. What the confirmation
# SAYS is checked against render.confirm_screen in test_log_screen.py.
# One log, and the activity is a label on a record in it -- §7f. There is no
# per-activity file to seed or to count afterwards, so the fixture writes the
# one log and the assertions read the records left in it.
SEED = ("activity_start=2026-10-11T13:00:00Z "
        "when=2026-10-11T14:00:00Z call=W1AW band=40m mode=SSB rst_s=59 "
        "rst_r=59 my_call=KD3CCO activity=Testpark activity_type=POTA\n")


def with_activity(keys, label, settle=3.0):
    """Run with one session already in the log. Returns (body, records left).

    Deleting an activity is now `_forget_session`: the label comes off the
    deck's LIST and every record keeps it, so what this returns is the log,
    and "deleted" means "gone from the list" rather than "gone from disk".
    """
    with tempfile.TemporaryDirectory() as tmp:
        log_path = os.path.join(tmp, "qso.log")
        with open(log_path, "w") as fh:
            fh.write(SEED)
        conf_path = os.path.join(tmp, "cyberdeck.conf")
        with open(conf_path, "w") as fh:
            fh.write(STATION + "LOGGING = yes\n"
                     + f"LOG_PATH = {log_path}\n")
        body = show(label, run(keys=keys, settle=settle, term="linux",
                               conf=conf_path))
        with open(log_path) as fh:
            return body, [l.strip() for l in fh if l.strip()]


# Down one first: row 0 is the master log and `d` on it refuses, so without
# this the delete never opens and the scenario tests nothing.
DOWN_L = "\x1b[B"

body, left = with_activity([RING_FWD, F2["linux"]], "the activity is listed")
check("it appears in the list", "Testpark" in body, body[:300])
check("with its contact count", "1 QSO" in body, body[:300])
check("and is marked as the one in use only when it is",
      "* Testpark" not in body, body[:300])

body, left = with_activity([RING_FWD, F2["linux"], DOWN_L, "d"],
                           "d alone forgets nothing")
check("the question alone changes nothing",
      any("activity=Testpark" in l for l in left), str(left))

body, left = with_activity([RING_FWD, F2["linux"], DOWN_L, "d", "\x1b"],
                           "Esc keeps it")
check("Esc keeps the activity", any("Testpark" in l for l in left), str(left))
check("and the list comes back", "ACTIVITIES" in body, body[:200])

body, left = with_activity([RING_FWD, F2["linux"], DOWN_L, "d", "x"],
                           "another key keeps it")
check("an unrelated key keeps it too — the default is to keep",
      any("Testpark" in l for l in left), str(left))

body, left = with_activity([RING_FWD, F2["linux"], DOWN_L, "d", "\r"],
                           "Enter forgets it")
# The CONTACT survives, with its label intact. That is the whole point of
# the change: deleting an activity takes it off the deck's list and leaves
# the records alone, so the session is still exportable by name and logging
# under it again brings it back.
equals("the contact is still in the log", len(left), 1)
check("and still carries the label",
      "activity=Testpark" in left[0], str(left))
check("and the deck says it came off the list",
      "removed from the list" in body, body)

print("\ndeleting an activity type asks first, then does it")


def with_type(keys, label, settle=3.4):
    """Run with two saved activity types. Returns (body, activities.conf)."""
    with tempfile.TemporaryDirectory() as tmp:
        acts = os.path.join(tmp, "activities.conf")
        with open(acts, "w") as fh:
            fh.write("[PAQP]\nlike = CONTEST\nlabel = Pennsylvania QSO "
                     "Party\n\n[KEEPME]\nlabel = Not this one\n")
        conf_path = os.path.join(tmp, "cyberdeck.conf")
        with open(conf_path, "w") as fh:
            fh.write(STATION + "LOGGING = yes\n"
                     + f"LOG_PATH = {os.path.join(tmp, 'qso.log')}\n")
        os.environ["CYBERDECK_ACTIVITIES"] = acts
        try:
            body = show(label, run(keys=keys, settle=settle, term="linux",
                                   conf=conf_path))
        finally:
            os.environ.pop("CYBERDECK_ACTIVITIES", None)
        return body, open(acts).read()


# The picker numbers EVERY type, the built-ins included, so the number for a
# saved one is not its position among the saved ones. Derived from the menu
# rather than counted by hand: hard-coding "2" picked KEEPME and the delete
# worked perfectly on the wrong type, which is a mistake worth making only
# once.
def type_key(name):
    table = dict(activities.BUILTIN)
    table["PAQP"] = table["CONTEST"]
    table["KEEPME"] = table["GENERAL"]
    menu = menus.activity_type_menu(sorted(table), "")
    for key, label in menu["items"]:
        if label.split()[0] == name:
            return key
    raise AssertionError(f"{name} is not in {menu['items']}")


PAQP_KEY = type_key("PAQP")
equals("the picker numbers built-ins too, so PAQP is not number 2",
       PAQP_KEY, "3")

body, text = with_type([RING_FWD, F1["linux"], "v"], "the types are listed")
check("the saved type is offered", "PAQP" in body, body[:400])
check("and the other one", "KEEPME" in body, body[:400])

body, text = with_type([RING_FWD, F1["linux"], "v", "d", PAQP_KEY],
                       "d then a number asks")
check("the question alone deletes nothing", "[PAQP]" in text, text)

body, text = with_type([RING_FWD, F1["linux"], "v", "d", PAQP_KEY, "\x1b"],
                       "Esc keeps the type")
check("Esc keeps it", "[PAQP]" in text, text)

body, text = with_type([RING_FWD, F1["linux"], "v", "d", PAQP_KEY, "\r"],
                       "Enter deletes the type")
check("the type is gone from the file", "[PAQP]" not in text, text)
check("and the one beside it is untouched",
      "[KEEPME]" in text and "Not this one" in text, text)

# A built-in has no section to remove. Nothing is written and nothing else is
# disturbed -- the file is the property worth asserting, because the note that
# explains it goes to the transcript, which a menu is covering.
body, text = with_type([RING_FWD, F1["linux"], "v", "d", "g", "\r"],
                       "a built-in cannot be deleted")
check("the file is untouched", "[PAQP]" in text and "[KEEPME]" in text, text)

# Selecting a type after pressing `d` and changing your mind must SELECT it,
# not delete it: the pending flag has to clear.
#
# **Esc now goes back ONE level, by the route taken.** The picker used to
# have one exit however it was reached -- straight out to the log screen --
# so this scenario went back in with `F3`. Opened from the logging menu with
# `v`, Esc returns to that menu, and `F3` pressed inside a menu means
# something else entirely. So `v` again is the way back in, which is also
# the point: the pending delete must be cleared whichever route is taken.
body, text = with_type([RING_FWD, F1["linux"], "v", "d", "\x1b",
                        "v", PAQP_KEY],
                       "d then Esc then a number selects")
check("the type still exists", "[PAQP]" in text, text)
check("and was selected", "PAQP" in body, body[:200])

print("\ncreating a type starts from the picker, not from a menu item")

# The logging menu used to carry a "New type, copied from this one" line. It
# asked the operator to decide to create a type before seeing what already
# existed, so it moved onto the picker that lists them.
body, _ = deck([RING_FWD, F1["linux"], "8"], "LOGGING = yes\n",
               term="linux", label="the logging menu")
check("the logging menu no longer offers to create a type",
      "New type" not in body, body)
# "Activity type" was renamed "log schema" in the interface on 2026-10-16.
check("but it still leads to the picker", "Log schema" in body, body)

body, text = with_type([RING_FWD, F1["linux"], "v"], "the picker advertises both")
check("copy is offered", "c+n copy" in body, body[-160:])
check("and so is a new type from nothing", "n new" in body, body[-160:])

body, text = with_type([RING_FWD, F1["linux"], "v", "c", PAQP_KEY],
                       "c then a number copies that type")
check("the field picker opens", "SELECT FIELDS" in body, body[:200])
# The title names the type by its NAME, not its label: the name is what the
# saved definition will say it came from.
check("and says what it was copied from", "from PAQP" in body, body[:200])
check("copying writes nothing until it is saved", "[PAQP]" in text, text)

# `c` and `d` are the same two-keystroke shape, so the pending flags have to
# be exclusive: pressing one and then the other must do the second thing.
body, text = with_type([RING_FWD, F1["linux"], "v", "d", "c", PAQP_KEY],
                       "d then c copies rather than deletes")
check("the type survives", "[PAQP]" in text, text)
check("and the field picker is what opened", "SELECT FIELDS" in body, body[:200])

# Same route back in, for the same reason as above.
body, text = with_type([RING_FWD, F1["linux"], "v", "c", "\x1b",
                        "v", PAQP_KEY],
                       "c then Esc then a number selects")
check("the type still exists", "[PAQP]" in text, text)
check("and was selected rather than copied", "PAQP" in body, body[:200])

body, text = with_type([RING_FWD, F1["linux"], "v", "n"],
                       "n starts a type from nothing")
check("the field picker opens", "SELECT FIELDS" in body, body[:200])
check("with nothing chosen", "0 of " in body, body[:200])
check("and it does not claim to be copied from anything",
      "from" not in body.splitlines()[0], body[:200])

print("\nsaving a type over a name that is taken asks first")

# `activities.save` replaces a section of that name on purpose -- saving twice
# under one name is what revising a definition looks like -- but it did it
# silently, so a name that collided destroyed the earlier type with no sign of
# it.
#
# These assert OUTCOMES, in the file. The harness quits with Ctrl-Q, and the
# confirmation treats every key but Enter as "no", so the last screen is never
# the question. What the question SAYS is checked against render.confirm_screen
# in test_log_screen.py.
# Copy CONTEST, accept its fields and their order, and name it PAQP -- which
# the fixture already has, with a label of its own to recognize it by.
#
# CONTEST and not the fixture's own KEEPME: KEEPME is `[KEEPME]` with a label
# and nothing else, so it has no fields at all and copying it lands on the
# refusal instead of the order screen. The letters of the name were then read
# as row-toggle keys -- the `A` of PAQP turning on whatever row `a` happened
# to be -- and the sequence ended three screens short of the question it was
# written to ask.
CONTEST_KEY = type_key("CONTEST")
RENAME = ["v", "c", CONTEST_KEY, "\r", "\r"] + list("PAQP") + ["\r"]

body, text = with_type([RING_FWD, F1["linux"]] + RENAME,
                       "the question alone replaces nothing")
check("the old PAQP is still there", "Pennsylvania QSO Party" in text, text)

body, text = with_type([RING_FWD, F1["linux"]] + RENAME + ["\x1b"],
                       "any other key keeps the old one")
check("Esc keeps it", "Pennsylvania QSO Party" in text, text)
check("and it was not written alongside itself",
      text.count("[PAQP]") == 1, text)
check("backing out returns to the name prompt, prefilled",
      "Name for this log schema" in body and "PAQP" in body, body[:200])

body, text = with_type([RING_FWD, F1["linux"]] + RENAME + ["\r"],
                       "Enter replaces it")
check("the old definition is gone",
      "Pennsylvania QSO Party" not in text, text)
check("and left one section, not two", text.count("[PAQP]") == 1, text)
check("the type beside it is untouched",
      "[KEEPME]" in text and "Not this one" in text, text)

# A built-in has no section in the file, so nothing of the operator's is lost
# -- but the name stops meaning what it means everywhere else on the deck.
BUILTIN_NAME = ["v", "c", CONTEST_KEY, "\r", "\r"] + list("POTA") + ["\r"]

body, text = with_type([RING_FWD, F1["linux"]] + BUILTIN_NAME + ["\x1b"],
                       "shadowing a built-in asks too")
check("nothing is written until it is answered", "[POTA]" not in text, text)

body, text = with_type([RING_FWD, F1["linux"]] + BUILTIN_NAME + ["\r"],
                       "Enter writes over the built-in")
check("the operator's POTA is now in the file", "[POTA]" in text, text)

# GENERAL is refused outright rather than confirmed: it is the fallback every
# other type is resolved against, so there is no version of replacing it that
# leaves the deck able to log.
GENERAL_NAME = ["v", "c", CONTEST_KEY, "\r", "\r"] + list("GENERAL") + ["\r"]
body, text = with_type([RING_FWD, F1["linux"]] + GENERAL_NAME,
                       "GENERAL cannot be taken")
check("nothing is written", "[GENERAL]" not in text, text)
check("and the refusal is on the screen, not only in the transcript",
      "GENERAL is the built-in" in body, body[:400])

print("\nnaming a new activity asks which type it uses")

body, left = with_activity([RING_FWD, F2["linux"], "n", "F", "D", "\r"],
                           "name an activity, then the type picker")
check("the schema picker comes up next", "LOG SCHEMA" in body, body[:200])
check("with the create paths on it", "n new" in body, body[-160:])

# Esc out of the picker must not land back on the activities list: that list
# is the screen the operator has already finished with.
body, left = with_activity([RING_FWD, F2["linux"], "n", "F", "D", "\r",
                            "\x1b", "\x1b"],
                           "Esc out of the picker")
check("it backs out onto the log screen, not the activities list",
      "ACTIVITIES" not in body, body[:200])

print("\nreading back and correcting a contact already logged")
# The arrows pick a logged contact; Tab and Shift-Tab move between fields,
# which is what they already did. The arrows used to be a redundant second way
# to do the same thing, so reading back and correcting what was already logged
# had no keys at all and could only be done over SSH.
ARROW_UP, ARROW_DOWN = "\x1b[A", "\x1b[B"
LOGGED = ("W1AW", "KD3CPP", "W3TM")


def with_logged(keys, label, settle=3.2, lines=""):
    """Run with three contacts on disk. Returns (body, the log file's text)."""
    import datetime as _dt
    with tempfile.TemporaryDirectory() as tmp:
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
        log = os.path.join(tmp, "qso.log")
        with open(log, "w") as fh:
            for i, call in enumerate(LOGGED):
                fh.write(f"when={stamp}T14:0{i}:00Z call={call} band=40m "
                         f"mode=SSB rst_s=59 rst_r=59 name=N{i} state=PA "
                         f"tx_power=6 my_rig=FTX-1 my_call=KD3CCO\n")
        conf_path = os.path.join(tmp, "cyberdeck.conf")
        with open(conf_path, "w") as fh:
            fh.write(STATION + "LOGGING = yes\n"
                     + f"LOG_PATH = {log}\n"
                     + (f"LOG_LINES = {lines}\n" if lines else ""))
        body = show(label, run(keys=keys, settle=settle, term="linux",
                               conf=conf_path))
        return body, open(log).read()


body, _ = with_logged([RING_FWD], "nothing picked yet")
check("the form has the keyboard", "Enter log" in body, body[-200:])
check("and it says the arrows pick", "\u2191\u2193 pick" in body, body[-200:])

body, _ = with_logged([RING_FWD, ARROW_UP], "Up picks a contact")
# The footer is the assertion, not the highlight: the picked row is drawn in
# reverse video, which is an attribute and not text, so a screen scrape cannot
# see it. What the footer says is what tells the operator Enter changed
# meaning, and that is the part worth pinning.
check("Enter now opens rather than logs", "Enter open" in body, body[-200:])
check("and Esc deselects rather than leaving",
      "Esc deselect" in body, body[-200:])
check("the log screen is still what is drawn", "UTC" in body, body[:200])

# Up from the form picks the NEWEST, because "did that last one go in" is
# almost always the question.
body, _ = with_logged([RING_FWD, ARROW_UP, "\r"], "Up then Enter opens the newest")
check("the contact screen opens", "CONTACT" in body, body[:120])
check("on the newest contact", LOGGED[-1] in body, body[:120])
check("and says where it is in the log", "3 of 3" in body, body[:120])

body, _ = with_logged([RING_FWD, ARROW_UP, ARROW_UP, "\r"],
                      "Up twice walks back one")
check("the arrows walk the list", "2 of 3" in body, body[:120])
check("onto the contact before it", LOGGED[1] in body, body[:120])

body, _ = with_logged([RING_FWD, ARROW_UP, "\r"], "the contact, field by field")
check("the timestamp is shown", "UTC" in body, body[:400])
check("the callsign is shown", "Call" in body, body[:400])
check("so are fields the list has no room for",
      "My rig" in body and "FTX-1" in body, body[:400])
check("and it says how to change one", "Enter edit" in body, body[-120:])

# A mis-hit arrow must not cost the screen, and must not eat the first letter
# of a callsign either.
body, _ = with_logged([RING_FWD, ARROW_UP, "\x1b"], "Esc deselects first")
check("one Esc puts the keyboard back on the form",
      "Enter log" in body, body[-200:])
check("and does not leave the log screen", "UTC" in body, body[:200])

body, _ = with_logged([RING_FWD, ARROW_UP] + list("KD3ZZZ"),
                      "typing returns to the form")
check("the callsign is typed in full, first letter included",
      "KD3ZZZ" in body, body[-400:])
check("and the selection is gone", "Enter log" in body, body[-200:])

print("\nan edit reaches the file")
# Ctrl-U clears the line, then the corrected call is typed and saved. The FILE
# is the assertion: the screen could say anything.
body, text = with_logged(
    [RING_FWD, ARROW_UP, ARROW_UP, "\r", "\r", "\x15"]
    + list("KD3CCP") + ["\r"], "correct a mis-taken callsign")
check("the corrected callsign is in the file", "call=KD3CCP" in text, text)
check("the wrong one is gone", "call=KD3CPP" not in text, text)
check("the contacts either side are untouched",
      "call=W1AW" in text and "call=W3TM" in text, text)
equals("and there are still three of them",
       len([l for l in text.splitlines() if l.strip()]), 3)

print("\nlines per contact")
# What the extra rows SHOW is the SCHEMA's own field order, carrying on from
# where the first row stops, and then the AUTOMATIC fields -- band, frequency,
# mode, power, rig, antenna -- which no schema lists because nobody types
# them. The fixture logs under general logging, whose fields all fit on the
# first row, so everything here comes from that automatic tier.
#
# It used to expect `State PA`. A state is in these records and in no
# schema's field list, so under §7g it is not shown: the display follows the
# schema, not the record. The contact screen is where every field is read.
body, _ = with_logged([RING_FWD], "one line each", lines="1")
check("one line shows the contact", "W3TM" in body, body[:300])
check("and nothing below it", "Band 40m" not in body, body[:300])

body, _ = with_logged([RING_FWD], "two lines each", lines="2")
check("two lines carry on down the fields", "Band 40m" in body, body[:400])
check("and a field no schema asks for is not among them",
      "State PA" not in body, body[:400])

body, _ = with_logged([RING_FWD], "three lines each", lines="3")
check("three lines reach what this station ran",
      "My rig FTX-1" in body or "My W 6" in body, body[:400])
# A contact is the same height whatever is filled in, because the arrows
# select whole contacts.
check("the contact's own band is shown, which the first row has no room for",
      "Band 40m" in body, body[:400])

print("\ndeleting a contact from the contact screen")
# Behind a confirmation, like the activity and activity-type deletes, and for
# a stronger reason: those throw away something the operator can rebuild and
# this throws away a contact nothing on the deck can recover. The FILE is the
# assertion -- the harness quits with Ctrl-Q and every key but Enter keeps the
# contact, so the last screen is never the question.
body, text = with_logged([RING_FWD, ARROW_UP, "d"], "d alone deletes nothing")
check("the question on its own destroys nothing",
      f"call={LOGGED[-1]}" in text, text)

body, text = with_logged([RING_FWD, ARROW_UP, "d", "\x1b"], "Esc keeps it")
check("Esc keeps the contact", f"call={LOGGED[-1]}" in text, text)

body, text = with_logged([RING_FWD, ARROW_UP, "\r", "d", "\r"],
                         "Enter deletes it")
check("the contact is gone from the file",
      f"call={LOGGED[-1]}" not in text, text)
check("the others are untouched",
      f"call={LOGGED[0]}" in text and f"call={LOGGED[1]}" in text, text)
equals("and two are left", len([l for l in text.splitlines() if l.strip()]), 2)

print("\nthe duplicate warning is not squatted on")
# One line carries three things: what the operator just did, the duplicate
# warning, and the callbook's status. They shared one attribute, so whichever
# was written last won -- and the callbook, which polls, was always last. The
# dupe appeared for an instant and was then overwritten by "name=..., qth=...".
#
# A successful lookup now says nothing at all: the fields filling in IS the
# message, and the one line this screen has is worth more than repeating it.


def with_worked(keys, label, dupe="call", settle=3.0):
    """Run with one contact already worked. Returns the message line."""
    import datetime as _dt
    with tempfile.TemporaryDirectory() as tmp:
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
        log = os.path.join(tmp, "qso.log")
        with open(log, "w") as fh:
            fh.write(f"when={stamp}T14:00:00Z call=W1AW band=40m mode=PSK31 "
                     f"rst_s=599 rst_r=599 my_call=KD3CCO\n")
        conf_path = os.path.join(tmp, "cyberdeck.conf")
        with open(conf_path, "w") as fh:
            fh.write(STATION + "LOGGING = yes\nCALLBOOK = no\n"
                     + f"DUPE_CHECK = {dupe}\n"
                     + f"LOG_PATH = {log}\n")
        scr = run(keys=keys, settle=settle, term="linux", conf=conf_path)
        show(label, scr)
        return "\n".join(scr.display)


body = with_worked([RING_FWD] + list("W1AW"), "a callsign already worked")
check("the duplicate warning is on the message line",
      "** W1AW worked" in body, body[-300:])
check("and says when, so it can be judged", "14:00" in body, body[-300:])

body = with_worked([RING_FWD] + list("W9ZZZ"), "a callsign not worked")
check("a station not worked gets no warning", "**" not in body, body[-300:])

# The receipt for the last contact must not outlive it either: it sat on this
# line through the next callsign and hid that contact's warning the same way.
body = with_worked([RING_FWD] + list("W9ZZZ") + ["\r"] + list("W1AW"),
                   "log one, then type a worked call", settle=3.4)
check("the previous contact's receipt is gone once typing starts",
      "logged W9ZZZ" not in body, body[-300:])
check("and the new callsign's warning gets the line",
      "** W1AW worked" in body, body[-300:])

print("\nthe one log holds every activity's contacts")
# There is one log -- §7f. An activity is a LABEL on a record in it, so a
# contact made under an activity is one record carrying `activity=` and
# `activity_start=`, and forgetting the activity later cannot take it with
# it because there is nothing of the activity's to remove.
#
# This section used to drive the two-file design: a per-activity file in
# `activities/` plus a duplicated write into a master, switched by a
# `MASTER_LOG` setting that no longer exists. What that bought was a
# per-activity export, which a filter gives for free; what it cost was two
# writes to keep in step and two places to find a contact in when correcting
# one.


def with_master(keys, label, settle=3.4):
    """Run under a named activity. Returns the records in the one log."""
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.join(tmp, "qso.log")
        conf_path = os.path.join(tmp, "cyberdeck.conf")
        with open(conf_path, "w") as fh:
            fh.write(STATION + "LOGGING = yes\nACTIVITY = Testpark\n"
                     "ACTIVITY_START = 2026-10-11T13:00:00Z\n"
                     + f"LOG_PATH = {base}\n")
        show(label, run(keys=keys, settle=settle, term="linux",
                        conf=conf_path))
        if not os.path.exists(base):
            return []
        with open(base) as fh:
            return [l for l in fh.read().splitlines() if l.strip()]


LOG_ONE = [RING_FWD] + list("W1AW") + ["\r"]

logged = with_master(LOG_ONE, "one contact under an activity")
equals("one record was written", len(logged), 1)
check("it is the contact", "call=W1AW" in logged[0], str(logged))
check("the activity is named on it", "activity=Testpark" in logged[0],
      logged[0])
# The session key, which is what makes the activity a session rather than a
# name: an activation from 23:50 to 00:30 is one session, and anything
# derived from the contacts' own dates would split it at midnight.
check("and so is the session it began at",
      "activity_start=2026-10-11T13:00:00Z" in logged[0], logged[0])

# Forgetting the ACTIVITY keeps the contact. This is the whole feature.
F2L = "\x1b[[B"
DOWN_M = "\x1b[B"
logged = with_master(LOG_ONE + [F2L, DOWN_M, "d", "\r"],
                     "forget the activity", settle=4.0)
equals("the contact survived", len(logged), 1)
check("with its label intact", "activity=Testpark" in logged[0], logged[0])

# Deleting a CONTACT does remove it: it was logged in error, and an archive
# that keeps a contact the operator said was wrong is worse than no archive.
logged = with_master(LOG_ONE + ["\x1b[A", "\r", "d", "\r"],
                     "delete the contact itself", settle=4.2)
equals("the log is empty", len(logged), 0)


print("\nEsc does not leave the logging application")
# It used to go to the conversation, which made sense while the log hung off
# the digimode screen and stopped making sense the moment the three became
# peers: there is no "up" from the log screen to go to, and ejecting an
# operator into a different application for pressing the back key is not
# backing out of anything. ^O and ^P are how you leave.
body, _ = deck([RING_FWD, "\x1b"], "LOGGING = yes\n", label="Ctrl-N then Esc")
check("the log screen is still what is drawn",
      "\u2190\u2192 field" in body, body[-200:])
check("and not the conversation", "^T over" not in body, body[-200:])

# Esc still backs out WITHIN the application, one level at a time. From the
# activities list it returns to the log screen rather than going nowhere.
F2L = "\x1b[[B"
body, _ = deck([RING_FWD, F2L, "\x1b"], "LOGGING = yes\n",
               label="activities then Esc")
check("Esc from the activities list returns to the log screen",
      "\u2190\u2192 field" in body, body[-200:])
check("and the list is gone", "ACTIVITIES" not in body, body[:200])

# And it puts down a picked contact before it does anything else, so a
# mis-hit arrow costs one keystroke rather than the screen.
body, _ = deck([RING_FWD, "\x1b[A", "\x1b"], "LOGGING = yes\n",
               label="pick a contact then Esc")
check("the selection is dropped", "Enter log" in body, body[-200:])
check("and the screen is unchanged", "\u2190\u2192 field" in body,
      body[-200:])

sys.exit(report())
