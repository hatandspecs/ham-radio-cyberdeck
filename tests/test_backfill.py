"""Filling in what the callbook knows and the log does not.

Two things that turned out to be one. The callbook has always answered with
a grid; `logform.LOOKUP` has always asked for it. But the answer was written
only into the FORM, and the general schema has no grid field -- so
`form.field("grid")` was None, the grid went nowhere, and every contact
logged under that schema reached the file without one. The contact map then
had nothing to plot. Found on the deck 2026-10-23.

The fix is in two halves, and both are here:

**Going forward**, a looked-up field the schema cannot show is kept aside and
written onto the record at commit. The record format has carried `grid` all
along and exports it as `GRIDSQUARE`; only the route was missing.

**Backwards**, the logger's danger zone looks up every callsign in the log
that has no grid and fills them in. It is on that menu because it rewrites
the whole file in one pass, not because it destroys anything -- it is the
only line there that does not.
"""
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import cyberdeck
import logform
import menus
import qsolog


def logfile(rows):
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "qso.adi")
    for call, grid in rows:
        rec = {"call": call, "band": "20m", "mode": "SSB",
               "when": "2026-10-22T12:00:00Z", "my_call": "KD3CCO"}
        if grid:
            rec["grid"] = grid
        qsolog.append(path, rec)
    return path


class FakeCallbook:
    """`Background`'s two methods. `take` returning {} means "nothing known"."""

    def __init__(self, answers):
        self.answers = answers
        self.asked = []

    def start(self, call):
        self.asked.append(call)

    def take(self, call):
        return self.answers.get(call, {})


def deck(path, answers, online=True):
    d = cyberdeck.Deck.__new__(cyberdeck.Deck)
    d.cfg = {}
    d.log_records = qsolog.read(path)
    d._log_path = lambda: path
    d.notes = []
    d._log_note = d.notes.append
    d._online = lambda: online
    d._close_menu = lambda: None
    d._callbook = FakeCallbook(answers)
    d._map_cache = d._map_points_cache = d._canvas_cache = None
    d.confirm = None
    d.screen = cyberdeck.LOG
    return d


print("the callbook is asked for a grid, and always has been")
equals("grid is one of the looked-up fields", "grid" in logform.LOOKUP, True)

print("\nthe general schema has no grid field, which is how it was lost")
import activities
form = logform.LogForm(activities.get("general", activities.load()))
equals("there is nowhere on the form to put it", form.field("grid"), None)
check("so a lookup answer has to be carried past the form",
      "grid" not in [f.name for f in form.fields],
      [f.name for f in form.fields])

print("\nwhich callsigns are missing something, one entry each")
# Per CALLSIGN, not per contact: four QSOs with one station are one lookup,
# and the answer fills all four. ANY missing field counts, not all of them
# -- a contact with a name and no grid still has something worth fetching.
recs = [{"call": "K2ABC", "grid": "EM12", "name": "Al", "qth": "Erie"},
        {"call": "W1XYZ"}, {"call": "W1XYZ"},
        {"call": "N3QE", "grid": "FM19"}, {"call": ""}]
missing = qsolog.missing_fields(recs)
equals("the complete one is left out", sorted(missing), ["N3QE", "W1XYZ"])
equals("and it counts the contacts behind each", missing["W1XYZ"], 2)
check("a contact with a grid but no name is still listed",
      "N3QE" in missing, missing)
check("and a record with no callsign is skipped", "" not in missing, missing)
equals("asked about one field only, it answers about that one",
       sorted(qsolog.missing_fields(recs, ("grid",))), ["W1XYZ"])

print("\nfilling writes only where there is a gap")
path = logfile([("K2ABC", "EM12"), ("W1XYZ", ""), ("W1XYZ", ""),
                ("N3QE", "")])
changed, filled = qsolog.fill_missing(
    path, {"W1XYZ": {"grid": "FN42", "name": "Pat"},
           "N3QE": {"grid": "FM19"},
           "K2ABC": {"grid": "ZZ99", "name": "Should not appear"}})
got = {r["call"]: r for r in qsolog.read(path)}
equals("four contacts changed", changed, 4)
equals("six fields filled", filled, 6)
equals("both contacts of one callsign got the answer",
       [r.get("grid") for r in qsolog.read(path) if r["call"] == "W1XYZ"],
       ["FN42", "FN42"])
equals("and the name came with it", got["W1XYZ"].get("name"), "Pat")
equals("a grid already in the log is not overwritten",
       got["K2ABC"].get("grid"), "EM12")
check("though a gap beside it is filled — this is per FIELD, not per record",
      got["K2ABC"].get("name") == "Should not appear", got["K2ABC"])

