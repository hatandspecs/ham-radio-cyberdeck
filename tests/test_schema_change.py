"""Changing log schema — `Deck._set_activity_type` and the guard in front of it.

The picker refuses to change schema over a part-typed contact, because the
change rebuilds the form and a typed callsign and reports would go with it.
`LogForm.typed()` is what that refusal reads.

**The bug this file exists for.** `typed()` counted a prefilled field
whenever its `touched` flag was set, and `touched` on those fields is
deliberately never cleared -- `commit` and `clear` both skip them, so that a
hand-corrected mode survives the next poll from the radio. One correction
therefore latched `typed()` non-empty for the life of the form, and the
schema could never be changed again. The message told the operator to log the
contact or press `^X`, and neither of those could clear it. Reported from the
deck 2026-10-23 as "the log schema is staying in the new log schema I
created".

The fix is in two halves and both are checked here: `_set_activity_type`
carries the prefilled fields across the rebuild **with their `touched`
flags**, so nothing is discarded, and `typed()` therefore stops counting
them at all.

Checked against the real `Deck._set_activity_type` and the real `LogForm`,
with no radio and no screen -- the method rebuilds the form and writes the
config, which is all of what is under test.
"""
import os
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report

import activities
import cyberdeck
import logform
import qsolog

MYCALL = "KD3CCO"


def deck(schema="", table=None):
    """A Deck with enough attached to change schema and nothing more."""
    d = cyberdeck.Deck.__new__(cyberdeck.Deck)
    d.cfg = {"CALLSIGN": MYCALL, "LOCATOR": "FN10", "ACTIVITY": "",
             "ACTIVITY_START": "", "ACTIVITY_TYPE": schema,
             "RIG": "FTX-1", "ANTENNA": "EFHW", "MY_PARK": "",
             "EXCHANGE_TX": ""}
    d.log_on = True
    d.screen = cyberdeck.LOG
    d.log_records = []
    d.log_message = ""
    d.picker_message = ""
    d.acts_message = ""
    d._looked_up = ""
    d._rig = None
    d._radio_cache = ("14.070.150", "BPSK31", 20)
    d._radio_at = time.monotonic()
    d._log_rig = lambda: None
    d._logfile = os.path.join(tempfile.mkdtemp(), "qso.log")
    d._log_path = lambda: d._logfile
    # `_set_activity_type` ends by saving state and offering the reference
    # editor. Neither is what this file is about, and both want a screen.
    d._save_state = lambda: None
    d._ask_my_park = lambda: None
    d._log_note = lambda text: setattr(d, "log_message", text)
    d.log_form = logform.LogForm(activities.get(
        schema, table if table is not None else activities.load()))
    return d


# A schema of the operator's own, the shape of the one the bug was reported
# against: made while naming an activity, and so the one the form is sitting
# in when they go back to the master log.
TABLE = dict(activities.BUILTIN)
TABLE["FIELDDAY"] = activities.ActivityType(
    "FIELDDAY", label="Field Day",
    entry=("rst_s", "rst_r", "exchange_tx", "exchange_rx", "comment"),
    labels={"exchange_rx": "Class/Sec"})


print("a hand-corrected mode no longer blocks a schema change")

d = deck(schema="FIELDDAY", table=TABLE)
d.log_form.from_radio(freq="14.070.150", mode="BPSK31", power="20")
equals("a fresh poll is not operator work", d.log_form.typed(), [])

# fldigi reports the modem it is running; the operator corrects it to what is
# actually on the air. This is the touch that used to be permanent.
d.log_form.set("mode", "BPSK63", touch=True)
check("the correction is marked as one", d.log_form.field("mode").touched)
equals("but it is not counted as a part-typed contact",
       d.log_form.typed(), [])

d.log_form.set("call", "K2ABC", touch=True)
d.log_form.commit()
equals("nor after the contact is logged", d.log_form.typed(), [])
# `^X` was the deck's own advice for clearing the refusal. It never could:
# `clear` skips the prefilled fields by the same design that keeps a
# correction, so it reports nothing to discard and leaves `touched` set.
d.log_form.clear()
check("^X leaves the correction in place", d.log_form.field("mode").touched)
equals("and the corrected value with it",
       d.log_form.value("mode"), "BPSK63")
equals("which is why it had to stop counting", d.log_form.typed(), [])


print("\nthe correction itself survives the schema change")

before = d.log_form.value("mode")
d._set_activity_type("GENERAL", TABLE)
equals("the schema changed", d.log_form.activity_type.name, "GENERAL")
equals("and the config followed it", d.cfg["ACTIVITY_TYPE"], "")
equals("the corrected mode came across", d.log_form.value("mode"), before)
check("still marked corrected", d.log_form.field("mode").touched)

# The whole point of the flag: the next poll must not undo the correction.
d.log_form.from_radio(freq="14.070.150", mode="BPSK31", power="20")
equals("so the next poll leaves it alone", d.log_form.value("mode"), "BPSK63")
equals("the frequency came across too",
       d.log_form.value("freq"), "14.070.150")


print("\nan uncorrected radio field comes across as uncorrected")

d = deck(schema="FIELDDAY", table=TABLE)
d.log_form.from_radio(freq="14.070.150", mode="BPSK31", power="20")
d._set_activity_type("GENERAL", TABLE)
equals("the mode is carried", d.log_form.value("mode"), "BPSK31")
check("and is still open to the radio",
      not d.log_form.field("mode").touched)
d.log_form.from_radio(freq="21.070.000", mode="RTTY", power="20")
equals("so a band change reaches it", d.log_form.value("mode"), "RTTY")


print("\nthe guard still refuses over a part-typed contact")

d = deck(schema="FIELDDAY", table=TABLE)
d.log_form.from_radio(freq="14.070.150", mode="BPSK31", power="20")
d.log_form.set("call", "W1XYZ", touch=True)
equals("a typed callsign counts", d.log_form.typed(), ["call"])

d.log_form.focus("rst_r")
d.log_form.kill()
d.log_form.type("57")
equals("and an edited report", sorted(d.log_form.typed()), ["call", "rst_r"])

# The refusal names fields the operator recognises, which is the only reason
# the message is worth printing.
labels = [qsolog.field_label(f) for f in d.log_form.typed()]
check("and the names are the ones on the form", all(labels), labels)

d.log_form.clear()
equals("clearing the contact releases it", d.log_form.typed(), [])


print("\nthe sticky fields are carried as they always were")

d = deck(schema="POTA", table=TABLE)
d.log_form.set("my_park", "US-5474")
d.log_form.set("comment", "picnic table")
equals("neither counts as typed", d.log_form.typed(), [])
d._set_activity_type("GENERAL", TABLE)
equals("the comment came across", d.log_form.value("comment"),
       "picnic table")

# GENERAL has no reference field, so there is nowhere for the park to go --
# which is correct, and the reason `set` returning False is not an error.
check("GENERAL has no reference field to carry it into",
      d.log_form.field("my_park") is None)
equals("so the park is not on the form", d.log_form.value("my_park"), "")


print("\nevery prefilled field is covered, not just the mode")

d = deck(schema="GENERAL", table=TABLE)
for name in logform.PREFILLED:
    f = d.log_form.field(name)
    if f is None:
        continue
    f.value = "X"
    f.touched = True
equals("a touched prefilled field is never counted", d.log_form.typed(), [])


sys.exit(report())
