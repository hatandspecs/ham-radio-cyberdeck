"""Received text that the screen cannot draw — src/fldigi_client.py, _put.

**This file exists because of a crash on the air.** On 2026-10-18, logging
SSB, the deck died with:

    File "cyberdeck.py", line 4748, in _put
      self.scr.addstr(row, x, chunk, colors.attr(kind))
    ValueError: embedded null character

The rig was out of a data mode, so the decoder was parked on fldigi's NULL
modem, and the text coming back from the RX buffer carried a `\x00`. curses
raises `ValueError` for that, not `curses.error`, so the handler around
`addstr` did not catch it. Every redraw hit the same byte, so the deck
crash-looped: systemd restarted it, the transcript was restored, and it
crashed again.

`errors="replace"` on the decode does not help. It handles bytes that are
not valid UTF-8; `0x00` IS valid UTF-8 and decodes to `"\x00"`.

Two defenses, and both are tested here: the text is cleaned where it enters,
and the draw path survives it anyway, because `_put` is what every screen on
the deck draws through.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import fldigi_client

NOISE = "CQ CQ\x00 DE\x01 KD3CCO\x7f\ttab\nline\r"

print("received text is cleaned where it enters")
got = NOISE.translate(fldigi_client._RX_STRIP)
check("the NUL is gone", "\x00" not in got, repr(got))
check("and the other C0 noise", "\x01" not in got, repr(got))
check("and DEL", "\x7f" not in got, repr(got))

# Newline and tab carry meaning in a line-based transcript and must survive.
check("newline is kept", "\n" in got, repr(got))
check("tab is kept", "\t" in got, repr(got))
check("carriage return is kept", "\r" in got, repr(got))
check("and the actual text is untouched",
      "CQ CQ DE KD3CCO" in got, repr(got))

print("\nevery byte below space is accounted for")
for i in range(32):
    ch = chr(i)
    kept = ch in "\n\r\t"
    present = ch in ch.translate(fldigi_client._RX_STRIP)
    equals(f"byte {i:>2} is {'kept' if kept else 'stripped'}",
           present, kept)

print("\nand the draw path survives one anyway")
# `_put` is what EVERY screen draws through, so a bad byte from any source
# -- not only fldigi -- must not be able to stop the deck.
#
# Against a stand-in rather than a real curses screen: what curses does with
# a NUL is not in question, the traceback from the deck settled it, and
# `curses.wrapper` needs a terminal this test tier does not have. What IS in
# question is whether `_put` survives it, which is this object's job to ask.
import cyberdeck

# `_put` evaluates `colors.attr(kind)` as an argument INSIDE its own try, so
# without an initialized terminal that raises `curses.error` first and the
# screen is never touched -- which made the first version of this test look
# like `_put` silently drew nothing. Neutralized so what is under test is
# the NUL handling and not curses' color setup.
cyberdeck.colors.attr = lambda kind: 0


class Screen:
    """A curses window that refuses NUL exactly as the real one does."""

    def __init__(self):
        self.written = []

    def addstr(self, row, col, text, attr=0):
        if "\x00" in text:
            raise ValueError("embedded null character")
        self.written.append(text)


def drawn(text):
    """Returns (escaped exception or None, what reached the screen)."""
    deck = cyberdeck.Deck.__new__(cyberdeck.Deck)
    deck.scr = Screen()
    try:
        deck._put(0, 0, [(text, "")], 40)
        return None, deck.scr.written
    except Exception as exc:                  # noqa: BLE001 - the point
        return exc, deck.scr.written


err, wrote = drawn("CQ DE KD3CCO")
equals("ordinary text draws", err, None)
equals("unchanged", wrote, ["CQ DE KD3CCO"])

# The exact shape of the string that crashed the deck.
err, wrote = drawn("CQ CQ\x00 DE KD3CCO")
equals("text with a NUL no longer raises", err, None)
check("and the readable part still reaches the screen",
      wrote and "KD3CCO" in wrote[-1], str(wrote))
check("with the NUL removed", wrote and "\x00" not in wrote[-1], str(wrote))

err, wrote = drawn("\x00\x01\x02")
equals("nothing but control characters is survivable", err, None)

# A screen that fails for some other reason must not crash the deck either.
class Hostile(Screen):
    def addstr(self, row, col, text, attr=0):
        raise ValueError("something else entirely")


deck = cyberdeck.Deck.__new__(cyberdeck.Deck)
deck.scr = Hostile()
try:
    deck._put(0, 0, [("anything", "")], 40)
    survived = True
except Exception:
    survived = False
check("a second failure is swallowed rather than raised", survived, "")

sys.exit(report())
