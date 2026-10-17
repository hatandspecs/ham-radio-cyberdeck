"""Capturing a window and decoding it, without ever blocking the draw loop.

`wsprsched` decides WHEN a slot captures or beacons; this does the doing. It
owns two subprocesses — `arecord` and `wsprd` — and the rule they are held
to is the deck's oldest: **nothing on a draw path may block.** The main loop
draws five times a second, `arecord` runs for 114 seconds and `wsprd` for
somewhere between 9 and 34 on a Pi 3A+, so both are spawned and then
*polled*, exactly as the callbook lookup is.

**Capture and decode are independent.** There are about six seconds between
the end of one window and the start of the next, and a decode routinely
outlives that. A decode still running when the next slot opens must not delay
the capture: the next window starts on time and the decode finishes when it
finishes. So this holds one capture and one decode at a time and they are not
the same slot's.

`spawn=` is the seam. Every test in `tests/test_wsprrx.py` runs with no sound
card, no `wsprd` and no radio.
"""

import os
import subprocess
import time

import wspr

#: `wsprd` wants 12 kHz mono 16-bit, and `plughw` converts from whatever the
#: codec runs natively -- measured on the deck, so there is no resampling
#: here. See `docs/wspr_design.md` §2b.
DEFAULT_DEVICE = "plughw:1,0"

CAPTURE_SECONDS = 114

#: A decode that has not finished by this is abandoned. Generous: the deck
#: measured 33.7 s for a deep search over a four-signal window, and a slot is
#: 120 s. This exists so a wedged `wsprd` cannot accumulate forever, not to
#: cut short a decode that is working.
# How long a calibration probe records. Long enough for an RMS that is not
# dominated by one syllable of noise, short enough that the meter feels live.
PROBE_SECONDS = 1

DECODE_TIMEOUT_S = 110

IDLE = "idle"
CAPTURING = "capturing"
DECODING = "decoding"


def capture_filename(when):
    """`YYMMDD_HHMM.wav` for a UTC datetime.

    **The name is load-bearing**, not tidiness: `wsprd` reads the date and
    time out of it. Proven on the deck by renaming a file and watching the
    reported time follow — the same audio as `261017_0208.wav` is reported as
    `0208`, and as `991231_2358.wav` as `2358`.
    """
    return when.strftime("%y%m%d_%H%M") + ".wav"


def arecord_command(path, device=DEFAULT_DEVICE, seconds=CAPTURE_SECONDS):
    """The capture command. Separate so a test can assert on it."""
    return ["arecord", "-D", device, "-f", "S16_LE",
            "-r", str(wspr.SAMPLE_RATE), "-c", "1",
            "-d", str(int(seconds)), path]


def wsprd_command(path, dial_hz, workdir, deep=True):
    """The decode command.

    `-a` points at the deck's own run directory so `wsprd`'s five files --
    `ALL_WSPR.TXT`, `wspr_spots.txt`, `hashtable.txt`, `wspr_timer.out`,
    `wspr_wisdom.dat` -- do not land wherever the process happened to start.

    `-d` is on by default: the deck measured 33.7 s against a 120 s slot, so
    deep search is affordable, and the whole point of WSPR is the signals
    near the threshold.
    """
    cmd = ["wsprd", "-a", workdir, "-f", f"{int(dial_hz) / 1_000_000:.6f}"]
    if deep:
        cmd.append("-d")
    return cmd + [path]


