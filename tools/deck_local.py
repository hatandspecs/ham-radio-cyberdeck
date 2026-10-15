#!/usr/bin/env python3
"""Run the real cyberdeck interactively on a laptop, at the panel's exact size.

    tools/deck_local.py                 the deck, 66x20, TERM=linux
    tools/deck_local.py --contacts      with a few contacts already logged
    tools/deck_local.py --term xterm     to compare key handling
    tools/deck_local.py --size 80x24     a different screen

This is the application itself — `src/cyberdeck.py` — not a mock-up and not a
re-render. Keys go to it, it draws, and the log it writes is a real log file.
What is different from the deck is only what cannot be here: no fldigi, no
rigctld, no radio. The program is built to survive all three being absent, so
it comes up and logs; the frequency and mode fields stay empty because nothing
is there to answer, and the transcript stays quiet.

**The size is pinned to 66x20 whatever the terminal is.** That is the whole
point. A layout fault at the panel's dimensions is invisible in an 80x24 window
and this is how it was being missed — `preview_log.py` draws the log screen at
the right size but cannot be typed into, and a bare `python3 src/cyberdeck.py`
is typeable but inherits the terminal's size.

**TERM defaults to `linux`, the framebuffer console's terminfo, not xterm.**
The deck is a console and the console captures control bytes that xterm passes
through: `kspd=^Z` turns Ctrl-Z into KEY_SUSPEND, and F1 is `\\e[[A` rather than
`\\eOP`. An undo that worked in every xterm test once shipped dead on the panel
for exactly this reason. Use `--term xterm` deliberately, to compare.

**Nothing it writes touches real state.** The log, the remembered state and
`activities.conf` all go to a temporary directory that is named on exit and
removed unless `--keep` is given. A test run once saved an activity into the
operator's own `~/.config/cyberdeck/activities.conf`, which is the kind of
thing a sandbox is for.

Quitting: Ctrl-Q twice, as on the deck. If the program wedges, Ctrl-] forces
the wrapper to let go and restores the terminal.
"""

import argparse
import errno
import fcntl
import os
import pty
import select
import shutil
import signal
import socket
import struct
import time
import sys
import re
import subprocess
import tempfile
import termios
import tty

_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_PROJECT, "src")
# The operator's own credentials. Used only with --callbook yes, because a
# callbook lookup is a network request carrying a callsign to a third party.
_REAL_SECRETS = os.path.join(_PROJECT, "cyberdeck.secrets")
sys.path.insert(0, os.path.join(_PROJECT, "tools"))

# Glyphs proven to exist in the panel's console font (AGENTS.md). Everything
# else renders there as a blank or a replacement box -- and renders perfectly
# on a laptop, which is why a font fault is invisible from here and why this
# wrapper audits what the program drew rather than trusting the eye.
PROVEN = set("\u2588\u00b7\u2713\u25b8\u2717\u2191\u2193")
# Box drawing, U+2500-U+257F, which the panel has in full.
BOX = {chr(c) for c in range(0x2500, 0x2580)}

# CSI and OSC. Stripped before the audit so the escape machinery is not
# mistaken for content.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
                   r"|\x1b[()][B0]|\x1b[=><]")


def audit_glyphs(text):
    """Characters the program drew that the panel's font cannot show.

    Returns [(char, codepoint, count)], commonest first.
    """
    stripped = _ANSI.sub("", text)
    counts = {}
    for ch in stripped:
        if ch in PROVEN or ch in BOX:
            continue
        if ch == "\n" or ch == "\r" or ch == "\t" or ch == "\x00":
            continue
        if 0x20 <= ord(ch) <= 0x7e:
            continue
        counts[ch] = counts.get(ch, 0) + 1
    return sorted(((c, ord(c), n) for c, n in counts.items()),
                  key=lambda t: -t[2])

# Ctrl-] — the wrapper's own escape, not the application's. Chosen because the
# deck binds no such key: Ctrl-C is stop, Ctrl-Q is quit, Ctrl-X clears, and a
# forced exit must not be a key the program would rather have.
FORCE_QUIT = b"\x1d"

