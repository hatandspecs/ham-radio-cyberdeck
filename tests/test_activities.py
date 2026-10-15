"""Activity types: a named set of fields, and the entry grammar they imply.

The load-bearing idea is that **the field list IS the grammar**. `W3ABC 123 MONT`
is a serial and a county in a QSO party and nothing of the kind in general
logging, and `599` is a valid report *and* a valid serial, so no parser can tell
them apart from the tokens. The activity resolves it, because the operator chose
the activity before they started typing.

What is pinned here:

  * **general logging is unchanged by all of this.** Choosing no activity has
    to behave exactly as the log did before activities existed, or every
    ordinary contact is a regression.
  * **a definition that cannot work is refused at load, with a reason.** An
    activity that silently does not exist looks identical to one that does
    nothing, and the operator finds out during a contact.
  * **`like` inherits, and an override replaces only what it names.** A state
    QSO party is a QSO party with a contest id and a different word for the
    exchange; restating the field list would let the two drift.
  * **a missing number does not shift every field after it.** The one failure
    that silently corrupts a log rather than visibly breaking it.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import activities
import qsolog

print("the list of possible fields")
names = [f for f, _l, _k in activities.field_choices()]
equals("every entry field is offered", set(names), set(activities.ENTRY_FIELDS))
# The order is ENTRY_FIELDS' own, declared once there, so the selection
# screen and this list cannot disagree. It used to be repeated here and in
# field_choices(); seven fields added to ENTRY_FIELDS were then selectable
# nowhere, because field_choices is what the panel asks.
equals("in ENTRY_FIELDS order, so the panel and the docs agree",
       names, list(activities.ENTRY_FIELDS))
check("the two reports lead, because nearly every activity wants them",
      names[:2] == ["rst_s", "rst_r"], str(names[:2]))

# Page one of the selection screen is QRZ's own QSO record. The fields QRZ
# matches a contact on -- the callsigns, the time, the band, the mode -- are
# stored on every contact and are not selectable, so what is left of that
# record is the report, the worked station, this station's side and the QSL
# route. An operator who chooses from page one alone uploads a complete log.
#
# Asserted as a list rather than a set: the page is derived from position in
# ENTRY_FIELDS, so an insertion in the wrong place silently pushes the last
# of these onto page two where it will not be found.
import render as _render
# Six of what QRZ's panel asks for are filled in rather than chosen -- the
# callsign, date, UTC time, band, frequency and mode are on every contact and
# are not selectable at all -- so this is the rest of it, with the worked
# station's details around them. `my_park` is absent on purpose: it is the
# same on every contact of an activation, so it is asked once for the activity
# rather than being a column that repeats itself down the file.
QRZ_PAGE = ["rst_s", "rst_r", "name", "qth", "state", "grid", "county",
            "country", "park", "comment", "tx_power", "my_rig", "my_antenna",
            "qsl_via"]
equals("page one is QRZ's QSO record", names[:_render.FIELDS_PER_PAGE],
       QRZ_PAGE)
equals("and it fills the page exactly", len(QRZ_PAGE),
       _render.FIELDS_PER_PAGE)
check("every row of that page has a key printed beside it",
      _render.FIELDS_PER_PAGE <= len(activities.PICK_KEYS),
      f"{_render.FIELDS_PER_PAGE} rows, {len(activities.PICK_KEYS)} keys")

# What is left is the contest exchange and the program references: the whole
# point inside one event, and noise outside it.
# Anything strictly contest-related, and anything outside general and POTA
# logging, goes here.
equals("page two is the exchange, the zones and the other programs",
       names[_render.FIELDS_PER_PAGE:],
       ["serial_rx", "exchange_rx", "check", "precedence", "power_rx",
        "cq_zone", "itu_zone", "iota", "sota", "wwff", "sat_name",
        "prop_mode", "age", "freq_rx"])
check("this station's own reference is not a per-contact field",
      "my_park" not in names, str(names))
check("each has a label and a kind",
      all(l and k for _f, l, k in activities.field_choices()),
      str(activities.field_choices()))

print("\nbuilt-ins")
equals("general is the default when nothing is named",
       activities.get("").name, "GENERAL")
equals("an unknown activity falls back rather than raising",
       activities.get("NOT-A-THING").name, "GENERAL")
check("case does not matter", activities.get("pota").name == "POTA")
equals("general's grammar is what the log always had",
       activities.GENERAL.entry, ("rst_s", "rst_r", "name", "qth"))
check("a contest has a serial and leaves reports out",
      activities.BUILTIN["CONTEST"].entry == ("serial_rx", "exchange_rx")
      and activities.BUILTIN["CONTEST"].serial,
      str(activities.BUILTIN["CONTEST"]))
# Three built-ins and only three. SOTA, WWFF, Field Day and the state QSO
# parties are examples in activities.conf.example to be copied, not built in:
# a built-in nobody uses is a line in a picker to scroll past forever.
equals("exactly three defaults", sorted(activities.BUILTIN),
       ["CONTEST", "GENERAL", "POTA"])

print("\nan activity renames a field to the word on the air")
equals("POTA calls it a park",
       activities.BUILTIN["POTA"].label_for("park"), "Park")
equals("and an unrenamed field keeps its default",
       activities.BUILTIN["POTA"].label_for("name"), "Name")

print("\ndefining one in a file")
table = activities.parse_file("""
[PAQP]
like = CONTEST
label = Pennsylvania QSO Party
contest_id = PA-QSO-PARTY
label_exchange_rx = County

