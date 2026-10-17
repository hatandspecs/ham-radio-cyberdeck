"""Capture and decode, without a sound card, `wsprd`, or a radio.

`spawn=` is the seam: a fake process stands in for `arecord` and `wsprd`, so
every case below runs in milliseconds — including the ones that take two
minutes in reality.

**The property this file exists to hold is that nothing blocks.** The deck
draws five times a second; `arecord` runs for 114 s and `wsprd` for up to
34 s on a Pi. Both are polled, and a `tick()` that waited for either would
freeze the panel for the length of a WSPR slot.
"""
import datetime
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import wsprrx

WHEN = datetime.datetime(2026, 10, 17, 2, 8, tzinfo=datetime.timezone.utc)
DIAL = 7_038_600
# Real output from the deck's own wsprd 2.7.0, 40 m, 2026-10-17.
REAL = ("0208 -25  0.7   7.040053  0  WW0WWV DN70 30 \n"
        "0208 -26  0.2   7.040115  0  KC0MVF EN13 30 \n"
        "<DecodeFinished>\n")


class FakeProc:
    """A subprocess that finishes when told to."""

    def __init__(self, out="", err="", code=0, finish_after=0):
        self._out, self._err, self._code = out, err, code
        self._left = finish_after
        self.killed = False

        class R:
            def __init__(self, text):
                self.text = text

            def read(self):
                return self.text
        self.stdout, self.stderr = R(out), R(err)

    @property
    def returncode(self):
        return self._code if self._left <= 0 else None

    def poll(self):
        if self._left > 0:
            self._left -= 1
            return None
        return self._code

    def kill(self):
        self.killed = True
        self._left = 0


class Spawner:
    """Hands out prepared processes and records the commands."""

    def __init__(self, procs):
        self.procs = list(procs)
        self.cmds = []

    def __call__(self, cmd, **kw):
        self.cmds.append(cmd)
        return self.procs.pop(0) if self.procs else FakeProc()


def wav(path, size=4096):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"\0" * size)
    return path


print("the commands are the ones that worked on the deck")
equals("the capture filename carries the slot",
       wsprrx.capture_filename(WHEN), "261017_0208.wav")
cmd = wsprrx.arecord_command("/tmp/x.wav", "plughw:1,0")
equals("12 kHz mono 16-bit for 114 s", cmd,
       ["arecord", "-D", "plughw:1,0", "-f", "S16_LE", "-r", "12000",
        "-c", "1", "-d", "114", "/tmp/x.wav"])
dec = wsprrx.wsprd_command("/tmp/x.wav", DIAL, "/tmp/rx")
check("the dial goes in as megahertz", "7.038600" in dec, str(dec))
check("-a points at the deck's own directory", "/tmp/rx" in dec, str(dec))
check("and deep search is on by default", "-d" in dec, str(dec))
equals("which can be turned off",
       "-d" in wsprrx.wsprd_command("/tmp/x.wav", DIAL, "/tmp/rx",
                                    deep=False), False)

print("\na capture that is still running produces no event")
with tempfile.TemporaryDirectory() as tmp:
    # finish_after=3: three ticks report nothing, which is what a 114-second
    # arecord looks like to a loop running five times a second.
    sp = Spawner([FakeProc(finish_after=3)])
    r = wsprrx.Receiver(tmp, spawn=sp)
    path = r.start_capture(WHEN, "40 m", DIAL)
    check("it started", path.endswith("261017_0208.wav"), path)
    equals("state is capturing", r.state, wsprrx.CAPTURING)
    for i in range(3):
        equals(f"tick {i + 1} reports nothing", r.tick(), [])
    wav(path)
    events = r.tick()
    equals("then the window is reported", [e[0] for e in events], ["captured"])
    equals("with its band", events[0][2], "40 m")
    equals("and the receiver is idle again", r.state, wsprrx.IDLE)
    equals("counted", r.captured, 1)

print("\na second capture is refused rather than replacing the first")
# Two arecords on one exclusive codec is the second one failing, and a
# capture that silently replaced the one in progress would lose a window.
with tempfile.TemporaryDirectory() as tmp:
    sp = Spawner([FakeProc(finish_after=9), FakeProc(finish_after=9)])
    r = wsprrx.Receiver(tmp, spawn=sp)
    first = r.start_capture(WHEN, "40 m", DIAL)
    equals("the second returns nothing", r.start_capture(WHEN, "30 m", DIAL),
           "")
    equals("and only one process was spawned", len(sp.cmds), 1)
    check("the first is still the one running", first != "", first)

