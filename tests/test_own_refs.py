"""This station's own program references — selected, sticky, and exported.

The own-side references used to be one welded pair: `my_park` appeared on the
form whenever `park` did, and could not appear without it. That made two
schemas impossible. A **hunting** schema carried an own-reference field it
never filled and was asked at the start of every activity which park this
station was in — a question a hunter has no answer to. An **activating**
schema could not have an own reference at all without also carrying a
their-park column that stayed blank all day.

SOTA, WWFF and IOTA had it worse: their side of each was selectable and
exported correctly, and there was no own side at all, so an activation of a
summit had nowhere to record the summit.

So each program's own reference is now a field in its own right. What this
file checks:

**Each is selectable alone, and sticky.** One activation is one reference;
`^U` on the field is how that is turned off.

**Each exports to its own program's ADIF field.** POTA is the one that needs
the generic `SIG`/`MY_SIG` pair alongside the dedicated `POTA_REF` — the
others have dedicated fields on both sides and must not go through `SIG`.
Writing `MY_SIG=SOTA` beside `MY_POTA_REF` is what routing a summit through
the park field would have produced.

**A site in two programs at once works.** A park that is also a WWFF
reference is ordinary, and both own-side fields go on one schema.

**Naming an activity no longer forces a schema decision**, but still asks for
the reference an activating schema wants.
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
import menus
import qsolog

BASE = {"call": "W3ABC", "when": "2026-10-23T14:02:00Z", "band": "20m",
        "mode": "SSB", "freq": "14285000", "rst_s": "59", "rst_r": "57",
        "my_call": "KD3CCO"}


def adif(**extra):
    """The ADIF tags for one record, as a dict of name -> value."""
    rec = dict(BASE)
    rec.update(extra)
    out = {}
    for tag in qsolog.adif_record(rec).split("<"):
        tag = tag.strip()
        if not tag or tag == "EOR>":
            continue
        head, _, value = tag.partition(">")
        name = head.split(":")[0]
        out[name] = value.strip()
    return out


print("each program's own reference exports to that program's field")

equals("a summit activation writes MY_SOTA_REF",
       adif(my_sota="W3/PD-001").get("MY_SOTA_REF"), "W3/PD-001")
equals("a WWFF activation writes MY_WWFF_REF",
       adif(my_wwff="KFF-1234").get("MY_WWFF_REF"), "KFF-1234")
equals("an island activation writes MY_IOTA",
       adif(my_iota="NA-123").get("MY_IOTA"), "NA-123")

# The failure this prevents: a summit routed through the park field would be
# announced as POTA and written into MY_POTA_REF.
for ref, field in (("my_sota", "MY_SOTA_REF"), ("my_wwff", "MY_WWFF_REF"),
                   ("my_iota", "MY_IOTA")):
    tags = adif(**{ref: "X-001"})
    check(f"{ref}: and says nothing about POTA",
          "MY_SIG" not in tags and "MY_POTA_REF" not in tags, str(tags))
    check(f"{ref}: nor claims a program on the other station's behalf",
          "SIG" not in tags, str(tags))


print("\nPOTA keeps both spellings, on both sides")

p2p = adif(park="US-1234", my_park="US-5474")
equals("their park, generic", p2p.get("SIG_INFO"), "US-1234")
equals("their park, dedicated", p2p.get("POTA_REF"), "US-1234")
equals("and the program is named", p2p.get("SIG"), "POTA")
equals("this station's park, generic", p2p.get("MY_SIG_INFO"), "US-5474")
equals("this station's park, dedicated", p2p.get("MY_POTA_REF"), "US-5474")
equals("and named on this side too", p2p.get("MY_SIG"), "POTA")

# A hunt is the same record with no own side. Nothing MY_ may appear, or
# every hunted contact claims an activation that did not happen.
hunt = adif(park="US-1234")
check("a hunt writes no MY_ reference",
      not any(k.startswith("MY_SIG") or k == "MY_POTA_REF" for k in hunt),
      str(hunt))


print("\na site in two programs at once")

both = adif(my_park="US-5474", my_wwff="KFF-1234")
equals("the park goes in the POTA field", both.get("MY_POTA_REF"), "US-5474")
equals("the WWFF ref goes in the WWFF field",
       both.get("MY_WWFF_REF"), "KFF-1234")
check("neither displaces the other",
      both.get("MY_SIG") == "POTA" and "MY_WWFF_REF" in both, str(both))


print("\nthe stored line carries them through a write and a read")

tmp = os.path.join(tempfile.mkdtemp(), "qso.log")
rec = dict(BASE)
rec.update({"my_park": "US-5474", "my_sota": "W3/PD-001",
            "my_wwff": "KFF-1234", "my_iota": "NA-123"})
qsolog.append(tmp, rec)
back = qsolog.read(tmp)
equals("one contact read back", len(back), 1)
for key in logform.OWN_REFS:
    equals(f"{key} survives the round trip", back[0].get(key), rec[key])


print("\nthe reference question is asked of the own-side field, not theirs")

TABLE = dict(activities.BUILTIN)
TABLE["HUNT"] = activities.ActivityType(
    "HUNT", label="Park hunting", entry=("rst_s", "rst_r", "park", "name"))
TABLE["ACTIVATE"] = activities.ActivityType(
    "ACTIVATE", label="Activating", entry=("rst_s", "rst_r", "my_park"))

# `needs_reference` resolves a schema name through `activities.load()` -- the
# operator's own `activities.conf` -- rather than through the table the deck
# is holding, so the schemas invented here have to be on that path.
activities.load = lambda path=None: TABLE

check("an activating schema is asked for this station's reference",
      menus.needs_reference("ACTIVATE"))
check("a hunting schema is not",
      not menus.needs_reference("HUNT"))
check("POTA is, because it carries both sides",
      menus.needs_reference("POTA"))
check("and general logging is not",
      not menus.needs_reference("GENERAL"))


print("\nnaming an activity no longer opens the schema picker")


def deck(schema="ACTIVATE"):
    d = cyberdeck.Deck.__new__(cyberdeck.Deck)
    d.cfg = {"CALLSIGN": "KD3CCO", "ACTIVITY": "", "ACTIVITY_START": "",
             "ACTIVITY_TYPE": schema, "MY_PARK": "US-0001",
             "EXCHANGE_TX": "", "FORGOTTEN_SESSIONS": []}
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
    d._save_state = lambda: None
    d._activity_table = lambda: TABLE
    d._log_note = lambda text: setattr(d, "log_message", text)
    d.log_form = logform.LogForm(activities.get(schema, TABLE))
    d.opened = []
    d._open_menu = lambda which: d.opened.append(which)
    d.asked = []
    d._open_editor = lambda key, label, sink=None: d.asked.append(key)
    return d


d = deck("ACTIVATE")
d._start_named_activity("Bald Eagle SP")
equals("the activity is named", d.cfg["ACTIVITY"], "Bald Eagle SP")
equals("no menu was opened", d.opened, [])
# The picker was where the own reference used to be asked for. Losing it
# without replacing the question left an activation logged with no reference.
equals("but the reference is still asked for", d.asked, ["MY_PARK"])
equals("and last week's is cleared first", d.cfg["MY_PARK"], "")

d = deck("HUNT")
d.log_form = logform.LogForm(TABLE["HUNT"])
d._start_named_activity("Saturday hunting")
equals("a hunting schema opens no menu", d.opened, [])
equals("and is asked nothing", d.asked, [])

d = deck("ACTIVATE")
d._start_named_activity("")
equals("going back to the master log asks nothing", d.asked, [])
equals("and opens nothing", d.opened, [])


sys.exit(report())
