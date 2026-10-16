"""Run the terminal in a pty at a given grid and read the screen back.

The deck's whole point is what it looks like, so the test drives the real
application through a real pseudo-terminal and reconstructs the screen with a
terminal emulator, rather than asserting on functions in isolation.
"""
import pty, time, fcntl, termios, struct, select
import os
import sys

# src/ holds the application; tests/ holds this. Both are addressed from the
# project root so a test can be run from anywhere.
_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_PROJECT, "src")
sys.path.insert(0, _SRC)
import pyte


def run(keys=(), cols=66, rows=20, settle=1.2, term="xterm", state_path="",
        settle_s="10", conf="", after=0.35):
    """Drive the real application in a pty and return the reconstructed screen.

    `term` is a parameter because it is not cosmetic. The deck runs on the
    framebuffer console as TERM=linux, whose terminfo maps some keys
    differently from xterm's — kspd=^Z above all, which turns Ctrl-Z into
    KEY_SUSPEND. Tests that only ever run under xterm cannot see that class of
    fault; test_console_keys.py runs under linux for exactly that reason.
    """
    screen = pyte.Screen(cols, rows)
    stream = pyte.ByteStream(screen)

    pid, fd = os.forkpty()
    if pid == 0:
        os.environ["TERM"] = term
        # No remembered state by default: every run starts from the configured
        # defaults, or a mode chosen by one test would leak into the next.
        # test_state.py passes a path on purpose, to check that it does leak
        # when it is supposed to.
        os.environ["CYBERDECK_STATE_PATH"] = state_path
        # A test cannot wait out the deck's ten-second settle window.
        os.environ["CYBERDECK_STATE_SETTLE_S"] = settle_s
        # A configuration of the test's own, used to point the deck at a
        # fldigi that a test controls — above all one that is not there yet.
        if conf:
            os.environ["CYBERDECK_CONF"] = conf
        else:
            os.environ.pop("CYBERDECK_CONF", None)
        os.environ["LINES"], os.environ["COLUMNS"] = str(rows), str(cols)
        os.chdir(_PROJECT)          # cyberdeck.conf is read from here
        os.execvp(sys.executable,
                  [sys.executable, os.path.join(_SRC, "cyberdeck.py")])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def pump(seconds):
        end = time.time() + seconds
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.1)
            if r:
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    return False
                if not data:
                    return False
                stream.feed(data)
        return True

    pump(settle)
    # `after` is the wait following each key, and it is a parameter because
    # some keys start an XML-RPC call before they produce anything on screen.
    # Ctrl-X is the clear case: it calls text.clear_rx, whose client timeout
    # is two seconds, and only then writes "transcript cleared". At the
    # default 0.35 the note could land after the quit keys were already
    # queued, so the check passed or failed according to how busy fldigi
    # happened to be — which late in a long suite is busy.
    for k in keys:
        os.write(fd, k if isinstance(k, bytes) else k.encode())
        pump(after)
    # Ctrl-Q twice: the first asks for confirmation, the second exits. Sending
    # one and closing the pty would also end the process, by hanging up its
    # terminal rather than by leaving the main loop — which would pass while
    # hiding a broken exit path.
    os.write(fd, b"\x11")
    pump(0.4)
    os.write(fd, b"\x11")
    pump(0.6)
    # Did it actually exit? waitpid before the pty is closed, so a process
    # still in the main loop is visibly still there. Recorded on the screen
    # object rather than asserted here, since most callers do not care.
    # Generous: the exit path calls fldigi.abort(), which blocks for up to the
    # client's own timeout when fldigi is busy, and curses has to restore the
    # terminal after that. Two seconds raced under full-suite load.
    exited = False
    for _ in range(60):
        try:
            done, _status = os.waitpid(pid, os.WNOHANG)
        except OSError:
            exited = True
            break
        if done:
            exited = True
            break
        pump(0.1)
    screen.exited_cleanly = exited
    try:
        os.close(fd)
        os.waitpid(pid, os.WNOHANG)
    except OSError:
        pass
    return screen


def show(title, screen):
    print(f"\n=== {title} ({screen.columns}x{screen.lines}) ===")
    print("+" + "-" * screen.columns + "+")
    for line in screen.display:
        print("|" + line + "|")
    print("+" + "-" * screen.columns + "+")
    return "\n".join(screen.display)


# The deck OPENS on DECK & RIG. `^O` steps backwards round the ring --
# settings | log | digimodes -- and the log is not on it while logging is
# off, so one `^O` wraps straight to the conversation. Every scenario below
# is about the CONVERSATION screen, so each one hops there first; without it
# they read the station fields and looked for a transcript.
TO_CHAT = "\x0f"

if __name__ == "__main__":
    body = show("startup, 66x20", run(keys=[TO_CHAT]))
    ok = []
    ok.append(("callsign in the status line", "KD3CCO" in body))
    ok.append(("hint line present", "F1 menu" in body))
    ok.append(("buffer indicator present", "[RX" in body))
    # The startup note scrolls off within a second when fldigi is decoding a
    # noise floor with squelch open, so assert on what stays put: a modem
    # name in the status line only appears if fldigi answered.
    ok.append(("fldigi connected (modem in status)", "BPSK31" in body))
    ok.append(("hint line is not truncated mid-word", "abor|" not in body and "F2 tune" in body))

    over = "NOCALL de KD3CCO  testing"
    typed = show("after typing an over", run(keys=[TO_CHAT, over]))
    ok.append(("typed text appears in compose", "testing" in typed))
    # Counted from the string rather than written in: the expected number
    # changed silently when the example callsign did.
    ok.append((f"indicator counts it ({len(over)})", f"[RX {len(over)}]" in typed))

    tune = show("F2 tuning screen",
                run(keys=[TO_CHAT, "\x1bOQ"]))   # F2 in xterm
    ok.append(("tuning screen reached", "quality" in tune or "TUNING" in tune))

    narrow_scr = run(keys=[TO_CHAT], cols=50, rows=15)
    narrow = show("50x15 grid", narrow_scr)
    ok.append(("fits a 50-column deck", "KD3CCO" in narrow))

    # Ctrl-Q confirms, then exits. Asserted because the confirmation read has
    # to block: written with the main loop's POLL_MS timeout still in force it
    # returns -1 within 200 ms and cancels itself, and every test above would
    # still pass — their processes die when the pty closes either way.
    ok.append(("Ctrl-Q twice leaves the main loop", narrow_scr.exited_cleanly))
    single = run(keys=[TO_CHAT])
    ok.append(("and the confirmation is actually shown",
               "Ctrl-Q again" in "\n".join(single.display)))

    print()
    for name, good in ok:
        print(f"  {'PASS' if good else 'FAIL'}  {name}")
    print("\n" + ("ALL PASS" if all(g for _, g in ok) else "SOME FAILED"))