STATION = """\
# Written by tools/deck_local.py. A sandbox, not your station.
CALLSIGN = {call}
NAME = Don
QTH = State College, PA
LOCATOR = FN10cs
RIG = FTX-1
ANTENNA = EFHW
TX_POWER_MAX = 10
TX_POWER = 0

LOGGING = yes
ACTIVITY = {activity}
ACTIVITY_TYPE = {activity_type}
EXCHANGE_TX = {exchange}
MY_PARK = {park}
CALLBOOK = {callbook}
DUPE_CHECK = band+mode
OPERATING = auto

FLDIGI_URL = {fldigi_url}
RIGCTLD_HOST = 127.0.0.1
RIGCTLD_PORT = {rigctld_port}

LOG_PATH = {log_path}
"""

SEED = (
    "when=2026-10-14T16:04:00Z call=W3ABC band=40m mode=SSB rst_s=59 "
    "rst_r=57 name=Bob qth=\"Pittsburgh, PA\" my_call=KD3CCO\n"
    "when=2026-10-14T16:11:00Z call=K2XYZ band=40m mode=SSB rst_s=59 "
    "rst_r=59 name=Jim my_call=KD3CCO\n"
    "when=2026-10-14T16:19:00Z call=OK2CQR band=40m mode=SSB rst_s=59 "
    "rst_r=55 name=Petr qth=\"Neratovice\" my_call=KD3CCO\n"
)


# The keys whose byte sequences differ between terminals often enough to
# matter here. Named by terminfo capability so the table is read rather than
# assumed.
_KEYCAPS = ("kf1", "kf2", "kf3", "kf4", "kf5", "kf6", "kf7", "kf8", "kf9",
            "kf10", "kf11", "kf12", "kcuu1", "kcud1", "kcub1", "kcuf1",
            "khome", "kend", "kich1", "kdch1", "knp", "kpp", "kcbt", "kspd")