[SPRINT]
label = My own order
entry = exchange_rx, serial_rx
serial = yes
serial_start = 100
""", inherit_from=activities.BUILTIN)

pa = table["PAQP"]
equals("inherits the grammar", pa.entry, ("serial_rx", "exchange_rx"))
equals("inherits the serial", pa.serial, True)
equals("overrides the label", pa.label, "Pennsylvania QSO Party")
equals("adds a contest id", pa.contest_id, "PA-QSO-PARTY")
equals("renames the exchange", pa.label_for("exchange_rx"), "County")

sp = table["SPRINT"]
equals("a custom order is kept as given", sp.entry, ("exchange_rx", "serial_rx"))
equals("and a starting serial", sp.serial_start, 100)
check("a file activity does not disturb the built-ins",
      activities.BUILTIN["CONTEST"].contest_id == "", "built-in was mutated")

print("\nloading merges over the built-ins")
import tempfile
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "activities.conf")
    with open(path, "w") as fh:
        fh.write("[POTA]\nlabel = My own POTA\n")
    merged = activities.load(path)
    equals("an override replaces that one", merged["POTA"].label, "My own POTA")
    check("and keeps its inherited grammar",
          merged["POTA"].entry == activities.BUILTIN["POTA"].entry,
          str(merged["POTA"].entry))
    check("while every other built-in survives",
          {"GENERAL", "CONTEST", "POTA"} <= set(merged), str(sorted(merged)))

equals("a missing file is the normal case",
       activities.load(os.path.join("/nonexistent", "activities.conf"))["POTA"].label,
       "Parks on the Air")

print("\nbad definitions are refused, with a reason")
def refuses(body, phrase):
    try:
        activities.parse_file(body, inherit_from=activities.BUILTIN)
    except activities.ActivityError as exc:
        check(f"refused, saying {phrase!r}", phrase in str(exc), str(exc))
    else:
        check(f"should have refused {body.strip()!r}", False, "it did not")

refuses("[X]\nentry = call, rst_r\n", "unknown entry field")
refuses("[X]\nentry = rst_r, rst_r\n", "listed twice")
refuses("[X]\nserial = maybe\n", "yes or no")
refuses("[X]\nserial_start = soon\n", "must be a number")
refuses("[X]\nlike = NOTHING\n", "not a known activity")
refuses("[X]\nwidgets = 3\n", "unknown setting")
# The message has to name the section, because a file may define a dozen.
try:
    activities.parse_file("[GOOD]\nentry = rst_r\n\n[BAD]\nentry = nope\n",
                          inherit_from=activities.BUILTIN)
except activities.ActivityError as exc:
    check("and names which section", "[BAD]" in str(exc), str(exc))

print("\nthe grammar drives the parser")
G = activities.GENERAL
QP = table["PAQP"]
FD = activities.parse_file("[FD]\nentry = exchange_rx\n",
                           inherit_from=activities.BUILTIN)["FD"]

print("  general logging is untouched")
equals("call only", qsolog.parse_entry("W3ABC", "USB", G)["rst_r"], "59")
equals("one report is the received one",
       qsolog.parse_entry("W3ABC 57", "USB", G)["rst_r"], "57")
equals("and the sent one defaults",
       qsolog.parse_entry("W3ABC 57", "USB", G)["rst_s"], "59")
both = qsolog.parse_entry("W3ABC 59 57 Bob Pittsburgh PA", "USB", G)
equals("both reports, name, and the rest as QTH",
       (both["rst_s"], both["rst_r"], both["name"], both["qth"]),
       ("59", "57", "Bob", "Pittsburgh PA"))
equals("no activity argument at all is general logging",
       qsolog.parse_entry("W3ABC 59 57 Bob", "USB"),
       qsolog.parse_entry("W3ABC 59 57 Bob", "USB", G))
check("and general logging has no exchange fields set",
      not qsolog.parse_entry("W3ABC 59 57 Bob", "USB", G)["serial_rx"]
      and not qsolog.parse_entry("W3ABC 59 57 Bob", "USB", G)["exchange_rx"])

print("  a QSO party reads the same shape differently")
qp = qsolog.parse_entry("W3ABC 123 MONT", "USB", QP)
equals("serial", qp["serial_rx"], "123")
equals("exchange", qp["exchange_rx"], "MONT")
equals("reports default rather than eating the serial",
       (qp["rst_s"], qp["rst_r"]), ("59", "59"))
check("and the serial did not become a name", not qp["name"], str(qp))
# 599 is both a valid report and a valid serial. This is the ambiguity the
# whole design exists to resolve, so it is pinned in both directions.
equals("599 is a serial here", qsolog.parse_entry("W3ABC 599 X", "USB", QP)["serial_rx"],
       "599")
equals("and a report in general logging",
       qsolog.parse_entry("W3ABC 599", "CW", G)["rst_r"], "599")

print("  a missing number does not shift the fields after it")
# The failure that corrupts a log quietly instead of loudly: if a skipped
# serial let the exchange slide into the numeric slot, every later field moves.
skipped = qsolog.parse_entry("W3ABC MONT", "USB", QP)
equals("no serial was invented", skipped["serial_rx"], "")
equals("and the exchange stayed the exchange", skipped["exchange_rx"], "MONT")

print("  a greedy last field takes the rest")
fd = qsolog.parse_entry("W3ABC 1B EPA", "USB", FD)
equals("class and section are one exchange", fd["exchange_rx"], "1B EPA")

print("  a custom order is honored")
sprint = qsolog.parse_entry("W3ABC MONT 44", "USB", sp)
equals("exchange first", sprint["exchange_rx"], "MONT")
equals("serial second", sprint["serial_rx"], "44")

print("  a park is still found by shape, in any activity")
for name, act in (("general", G), ("qso party", QP), ("field day", FD)):
    equals(f"{name}: a park reference is pulled out regardless",
           qsolog.parse_entry("W3ABC US-1234", "USB", act)["park"], "US-1234")

print("\npicking fields, and putting them in order")
# Two screens on the panel, two operations here: WHICH fields, then WHAT
# order. Split because each is then answerable with one keystroke.
pick = activities.FieldPicker(["rst_s", "rst_r", "serial_rx", "exchange_rx"])
equals("it starts with what it was given",
       [f for _n, f, _l in pick.order()],
       ["rst_s", "rst_r", "serial_rx", "exchange_rx"])
equals("numbered from one", [n for n, _f, _l in pick.order()], [1, 2, 3, 4])

print("  toggling")
check("a field not chosen is off", not pick.is_on("park"))
equals("turning it on reports its new state", pick.toggle("park"), True)
check("and it joins the end, where the operator is thinking",
      pick.entry()[-1] == "park", str(pick.entry()))
equals("turning it off again", pick.toggle("park"), False)
check("and it is gone", "park" not in pick.entry(), str(pick.entry()))
equals("an unknown field cannot be toggled on", pick.toggle("nonsense"), False)
equals("every available field is offered with a label and a state",
       len(pick.rows()), len(activities.ENTRY_FIELDS))
check("and the states are right",
      dict((f, on) for f, _l, on in pick.rows())["rst_s"] is True,
      str(pick.rows()))

print("  renumbering is remove-and-insert, so one rule moves both ways")
pick.move("exchange_rx", 1)
equals("typing 1 on the last item makes it first and pushes the rest down",
       [f for _n, f, _l in pick.order()],
       ["exchange_rx", "rst_s", "rst_r", "serial_rx"])
pick.move("rst_r", 4)
equals("typing 4 on the third makes it fourth and pulls the rest up",
       [f for _n, f, _l in pick.order()],
       ["exchange_rx", "rst_s", "serial_rx", "rst_r"])
# On a panel the operator types a single digit at a list of four things, and
# 9 plainly means last.
pick.move("exchange_rx", 9)
equals("too large is last", pick.order()[-1][1], "exchange_rx")
pick.move("exchange_rx", 0)
equals("zero is first", pick.order()[0][1], "exchange_rx")
equals("the numbering is always 1..N with no gaps",
       [n for n, _f, _l in pick.order()], [1, 2, 3, 4])
equals("and nothing is lost or duplicated",
       sorted(pick.entry()),
       sorted(["exchange_rx", "rst_s", "rst_r", "serial_rx"]))
equals("a field not selected cannot be moved", pick.move("qth", 1), False)
equals("nor can a number that is not one", pick.move("rst_s", "soon"), False)

print("\nsaving an activity writes the file an operator can hand-edit")
import tempfile
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "activities.conf")
    with open(path, "w") as fh:
        fh.write("# notes of my own\n\n[MYOLD]\nentry = rst_s, rst_r\n")

    text = activities.format_activity(
        "PAQP", ("serial_rx", "exchange_rx"), label="PA QSO Party",
        like="CONTEST", contest_id="PA-QSO-PARTY", serial=True,
        labels={"exchange_rx": "County"})
    activities.save(path, "PAQP", text)

    table = activities.load(path)
    saved = table["PAQP"]
    equals("it reads back through the real parser",
           saved.entry, ("serial_rx", "exchange_rx"))
    equals("with its label", saved.label, "PA QSO Party")
    equals("its contest id", saved.contest_id, "PA-QSO-PARTY")
    equals("its serial", saved.serial, True)
    equals("and its renamed field", saved.label_for("exchange_rx"), "County")

    body = open(path).read()
    check("a section written by hand survives", "MYOLD" in table, str(sorted(table)))
    check("and so do the comments around it", "notes of my own" in body, body)

    # Saving twice under one name is what an operator does while getting a
    # definition right. Two sections of the same name would mean the second
    # silently wins with no sign of the first.
    activities.save(path, "PAQP", activities.format_activity(
        "PAQP", ("rst_s", "rst_r"), label="changed my mind"))
    body = open(path).read()
    equals("saving again replaces rather than appends", body.count("[PAQP]"), 1)
    equals("and the new definition is the one that loads",
           activities.load(path)["PAQP"].entry, ("rst_s", "rst_r"))

    fresh = os.path.join(tmp, "sub", "new.conf")
    activities.save(fresh, "X", activities.format_activity("X", ("rst_r",)))
    equals("a file that did not exist is created",
           activities.load(fresh)["X"].entry, ("rst_r",))

print("\nserials come from the log, not a counter file")
# A counter in its own file is a second source of truth that can disagree with
# the log, and sending a serial twice is not noticed until the log is checked.
recs = [{"activity": "PAQP", "serial_tx": "1"},
        {"activity": "PAQP", "serial_tx": "2"},
        {"activity": "FD", "serial_tx": "9"},
        {"call": "NOACTIVITY"}]
equals("next is one past the highest", qsolog.next_serial(recs, "PAQP"), 3)
equals("scoped per activity", qsolog.next_serial(recs, "FD"), 10)
equals("a new event starts at one", qsolog.next_serial(recs, "NEW"), 1)
equals("or at its configured start",
       qsolog.next_serial(recs, "NEW", start=100), 100)
equals("an empty log starts at the start",
       qsolog.next_serial([], "PAQP", start=5), 5)
equals("junk in the field does not raise",
       qsolog.next_serial([{"activity": "P", "serial_tx": "x"}], "P"), 1)
# Out of order is the case that matters: the highest wins, not the last.
equals("out-of-order entries still give the highest",
       qsolog.next_serial([{"activity": "P", "serial_tx": "7"},
                           {"activity": "P", "serial_tx": "3"}], "P"), 8)

print("\nthe exchange reaches ADIF in the right fields")
import datetime
WHEN = datetime.datetime(2026, 10, 11, 16, 0, 0)
# An ACTIVITY TYPE is the template; an ACTIVITY is the session using it and
# carries the operator's own name. make_record takes both, and they are
# separate arguments because they answer different questions: the type says
# how to read the fields, the name says which event they belong to.
rec = qsolog.make_record(
    qsolog.parse_entry("W3ABC 123 MONT", "USB", QP), WHEN,
    freq_hz=7_040_000, mode="USB", my_call="KD3CCO",
    activity_type=QP, activity="PAQP 2026",
    serial_tx=57, exchange_tx="CENT")
adif = qsolog.adif_record(rec)
for field, value in (("STX", "57"), ("SRX", "123"),
                     ("STX_STRING", "CENT"), ("SRX_STRING", "MONT"),
                     ("CONTEST_ID", "PA-QSO-PARTY")):
    check(f"<{field}> is {value}", f"<{field}:{len(value)}>{value}" in adif, adif)
equals("the session is recorded under the operator's name for it",
       rec["activity"], "PAQP 2026")
equals("and the type beside it, because it says how to read the fields",
       rec["activity_type"], "PAQP")
equals("both come back out together",
       qsolog.activity_of(rec), ("PAQP 2026", "PAQP"))
check("and the record round trips through storage",
      qsolog.parse_record(qsolog.format_record(rec)) == rec,
      qsolog.format_record(rec))

# A record written before the two were different things has the TYPE in
# `activity` and no `activity_type`. Reading it as a session of that name
# using that type is the only reading that loses nothing.
equals("a pre-split record reads as both",
       qsolog.activity_of({"activity": "CONTEST"}), ("CONTEST", "CONTEST"))
equals("but a name that is not a type name stays only a name",
       qsolog.activity_of({"activity": "Bald Eagle SP"}),
       ("Bald Eagle SP", ""))

general_rec = qsolog.make_record(
    qsolog.parse_entry("W3ABC 59 57 Bob", "USB", G), WHEN, freq_hz=7_040_000,
    mode="USB", my_call="KD3CCO", activity_type=G)
plain_adif = qsolog.adif_record(general_rec)
check("an ordinary contact carries no exchange fields at all",
      not any(f"<{f}" in plain_adif
              for f in ("STX", "SRX", "STX_STRING", "SRX_STRING",
                        "CONTEST_ID")),
      plain_adif)
check("and nothing about an activity in storage",
      "activity" not in general_rec and "activity_type" not in general_rec,
      str(general_rec))

# A contact can belong to a named session while using general logging: an
# afternoon called "SOTA hike" with no special fields is still one event.
named_general = qsolog.make_record(
    qsolog.parse_entry("W3ABC 59 57 Bob", "USB", G), WHEN, freq_hz=7_040_000,
    mode="USB", my_call="KD3CCO", activity_type=G, activity="SOTA hike")
equals("the name is kept with no type", named_general["activity"], "SOTA hike")
check("and no type is invented for it",
      "activity_type" not in named_general, str(named_general))

print("\nan activity's own log file, dated once")
equals("named after the activity, stamped with the day",
       qsolog.activity_log_path("Bald Eagle SP", "/tmp/l/qso.log",
                                date="2026-10-11"),
       "/tmp/l/activities/Bald-Eagle-SP_2026-10-11.log")
equals("the same name on another day is another activation",
       qsolog.activity_log_path("Bald Eagle SP", "/tmp/l/qso.log",
                                date="2026-09-14"),
       "/tmp/l/activities/Bald-Eagle-SP_2026-09-14.log")
equals("no activity means the default log, not a file named for an event",
       qsolog.activity_log_path("", "/tmp/l/qso.log"), "/tmp/l/qso.log")
equals("a name with nothing usable in it is no activity",
       qsolog.activity_log_path("  --  ", "/tmp/l/qso.log"), "/tmp/l/qso.log")
equals("the stem reads back to the name and the date",
       qsolog.split_activity_stem("Bald-Eagle-SP_2026-10-11"),
       ("Bald Eagle SP", "2026-10-11"))
equals("an undated file still gives a name",
       qsolog.split_activity_stem("PAQP"), ("PAQP", ""))
# The log is key=value text and the export is ADIF. Naming the log .adi would
# make the file that is not ADIF look like the one that is.
equals("the export sits beside the log under the same name",
       qsolog.export_path("/tmp/l/activities/PAQP_2026-10-10.log"),
       "/tmp/l/activities/PAQP_2026-10-10.adi")

print("\ndeleting an activity type")
import tempfile as _tf
with _tf.TemporaryDirectory() as _tmp:
    _conf = os.path.join(_tmp, "activities.conf")
    with open(_conf, "w") as fh:
        fh.write("[PAQP]\nlike = CONTEST\nlabel = Pennsylvania QSO Party\n\n"
                 "[SPRINT]\nlabel = Keep me\n")
    ok, detail = activities.delete(_conf, "PAQP")
    check("a type defined in the file is deleted", ok, detail)
    body = open(_conf).read()
    check("its section is gone", "[PAQP]" not in body, body)
    check("and the rest of the file is untouched",
          "[SPRINT]" in body and "Keep me" in body, body)

    ok, detail = activities.delete(_conf, "NOPE")
    check("a type that is not there is refused", not ok, detail)
    check("and says so", "not in" in detail, detail)

    ok, detail = activities.delete(_conf, "POTA")
    check("a built-in with no section cannot be deleted", not ok, detail)
    check("and says it is built in", "built in" in detail, detail)
    check("POTA is known to be a built-in", activities.is_builtin("POTA"))
    check("and a saved one is not", not activities.is_builtin("PAQP"))

    # Overriding a built-in and then deleting the override restores the
    # built-in, which is what an operator who edited one wants back.
    with open(_conf, "a") as fh:
        fh.write("\n[POTA]\nlabel = My own POTA\n")
    equals("the override is in force",
           activities.load(_conf)["POTA"].label, "My own POTA")
    ok, detail = activities.delete(_conf, "POTA")
    check("deleting the override is allowed", ok, detail)
    check("and it says the built-in is back", "built-in" in detail, detail)
    equals("because it is", activities.load(_conf)["POTA"].label,
           "Parks on the Air")

sys.exit(report())
