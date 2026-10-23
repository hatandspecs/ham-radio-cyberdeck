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

# **Two backwards hops, not one.** WSPR made the ring four areas --
# settings | log | digimodes | WSPR -- so one `^O` back from the boot screen
# wraps onto WSPR, where F5 is not a memory key and nothing is composed.
TO_CHAT = "\x0f\x0f\x0f"
# Three hops: the ring is five areas now (the band plan joined it),
# and `^O` x3 lands on the conversation whether or not logging is on --
# which is the property the old two-hop constant had. See the ring-hop
# trap in AGENTS.md.


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
    # TO_CHAT, not a bare "\x0f": the ring has four areas since WSPR, so one
    # hop back from the boot screen lands on WSPR and F5 goes nowhere.
    inserted = run(keys=[TO_CHAT, f5], term="linux")
    check("F5 inserts a memory on the console",
          CQ in compose_of(inserted), compose_of(inserted))

    # **These three reach the conversation first too.** Without the hop F5
    # never inserts anything, so "the memory is gone" is true before Ctrl-Z
    # is pressed and the case passes whether undo works or not. It is only
    # an undo test if the thing being undone was there to start with, which
    # the first check below establishes.
    undone = run(keys=[TO_CHAT, f5, b"\x1a"], term="linux")
    check("the memory was there to undo", CQ in compose_of(inserted),
          compose_of(inserted))
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
    x_inserted = run(keys=[TO_CHAT, x_f5], term="xterm")
    check("F5 inserts a memory under xterm too",
          CQ in compose_of(x_inserted), compose_of(x_inserted))
    x_undone = run(keys=[TO_CHAT, x_f5, b"\x1a"], term="xterm")
    check("Ctrl-Z still undoes it under xterm",
          CQ not in compose_of(x_undone), compose_of(x_undone))

    sys.exit(report())