print("\na decode yields deduplicated spots")
with tempfile.TemporaryDirectory() as tmp:
    sp = Spawner([FakeProc(out=REAL)])
    r = wsprrx.Receiver(tmp, spawn=sp)
    check("it started", r.start_decode(wav(f"{tmp}/w.wav"), "40 m", DIAL), "")
    equals("state is decoding", r.state, wsprrx.DECODING)
    events = r.tick()
    equals("spots came out", [e[0] for e in events], ["spots"])
    spots = events[0][1]
    equals("two stations", len(spots), 2)
    equals("the calls", [s["call"] for s in spots], ["WW0WWV", "KC0MVF"])
    equals("with the band they were heard on", events[0][2], "40 m")
    equals("counted", r.decoded, 1)

print("\ncapture and decode run at the same time and do not block each other")
# A decode routinely outlives its slot. The next window must still start on
# time -- that is the whole reason these are independent.
with tempfile.TemporaryDirectory() as tmp:
    sp = Spawner([FakeProc(out=REAL, finish_after=5),   # the decode, slow
                  FakeProc(finish_after=1)])            # the next capture
    r = wsprrx.Receiver(tmp, spawn=sp)
    r.start_decode(wav(f"{tmp}/old.wav"), "40 m", DIAL)
    check("a decode is running", r.busy_decoding, "")
    nxt = r.start_capture(WHEN, "30 m", DIAL)
    check("and the next capture still started", nxt != "", nxt)
    equals("both processes exist", len(sp.cmds), 2)
    wav(nxt)
    r.tick()
    events = r.tick()
    kinds = [e[0] for e in events]
    check("the capture finished first, independently",
          "captured" in kinds or r.captured == 1, str(kinds))

print("\nno end marker means the decoder died, not that nothing was heard")
# wsprd prints the marker whether or not anything decoded, so its absence
# means the run never finished. Treating the two alike would record an empty
# window for a decoder that was killed.
with tempfile.TemporaryDirectory() as tmp:
    sp = Spawner([FakeProc(out="0208 -25  0.7   7.040053  0  WW0WWV DN70 30")])
    r = wsprrx.Receiver(tmp, spawn=sp)
    r.start_decode(wav(f"{tmp}/w.wav"), "40 m", DIAL)
    events = r.tick()
    equals("it is reported as a failure", [e[0] for e in events], ["failed"])
    equals("naming the decode", events[0][1], "decode")
    check("and not as an empty window", r.decoded == 0, str(r.decoded))
    check("the reason is kept for the screen",
          "end marker" in r.last_error, r.last_error)

print("\nan empty window is not a failure")
with tempfile.TemporaryDirectory() as tmp:
    sp = Spawner([FakeProc(out="<DecodeFinished>\n")])
    r = wsprrx.Receiver(tmp, spawn=sp)
    r.start_decode(wav(f"{tmp}/w.wav"), "40 m", DIAL)
    events = r.tick()
    equals("spots, of which there are none", [e[0] for e in events], ["spots"])
    equals("no spots", events[0][1], [])
    equals("and it counts as a decode", r.decoded, 1)
    equals("with no failure", r.failed, 0)

print("\na capture that wrote nothing is caught")
with tempfile.TemporaryDirectory() as tmp:
    sp = Spawner([FakeProc()])
    r = wsprrx.Receiver(tmp, spawn=sp)
    r.start_capture(WHEN, "40 m", DIAL)      # no file created
    events = r.tick()
    equals("reported as a failure", [e[0] for e in events], ["failed"])
    equals("naming the capture", events[0][1], "capture")

print("\nso is a capture that exited badly")
with tempfile.TemporaryDirectory() as tmp:
    sp = Spawner([FakeProc(err="arecord: main:850: audio open error: "
                               "Device or resource busy", code=1)])
    r = wsprrx.Receiver(tmp, spawn=sp)
    r.start_capture(WHEN, "40 m", DIAL)
    events = r.tick()
    equals("reported as a failure", [e[0] for e in events], ["failed"])
    # The exact message the deck produces when fldigi still holds the codec.
    check("carrying the reason arecord gave",
          "busy" in r.last_error, r.last_error)

