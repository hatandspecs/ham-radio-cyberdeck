"""Beaconing — docs/wspr_design.md §6. Nothing here keys a radio.

The rig, the player and the clock are all injected, so a 110-second
transmission tests in milliseconds.

**The first six blocks are about PTT, not about WSPR.** This is the module
that keys a transmitter, and the failure that matters is a radio left keyed.
Everything else in the file is secondary to proving that every path out of a
transmission drops PTT.
"""
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import wspr
import wsprtx


class FakeRig:
    """A radio that records keying, and can be told to misbehave."""

    def __init__(self, accepts=True, reads=True):
        self.accepts = accepts        # does set_ptt report success
        self.reads = reads            # what ptt() says: True/False/None
        self.history = []

    def set_ptt(self, on):
        self.history.append(bool(on))
        return self.accepts

    def ptt(self):
        return self.reads

    @property
    def keyed(self):
        return bool(self.history) and self.history[-1]


class FakeProc:
    def __init__(self, code=0, err="", finish_after=0):
        self._code, self._left = code, finish_after
        self.killed = False

        class R:
            def __init__(self, t):
                self.t = t

            def read(self):
                return self.t
        self.stderr = R(err)

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


def spawner(procs):
    out = {"cmds": []}

    def spawn(cmd, **kw):
        out["cmds"].append(cmd)
        return procs.pop(0) if procs else FakeProc()
    out["spawn"] = spawn
    return out


def tx(tmp, rig, procs=None, clock=None):
    sp = spawner(procs if procs is not None else [FakeProc()])
    t = wsprtx.Transmitter(tmp, rig=rig, spawn=sp["spawn"],
                           now=(lambda: clock[0]) if clock else None)
    return t, sp


def a_wav(tmp, name="x.wav"):
    return wsprtx.write_wav(os.path.join(tmp, name),
                            wsprtx.tone_samples(seconds=0.05))


print("a completed transmission unkeys")
with tempfile.TemporaryDirectory() as tmp:
    rig = FakeRig()
    t, sp = tx(tmp, rig)
    equals("it starts", t.send(a_wav(tmp)), "")
    check("the radio is keyed", rig.keyed, str(rig.history))
    equals("state", t.state, wsprtx.SENDING)
    events = t.tick()
    equals("it completed", [e[0] for e in events], ["sent"])
    check("and the radio is UNKEYED", not rig.keyed, str(rig.history))
    equals("keyed then unkeyed, once each", rig.history, [True, False])
    equals("counted", t.sent, 1)
    equals("and it is idle", t.state, wsprtx.IDLE)

print("\na FAILED transmission unkeys")
with tempfile.TemporaryDirectory() as tmp:
    rig = FakeRig()
    t, sp = tx(tmp, rig, [FakeProc(code=1, err="aplay: device busy")])
    t.send(a_wav(tmp))
    events = t.tick()
    equals("reported as failed", [e[0] for e in events], ["failed"])
    check("and the radio is UNKEYED", not rig.keyed, str(rig.history))
    check("with aplay's reason kept", "busy" in t.last_error, t.last_error)

print("\na transmission that will not stop is cut off, and unkeys")
with tempfile.TemporaryDirectory() as tmp:
    rig = FakeRig()
    clock = [0.0]
    proc = FakeProc(finish_after=10_000)
    t, sp = tx(tmp, rig, [proc], clock)
    t.send(a_wav(tmp))
    equals("nothing while it is inside its deadline", t.tick(), [])
    check("still keyed", rig.keyed, str(rig.history))
    clock[0] = wsprtx.TX_TIMEOUT_S + 1
    events = t.tick()
    equals("then it gives up", [e[0] for e in events], ["failed"])
    check("having killed the player", proc.killed, "")
    check("and UNKEYED the radio", not rig.keyed, str(rig.history))

print("\nstop unkeys from the middle of a transmission")
# This is the path Ctrl-C, leaving WSPR, and the time-out timer all take.
with tempfile.TemporaryDirectory() as tmp:
    rig = FakeRig()
    proc = FakeProc(finish_after=10_000)
    t, sp = tx(tmp, rig, [proc])
    t.send(a_wav(tmp))
    check("keyed", rig.keyed, str(rig.history))
    t.stop()
    check("the player was killed", proc.killed, "")
    check("and the radio is UNKEYED", not rig.keyed, str(rig.history))
    equals("idle", t.state, wsprtx.IDLE)
    t.stop()
    check("stopping twice is harmless", not rig.keyed, str(rig.history))

