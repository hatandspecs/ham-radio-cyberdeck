"""The capture mixer, set for a WSPR session and put back afterwards.

**Why this exists rather than a digital gain.** Scaling the samples after
they are captured changes the numbers and not the signal: the analog-to-
digital converter has already decided how much of its range the audio used,
and multiplying a quiet recording makes a loud recording of the same noise.
What `wsprd` wants — roughly -30 to -20 dBFS — is a property of the ADC's
input level, and on this board that is one ALSA control.

**Why it is safe to touch a control fldigi shares.** WSPR already owns the
codec exclusively: it stops fldigi before it captures anything, which is
measured in `docs/wspr_deploy.md` §4a and is not negotiable. So the mixer is
unobserved for the length of a session. The previous value is read before
anything is written and restored when the session ends, which is what makes
this a per-function level rather than a change to the station.

The transmit side is NOT done this way. Playback amplitude is scaled where
the audio is rendered -- `wsprtx.Transmitter.level` -- because nothing else
plays that file and so nothing else can be affected. Using the playback
mixer would have turned the digimodes down along with WSPR.

Percent and not raw steps: codecs differ in range (this one is 0-16) and
`amixer` accepts and reports percent on all of them.
"""
import re
import subprocess

DEFAULT_CARD = 1
DEFAULT_CONTROL = "Mic"
DEFAULT_GAIN = 70

# `[62%]` in amixer's per-channel line. The dB figure beside it is not used:
# it is the codec's own scale and is missing on controls that have none.
_PCT = re.compile(r"\[(\d{1,3})%\]")


def get_command(card=DEFAULT_CARD, control=DEFAULT_CONTROL):
    """What to run to read the control."""
    return ["amixer", "-c", str(card), "sget", str(control), "capture"]


def set_command(pct, card=DEFAULT_CARD, control=DEFAULT_CONTROL):
    """What to run to set it, as a percentage."""
    return ["amixer", "-c", str(card), "sset", str(control),
            f"{int(pct)}%", "capture"]


def parse_level(text):
    """The first percentage in amixer's output, or None.

    None is not zero. A control that cannot be read is not a control known
    to be silent, and the difference decides whether the deck reports a
    level or reports that it has none.
    """
    m = _PCT.search(str(text or ""))
    if not m:
        return None
    return max(0, min(100, int(m.group(1))))


def level_of(path, stride=None):
    """`(rms, peak, dbfs)` for a captured WAV, or None if it cannot be read.

    Here rather than in the panel so the draw loop has one call to make and
    no `wave` handling of its own.
    """
    import wave
    import wspr
    try:
        with wave.open(path) as w:
            if w.getsampwidth() != 2 or w.getnchannels() != 1:
                return None
            frames = w.readframes(w.getnframes())
    except Exception:
        return None
    if not frames:
        return None
    return wspr.audio_level(frames, stride=stride or wspr.LEVEL_STRIDE)


class Gain:
    """The capture control, with the operator's value and the one found.

    `run` is injected so every path here is testable without a sound card:
    it takes a command list and returns `(returncode, stdout, stderr)`.
    """

    def __init__(self, card=DEFAULT_CARD, control=DEFAULT_CONTROL, run=None):
        self.card = card
        self.control = control
        self._run = run or self._real_run
        self.previous = None       # what was there before the session
        self.applied = None        # what this object set
        self.last_error = ""

    @staticmethod
    def _real_run(cmd):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=10, stdin=subprocess.DEVNULL)
            return r.returncode, r.stdout, r.stderr
        except Exception as exc:
            return 1, "", str(exc)

    def read(self):
        """The control's current percentage, or None."""
        code, out, err = self._run(get_command(self.card, self.control))
        if code != 0:
            self.last_error = (err or out or "amixer failed").strip()
            return None
        self.last_error = ""
        return parse_level(out)

    def apply(self, pct):
        """Set the control, remembering what was there. Returns why, or "".

        The previous value is captured once per session and not overwritten
        by a later change, so a gain adjusted three times mid-session still
        restores to what the station had.
        """
        if self.previous is None:
            self.previous = self.read()
        code, out, err = self._run(
            set_command(pct, self.card, self.control))
        if code != 0:
            self.last_error = (err or out or "amixer failed").strip()
            # A control name that does not exist on this codec is the
            # commonest cause and the message says so, because `amixer`'s own
            # wording ("Unable to find simple control") does not say which
            # setting to change.
            if "find simple control" in self.last_error:
                self.last_error = (f"no capture control named "
                                   f"{self.control!r} on card {self.card}")
            return self.last_error
        self.applied = int(pct)
        self.last_error = ""
        return ""

    def restore(self):
        """Put the control back. Returns why, or "".

        Does nothing when nothing was applied, so calling it on a session
        that never captured is harmless.
        """
        if self.previous is None or self.applied is None:
            return ""
        code, out, err = self._run(
            set_command(self.previous, self.card, self.control))
        if code != 0:
            self.last_error = (err or out or "amixer failed").strip()
            return self.last_error
        self.applied = None
        self.previous = None
        self.last_error = ""
        return ""
