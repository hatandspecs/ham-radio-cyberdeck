"""Continuing a session keeps its spots on screen -- panel report 2026-11-24.

What the operator saw: an existing WSPR session continued, and the spot
section of the WSPR screen empty, with the header still counting everything
the session had heard.

`_wspr_resume` was not the fault. It calls `_wspr_load_spots` and fills the
list correctly; the screen is right at that moment. **`_wspr_start` then
cleared it**, with a bare `self.wspr_spots = []` that was correct for a new
session and wrong for a continued one. Resuming and then starting, which is
what "continue this session" means, lost the history between the two steps.

That is the same disagreement `_wspr_load_spots` was written to fix one step
earlier: the counts come from the log and the list did not, so a screen
reporting thousands heard drew nothing. Hence the rule these checks pin:
**anything that resets the spot list reloads it from the log rather than
emptying it**, because the log is where the counts beside it come from.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report

import cyberdeck
import wsprlog


def write_log(path, rows):
    """rows: [(session, start, call)]"""
    with open(path, "w") as fh:
        for i, (sess, start, call) in enumerate(rows):
            fh.write(
                f"kind=rx when=2026-11-20T0{i % 10}:1{i % 10}:00Z "
                f"activity={sess} activity_start={start} band=20m "
                f"my_call=KD3CCO my_grid=FN10cs call={call} grid=FN31pr "
                f"dbm=37 snr=-12\n")
    return path


class Clock:
    """The slot scheduler, reduced to what `_wspr_start` touches."""

    def __init__(self):
        self.wspr = False
        self.started = None

    def start(self, now):
        self.wspr = True
        self.started = now


def deck(log_path, session="", start=""):
    d = cyberdeck.Deck.__new__(cyberdeck.Deck)
    d.cfg = {"LOCATOR": "FN10cs", "CALLSIGN": "KD3CCO",
             "WSPR_LOG_PATH": log_path,
             "WSPR_SESSION": session, "WSPR_SESSION_START": start}
    d.wspr_spots = []
    d.wspr_sel = None
    d.wspr_dbfs = None
    d.wspr_band = "20m"
    d._wspr_loaded = False
    d.notes = []
    d._wspr_note = d.notes.append
    d._save_state = lambda: None
    d._wspr_counts_stale = lambda: None
    return d


class Gain:
    def apply(self, level):
        return ""

    def silence_agc(self):
        return ""


def arm(d, clock, bands=("20m",)):
    """Stub out everything `_wspr_start` touches except the spot list.

    The real method is then called, rather than a copy of its tail. A copy
    would pass whatever it was written to do, which is the trap this file
    exists to avoid: the fault was one line in the real function.
    """
    d.wspr = clock
    d.wspr_gain = Gain()
    d._wspr_build = lambda: None
    d._wspr_bands = lambda: list(bands)
    d._wspr_ensure_session = lambda: None
    d._wspr_take_audio = lambda: True
    d._wspr_preflight_dial = lambda: None
    d._wspr_preflight_modes = lambda: None
    return d


def start_run(d):
    d._wspr_start()


LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "_wspr_resume_spots.log")
write_log(LOG, [
    ("fieldday", "2026-11-20T01:00:00Z", "W1AW"),
    ("fieldday", "2026-11-20T01:00:00Z", "K2ABC"),
    ("fieldday", "2026-11-20T01:00:00Z", "N3XYZ"),
    ("tonight", "2026-11-24T02:00:00Z", "W4DEF"),
])

try:
    print("resuming a session shows its spots")
    d = deck(LOG)
    d._wspr_resume("fieldday", "2026-11-20T01:00:00Z")
    equals("all three are on the list", len(d.wspr_spots), 3)
    check("and the operator is told the count",
          "3 spot" in d.notes[-1], d.notes[-1])

    print("\nand STARTING the run does not throw them away")
    # The reported fault. Resume then start is what "continue this session"
    # means, and the second step emptied what the first step loaded.
    clock = Clock()
    arm(d, clock)
    start_run(d)
    equals("still three after start", len(d.wspr_spots), 3)
    check("the clock did start", clock.wspr, clock.wspr)

    print("\nonly this session's spots, not the whole log")
    equals("the other session is not mixed in",
           sorted(s["call"] for s in d.wspr_spots),
           ["K2ABC", "N3XYZ", "W1AW"])

    print("\na genuinely new session starts empty, as clearing used to")
    d2 = deck(LOG, session="brand-new", start="2026-11-25T00:00:00Z")
    clock2 = Clock()
    arm(d2, clock2)
    start_run(d2)
    equals("no records yet, so no spots", len(d2.wspr_spots), 0)

    print("\nstarting a DIFFERENT session does not inherit the last one")
    # The case the bare clear got right and which the reload must not break.
    d3 = deck(LOG)
    d3._wspr_resume("fieldday", "2026-11-20T01:00:00Z")
    equals("fieldday loaded", len(d3.wspr_spots), 3)
    d3.cfg["WSPR_SESSION"] = "tonight"
    d3.cfg["WSPR_SESSION_START"] = "2026-11-24T02:00:00Z"
    clock3 = Clock()
    arm(d3, clock3)
    start_run(d3)
    equals("now only tonight's one spot", len(d3.wspr_spots), 1)
    equals("and it is the right one", d3.wspr_spots[0]["call"], "W4DEF")

    print("\nthe selection is released, because the list changed under it")
    d4 = deck(LOG)
    d4._wspr_resume("fieldday", "2026-11-20T01:00:00Z")
    d4.wspr_sel = 2
    clock4 = Clock()
    arm(d4, clock4)
    start_run(d4)
    equals("selection cleared", d4.wspr_sel, None)

    print("\n_wspr_start reloads rather than clearing")
    # Pinned against the source, because the whole fault was one line that
    # looked harmless and the next tidy-up could put it back.
    import inspect
    src = inspect.getsource(cyberdeck.Deck._wspr_start)
    check("it calls _wspr_load_spots", "_wspr_load_spots()" in src, src[-300:])
    check("and does not empty the list outright",
          "self.wspr_spots = []" not in src,
          "a bare clear here loses a continued session's history")
    after = src.index("self.wspr.start(")
    check("the reload comes after the clock starts",
          src.index("_wspr_load_spots()") > after,
          "order matters only for the note that follows")

    print("\na missing log leaves an empty list rather than raising")
    d5 = deck(os.path.join(os.path.dirname(LOG), "_no_such_wspr.log"))
    clock5 = Clock()
    arm(d5, clock5)
    start_run(d5)
    equals("empty, not an exception", d5.wspr_spots, [])
finally:
    for p in (LOG,):
        try:
            os.unlink(p)
        except OSError:
            pass

sys.exit(report())