print("\na player that cannot be started unkeys again")
# The case that would otherwise leave the radio keyed with nothing on it.
with tempfile.TemporaryDirectory() as tmp:
    rig = FakeRig()

    def boom(cmd, **kw):
        raise OSError("aplay: command not found")
    t = wsprtx.Transmitter(tmp, rig=rig, spawn=boom)
    why = t.send(a_wav(tmp))
    check("it reports the reason", "not found" in why, why)
    check("and the radio is UNKEYED", not rig.keyed, str(rig.history))
    equals("keyed, then unkeyed again", rig.history, [True, False])

print("\na radio that does not key is not transmitted into")
# set_ptt returning True means the command was SENT. A Yaesu answers with
# silence, so the state is read back -- and a radio reporting receive after
# being told to transmit is a radio that did not key.
with tempfile.TemporaryDirectory() as tmp:
    rig = FakeRig(accepts=True, reads=False)
    t, sp = tx(tmp, rig)
    why = t.send(a_wav(tmp))
    check("it refuses", why != "", why)
    check("saying the radio did not key", "did not key" in why, why)
    equals("nothing was played", len(sp["cmds"]), 0)
    check("and it unkeyed anyway, in case the command arrived late",
          not rig.keyed, str(rig.history))

print("\na PTT command that fails stops it before anything is played")
with tempfile.TemporaryDirectory() as tmp:
    rig = FakeRig(accepts=False)
    t, sp = tx(tmp, rig)
    why = t.send(a_wav(tmp))
    check("it refuses", "PTT" in why, why)
    equals("nothing was played", len(sp["cmds"]), 0)

print("\nan unreadable PTT state proceeds, but says so")
# None means the state could not be read. Refusing would take transmit away
# from a radio whose readback is simply unsupported, which is a worse failure
# than the one being prevented.
with tempfile.TemporaryDirectory() as tmp:
    rig = FakeRig(accepts=True, reads=None)
    t, sp = tx(tmp, rig)
    equals("it proceeds", t.send(a_wav(tmp)), "")
    check("but records that it could not confirm",
          "could not be read" in t.last_error, t.last_error)

print("\nno rig at all is a refusal, not a crash")
with tempfile.TemporaryDirectory() as tmp:
    t = wsprtx.Transmitter(tmp, rig=None, spawn=spawner([])["spawn"])
    equals("it refuses", t.send(a_wav(tmp)), "no rig")

print("\nonly one transmission at a time")
with tempfile.TemporaryDirectory() as tmp:
    rig = FakeRig()
    t, sp = tx(tmp, rig, [FakeProc(finish_after=99), FakeProc()])
    t.send(a_wav(tmp))
    equals("the second is refused", t.send(a_wav(tmp, "y.wav")),
           "already transmitting")
    equals("and only one player was spawned", len(sp["cmds"]), 1)

print("\nnothing to send is a refusal")
with tempfile.TemporaryDirectory() as tmp:
    rig = FakeRig()
    t, sp = tx(tmp, rig)
    equals("a missing file", t.send(os.path.join(tmp, "nope.wav")),
           "nothing to send")
    check("the radio was never keyed", not rig.history, str(rig.history))


# -- the audio ----------------------------------------------------------

print("\nthe beacon audio is rendered once and cached")
# A WSPR message does not change within a session, and rendering costs about
# two seconds on a Pi. Rendering per beacon would spend that every slot.
with tempfile.TemporaryDirectory() as tmp:
    t = wsprtx.Transmitter(tmp, rig=FakeRig())
    first = t.beacon_wav("KD3CCO", "FN10", 37)
    check("it wrote a file", os.path.exists(first), first)
    mtime = os.path.getmtime(first)
    again = t.beacon_wav("KD3CCO", "FN10", 37)
    equals("the same path", again, first)
    equals("and it was not rewritten", os.path.getmtime(again), mtime)
    # The power is the one of the three an operator changes mid-session.
    t.beacon_wav("KD3CCO", "FN10", 40)
    check("a power change re-renders", os.path.getmtime(first) != mtime,
          "the cache must not beacon the old wattage")
    t.forget_cache()
    check("and the cache can be dropped", t._cache_key is None, "")

print("\nthe beacon is 111.6 seconds: one second of lead, then the signal")
with tempfile.TemporaryDirectory() as tmp:
    import wave
    t = wsprtx.Transmitter(tmp, rig=FakeRig())
    with wave.open(t.beacon_wav("KD3CCO", "FN10", 37)) as w:
        secs = w.getnframes() / w.getframerate()
        equals("12 kHz mono", (w.getframerate(), w.getnchannels()),
               (12000, 1))
    check("one second of lead before 110.6 of signal",
          abs(secs - (1.0 + 110.6)) < 0.1, f"{secs:.2f} s")

