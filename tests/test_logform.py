"""The entry form: tab order, prefill, and what survives a commit.

The form replaced a single typed line, and in doing so dissolved the problem
that line was designed around: `599` is a valid report and a valid serial, and
on one line only the activity could say which. In a field of its own the
question cannot arise.

What is pinned here is mostly about *what happens between contacts*, because
that is where an entry form is either a help or a liability:

  * **the typing path comes first.** Call, then what the other station sent,
    then Enter. Everything prefilled — own serial, own exchange, frequency,
    mode — sits after it. The first version put the radio fields second and
    the exchange got typed into the frequency.
  * **sticky fields survive a commit, per-contact fields do not.** Retyping
    an exchange eighty times is eighty chances to mistype it; retaining the
    previous station's callsign is a wrong log entry.
  * **clearing a sticky field is how it is turned off.** No separate gesture,
    because deleting it is what an operator would try first.
  * **a radio field stops tracking the radio once edited.** A correction that
    got overwritten on the next poll could never be made.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import activities
import logform
import render
import qsolog

CONTEST = activities.parse_file(
    "[PAQP]\nlike = CONTEST\nlabel = PA QSO Party\nlabel_exchange_rx = County\n",
    inherit_from=activities.BUILTIN)["PAQP"]


def names(form):
    return [f.name for f in form.fields]


print("the tab order puts typing first and prefill last")
equals("general logging", names(logform.LogForm(activities.GENERAL)),
       ["call", "rst_s", "rst_r", "name", "qth", "comment", "freq", "mode"])
equals("a park activation adds the reference and this station's own",
       names(logform.LogForm(activities.BUILTIN["POTA"])),
       ["call", "rst_s", "rst_r", "park", "name", "comment", "my_park",
        "freq", "mode"])
equals("a contest adds both serials and both exchanges",
       names(logform.LogForm(CONTEST)),
       ["call", "serial_rx", "exchange_rx", "comment", "serial_tx",
        "exchange_tx", "freq", "mode"])
# The bug this pins: with the radio fields second, tabbing off the callsign
# landed on the frequency and the exchange was typed into it.
for act in (activities.GENERAL, activities.BUILTIN["POTA"], CONTEST):
    f = logform.LogForm(act)
    equals(f"{act.name}: the callsign leads", names(f)[0], "call")
    check(f"{act.name}: the radio does not interrupt the typing path",
          names(f)[1] not in ("freq", "mode"), str(names(f)))
    check(f"{act.name}: and is reachable at the end",
          {"freq", "mode"} <= set(names(f)), str(names(f)))

check("an activity with no reference has no my_park field",
      "my_park" not in names(logform.LogForm(CONTEST)), str(names(logform.LogForm(CONTEST))))
check("an activity that sends no serial has no serial_tx",
      "serial_tx" not in names(logform.LogForm(activities.GENERAL)))
check("the field labels are the activity's own words",
      "County" in [f.label for f in logform.LogForm(CONTEST).fields],
      str([f.label for f in logform.LogForm(CONTEST).fields]))

print("\nmoving")
f = logform.LogForm(CONTEST)
f.type("W3ABC")
equals("typing lands in the first field", f.value("call"), "W3ABC")
f.tab()
equals("tab moves on", f.current.name, "serial_rx")
f.tab(back=True)
equals("shift-tab moves back", f.current.name, "call")
equals("and the cursor goes to the end of what is there", f.cursor, 5)
f.tab(back=True)
# Wrapping rather than stopping: a key that does nothing makes the operator
# look down to find out why.
equals("shift-tab from the first field wraps to the last",
       f.current.name, "mode")
f.tab()
equals("and forward from the last wraps to the first", f.current.name, "call")
check("focus by name works", f.focus("exchange_rx")
      and f.current.name == "exchange_rx")
equals("and an unknown name changes nothing", f.focus("nope"), False)

print("\nediting")
f = logform.LogForm(activities.GENERAL)
f.type("W1AW")
f.backspace()
equals("backspace", f.value("call"), "W1A")
f.left(); f.left(); f.type("X")
equals("insert at the cursor", f.value("call"), "WX1A")
f.home(); f.delete()
equals("delete forward", f.value("call"), "X1A")
f.end()
equals("end goes past the last character", f.cursor, 3)
f.kill()
equals("kill empties the field", f.value("call"), "")
equals("and parks the cursor", f.cursor, 0)
f.backspace()
equals("backspace on an empty field does nothing", f.value("call"), "")

print("\nthe radio fills in, until it is corrected")
f = logform.LogForm(activities.GENERAL)
f.from_radio(freq="7.185", mode="SSB")
equals("frequency", f.value("freq"), "7.185")
equals("mode", f.value("mode"), "SSB")
f.from_radio(freq="14.250", mode="USB")
equals("and keeps up while untouched", f.value("freq"), "14.250")

f.focus("freq"); f.kill(); f.type("18.100")
f.from_radio(freq="14.250", mode="USB")
equals("a corrected field stops tracking", f.value("freq"), "18.100")
equals("while its neighbour carries on", f.value("mode"), "USB")
f2 = logform.LogForm(activities.GENERAL)
f2.from_radio(freq="", mode="")
equals("nothing from the radio leaves it blank, not 'None'",
       f2.value("freq"), "")

print("\nCtrl-Z puts a prefill back")
# The request this exists for: typing over a prefilled field by accident.
# The deck must bind it as (26, curses.KEY_SUSPEND) -- TERM=linux defines
# kspd=^Z so ncurses eats byte 26 and returns KEY_SUSPEND. Matching only 26
# ships dead on the panel, which has happened here once already.
f = logform.LogForm(activities.GENERAL)
f.from_radio(freq="14.070", mode="BPSK31")
f.focus("rst_r")
equals("the mode prefilled the report", f.value("rst_r"), "599")
f.kill(); f.type("579")
equals("typed over", f.value("rst_r"), "579")
check("ctrl-z restores it", f.restore())
equals("to the prefill", f.value("rst_r"), "599")
check("pressed again it puts back what it displaced", f.restore())
equals("the typed value", f.value("rst_r"), "579")
check("and it keeps flipping rather than doing nothing", f.restore())
equals("back to the prefill", f.value("rst_r"), "599")

# Without this guard, ctrl-z on a freshly typed callsign wipes it -- which is
# not undoing a mistake, it is making one.
bare = logform.LogForm(activities.GENERAL)
bare.focus("call"); bare.type("W1AW")
equals("a field that was never prefilled refuses", bare.restore(), False)
equals("and keeps what was typed", bare.value("call"), "W1AW")

f.focus("freq"); f.kill(); f.type("18.100")
check("a corrected radio field stops tracking", f.field("freq").touched)
f.restore()
check("and restoring it starts tracking again",
      not f.field("freq").touched,
      "restoring the prefill says the override was not meant")
f.from_radio(freq="21.070", mode="BPSK31")
equals("so the radio fills it in again", f.value("freq"), "21.070")

sticky = logform.LogForm(activities.GENERAL)
sticky.focus("comment"); sticky.type("5W to a wire")
sticky.focus("call"); sticky.type("W3ABC")
sticky.commit()
sticky.focus("comment"); sticky.type("!!!")
sticky.restore()
equals("a sticky value carried through a commit is restorable",
       sticky.value("comment"), "5W to a wire")

print("\nreports are prefilled, or the form would be more typing than the line")
voice = logform.LogForm(activities.GENERAL)
voice.from_radio(freq="7.185", mode="SSB")
equals("voice", (voice.value("rst_s"), voice.value("rst_r")), ("59", "59"))
digital = logform.LogForm(activities.GENERAL)
digital.from_radio(freq="14.070", mode="BPSK31")
equals("digital", (digital.value("rst_s"), digital.value("rst_r")),
       ("599", "599"))
edited = logform.LogForm(activities.GENERAL)
edited.from_radio(mode="SSB")
edited.focus("rst_r"); edited.kill(); edited.type("57")
edited.from_radio(mode="SSB")
equals("an edited report is not overwritten", edited.value("rst_r"), "57")
equals("while the other one still defaults", edited.value("rst_s"), "59")
# A contest activity lists no reports, so there is nothing to prefill.
nore = logform.LogForm(CONTEST)
nore.from_radio(mode="SSB")
equals("an activity without reports is unaffected", nore.field("rst_r"), None)

print("\nwhat survives a commit")
f = logform.LogForm(CONTEST)
f.from_radio(freq="3.820", mode="SSB")
f.set("exchange_tx", "CENT")
f.set("serial_tx", "58")
f.focus("comment"); f.type("5W to a wire")
f.focus("call"); f.type("K3PP")
f.focus("serial_rx"); f.type("44")
f.focus("exchange_rx"); f.type("CHES")

out = f.commit()
equals("the contact comes back whole", out["call"], "K3PP")
equals("with what they sent", (out["serial_rx"], out["exchange_rx"]),
       ("44", "CHES"))
equals("and what we sent", (out["serial_tx"], out["exchange_tx"]),
       ("58", "CENT"))

equals("the callsign is cleared", f.value("call"), "")
equals("and what they sent", f.value("serial_rx"), "")
equals("and their exchange", f.value("exchange_rx"), "")
equals("our exchange stays", f.value("exchange_tx"), "CENT")
equals("the comment stays", f.value("comment"), "5W to a wire")
equals("the frequency stays", f.value("freq"), "3.820")
equals("and focus returns to the callsign", f.current.name, "call")

f.focus("comment"); f.kill()
f.focus("call"); f.type("W1AW")
out2 = f.commit()
equals("clearing a sticky field is how it is turned off", out2["comment"], "")
equals("and it stays cleared", f.value("comment"), "")

print("\nthe serial comes from the log, and advances")
recs = [{"activity": "PAQP", "serial_tx": "55"},
        {"activity": "PAQP", "serial_tx": "56"},
        {"activity": "FD", "serial_tx": "9"}]
f = logform.LogForm(CONTEST)
equals("one past the highest for this activity",
       f.advance_serial(recs), 57)
equals("and it is on the form", f.value("serial_tx"), "57")
recs.append({"activity": "PAQP", "serial_tx": "57"})
equals("after a contact it advances again", f.advance_serial(recs), 58)
equals("an activity that sends none gets none",
       logform.LogForm(activities.GENERAL).advance_serial(recs), 0)
equals("a fresh event starts at the configured number",
       logform.LogForm(CONTEST).advance_serial([], start=100), 100)

print("\nready to log")
f = logform.LogForm(activities.GENERAL)
check("a blank form is not", not f.ready())
f.type("   ")
check("and neither is whitespace", not f.ready())
f.kill(); f.type("W1AW")
check("a callsign is enough", f.ready())

print("\nrendering")
f = logform.LogForm(CONTEST)
f.from_radio(freq="3.820", mode="SSB")
f.set("exchange_tx", "CENT")
f.advance_serial(recs)
f.type("K3PP")

rows = render.form_rows(f, 66)
flat = "\n".join(render.plain(r) for r in rows)
for want in ("Call", "K3PP", "County", "My exch", "CENT", "3.820"):
    check(f"{want} is on the form", want in flat, flat)
check("the focused field carries a block cursor", "█" in flat, flat)
check("a set sticky field is marked", "*" in flat, flat)

for w in (50, 66, 80, 100):
    rows = render.form_rows(f, w)
    over = [render.plain(r) for r in rows if len(render.plain(r)) > w]
    check(f"{w}: nothing overflows", not over, str(over[:2]))

print("\nthe whole screen")
RECS = [{"when": "2026-10-11T18:31:00Z", "call": "W3ABC", "rst_s": "59",
         "rst_r": "59", "serial_tx": "55", "serial_rx": "101",
         "exchange_rx": "MONT"}]
for w, h in ((50, 12), (66, 20), (80, 24), (100, 30)):
    lines = render.log_screen(RECS, "", w, h, form=f,
                              header={"activity": "PAQP", "count": 1})
    equals(f"{w}x{h}: exactly {h} rows", len(lines), h)
    bad = [i for i, l in enumerate(lines) if len(render.plain(l)) != w]
    check(f"{w}x{h}: every row is {w} wide", not bad, str(bad[:4]))
    flat = "\n".join(render.plain(l) for l in lines)
    check(f"{w}x{h}: the form is on it", "K3PP" in flat, flat[:200])
    check(f"{w}x{h}: so is the contact already logged", "W3ABC" in flat,
          flat[:200])
    check(f"{w}x{h}: and the footer says how to move", "Tab" in flat,
          flat[-120:])

# With no form the old single-line entry is still drawn, which is what
# tools/qso.py and the tests predating the form use.
old = render.log_screen(RECS, "W3ABC 59 57", 66, 20)
check("the one-line entry still works without a form",
      "W3ABC 59 57" in "\n".join(render.plain(l) for l in old))

print("\na looked-up value lands where the cursor can reach it")
# Found on the deck 2026-10-11 with a name pulled from HamQTH: the operator
# was sitting in the Name field when the answer arrived, so the value appeared
# under a cursor still at 0, and Backspace returned early on `cursor <= 0`.
# The name could not be deleted.
f = logform.LogForm(activities.GENERAL)
f.from_radio(freq="14.285", mode="SSB")
f.focus("call")
f.type("W3ABC")
f.focus("name")
equals("the empty field puts the cursor at 0", f.cursor, 0)
f.set("name", "Ryan")
equals("a value written into the focused field moves the cursor after it",
       f.cursor, 4)
f.backspace()
equals("so Backspace deletes, as it must", f.value("name"), "Rya")

# A write into a field that is NOT focused must not move the cursor.
f.focus("call")
f.cursor = 2
f.set("qth", "Erie, PA")
equals("a write elsewhere leaves the cursor alone", f.cursor, 2)

print("\nthe callbook details belong to the callsign that fetched them")
# The second fault from the same session: after backspacing the callsign and
# typing another, the new lookup arrived and the first station's name stayed
# on the form, because the merge only filled fields that were EMPTY.
f = logform.LogForm(activities.GENERAL)
f.set("name", "Ryan")
f.set("qth", "Boalsburg, PA")
check("a callbook name is dropped when the callsign changes",
      f.forget_lookup())
equals("the name is gone", f.value("name"), "")
equals("and the QTH with it", f.value("qth"), "")

# What the operator typed is a correction and outranks any callbook.
f = logform.LogForm(activities.GENERAL)
f.focus("name")
f.type("Ryan")
f.focus("qth")
f.set("qth", "Boalsburg, PA")
equals("a typed name survives", (f.forget_lookup(), f.value("name"))[1], "Ryan")
equals("while the looked-up QTH goes", f.value("qth"), "")
check("and it reports having nothing left to drop",
      not f.forget_lookup())

check("every lookup field is a real field name",
      all(n in activities.ENTRY_FIELDS for n in logform.LOOKUP),
      str(logform.LOOKUP))

print("\nCtrl-X throws away the staged contact and keeps the session")
act = activities.get("POTA", activities.load())
f = logform.LogForm(act)
f.from_radio(freq="14.285", mode="SSB")
f.set("my_park", "US-5678")
f.set("comment", "5W to a wire")
f.focus("call")
f.type("W3ABC")
f.focus("name")
f.type("Ryan")
check("there is something to clear", f.clear())
equals("the callsign is gone", f.value("call"), "")
equals("and the name with it", f.value("name"), "")
# The reports are prefilled from the MODE, not from the station worked, so
# clearing must not cost the operator the 59 that was already there.
equals("the report is back to the mode default", f.value("rst_s"), "59")
equals("this station's reference stays — it is the session, not the contact",
       f.value("my_park"), "US-5678")
equals("so does the comment", f.value("comment"), "5W to a wire")
equals("and the frequency", f.value("freq"), "14.285")
equals("focus returns to the callsign", f.current.name, "call")
check("a second clear reports nothing to do", not f.clear())

print("\nevery selectable field has help and an ADIF home")
import qsolog as _q
_mapped = {k for k, _a in _q._ADIF_FIELDS}
for name in activities.ENTRY_FIELDS:
    check(f"{name}: described for the selection screen",
          bool(activities.FIELD_HELP.get(name)), name)
    # `park` is written as POTA_REF/SIG/SIG_INFO rather than through the
    # table, because one typed reference becomes three ADIF fields.
    if name != "park":
        check(f"{name}: survives an export", name in _mapped, name)

print("\nthe row keys reach every field on a page")
# The keys address a row on the CURRENT page, not a position in the whole
# list, so the invariant is one key per row of a page -- not one per field.
# The list outgrew both the screen and the keys; pretending otherwise is how
# a row only the arrows can reach gets shipped, and a row most operators
# never find is a row that may as well not be selectable.
import render as _render
check("there are more fields than digits",
      len(activities.ENTRY_FIELDS) > 9, str(len(activities.ENTRY_FIELDS)))
check("and more fields than fit on one page",
      len(activities.ENTRY_FIELDS) > _render.FIELDS_PER_PAGE,
      f"{len(activities.ENTRY_FIELDS)} in {_render.FIELDS_PER_PAGE}")
check("a key for every row of a page",
      all(activities.pick_key(i)
          for i in range(_render.FIELDS_PER_PAGE)),
      str(_render.FIELDS_PER_PAGE))
keys = [activities.pick_key(i) for i in range(_render.FIELDS_PER_PAGE)]
equals("no key is used twice", len(set(keys)), len(keys))
for i, k in enumerate(keys):
    equals(f"{k!r} selects row {i}", activities.pick_index(ord(k)), i)
equals("an upper-case letter works too",
       activities.pick_index(ord("A")), activities.pick_index(ord("a")))
equals("and an unbound key selects nothing",
       activities.pick_index(ord("/")), -1)

print("\nthe callsign is upper case however it is typed")
# Caps Lock and the Shift key should not be able to produce a lower-case
# callsign, and the operator should not have to look at the field to find out
# which they got. A callsign is upper case everywhere it is ever written.
f = logform.LogForm(activities.get("POTA", activities.load()))
f.focus("call")
f.type("kd3cco")
equals("typed lower, held upper", f.value("call"), "KD3CCO")
f.focus("park")
f.type("us-1234")
equals("and so is a reference", f.value("park"), "US-1234")
f.set("my_park", "us-5678")
equals("set programmatically too", f.value("my_park"), "US-5678")
f.focus("name")
f.type("Ryan")
equals("a name is left exactly as typed", f.value("name"), "Ryan")
# A Maidenhead locator is conventionally mixed case, so upper-casing it would
# be wrong rather than tidy.
check("grid is not an upper-case field", "grid" not in logform.UPPER,
      str(logform.UPPER))

print("\nthe frequency field holds the radio's full resolution")
f = logform.LogForm(activities.GENERAL)
f.from_radio(freq="7.185.000", mode="SSB")
equals("as the radio reads it", f.value("freq"), "7.185.000")
equals("and parses back to hertz", qsolog.parse_freq(f.value("freq")), 7185000)
# An operator correcting it by hand types megahertz, which still has to work.
f.focus("freq")
f.kill()
f.type("14.0706")
equals("a hand-typed megahertz value is read as megahertz",
       qsolog.parse_freq(f.value("freq")), 14070600)

sys.exit(report())