def _capabilities(term):
    """{capability: byte sequence} for one TERM, from its terminfo entry.

    Read with `infocmp` rather than hard-coded, because the whole reason this
    function exists is that assuming a key's bytes is what breaks. Returns {}
    if the entry cannot be read, and the caller then translates nothing.
    """
    try:
        out = subprocess.run(["infocmp", "-1", term], check=True,
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    caps = {}
    for line in out.splitlines():
        line = line.strip().rstrip(",")
        if "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name not in _KEYCAPS:
            continue
        # terminfo escapes: \E for escape, ^X for a control byte, \\ for a
        # literal backslash. Nothing else appears in these capabilities.
        seq, i = [], 0
        while i < len(value):
            c = value[i]
            if c == "\\" and i + 1 < len(value):
                nxt = value[i + 1]
                if nxt in "Ee":
                    seq.append("\x1b")
                elif nxt == "\\":
                    seq.append("\\")
                elif nxt == "n":
                    seq.append("\n")
                elif nxt == "r":
                    seq.append("\r")
                elif nxt == "t":
                    seq.append("\t")
                elif nxt.isdigit():
                    seq.append(chr(int(value[i + 1:i + 4], 8)))
                    i += 4
                    continue
                else:
                    seq.append(nxt)
                i += 2
                continue
            if c == "^" and i + 1 < len(value):
                seq.append(chr(ord(value[i + 1].upper()) ^ 0x40))
                i += 2
                continue
            seq.append(c)
            i += 1
        caps[name] = "".join(seq).encode("latin-1", "replace")
    return caps


def key_translation(host_term, child_term):
    """{bytes the host sends: bytes the child expects}, for keys that differ.

    The host terminal encodes a key its own way and the child's ncurses
    decodes using the child's terminfo. Where those disagree the key is simply
    dead — which is what F1 through F5 are when an xterm drives a child running
    as the framebuffer console: the terminal sends ESC O P and `linux` is
    waiting for ESC [ [ A. F6 upward happen to agree, which is why the failure
    looks partial rather than total.

    Arrows usually agree too, because `linux` has no `smkx`, so nothing puts
    the host terminal into application-cursor mode and it keeps sending the
    ESC [ A form that `linux` also expects.
    """
    host = _capabilities(host_term)
    child = _capabilities(child_term)
    if not host or not child:
        return {}
    table = {}
    for cap in _KEYCAPS:
        h, c = host.get(cap), child.get(cap)
        if h and c and h != c:
            table[h] = c
    return table


class KeyStream:
    """Rewrites key sequences on the way to the child.

    Buffers, because a sequence can arrive split across reads and a prefix of
    one must not be forwarded as itself. `flush_after` is how long a partial
    sequence is held before being given up on and passed through — which is
    what keeps a bare Esc from waiting forever for the rest of an arrow key.
    """

    def __init__(self, table, flush_after=0.05):
        self.table = table
        self.longest = max((len(k) for k in table), default=0)
        self.flush_after = flush_after
        self.buf = b""
        self.pending_since = None

    def feed(self, data, now):
        self.buf += data
        self.pending_since = now
        return self._drain(now, final=False)

    def idle(self, now):
        """Anything held longer than flush_after goes through untranslated."""
        if not self.buf or self.pending_since is None:
            return b""
        if now - self.pending_since < self.flush_after:
            return b""
        return self._drain(now, final=True)

    def _drain(self, now, final):
        out = bytearray()
        while self.buf:
            hit = None
            for seq in sorted(self.table, key=len, reverse=True):
                if self.buf.startswith(seq):
                    hit = seq
                    break
            if hit:
                out += self.table[hit]
                self.buf = self.buf[len(hit):]
                continue
            # A prefix of something longer: wait for the rest, unless time is
            # up or the buffer is already longer than any sequence could be.
            if not final and len(self.buf) < self.longest and any(
                    seq.startswith(self.buf) for seq in self.table):
                self.pending_since = now
                return bytes(out)
            out += self.buf[:1]
            self.buf = self.buf[1:]
        self.pending_since = None
        return bytes(out)


def _free_port(preferred):
    """`preferred` if it is free, else any free port.

    The standard ports are not assumed available: a real fldigi on 7362 is the
    normal state of this laptop during development, and the sandbox has no
    business taking it or failing because of it. The deck is pointed at
    whatever comes back, which is why FLDIGI_URL and RIGCTLD_PORT are written
    into the sandbox configuration rather than left at their defaults.
    """
    for candidate in (preferred, 0):
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", candidate))
            port = probe.getsockname()[1]
            probe.close()
            return port
        except OSError:
            probe.close()
    return preferred


def _write_all(fd, data):
    """Write every byte, looping until it is gone.

    `os.write` may write fewer bytes than it is handed, and the amount is not
    an error -- it is the normal contract. Ignoring the return value drops
    part of whatever was being written, and when that is a frame of screen
    output the result is a display that tears and smears. A terminal frame at
    66x20 is only a few kilobytes, which is precisely the size that *usually*
    goes in one call and occasionally does not.
    """
    view = memoryview(data)
    while view:
        try:
            sent = os.write(fd, view)
        except InterruptedError:
            continue
        except BrokenPipeError:
            return
        view = view[sent:]


def _set_size(fd, rows, cols):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _terminal_size():
    try:
        s = shutil.get_terminal_size()
        return s.lines, s.columns
    except Exception:
        return 24, 80


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--size", default="66x20", metavar="COLSxROWS",
                    help="the screen to give it (default 66x20, the panel)")
    ap.add_argument("--term", default="linux",
                    help="TERM for the child (default linux, the console)")
    ap.add_argument("--contacts", action="store_true",
                    help="seed the log with a few contacts")
    ap.add_argument("--activity", default="", help="ACTIVITY (session name)")
    ap.add_argument("--activity-type", default="", dest="activity_type",
                    help="ACTIVITY_TYPE: POTA, CONTEST, or one of your own")
    ap.add_argument("--exchange", default="", help="EXCHANGE_TX")
    ap.add_argument("--park", default="", help="MY_PARK")
    ap.add_argument("--callsign", default="KD3CCO")
    ap.add_argument("--callbook", default="yes", choices=("yes", "no"),
                    help="network callsign lookup. On by default, matching "
                         "the deck -- so every call typed here really is sent "
                         "to callook.info, HamQTH and QRZ. --callbook no "
                         "keeps it local")
    ap.add_argument("--keep", action="store_true",
                    help="keep the sandbox directory and say where it is")
    ap.add_argument("--no-translate", action="store_true", dest="no_translate",
                    help="forward keys byte for byte. F1-F5 are then dead "
                         "under --term linux from an xterm, which is "
                         "occasionally what you want to see")
    radio = ap.add_argument_group(
        "pretend radio",
        "A fake fldigi and a fake rigctld, so the deck reads a mode, a "
        "frequency and a transmit power instead of blanks. See "
        "tools/fake_radio.py.")
    radio.add_argument("--no-radio", action="store_true", dest="no_radio",
                       help="do not start them; the deck sees no radio at all, "
                            "which is also worth testing")
    radio.add_argument("--mode", default="PSK31",
                       help="fldigi's modem (default PSK31)")
    radio.add_argument("--rig-mode", default="PKTUSB", dest="rig_mode",
                       help="the radio's own mode (default PKTUSB)")
    radio.add_argument("--freq", type=int, default=3_580_000,
                       help="VFO in Hz (default 3580000, 80 m)")
    radio.add_argument("--carrier", type=int, default=1500)
    radio.add_argument("--power", type=float, default=0.6,
                       help="hamlib's normalized power level 0.0-1.0 "
                            "(default 0.6, so 6 W of a 10 W ceiling)")
    args = ap.parse_args(argv)

    try:
        cols, rows = (int(n) for n in args.size.lower().split("x"))
    except ValueError:
        ap.error(f"--size wants COLSxROWS, not {args.size!r}")

    if not sys.stdin.isatty():
        print("deck_local.py needs a real terminal: it puts stdin in raw mode "
              "and forwards keys. For a scripted run use the harness in "
              "tests/test_screen.py, which drives the same program through a "
              "pty and reads the screen back.", file=sys.stderr)
        return 2

    have_rows, have_cols = _terminal_size()
    if have_cols < cols or have_rows < rows:
        print(f"-- this terminal is {have_cols}x{have_rows} and the deck needs "
              f"{cols}x{rows}; the display will wrap", file=sys.stderr)

    sandbox = tempfile.mkdtemp(prefix="deck-local-")
    log_path = os.path.join(sandbox, "qso.log")
    conf_path = os.path.join(sandbox, "cyberdeck.conf")

    # Started before the configuration is written, because the ports they end
    # up on are what the configuration has to say.
    started, fldigi_port, rigctld_port = [], 0, 0
    if not args.no_radio:
        import fake_radio
        rig = fake_radio.Radio(mode=args.mode, freq=args.freq,
                               rig_mode=args.rig_mode, carrier=args.carrier,
                               power=args.power, max_watts=10)
        # Each one on its own, so a port collision on one does not cost the
        # other. A deck with a frequency and no modem is still worth having.
        for label, start, preferred in (
                ("fldigi", fake_radio.fldigi_server, 7362),
                ("rigctld", fake_radio.rigctld_server, 4532)):
            port = _free_port(preferred)
            try:
                start(rig, port=port)
                started.append(f"{label}:{port}")
                if label == "fldigi":
                    fldigi_port = port
                else:
                    rigctld_port = port
            except OSError as exc:
                print(f"-- no pretend {label} ({exc})", file=sys.stderr)

    # An unreachable address rather than a wrong one when a fake did not
    # start: port 1 refuses immediately, so the deck reports no radio quickly
    # instead of waiting out a timeout on every poll.
    fldigi_url = f"http://127.0.0.1:{fldigi_port or 1}/"

    with open(conf_path, "w") as fh:
        fh.write(STATION.format(
            call=args.callsign, activity=args.activity,
            activity_type=args.activity_type, exchange=args.exchange,
            park=args.park, callbook=args.callbook, log_path=log_path,
            fldigi_url=fldigi_url, rigctld_port=rigctld_port or 1))
    if args.contacts:
        with open(log_path, "w") as fh:
            fh.write(SEED)

    if args.callbook == "yes":
        if os.path.exists(_REAL_SECRETS):
            print("-- callbook lookup ON, with your real credentials from "
                  f"{os.path.basename(_REAL_SECRETS)}.")
            print("   Every callsign typed here goes to callook.info, HamQTH "
                  "and QRZ.")
        else:
            print(f"-- callbook is on but {_REAL_SECRETS} is missing: "
                  "callook.info still answers for US calls, HamQTH and QRZ "
                  "will not", file=sys.stderr)

    print(f"-- sandbox {sandbox}")
    if started:
        watts = args.power * 10
        print(f"-- pretend radio ({', '.join(started)}): modem {args.mode}, "
              f"rig {args.rig_mode}, VFO {args.freq / 1e6:.6f} MHz, "
              f"{watts:g} W of 10")
    else:
        print("-- no fldigi and no radio")
    print(f"-- {cols}x{rows} characters, TERM={args.term}")
    print(f"-- Ctrl-N opens the log. Ctrl-Q twice quits. "
          f"Ctrl-] forces the wrapper to let go.")
    print()

    pid, master = pty.fork()
    if pid == 0:
        os.environ["TERM"] = args.term
        os.environ["CYBERDECK_CONF"] = conf_path
        # Remembered state and saved activities go in the sandbox, never in
        # ~/.config or ~/.local.
        os.environ["CYBERDECK_STATE_PATH"] = os.path.join(sandbox, "state.json")
        os.environ["CYBERDECK_ACTIVITIES"] = os.path.join(
            sandbox, "activities.conf")
        os.environ["LINES"], os.environ["COLUMNS"] = str(rows), str(cols)
        # Explicit either way rather than left to the search path, which
        # would otherwise find the operator's real cyberdeck.secrets at the
        # repository root and use it without ever saying so.
        if args.callbook == "yes":
            os.environ["CYBERDECK_SECRETS"] = _REAL_SECRETS
        else:
            os.environ["CYBERDECK_SECRETS"] = os.path.join(
                sandbox, "no-secrets")
        os.chdir(_PROJECT)
        os.execvp(sys.executable, [sys.executable,
                                   os.path.join(_SRC, "cyberdeck.py")])
        os._exit(127)                                   # pragma: no cover

    host_term = os.environ.get("TERM", "") or "xterm"
    table = {} if args.no_translate else key_translation(host_term, args.term)
    if table:
        print(f"-- translating {len(table)} key sequences from {host_term} "
              f"to {args.term}")
    elif not args.no_translate and host_term != args.term:
        print(f"-- no key translation available between {host_term} and "
              f"{args.term}; some keys may be dead", file=sys.stderr)
    keys = KeyStream(table)

    _set_size(master, rows, cols)
    saved = termios.tcgetattr(sys.stdin)
    forced = False
    drawn = []
    try:
        tty.setraw(sys.stdin.fileno())
        while True:
            try:
                # Short, because a partial key sequence is only flushed on an
                # idle pass. At 0.2 s a bare Esc could sit for a fifth of a
                # second before reaching the program, on top of the 100 ms
                # ESCDELAY it sets for itself -- which feels like a dropped
                # key rather than a slow one.
                ready, _, _ = select.select([sys.stdin, master], [], [], 0.02)
            except InterruptedError:
                continue
            if sys.stdin in ready:
                data = os.read(sys.stdin.fileno(), 1024)
                if not data:
                    break
                if FORCE_QUIT in data:
                    forced = True
                    break
                out = keys.feed(data, time.monotonic())
                if out:
                    _write_all(master, out)
            else:
                out = keys.idle(time.monotonic())
                if out:
                    _write_all(master, out)
            if master in ready:
                try:
                    out = os.read(master, 65536)
                except OSError as exc:
                    if exc.errno == errno.EIO:        # the child let go
                        break
                    raise
                if not out:
                    break
                # Kept for the glyph audit, bounded: a long session would
                # otherwise hold every frame it ever drew in memory, and the
                # audit only needs to have seen each character once.
                drawn.append(out)
                if len(drawn) > 4000:
                    del drawn[:2000]
                _write_all(sys.stdout.fileno(), out)
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, saved)
        os.close(master)
        if forced:
            os.kill(pid, signal.SIGTERM)
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
        # The program leaves the terminal in whatever state it had; a forced
        # exit skipped its own cleanup, so reset rather than hand back a
        # terminal with no cursor and the alternate screen still up.
        sys.stdout.write("\x1b[?25h\x1b[0m\r\n")
        sys.stdout.flush()

    bad = audit_glyphs(b"".join(drawn).decode("utf-8", "replace"))
    if bad:
        print("-- glyphs the panel's font cannot show:")
        for ch, cp, n in bad:
            print(f"   {ch!r}  U+{cp:04X}  x{n}")
        print("   These render here and appear as blanks or boxes on the deck.")
        print("   Proven safe: block, middot, check, triangle, cross, arrows,")
        print("   box drawing, and plain ASCII.")
    else:
        print("-- every glyph drawn is one the panel's font has")

    lines = []
    if os.path.exists(log_path):
        with open(log_path) as fh:
            lines = [l.strip() for l in fh if l.strip()]
    print(f"-- {len(lines)} contact{'' if len(lines) == 1 else 's'} in the log")
    for line in lines[-5:]:
        print(f"   {line}")
    acts = os.path.join(sandbox, "activities.conf")
    if os.path.exists(acts):
        print(f"-- activities.conf was written:")
        for line in open(acts).read().splitlines():
            if line.strip():
                print(f"   {line}")
    if args.keep:
        print(f"-- kept: {sandbox}")
    else:
        shutil.rmtree(sandbox, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
