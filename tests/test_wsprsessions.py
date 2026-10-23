"""WSPR sessions — the list, and the four things it does with one.

A WSPR session and a logger activity are the same idea, so they get the same
keys: `Enter` resumes, `n` starts one, `r` renames, `d` forgets, `Esc` backs
out. It is simpler by exactly one thing -- a session has no schema, because
every spot carries the same fields.

Two faults this exists to hold down, both found on the panel:

**`F2` opened the name editor**, which can only START a session, so there was
no way back into an earlier one. The deck came up on `general`, reported
`heard 5992` in its own header, and drew an empty spot list underneath --
because `wspr_spots` only ever held what the current RUN had decoded.

**Sessions were told apart by date alone.** Three runs named `general` on two
days were indistinguishable. A WSPR session is evidence about propagation and
propagation is a function of time of day, so the hour is data rather than a
tiebreaker.
"""
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import curses

import cyberdeck
import render
import session as session_mod
import wsprlog

SIZES = ((66, 20), (50, 15), (80, 24), (40, 12))
OLD = "2026-10-22T18:04:00Z"
MID = "2026-10-23T06:30:00Z"
NEW = "2026-10-23T19:12:00Z"


def text(lines):
    return "\n".join("".join(t for t, _k in ln) for ln in lines)


def rows(*starts):
    return [{"name": "general", "start": s, "heard": 10, "sent": 1,
             "bands": ["40 m"]} for s in starts]


def logfile(entries):
    """`entries` is [(name, start, how many spots), ...]."""
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "wspr.log")
    for name, start, count in entries:
        for i in range(count):
            wsprlog.append(path, {
                "kind": "rx", "call": f"K{i}ABC", "grid": "FN67",
                "band": "40 m", "when": start, "activity": name,
                "activity_start": start, "snr": -20})
    return path


def deck(path, name="general", start=OLD, forgotten=()):
    d = cyberdeck.Deck.__new__(cyberdeck.Deck)
    d.cfg = {"WSPR_LOG_PATH": path, "LOCATOR": "FN10",
             "WSPR_SESSION": name, "WSPR_SESSION_START": start,
             "WSPR_FORGOTTEN": [list(p) for p in forgotten]}
    d.wspr = None
    d.wspr_spots = []
    d._wspr_loaded = False
    d.wspr_sel = None
    d.screen = cyberdeck.WSPR
    d.session = session_mod.Session(callsign="KD3CCO")
    d.notes = []
    d._wspr_note = d.notes.append
    d._save_state = lambda: None
    d._wspr_counts_stale = lambda: None
    d._close_menu = lambda: None
    d.confirm = None
    d._ask_confirm = lambda *a, **k: setattr(d, "confirm", (a, k))
    return d


print("the list is two rows of chrome and one per session, at any size")
for w, h in SIZES:
    lines = render.wspr_sessions_screen(rows(OLD, MID, NEW), 0, w, h)
    equals(f"{w}x{h}: exactly {h} rows", len(lines), h)
    equals(f"{w}x{h}: each exactly {w} wide",
           {sum(len(t) for t, _k in ln) for ln in lines}, {w})

print("\nsessions are told apart by the hour, not just the day")
# Three runs named `general`, two of them on one date. The date alone made
# two of these identical on screen.
body = text(render.wspr_sessions_screen(rows(OLD, MID, NEW), 0, 66, 20))
for start in (OLD, MID, NEW):
    stamp = start[:16].replace("T", " ")
    check(f"{stamp} is shown to the minute", stamp in body, body)
check("and the times are marked UTC", "UTC" in body, body)
check("which is what the log stores", "Z" in body, body)

print("\nthe session in use is marked, not hidden")
body = text(render.wspr_sessions_screen(rows(OLD, NEW), 1, 66, 20,
                                        current=("general", NEW)))
check("both are listed", body.count("general") == 2, body)
check("and one is marked", "*general" in body, body)

print("\nan empty list says what starts one")
body = text(render.wspr_sessions_screen([], 0, 66, 12))
check("it says there are none", "no sessions" in body, body)
check("and names the key", "n starts one" in body, body)

print("\nthe list is built from the log, newest first")
path = logfile([("general", OLD, 3), ("fieldday", MID, 2)])
d = deck(path)
got = d._wspr_session_rows()
equals("both sessions are there", sorted(r["name"] for r in got),
       ["fieldday", "general"])
