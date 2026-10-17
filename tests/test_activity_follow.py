"""What follows an activity, and what does not — docs/qso_log_design.md §7i.

The pure half: renaming a session, and `sessions_in` reporting the schema and
reference to resume under. The deck half, in `test_activity_paths.py`, drives
the keys.

`sessions_in` is the piece the resume depends on, and the thing it has to get
right is **which** contact it answers from. A session can hold contacts logged
under more than one schema — §7g makes that possible — and resuming it has to
use the latest, because that is the operator's most recent decision about how
the session is read. Reporting the FIRST one, which it used to, would resume a
session under a schema the operator had already moved away from.
"""
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import qsolog

BEGAN = "2026-10-15T13:00:00Z"


def log_with(lines):
    """A temporary log holding `lines`. Returns its path."""
    tmp = tempfile.mkdtemp(prefix="cyberdeck-follow-")
    path = os.path.join(tmp, "qso.log")
    with open(path, "w") as fh:
        fh.write("".join(l if l.endswith("\n") else l + "\n" for l in lines))
    return path


def rec(when, call, **kw):
    parts = [f"when={when}", f"call={call}"]
    for k, v in kw.items():
        parts.append(f'{k}="{v}"' if " " in str(v) else f"{k}={v}")
    return " ".join(parts)


print("the schema reported is the LATEST contact's, not the first")
# POTA first, then the operator switched to general logging and worked two
# more. `make_record` writes no `activity_type` for GENERAL, so the newest
# contact carries none -- and "" is what the deck resolves to GENERAL.
path = log_with([
    rec("2026-10-15T14:00:00Z", "W3ABC", activity_start=BEGAN,
        activity="Bald Eagle SP", activity_type="POTA", my_park="US-5678"),
    rec("2026-10-15T14:05:00Z", "K3XYZ", activity_start=BEGAN,
        activity="Bald Eagle SP", my_park="US-5678"),
])
ses = qsolog.sessions_in(qsolog.read(path))
equals("one session", len(ses), 1)
equals("and its schema is the newest contact's", ses[0]["type"], "")
equals("with the reference it carried", ses[0]["park"], "US-5678")

print("\nand the other way round, so this is not just 'the last field wins'")
path = log_with([
    rec("2026-10-15T14:00:00Z", "W3ABC", activity_start=BEGAN,
        activity="PAQP", my_park=""),
    rec("2026-10-15T14:05:00Z", "K3XYZ", activity_start=BEGAN,
        activity="PAQP", activity_type="CONTEST"),
])
ses = qsolog.sessions_in(qsolog.read(path))
equals("the newest contact's schema is reported", ses[0]["type"], "CONTEST")

print("\nfile order does not decide it; the timestamp does")
# Written newest-first, which a hand-edited log can be.
path = log_with([
    rec("2026-10-15T14:05:00Z", "K3XYZ", activity_start=BEGAN,
        activity="PAQP", activity_type="CONTEST"),
    rec("2026-10-15T14:00:00Z", "W3ABC", activity_start=BEGAN,
        activity="PAQP", activity_type="POTA"),
])
ses = qsolog.sessions_in(qsolog.read(path))
equals("still the latest by time", ses[0]["type"], "CONTEST")

print("\nrenaming a session relabels its contacts and nothing else")
path = log_with([
    rec("2026-10-15T14:00:00Z", "W3ABC", activity_start=BEGAN,
        activity="Bald Eagle SP", activity_type="POTA"),
    rec("2026-10-15T14:05:00Z", "K3XYZ", activity_start=BEGAN,
        activity="Bald Eagle SP", activity_type="POTA"),
    # A second session of the SAME name, a different day. Renaming one must
    # not touch the other, which is the whole reason a session is
    # (name, start) and not a name.
    rec("2026-10-16T14:00:00Z", "N3QRP",
        activity_start="2026-10-16T13:00:00Z",
        activity="Bald Eagle SP", activity_type="POTA"),
    rec("2026-10-15T09:00:00Z", "W1AW"),
])
moved = qsolog.rename_session(path, "Bald Eagle SP", BEGAN,
                              "Black Moshannon SP")
equals("both contacts of that session moved", moved, 2)
left = qsolog.read(path)
equals("the log is the same length", len(left), 4)
names = sorted({str(r.get("activity", "")) for r in left})
equals("and holds both names plus the unlabeled one", names,
       ["", "Bald Eagle SP", "Black Moshannon SP"])
check("the other session of that name is untouched",
      any(r.get("activity") == "Bald Eagle SP" for r in left), str(names))
check("the unlabeled contact is untouched",
      any(r.get("call") == "W1AW" and not r.get("activity") for r in left),
      str(left))
check("every renamed contact kept its session start",
      all(r.get("activity_start") == BEGAN for r in left
          if r.get("activity") == "Black Moshannon SP"), str(left))
check("and its schema", all(r.get("activity_type") == "POTA" for r in left
                            if r.get("activity") == "Black Moshannon SP"),
      str(left))

print("\nthe renamed session is one session, under the new name")
ses = {s["name"]: s for s in qsolog.sessions_in(left)}
equals("two sessions in all", len(ses), 2)
equals("the renamed one has both contacts",
       ses["Black Moshannon SP"]["contacts"], 2)
equals("and the same start it had", ses["Black Moshannon SP"]["start"], BEGAN)

print("\na rename that cannot mean anything changes nothing")
before = qsolog.read(path)
equals("no name", qsolog.rename_session(path, "Black Moshannon SP", BEGAN,
                                        "   "), 0)
equals("punctuation only", qsolog.rename_session(path, "Black Moshannon SP",
                                                 BEGAN, "..."), 0)
equals("a session that is not there",
       qsolog.rename_session(path, "Nowhere", BEGAN, "Somewhere"), 0)
equals("and the log is byte-for-byte what it was",
       qsolog.read(path), before)

print("\nrenaming to the name it already has is not a rewrite")
equals("nothing moved", qsolog.rename_session(path, "Black Moshannon SP",
                                              BEGAN, "Black Moshannon SP"), 0)

print("\na session whose contacts carry no start is matched by name alone")
# Hand-written over SSH, or logged before sessions existed. `for_session`
# treats an empty start as "every contact of that name", so a rename has to
# reach them.
path = log_with([rec("2026-10-14T14:00:00Z", "W3ABC", activity="Old Park")])
equals("it renames", qsolog.rename_session(path, "Old Park", "", "New Park"),
       1)
equals("and the contact carries the new name",
       qsolog.read(path)[0].get("activity"), "New Park")

sys.exit(report())