print("\nnothing to fill rewrites nothing")
path = logfile([("K2ABC", "EM12")])
before = open(path, "rb").read()
equals("no change reported", qsolog.fill_missing(path, {}), (0, 0))
equals("and the file is byte-identical", open(path, "rb").read(), before)

print("\nthe deck queues one lookup per callsign and writes once at the end")
path = logfile([("K2ABC", "EM12"), ("W1XYZ", ""), ("W1XYZ", ""),
                ("N3QE", ""), ("VE3QQQ", "")])
d = deck(path, {"W1XYZ": {"grid": "FN42"}, "N3QE": {"grid": "FM19"},
                "VE3QQQ": {}})
equals("four callsigns are missing something",
       sorted(d._backfill_missing()),
       ["K2ABC", "N3QE", "VE3QQQ", "W1XYZ"])
d._start_backfill()
equals("each is asked once", sorted(d._callbook.asked),
       ["K2ABC", "N3QE", "VE3QQQ", "W1XYZ"])
d._poll_backfill()
got = qsolog.read(path)
equals("the answers landed",
       [r.get("grid", "") for r in got],
       ["EM12", "FN42", "FN42", "FM19", ""])
check("and it says what it did",
       any("filled" in n for n in d.notes), d.notes)
check("the station nobody knows is still missing",
      "VE3QQQ" in d._backfill_missing(), d._backfill_missing())

print("\na run where nothing is known writes nothing and says so")
path = logfile([("W1XYZ", "")])
d = deck(path, {"W1XYZ": {}})
d._start_backfill()
d._poll_backfill()
check("it reports finding nothing",
      any("knew nothing" in n for n in d.notes), d.notes)
equals("and the contact is untouched", qsolog.read(path)[0].get("grid", ""),
       "")

print("\nit waits for every answer before writing")
path = logfile([("W1XYZ", ""), ("N3QE", "")])
d = deck(path, {"W1XYZ": {"grid": "FN42"}})
# `take` returning None means still running; this callbook answers for one
# and leaves the other pending.
d._callbook.take = lambda call: ({"grid": "FN42"} if call == "W1XYZ"
                                 else None)
d._start_backfill()
d._poll_backfill()
equals("nothing written while one is outstanding",
       [r.get("grid", "") for r in qsolog.read(path)], ["", ""])
check("and the job is still open", d._backfill is not None)

print("\nit refuses without a network, and when there is nothing to do")
d = deck(logfile([("W1XYZ", "")]), {}, online=False)
d._ask_backfill()
check("no network says so", any("network" in n for n in d.notes), d.notes)
equals("and asks nothing", d.confirm, None)

complete = logfile([("K2ABC", "EM12")])
recs = qsolog.read(complete)
recs[0].update({"name": "Al", "qth": "Erie"})
qsolog._rewrite(complete, recs)
d = deck(complete, {})
d._ask_backfill()
check("nothing missing says so",
      any("already has" in n for n in d.notes), d.notes)
equals("and asks nothing", d.confirm, None)

print("\nwith work to do it asks first, and says what it will not touch")
d = deck(logfile([("W1XYZ", ""), ("N3QE", "")]), {})
d._ask_backfill()
check("it raises a confirmation", d.confirm is not None)
body = " ".join(d.confirm["lines"])
check("naming the callsigns", "2 callsigns" in body, body)
check("and saying it fills gaps only", "fills gaps" in body, body)
check("and that nothing already logged changes",
      "Nothing already in" in body, body)

print("\nthe danger zone offers it, and says why when it cannot")
items = dict((k, v) for k, v in
             menus.danger_menu("Park", 412, 12, 3, missing=7,
                               online=True)["items"])
check("the line is there", "f" in items, sorted(items))
check("with the count", "7 contacts" in items["f"], items["f"])
offline = dict((k, v) for k, v in
               menus.danger_menu("Park", 412, 12, 3, missing=7,
                                 online=False)["items"])
check("and offline it says what is missing",
      "needs a network" in offline["f"], offline["f"])
none = dict((k, v) for k, v in
            menus.danger_menu("Park", 412, 12, 3, missing=0,
                              online=True)["items"])
check("with nothing to do it says that instead",
      "nothing missing" in none["f"], none["f"])

print("\nit is the one line on that menu that destroys nothing")
labels = [v for _k, v in menus.danger_menu("Park", 412, 12, 3, missing=7,
                                           online=True)["items"]]
check("the others say delete or forget",
      sum(1 for l in labels if "Delete" in l or "Forget" in l) == 3, labels)
check("and this one says fill",
      any(l.startswith("Fill in") for l in labels), labels)

sys.exit(report())
