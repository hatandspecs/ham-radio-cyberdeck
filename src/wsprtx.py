"""Beaconing: render the audio once, key the radio, play it, unkey.

Pure of clocks and radios in the sense that matters — the clock, the rig and
the subprocess runner are all injected, so a 110-second transmission tests in
milliseconds and no test keys anything.

**This module keys a transmitter.** Three properties come before every
feature in it, and each is tested:

  1. **It always unkeys.** Every path out of a transmission drops PTT,
     including a failed playback, an exception, and a caller that stops
     mid-over. A transmitter left keyed is the worst failure the deck has.
  2. **It is time-bounded.** A transmission that has not finished by its own
     deadline is cut off and the radio unkeyed, because a wedged `aplay` must
     not hold the air.
  3. **PTT is read back.** `set_ptt` returning True means the command was
     sent, not that the radio is keyed — a Yaesu set command answers with
     silence. So the state is confirmed rather than assumed, and a radio that
     did not key is reported instead of being transmitted into.

**The rendered audio is cached**, which is the one performance decision here.
A WSPR message is identical for every transmission of a session: the same
call, the same grid, the same power. Rendering costs about two seconds on a
Pi 3A+, so rendering per beacon would spend that in every slot for no
reason. The cache is keyed on what the message is made of and invalidates
itself when the power changes.
"""

import os
import subprocess
import time

import wspr

#: WSPR transmits from one second after the even minute for 110.6 s.
TX_OFFSET_S = 1.0
TX_SECONDS = 110.6

#: A transmission not finished by this is cut off. The signal is 110.6 s and
#: the slot is 120, so this leaves a margin and still ends before the next
#: slot opens. Nothing legitimate reaches it.
TX_TIMEOUT_S = 118.0

#: A test tone runs for this long unless stopped. Short deliberately: it
#: exists for setting audio drive against a power meter, and a tone that
#: outlives the operator's attention is a transmitter left keyed.
# Transmit amplitude as a percent of full digital scale. 50 is what the
# first build sent unconditionally; the deck measured close to 10 W with the
# radio set to 5 W and the ALC half-scale, so this is the control that was
# missing rather than a refinement. The floor is 1 and not 0 because a level
# of nothing is an unkeyed transmitter dressed up as a transmission.
# How long to let the PTT readback catch up before concluding the radio did
# not key. The FTX-1 does not report PTT the instant the command lands, and
# asking once answered False on a radio that was keyed.
# The calibration tone is longer than the menu's one-shot: the operator is
# adjusting a level under it and watching a meter settle, which ten seconds
# does not allow. Still bounded, for the same reason everything here is.
CAL_TONE_S = 40.0

PTT_CONFIRM_S = 0.6
PTT_POLL_S = 0.05

DEFAULT_LEVEL = 50
MIN_LEVEL = 1

TEST_TONE_S = 10.0

DEFAULT_DEVICE = "plughw:1,0"

IDLE = "idle"
SENDING = "sending"
TESTING = "testing"


def aplay_command(path, device=DEFAULT_DEVICE):
    """The playback command. Separate so a test can assert on it."""
    return ["aplay", "-D", device, "-q", path]


def write_wav(path, samples, rate=None):
    """Write mono 16-bit samples to `path`. Returns the path.

    `array` and one `tobytes`, not `struct.pack` per sample: the latter is
    most of what made an earlier benchmark look like the transmit path was
    slow when it was the harness.
    """
    import array
    import wave
    rate = rate or wspr.SAMPLE_RATE
    frames = array.array(
        "h", (int(max(-1.0, min(1.0, s)) * 32000) for s in samples))
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fh = wave.open(path, "w")
    try:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        fh.writeframes(frames.tobytes())
    finally:
        fh.close()
    return path


def tone_samples(hz=1500.0, seconds=TEST_TONE_S, amplitude=0.4,
                 rate=None):
    """A steady tone, for setting audio drive against the radio's meter.

    One tone and not the WSPR signal: the drive level is being set, and a
    constant amplitude is what a power meter can be read against. WSPR is
    constant envelope anyway, so a single tone represents it honestly.
    """
    import math
    rate = rate or wspr.SAMPLE_RATE
    step = 2.0 * math.pi * hz / rate
    return [amplitude * math.sin(step * i)
            for i in range(int(rate * seconds))]


