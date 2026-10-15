"""Direct CAT to the radio, through rigctld.

Why this exists
---------------
Hamlib 4.6.2 — the version in Raspberry Pi OS Trixie — builds a malformed
frequency command for the FT-991 model, which is the closest model that reads
the FTX-1 correctly. From a live trace on the deck:

    newcat_set_freq: is_ft991=1, CACHE(rig)->split=0, vfo=VFOA
    newcat_set_freq:1388 cmd_str = FA14075000;

That is ``FA`` plus **eight** digits. The FTX-1 CAT manual (p.16) specifies
nine, zero-padded, and the radio's own replies use nine:

    ret_data = FA014070000;

An eight-digit command is silently discarded — no error, no change, and the
deck's display snaps back to the radio's real frequency a moment later, which
looks exactly like the deck fighting the radio. Writing the documented form by
hand moves the VFO immediately:

    printf 'FA014075000;' > /dev/ttyUSB0      # confirmed on the deck

The same fault blocks every frequency path: the band presets, the tuning
screen's VFO keys, and anything fldigi tries to do through hamlib.

Rather than take the serial port away from rigctld — which also carries PTT,
and which fldigi needs — this sends the correct bytes *through* it. rigctld's
``w`` (send_cmd) forwards a raw string to the rig, so there is still exactly
one owner of the port.

This is a workaround for a bug in one hamlib version, not a better design. If
the deck is ever on a hamlib that formats the command properly, CAT_VFO can be
turned off in cyberdeck.conf and fldigi's own rig control does the job.
"""
import re
import socket


def _watts(value):
    """A wattage as a number, keeping a fraction only when there is one.

    0.5 stays 0.5 because half a watt is a meaningful QRP power; 6.0 becomes 6
    because "6.0 W" in a log is noise. ADIF's TX_PWR is a Number, so both are
    valid in an export.
    """
    try:
        watts = round(float(value), 2)
    except (TypeError, ValueError):
        return 0
    if watts <= 0:
        return 0
    return int(watts) if watts == int(watts) else watts


