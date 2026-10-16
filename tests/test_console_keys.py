"""Keys as the framebuffer console delivers them, not as xterm does.

Every other pty test runs under TERM=xterm, because that is what a development
machine and an SSH session provide. The deck does not run under xterm. It runs
on tty1 as TERM=linux, and the two terminfo entries disagree about what some
keystrokes mean:

    linux:  kspd=^Z       ncurses consumes byte 26, returns KEY_SUSPEND (407)
    xterm:  no kspd       byte 26 arrives as 26

So a handler written as `ch == 26` works over SSH, passes the whole test
suite, and does nothing at all on the panel. That is how Ctrl-Z shipped
broken: the undo was correct, the dispatch never reached it.

kspd is the only capability in the linux entry that captures a control byte
the deck uses (kbs=^? is the other, and backspace already accepts it), so the
exposure is small — but it is invisible without running under the real
terminal type, which is what this file does.

Function keys differ too, which is why the sequences below are read from
terminfo rather than written as literals. Hard-coding xterm's \\E[15~ into a
TERM=linux run produces a test that fails for the wrong reason.
"""
import subprocess
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from harness import check, report
from test_screen import run


def cap(name, term="linux"):
    """The escape sequence terminfo gives `name` under `term`.

    In a subprocess because ncurses caches the terminal it was set up for:
    calling setupterm() twice in one process keeps answering for the first
    terminal, so a comparison between two of them silently compares one with
    itself. That produced two tests that passed for the wrong reason here.
    """
    probe = ("import curses, sys\n"
             "curses.setupterm()\n"
             "v = curses.tigetstr(sys.argv[1])\n"
             "sys.stdout.buffer.write(v or b'')\n")
    out = subprocess.run([sys.executable, "-c", probe, name],
                         capture_output=True,
                         env={**os.environ, "TERM": term})
    return out.stdout or None


CQ = "CQ CQ CQ DE"          # the opening of the default MEMORY_5


def compose_of(screen):
    """The compose line: two rows above the hint line."""
    return screen.display[screen.lines - 3].strip()


if __name__ == "__main__":
    print("Console key handling (TERM=linux)")

    f5 = cap("kf5")
    check("terminfo gives linux an F5 sequence", f5 is not None)
    check("linux F5 differs from xterm F5", f5 != cap("kf5", "xterm"),
          f"linux {f5!r} vs xterm {cap('kf5', 'xterm')!r}")

    # The fault itself, stated as the property that was untrue.
    check("linux terminfo maps Ctrl-Z to kspd",
          cap("kspd") == b"\x1a",
          f"kspd={cap('kspd')!r} — if this is None the premise has changed")
    check("xterm terminfo does not", cap("kspd", "xterm") is None)

    # And the behavior, driven through the real program under TERM=linux.
    # ^O first: the deck opens on DECK & RIG and the memories are a digimode
    # key, inserted into the line being composed on the conversation screen.
    inserted = run(keys=["\x0f", f5], term="linux")
    check("F5 inserts a memory on the console",
          CQ in compose_of(inserted), compose_of(inserted))

    undone = run(keys=[f5, b"\x1a"], term="linux")
    check("Ctrl-Z undoes it on the console",
          CQ not in compose_of(undone), compose_of(undone))

    # A key that reaches no handler is logged; the undo must not be one.
    body = "\n".join(undone.display)
    check("Ctrl-Z is not reported as an unhandled key",
          "KEY_SUSPEND" not in body and "unhandled key 407" not in body,
          body[-200:])

    # The same two steps under xterm, so a fix that works only on the console
    # is caught as well. Both terminals have to reach the same handler.
    x_f5 = cap("kf5", "xterm")
    x_undone = run(keys=[x_f5, b"\x1a"], term="xterm")
    check("Ctrl-Z still undoes it under xterm",
          CQ not in compose_of(x_undone), compose_of(x_undone))

    sys.exit(report())