equals("newest first", got[0]["name"], "fieldday")
equals("with their counts", {r["name"]: r["heard"] for r in got},
       {"general": 3, "fieldday": 2})

print("\na forgotten session is left off, and its spots are untouched")
# `WSPR_FORGOTTEN` is written by the danger zone and was read by nothing,
# so "forget all sessions" set a value that changed no screen.
d = deck(path, forgotten=[("general", OLD)])
equals("only the other one is listed",
       [r["name"] for r in d._wspr_session_rows()], ["fieldday"])
equals("and every record is still in the log", len(wsprlog.read(path)), 5)

print("\nopening the list puts the cursor on the session in use")
d = deck(path, name="general", start=OLD)
d._open_wspr_sessions()
equals("the screen opened", d.screen, cyberdeck.WSPRSES)
equals("on the one in use",
       (d.wspr_ses_rows[d.wspr_ses_sel]["name"],
        d.wspr_ses_rows[d.wspr_ses_sel]["start"]), ("general", OLD))

print("\nEnter resumes a session and fills the spot list from the log")
# `wspr_spots` held only what the current RUN had decoded, so a deck
# powered on into a session with a night behind it drew an empty list
# under a header reporting thousands heard.
d = deck(path, name="fieldday", start=MID)
d._open_wspr_sessions()
d.wspr_ses_sel = [i for i, r in enumerate(d.wspr_ses_rows)
                  if r["name"] == "general"][0]
d._handle_wspr_sessions(10)                       # Enter
equals("it returns to the WSPR screen", d.screen, cyberdeck.WSPR)
equals("the session changed", d.cfg["WSPR_SESSION"], "general")
equals("and its start came with it", d.cfg["WSPR_SESSION_START"], OLD)
equals("the spot list holds that session's spots", len(d.wspr_spots), 3)
check("and it says how many", any("3 spot" in n for n in d.notes), d.notes)

print("\nswitching is refused while WSPR runs")
# The rest of the night would be filed under a name chosen for a different
# run, and the spots decoded in the open slot would land in whichever
# session was current when it ended.
d = deck(path)
d.wspr = type("W", (), {"wspr": True})()
d.screen = cyberdeck.WSPR
d._open_wspr_sessions()
equals("the list does not open", d.screen, cyberdeck.WSPR)
check("and it says why", any("stop WSPR" in n for n in d.notes), d.notes)

print("\nrename relabels every record and keeps the start")
# The START is what gives a session its identity; only the name changes,
# so renaming back undoes it exactly.
path2 = logfile([("general", OLD, 3), ("fieldday", MID, 2)])
d = deck(path2, name="general", start=OLD)
d._open_wspr_sessions()
d._wspr_renaming = ("general", OLD)
d._wspr_rename_session("saturday night")
names = {r.get("activity") for r in wsprlog.read(path2)}
equals("the records carry the new name", names, {"saturday night",
                                                 "fieldday"})
starts = {r.get("activity_start") for r in wsprlog.read(path2)
          if r.get("activity") == "saturday night"}
equals("and the same start", starts, {OLD})
equals("the session in use followed its own rename",
       d.cfg["WSPR_SESSION"], "saturday night")

print("\nforget takes it off the list and destroys nothing")
d = deck(path2, name="fieldday", start=MID)
d._open_wspr_sessions()
before = len(wsprlog.read(path2))
d._wspr_forget_session("saturday night", OLD)
equals("it is off the list",
       [r["name"] for r in d._wspr_session_rows()], ["fieldday"])
equals("every record is still there", len(wsprlog.read(path2)), before)
check("and it says so", "still there" in d.wspr_ses_message,
      d.wspr_ses_message)

print("\nd asks before forgetting")
d = deck(path2, name="fieldday", start=MID)
d._open_wspr_sessions()
d._handle_wspr_sessions(ord("d"))
check("a confirmation is raised", d.confirm is not None)
lines = " ".join(d.confirm[0][1])
check("saying the spots stay in the log", "stay in" in lines, lines)
check("and naming the session to the minute",
      MID[:16].replace("T", " ") in lines, lines)

print("\nEsc backs out without changing anything")
d = deck(path2, name="fieldday", start=MID)
d._open_wspr_sessions()
d._handle_wspr_sessions(27)
equals("back on the WSPR screen", d.screen, cyberdeck.WSPR)
equals("the session is unchanged", d.cfg["WSPR_SESSION"], "fieldday")

sys.exit(report())