class Rigctld:
    """A small client for rigctld's text protocol on localhost."""

    def __init__(self, host="127.0.0.1", port=4532, timeout=2.0):
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self.last_error = ""

    def _talk(self, line, expect_reply=True):
        """Send one command. Returns the reply text, or None on failure.

        Never raises: the deck has to keep running with the radio unplugged,
        and a failed frequency change is a note on screen, not a crash.
        """
        try:
            with socket.create_connection((self.host, self.port), self.timeout) as s:
                s.sendall((line + "\n").encode("ascii"))
                if not expect_reply:
                    return ""
                s.settimeout(self.timeout)
                try:
                    return s.recv(4096).decode("ascii", "replace").strip()
                except socket.timeout:
                    # A Yaesu set command produces no reply. Silence here is
                    # success, not a fault.
                    return ""
        except OSError as exc:
            self.last_error = str(exc)
            return None

    @property
    def connected(self):
        return self._talk("f") is not None

    def send_cat(self, command):
        """Forward a raw CAT string such as 'FA014075000;' to the radio."""
        return self._talk(f"w {command}", expect_reply=False) is not None

    def read_cat(self, command):
        """Send a raw CAT query and return the answer, or "".

        The same `w` that `send_cat` uses, but keeping the reply. Yaesu answers
        terminate with `;`, and hamlib passes the string through untouched —
        **including a trailing NUL**. Measured on the deck, 2026-10-11:

            w FA;  ->  'FA146850000;\x00'
            w PC;  ->  'PC1006;\x00'

        `str.strip()` does not remove a NUL, so it has to be stripped by name.
        It matters for anything that compares or stores the answer whole; the
        field parsers here use `search` and would have survived it, which is
        exactly why it would have gone unnoticed.
        """
        reply = self._talk(f"w {command}")
        if not reply:
            return ""
        line = reply.strip().strip("\x00").strip().splitlines()[0].strip()
        if line.startswith("RPRT"):
            return ""
        return line

    # ---- rig-specific, and deliberately isolated ------------------------
    #
    # Everything from here to the end of `power_control` is Yaesu FTX-1 only.
    # It is an optimization on top of the generic path in `power`, not a
    # dependency of it: on any other radio the command is not understood, the
    # method returns (0, ""), and the generic path carries on. Deleting this
    # block costs the FTX-1 its automatic configuration detection and costs
    # every other radio nothing.
    #
    # The FTX-1 reports its transmit power in WATTS, and says which back end
    # it is running, in one command (CAT reference p. 21):
    #
    #     PC;  ->  PC P1 P2 P2 P2 ;
    #
    #     P1  1: FTX-1 field head      P2  P1=1: 005 - 010 W
    #         2: SPA-1 (the amplifier)     P1=2: 005 - 100 W
    #
    # so `PC1010;` is the field head at 10 W and `PC2100;` is the SPA-1 at
    # 100 W.
    #
    # **The manual is wrong about P2.** It documents three digits, and at the
    # bottom of the range the radio sends a decimal instead — measured
    # 2026-10-11, the field head at its 0.5 W minimum answers `PC10.5;`, not
    # `PC1005;`. A three-digit pattern simply fails to match there and reports
    # "no answer", which is the quiet kind of wrong: full power reads fine and
    # QRP does not.
    _PC = re.compile(r"PC([12])(\d+(?:\.\d+)?)")

    BACKENDS = {"1": "field", "2": "SPA-1"}

    def power_control(self):
        """(watts, back end) from the radio's own PC command, or (0, "").

        Watts may be fractional: this radio goes down to 0.5 W.

        Preferred over hamlib's normalized level for a reason that is not
        stylistic. `l RFPOWER` reports the position of the power control as
        0.0-1.0, and turning that into watts needs `power2mW`, which uses a
        **static** power curve compiled into the hamlib backend. That curve
        cannot know which back end is fitted — so on a 6 W battery setup a
        curve built for 100 W logs a full-scale control position as 100 W,
        a sixteen-fold error written silently into the log.

        The radio knows, so asking it is both simpler and correct — but only
        this radio knows, which is why it sits behind the generic path rather
        than in front of it.
        """
        answer = self.read_cat("PC;")
        if not answer:
            return 0, ""
        found = self._PC.search(answer)
        if not found:
            return 0, ""
        return _watts(found.group(2)), self.BACKENDS.get(found.group(1), "")

    def set_frequency(self, hz):
        """Set the MAIN VFO using the FTX-1's documented nine-digit form."""
        hz = int(round(float(hz)))
        if hz <= 0:
            return False
        return self.send_cat(f"FA{hz:09d};")

    def mode(self):
        """(mode, passband_hz) as the radio reports them, or ("", 0).

        rigctld's `m` answers with the mode on one line and the passband width
        on the next:

            USB
            2400

        The mode string is hamlib's, not ADIF's — `USB`, `LSB`, `PKTUSB`,
        `RTTY` — and `qsolog.adif_mode` does the translation. Never raises,
        for the same reason as `frequency`: the radio being unplugged is an
        ordinary condition.
        """
        reply = self._talk("m")
        if not reply:
            return "", 0
        lines = [l.strip() for l in reply.splitlines() if l.strip()]
        if not lines or lines[0].startswith("RPRT"):
            return "", 0
        width = 0
        if len(lines) > 1:
            try:
                width = int(lines[1])
            except ValueError:
                width = 0
        return lines[0].upper(), width

    def power(self, max_watts=0, freq_hz=0, mode=""):
        """Transmit power in watts, or 0 if it cannot be established.

        Three sources, most portable first. The ordering is deliberate: a
        logger that only works with one radio is worth less than one that
        works with any, so the rig-specific path is an optimization layered on
        top of a generic one rather than the foundation.

        1. **`l RFPOWER` scaled by `max_watts`** — works on every hamlib rig.
           hamlib reports the power control as a normalized 0.0-1.0, which is
           a *position*, not a wattage; the operator supplies the ceiling of
           whatever configuration they are running and the position is scaled
           into it. One setting, any radio.
        2. **`power2mW`** — hamlib converting the same position with the power
           curve compiled into its backend. Generic in form, but the curve is
           static and cannot know which back end is fitted, so it is wrong by
           whatever factor the configuration differs by. Used only when no
           ceiling has been given.
        3. **`power_control()`** — the radio asked directly. Accurate and
           self-describing where it exists, and silently skipped where it does
           not. See the note on that method about portability.

        Anything unexpected at any step returns 0, and the caller falls back
        to a configured fixed wattage.

        **Unverified against a radio.** Written from the rigctld protocol
        documentation; nothing here has seen a real reply.
        """
        level = self._rf_power_level()

        # 1. Generic: a position scaled into a ceiling the operator gave us.
        if level is not None and max_watts:
            # Linear from zero, which is measured rather than assumed: this
            # radio reads 0.05 at 0.5 W, 0.6 at 6 W and 1.0 at 10 W against a
            # 10 W ceiling. Had hamlib normalized against the rig's 5 W floor,
            # 6 W would have read 0.2.
            #
            # NOT rounded to whole watts. A QRP station running half a watt
            # is the case that cares most about this field, and `max(1, ...)`
            # would have turned every sub-watt contact into 1 W.
            return _watts(level * float(max_watts))

        # 3. Rig-specific, tried before hamlib's curve because it is right
        # when it answers. Delete `power_control` and this block and the
        # generic path above still works unchanged.
        watts, _backend = self.power_control()
        if watts:
            return watts

        # 2. hamlib's own curve, as a last resort before giving up.
        if level is None or level <= 0:
            return 0
        if not freq_hz:
            freq_hz = self.frequency()
        if not mode:
            mode = self.mode()[0]
        if not freq_hz or not mode:
            return 0
        converted = self._talk(f"power2mW {level} {int(freq_hz)} {mode}")
        if not converted:
            return 0
        line = converted.strip().splitlines()[0].strip()
        if line.startswith("RPRT"):
            return 0
        try:
            return _watts(float(line) / 1000.0)
        except ValueError:
            return 0

    def _rf_power_level(self):
        """The power control as hamlib's normalized 0.0-1.0, or None.

        A *position*, not a wattage. Logging it directly would record "0.4
        watts" for a transmission at 40 percent of whatever the rig can do.
        """
        reply = self._talk("l RFPOWER")
        if not reply:
            return None
        line = reply.strip().splitlines()[0].strip()
        if line.startswith("RPRT"):
            return None
        try:
            return float(line)
        except ValueError:
            return None

    def frequency(self):
        """The radio's frequency in Hz, or 0.0 if it cannot be read.

        Reads go through hamlib normally — it is only the set path that is
        broken — so this uses rigctld's own 'f' rather than another raw
        command.
        """
        reply = self._talk("f")
        if not reply:
            return 0.0
        for line in reply.splitlines():
            line = line.strip()
            if line.lstrip("-").isdigit():
                return float(line)
        return 0.0