print("\nthe test tone is time-bounded by construction")
with tempfile.TemporaryDirectory() as tmp:
    rig = FakeRig()
    t, sp = tx(tmp, rig)
    equals("it starts", t.test_tone(seconds=2.0), "")
    equals("as a test, not a beacon", t.state, wsprtx.TESTING)
    check("keyed", rig.keyed, str(rig.history))
    events = t.tick()
    equals("and it completes", [e[0] for e in events], ["sent"])
    equals("reporting which kind it was", events[0][1], wsprtx.TESTING)
    check("unkeyed", not rig.keyed, str(rig.history))
    import wave
    with wave.open(os.path.join(tmp, "tone.wav")) as w:
        equals("two seconds of tone",
               round(w.getnframes() / w.getframerate()), 2)
check("the default is short enough to not outlive attention",
      wsprtx.TEST_TONE_S <= 30, f"{wsprtx.TEST_TONE_S} s")

print("\nthe deadline is inside the slot")
check("a transmission cannot run into the next slot",
      wsprtx.TX_TIMEOUT_S < 120, f"{wsprtx.TX_TIMEOUT_S} s")
check("but is longer than the signal",
      wsprtx.TX_TIMEOUT_S > wsprtx.TX_SECONDS,
      f"{wsprtx.TX_TIMEOUT_S} vs {wsprtx.TX_SECONDS}")

print("\nthe player command is the one that matches the capture device")
equals("aplay, quiet, on the same codec",
       wsprtx.aplay_command("/tmp/b.wav"),
       ["aplay", "-D", "plughw:1,0", "-q", "/tmp/b.wav"])

print("\nthe transmit level scales the audio, and only WSPR's audio")
# The deck measured close to 10 W with the radio set to 5 W and the ALC
# half-scale, so this is the control that was missing. It is a digital
# amplitude and NOT the playback mixer, because fldigi shares that one and
# turning WSPR down there turns the digimodes down with it.
import struct
import wave

def peak_of(path):
    with wave.open(path) as w:
        frames = w.readframes(w.getnframes())
    vals = struct.unpack(f"<{len(frames) // 2}h", frames)
    return max(abs(v) for v in vals)

with tempfile.TemporaryDirectory() as tmp:
    tx = wsprtx.Transmitter(tmp, rig=None, spawn=lambda c, **k: FakeProc())
    equals("the default level is the one config ships", tx.level,
           wsprtx.DEFAULT_LEVEL)
    tx.level = 50
    loud = peak_of(tx.beacon_wav("KD3CCO", "FN10", 37))
    tx.level = 25
    quiet = peak_of(tx.beacon_wav("KD3CCO", "FN10", 37))
    check("half the level is half the amplitude",
          0.45 < quiet / float(loud) < 0.55, f"{quiet} vs {loud}")
    tx.level = 100
    full = peak_of(tx.beacon_wav("KD3CCO", "FN10", 37))
    check("100% stays inside 16-bit full scale", full <= 32767, str(full))

    print("\na level change invalidates the rendered audio")
    # Otherwise the next beacon goes out at the old amplitude and the
    # operator watches a power meter that does not move.
    tx.level = 50
    first = tx.beacon_wav("KD3CCO", "FN10", 37)
    again = tx.beacon_wav("KD3CCO", "FN10", 37)
    equals("the same level re-uses the render", first, again)
    before = peak_of(first)
    tx.level = 20
    after = peak_of(tx.beacon_wav("KD3CCO", "FN10", 37))
    check("a changed level re-renders", after < before, f"{after} {before}")

    print("\nthe level is clamped, and never to silence")
    tx.level = 0
    equals("zero becomes the floor", tx.level, wsprtx.MIN_LEVEL)
    tx.level = 500
    equals("and anything over full scale is full scale", tx.level, 100)
    tx.level = "not a number"
    equals("nonsense falls back to the default", tx.level,
           wsprtx.DEFAULT_LEVEL)

    print("\nthe test tone is sent at the beacon's level")
    # A tone at a level the beacon will not use sets the drive for a
    # transmission that never happens.
    tx.level = 30
    tx.test_tone(seconds=0.2)
    tone = peak_of(os.path.join(tmp, "tone.wav"))
    tx.stop()
    beacon = peak_of(tx.beacon_wav("KD3CCO", "FN10", 37))
    check("the tone and the beacon are within a few percent",
          abs(tone - beacon) / float(beacon) < 0.25,
          f"tone={tone} beacon={beacon}")

report()