print("\na wedged decoder is killed rather than left to accumulate")
with tempfile.TemporaryDirectory() as tmp:
    proc = FakeProc(out=REAL, finish_after=10_000)
    clock = [0.0]
    r = wsprrx.Receiver(tmp, spawn=Spawner([proc]), now=lambda: clock[0])
    r.start_decode(wav(f"{tmp}/w.wav"), "40 m", DIAL)
    equals("nothing at first", r.tick(), [])
    clock[0] = wsprrx.DECODE_TIMEOUT_S + 1
    events = r.tick()
    equals("then it gives up", [e[0] for e in events], ["failed"])
    check("having killed the process", proc.killed, "")
    equals("and is idle for the next slot", r.state, wsprrx.IDLE)

print("\nspawning that raises is a failure, not a crash")
def boom(cmd, **kw):
    raise OSError("arecord: command not found")
with tempfile.TemporaryDirectory() as tmp:
    r = wsprrx.Receiver(tmp, spawn=boom)
    equals("the capture does not start", r.start_capture(WHEN, "40 m", DIAL),
           "")
    equals("the decode does not either",
           r.start_decode("/tmp/w.wav", "40 m", DIAL), False)
    equals("both counted", r.failed, 2)
    check("and the reason is kept", "not found" in r.last_error,
          r.last_error)

print("\nstop kills both and never raises")
with tempfile.TemporaryDirectory() as tmp:
    cap, dec = FakeProc(finish_after=99), FakeProc(finish_after=99)
    r = wsprrx.Receiver(tmp, spawn=Spawner([cap, dec]))
    r.start_capture(WHEN, "40 m", DIAL)
    r.start_decode(wav(f"{tmp}/w.wav"), "40 m", DIAL)
    r.stop()
    check("the capture was killed", cap.killed, "")
    check("the decode was killed", dec.killed, "")
    equals("and it is idle", r.state, wsprrx.IDLE)
    r.stop()
    check("stopping twice is harmless", True, "")

print("\nthe calibration probe never costs a window")
# The codec takes one client. A one-second probe straddling the slot
# boundary would make the window's `arecord` fail "Device or resource busy",
# which trades a decode for a meter reading.
with tempfile.TemporaryDirectory() as tmp:
    sp = Spawner([FakeProc(finish_after=9), FakeProc(finish_after=9)])
    r = wsprrx.Receiver(tmp, spawn=sp)
    probe = r.start_probe()
    check("a probe starts", probe.endswith("probe.wav"), probe)
    check("and is running", r.probing, "")
    got = r.start_capture(WHEN, "40 m", DIAL)
    check("a window starts anyway", bool(got), got)
    check("and the probe was killed to make room", not r.probing, "")
    check("the window is what is recording", r.busy_capturing, "")

print("\nand a probe refuses while a window is recording")
with tempfile.TemporaryDirectory() as tmp:
    sp = Spawner([FakeProc(finish_after=9)])
    r = wsprrx.Receiver(tmp, spawn=sp)
    r.start_capture(WHEN, "40 m", DIAL)
    equals("the probe is refused", r.start_probe(), "")
    check("the window is untouched", r.busy_capturing, "")
    equals("and nothing extra was spawned", len(sp.cmds), 1)

print("\na probe's level is read off the file it wrote")
with tempfile.TemporaryDirectory() as tmp:
    # finish_after=1, so the FIRST poll reports it still running. With a
    # process that had already exited, "nothing while it runs" passed
    # because the probe had completed AND failed -- the file was not
    # written yet -- which is a pass for the opposite reason.
    sp = Spawner([FakeProc(finish_after=1)])
    r = wsprrx.Receiver(tmp, spawn=sp)
    path = r.start_probe()
    equals("nothing while it runs", r.probe_done(), "")
    check("and it is still accounted for", r.probing, "")
    wav(path)
    equals("then the path, once", r.probe_done(), path)
    equals("and not twice", r.probe_done(), "")
    check("the probe is finished with", not r.probing, "")
    check("the command is a one-second capture",
          "-d" in sp.cmds[0] and sp.cmds[0][sp.cmds[0].index("-d") + 1] == "1",
          str(sp.cmds[0]))

report()