class Receiver:
    """One capture and one decode, polled.

    Nothing here decides what time it is or which band to use. `tick` is
    called from the draw loop and returns events the caller acts on:

        ("captured", path, band)      a window finished and is on disk
        ("spots", [spot, ...], band)  a decode finished, deduplicated
        ("failed", what, why)         a subprocess did not work
    """

    def __init__(self, workdir, device=DEFAULT_DEVICE, spawn=None,
                 deep=True, now=None):
        self.workdir = workdir
        self.device = device
        self.deep = deep
        self._spawn = spawn or self._real_spawn
        self._now = now or time.monotonic
        self._capture = None          # (proc, path, band, started)
        self._probe = None            # (proc, path, started), calibration
        self._decode = None           # (proc, path, band, started)
        self.captured = 0
        self.decoded = 0
        self.failed = 0
        self.last_error = ""

    @staticmethod
    def _real_spawn(cmd, **kw):
        return subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, **kw)

    # -- state ------------------------------------------------------------

    @property
    def state(self):
        if self._capture is not None:
            return CAPTURING
        if self._decode is not None:
            return DECODING
        return IDLE

    @property
    def busy_capturing(self):
        """Whether a real window is recording. The probe must not start one
        on top of it: the codec takes one client."""
        return self._capture is not None

    @property
    def busy_decoding(self):
        """Whether a decode is still running. Shown, not enforced.

        A decode outliving its slot is normal and not an error -- what would
        be an error is letting it delay the next capture.
        """
        return self._decode is not None

    # -- doing ------------------------------------------------------------

    def start_capture(self, when, band, dial_hz, seconds=CAPTURE_SECONDS):
        """Begin a window. Returns its path, or "" if one is already running.

        Refuses rather than queues: two `arecord` processes on one exclusive
        codec is the second one failing, and a capture that silently replaced
        the one in progress would lose a window without saying so.
        """
        if self._capture is not None:
            return ""
        # **A probe is killed to make room; a window is never killed for a
        # probe.** The codec takes one client, so a one-second calibration
        # probe straddling the slot boundary would make this window's
        # `arecord` fail "Device or resource busy" -- trading a decode for a
        # meter reading. The reverse refusal is in `start_probe`.
        self.stop_probe()
        os.makedirs(self.workdir, exist_ok=True)
        path = os.path.join(self.workdir, capture_filename(when))
        cmd = arecord_command(path, self.device, seconds)
        try:
            proc = self._spawn(cmd)
        except Exception as exc:
            self.failed += 1
            self.last_error = f"arecord: {exc}"
            return ""
        self._capture = (proc, path, band, self._now())
        return path

    def start_probe(self, seconds=PROBE_SECONDS):
        """Capture a short sample for a level reading. Returns its path or "".

        For the calibration screen, which needs a figure every second or so
        rather than every two minutes. One file, overwritten: nothing keeps
        a probe and a timestamped name would leave a directory full of them.

        Refuses while a real window is running, for the same reason
        `start_capture` refuses a second one -- the codec is exclusive, and
        a probe that killed a session's window would trade a decode for a
        meter reading.
        """
        if self._capture is not None or self._probe is not None:
            return ""
        os.makedirs(self.workdir, exist_ok=True)
        path = os.path.join(self.workdir, "probe.wav")
        try:
            proc = self._spawn(arecord_command(path, self.device, seconds))
        except Exception as exc:
            self.last_error = f"arecord: {exc}"
            return ""
        self._probe = (proc, path, self._now())
        return path

    def probe_done(self):
        """The finished probe's path, or "" while it runs or if it failed.

        Polled, never waited on: this is called from the draw loop.
        """
        if self._probe is None:
            return ""
        proc, path, _started = self._probe
        if proc.poll() is None:
            return ""
        self._probe = None
        if proc.returncode != 0 or not os.path.exists(path):
            err = ""
            try:
                err = (proc.stderr.read() or "").strip().splitlines()[-1]
            except Exception:
                pass
            self.last_error = f"arecord: {err}" if err else "arecord failed"
            return ""
        return path

    @property
    def probing(self):
        return self._probe is not None

    def stop_probe(self):
        """Kill a running probe. For leaving the calibration screen."""
        if self._probe is None:
            return
        proc = self._probe[0]
        self._probe = None
        try:
            proc.kill()
        except Exception:
            pass

    def start_decode(self, path, band, dial_hz):
        """Begin a decode. Returns whether it started.

        One at a time. A second decode while one is running would double the
        CPU on a board that has one core's worth of headroom, and the window
        it would decode is already on disk — it can wait for the next tick.
        """
        if self._decode is not None:
            return False
        cmd = wsprd_command(path, dial_hz, self.workdir, self.deep)
        try:
            proc = self._spawn(cmd)
        except Exception as exc:
            self.failed += 1
            self.last_error = f"wsprd: {exc}"
            return False
        self._decode = (proc, path, band, self._now())
        return True

    def tick(self):
        """Collect whatever has finished. Returns a list of events.

        Never waits. A subprocess still running produces no event and is
        looked at again on the next call, which is a fifth of a second later.
        """
        events = []
        events.extend(self._tick_capture())
        events.extend(self._tick_decode())
        return events

    def _tick_capture(self):
        if self._capture is None:
            return []
        proc, path, band, started = self._capture
        if proc.poll() is None:
            return []
        self._capture = None
        if proc.returncode != 0:
            why = self._stderr_tail(proc) or f"exit {proc.returncode}"
            self.failed += 1
            self.last_error = f"arecord: {why}"
            return [("failed", "capture", why)]
        if not os.path.exists(path) or os.path.getsize(path) < 1024:
            self.failed += 1
            self.last_error = "arecord wrote nothing"
            return [("failed", "capture", "wrote nothing")]
        self.captured += 1
        return [("captured", path, band)]

    def _tick_decode(self):
        if self._decode is None:
            return []
        proc, path, band, started = self._decode
        if proc.poll() is None:
            if self._now() - started > DECODE_TIMEOUT_S:
                # A wedged decoder must not accumulate. Killed rather than
                # waited on, because the next slot is coming either way.
                try:
                    proc.kill()
                except Exception:
                    pass
                self._decode = None
                self.failed += 1
                self.last_error = "wsprd did not finish"
                return [("failed", "decode", "timed out")]
            return []
        self._decode = None
        out = ""
        try:
            out = proc.stdout.read() if proc.stdout else ""
        except Exception:
            out = ""
        # The end marker is how a finished run is told from a killed one.
        # `wsprd` prints it whether or not anything decoded, so its ABSENCE
        # means the run died -- and a caller that treated "no decodes" and
        # "no marker" alike would record an empty window for a decoder that
        # never ran.
        if not wspr.decode_complete(out):
            self.failed += 1
            self.last_error = "wsprd produced no end marker"
            return [("failed", "decode", "no end marker")]
        self.decoded += 1
        return [("spots", wspr.dedupe(wspr.parse_decodes(out)), band)]

    @staticmethod
    def _stderr_tail(proc):
        try:
            text = (proc.stderr.read() or "").strip() if proc.stderr else ""
        except Exception:
            return ""
        lines = [l for l in text.splitlines() if l.strip()]
        return lines[-1] if lines else ""

    def stop(self):
        """Kill both subprocesses. For leaving WSPR, and for shutdown.

        Both, and neither raises: this is called from the path that puts
        fldigi back, and a failure here must not stop that happening.
        """
        # The probe too: it holds the exclusive codec exactly as a window
        # does, and one left running would keep fldigi from reopening it.
        for holder in (self._capture, self._decode, self._probe):
            if holder is None:
                continue
            try:
                holder[0].kill()
            except Exception:
                pass
        self._capture = None
        self._decode = None
        self._probe = None