class Transmitter:
    """One transmission at a time, keyed and unkeyed deliberately.

    `rig` needs `set_ptt(bool)` and `ptt()`. `spawn` runs the player. `now`
    is the clock. All three are injected; nothing here opens a device by
    itself.
    """

    def __init__(self, workdir, rig=None, device=DEFAULT_DEVICE, spawn=None,
                 now=None, level=DEFAULT_LEVEL):
        self.workdir = workdir
        self.rig = rig
        self.device = device
        # **Digital amplitude, WSPR's alone.** The alternative was the ALSA
        # playback mixer, which fldigi shares -- turning WSPR down that way
        # turns the digimodes down with it. Scaling the samples as they are
        # rendered cannot touch anything else, because nothing else plays
        # this file.
        self.level = level
        self._spawn = spawn or self._real_spawn
        self._now = now or time.monotonic
        self._proc = None
        self._started = 0.0
        self._kind = IDLE
        self._deadline = TX_TIMEOUT_S
        self._cache_key = None
        self._cache_path = ""
        self.sent = 0
        self.failed = 0
        self.last_error = ""

    @staticmethod
    def _real_spawn(cmd, **kw):
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, text=True, **kw)

    @property
    def state(self):
        return self._kind

    @property
    def keyed(self):
        """Whether a transmission is running as far as this object knows."""
        return self._proc is not None

    # -- the audio --------------------------------------------------------

    @property
    def level(self):
        """Transmit amplitude as a percent of full scale, 1 to 100."""
        return self._level

    @level.setter
    def level(self, pct):
        try:
            pct = int(round(float(pct)))
        except (TypeError, ValueError):
            pct = DEFAULT_LEVEL
        pct = max(MIN_LEVEL, min(100, pct))
        # A level change has to invalidate the rendered audio, or the next
        # beacon goes out at the old amplitude and the operator watches a
        # power meter that does not move.
        if getattr(self, "_level", None) != pct:
            self._level = pct
            self.forget_cache()

    @property
    def amplitude(self):
        """The level as the renderers want it: 0.0 to 1.0."""
        return self._level / 100.0

    def beacon_wav(self, call, grid, dbm, base_hz=None):
        """The rendered transmission, from cache when it can be.

        A WSPR message does not change within a session, so this renders
        once. Keyed on everything the audio depends on, so a power change —
        the one of the three an operator adjusts mid-session — invalidates it
        rather than beaconing the old wattage.
        """
        base_hz = base_hz if base_hz is not None else 1500.0
        key = (str(call).upper(), str(grid).upper(), int(dbm), float(base_hz),
               self._level)
        if key == self._cache_key and self._cache_path \
                and os.path.exists(self._cache_path):
            return self._cache_path
        path = os.path.join(self.workdir, "beacon.wav")
        # One second of silence first: WSPR starts at the even minute plus
        # one, and padding the file is simpler and more reliable than timing
        # the start of playback to a tenth of a second.
        lead = [0.0] * int(wspr.SAMPLE_RATE * TX_OFFSET_S)
        write_wav(path, lead + wspr.samples(call, grid, dbm, base_hz=base_hz,
                                            amplitude=self.amplitude))
        self._cache_key, self._cache_path = key, path
        return path

    def forget_cache(self):
        """Drop the rendered audio. For leaving a session."""
        self._cache_key, self._cache_path = None, ""

    # -- keying -----------------------------------------------------------

    def _key(self):
        """Key the radio and confirm it. Returns an error string, or "".

        **The confirmation is the point.** `set_ptt` answers with silence on
        a Yaesu, so a True return means the command went and nothing more.
        A radio that did not key would otherwise be played into silently,
        and the operator would see a transmission that never happened.
        """
        if self.rig is None:
            return "no rig"
        if not self.rig.set_ptt(True):
            return "PTT command failed"
        # **The readback is given time to become true.** Asked immediately,
        # the FTX-1 has not reported PTT yet and answers False -- so the
        # deck keyed the radio, read "not keyed", unkeyed it and reported
        # "the radio did not key", which is what an operator saw as a brief
        # click followed by a refusal. The radio is already keyed at this
        # point, so the wait costs nothing that is not already happening.
        state = self.rig.ptt()
        waited = 0.0
        while state is not True and waited < PTT_CONFIRM_S:
            time.sleep(PTT_POLL_S)
            waited += PTT_POLL_S
            state = self.rig.ptt()
        if state is False:
            # Unkey anyway: the command may have arrived late, and leaving
            # a maybe-keyed radio is the thing this module exists to avoid.
            self.rig.set_ptt(False)
            return "the radio did not key"
        # None means the state could not be read. Proceeding is the lesser
        # evil -- refusing would take transmit away from a radio whose PTT
        # readback is simply unsupported -- but it is reported.
        if state is None:
            self.last_error = "PTT state could not be read"
        return ""

    def _unkey(self):
        """Drop PTT. Never raises, and tries even when it has already been
        asked: this is called from every path out of a transmission."""
        if self.rig is None:
            return
        try:
            self.rig.set_ptt(False)
        except Exception:
            pass

    # -- transmitting -----------------------------------------------------

    def send(self, path, kind=SENDING, seconds=TX_TIMEOUT_S):
        """Key the radio and start playing `path`. Returns an error, or "".

        Refuses while something is already going out. The radio is unkeyed
        again if the player cannot be started, which is the case that would
        otherwise leave it keyed with nothing on it.
        """
        if self._proc is not None:
            return "already transmitting"
        if not path or not os.path.exists(path):
            return "nothing to send"
        why = self._key()
        if why:
            self.failed += 1
            self.last_error = why
            return why
        try:
            proc = self._spawn(aplay_command(path, self.device))
        except Exception as exc:
            self._unkey()
            self.failed += 1
            self.last_error = f"aplay: {exc}"
            return self.last_error
        self._proc = proc
        self._started = self._now()
        self._kind = kind
        self._deadline = seconds
        return ""

    def beacon(self, call, grid, dbm, base_hz=None):
        """Render if needed, then transmit. Returns an error, or ""."""
        try:
            path = self.beacon_wav(call, grid, dbm, base_hz)
        except Exception as exc:
            self.failed += 1
            self.last_error = f"render: {exc}"
            return self.last_error
        return self.send(path, SENDING, TX_TIMEOUT_S)

    def test_tone(self, hz=1500.0, seconds=TEST_TONE_S):
        """A steady tone for setting drive. Time-bounded by construction.

        At the SAME amplitude as a beacon, which is the only thing that makes
        it a calibration: a tone sent at a level the beacon will not use
        sets the drive for a transmission that never happens.
        """
        path = os.path.join(self.workdir, "tone.wav")
        try:
            write_wav(path, tone_samples(hz, seconds,
                                         amplitude=self.amplitude))
        except Exception as exc:
            self.failed += 1
            self.last_error = f"tone: {exc}"
            return self.last_error
        return self.send(path, TESTING, seconds + 4.0)

    def tick(self):
        """Collect what has finished. Returns events, possibly empty.

            ("sent", kind)          the transmission completed
            ("failed", kind, why)   it did not

        **Unkeys on every outcome.** Called from the draw loop, so it never
        waits.
        """
        if self._proc is None:
            return []
        kind = self._kind
        if self._proc.poll() is None:
            if self._now() - self._started <= self._deadline:
                return []
            # Over its deadline. Cut it off rather than let it hold the air.
            try:
                self._proc.kill()
            except Exception:
                pass
            self._finish()
            self.failed += 1
            self.last_error = f"{kind} did not finish"
            return [("failed", kind, "timed out")]
        code = self._proc.returncode
        err = ""
        try:
            err = (self._proc.stderr.read() or "").strip() \
                if self._proc.stderr else ""
        except Exception:
            err = ""
        self._finish()
        if code != 0:
            self.failed += 1
            self.last_error = f"aplay: {err or f'exit {code}'}"
            return [("failed", kind, err or f"exit {code}")]
        self.sent += 1
        return [("sent", kind)]

    def _finish(self):
        """Unkey and forget the process. The single exit from transmitting."""
        self._unkey()
        self._proc = None
        self._kind = IDLE

    def stop(self):
        """Cut a transmission short and unkey. Safe to call at any time.

        This is what `Ctrl-C`, leaving WSPR, the time-out timer and shutdown
        all go through, so it must work from every state and never raise.
        """
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
        self._finish()
