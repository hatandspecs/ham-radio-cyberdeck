"""The five monochrome schemes (docs/digimodes_design.md §5.9).

Each is one hue on black, with a dim variant for the timestamp and callsign
columns. Monochrome means one hue, not one intensity — and in Ripley's case
no hue at all, which is the oldest meaning of the word.

Two paths to the color, because the deck and the development machine are not
the same thing:

* **A Linux virtual console** takes `OSC P` escape sequences, which redefine
  palette entries outright. That is what allows a true amber and a true Matrix
  green rather than the ANSI approximations of yellow and green, and it is why
  switching schemes costs four escape sequences rather than a repaint.
* **Anything else** — a terminal emulator over SSH, which is where this gets
  developed — falls back to the nearest of the eight ANSI colors. Deckard
  becomes yellow and loses its amber, which is a development compromise and
  not what the panel will show.
"""

import curses
import fcntl
import os

SCHEMES = {
    "matrix":  {"name": "Matrix",  "bright": "00FF41", "dim": "00A62A", "ansi": curses.COLOR_GREEN},
    "deckard": {"name": "Deckard", "bright": "FFB000", "dim": "B27B00", "ansi": curses.COLOR_YELLOW},
    "hal":     {"name": "Hal",     "bright": "FF3B30", "dim": "A62018", "ansi": curses.COLOR_RED},
    "tron":    {"name": "Tron",    "bright": "00D9FF", "dim": "0089A8", "ansi": curses.COLOR_CYAN},
    # White is monochrome in the oldest sense: no hue at all, just intensity.
    # It redefines entries 7 and 15, which are the console's own default
    # foreground and its bold — the one scheme that changes what a plain
    # console looks like rather than a color it was not using. That is safe
    # because the deck owns tty1 and restore() puts the table back on exit.
    "ripley":  {"name": "Ripley",  "bright": "FFFFFF", "dim": "A0A0A0", "ansi": curses.COLOR_WHITE},
}
ORDER = ("matrix", "deckard", "hal", "tron", "ripley")

# Which palette entries to redefine on a Linux console.
#
# These are NOT free-choice slots. A curses color pair on the Linux console can
# only name entries 0-7 — entries 8-15 are reachable for a foreground only via
# A_BOLD, which the console implements by adding 8, and not at all for a
# background. So the two entries the console will actually land on for a given
# scheme are:
#
#     dim text      -> the ANSI index itself          (e.g. yellow = 3)
#     bright text   -> that index + 8, via A_BOLD     (e.g. 11)
#
# An earlier version redefined entries 8 and 9 instead, on the reasoning that
# nothing else uses them. Nothing else did — including this program, which
# drew with the ANSI index and never referenced them. Every scheme rendered as
# its ANSI approximation, and Deckard's amber came out as yellow.
def _slots(ansi):
    """(dim entry, bright entry) for an ANSI color index."""
    return ansi, ansi + 8


# A background can name any entry in 0-7, just not 8-15 — so the reverse-video
# bar does not have to settle for the scheme's dim entry. Entry 5 is given over
# to it and redefined to the scheme's BRIGHT hex, which makes the status bar
# full brightness while leaving dim text dim. 5 is free: no scheme uses it
# (they use 1, 2, 3, 6 and 7), and this program owns the console.
_SLOT_BAR = 5

# One set of color pairs per scheme, rather than three pairs redefined in
# place.
#
# This is not tidiness. ncurses rewrites a cell only when its character or its
# attribute changed, and an attribute includes the PAIR NUMBER but not the
# pair's definition. Redefining pair 3 leaves every cell's attribute identical,
# so ncurses skips them all — and fbcon resolved each glyph's color when it was
# drawn, so the old colors stay on screen. The symptom is unmistakable once
# seen: after switching to Hal, only the digits that happened to change value
# came out red, while the rest of the status bar stayed the previous scheme's
# green.
#
# Giving each scheme its own pair numbers makes the attribute change, which
# makes every cell dirty, which forces the repaint.
_PAIR_BASE = {name: 1 + i * 3 for i, name in enumerate(ORDER)}
_active = ORDER[0]


def _pairs(scheme_key=None):
    """(bright, dim, reverse) pair numbers for a scheme."""
    base = _PAIR_BASE[scheme_key or _active]
    return base, base + 1, base + 2




def on_linux_console():
    """True on a bare virtual console, where the palette can be redefined."""
    return os.environ.get("TERM", "") == "linux"


# Setting the console palette.
#
# `OSC P` (ESC ] P n rrggbb) is the documented way and it DOES NOT WORK on this
# deck. It is a VGA-console feature; the panel runs fbcon on the vc4 DRM
# driver, which ignores it. Proven by writing the sequence straight to
# /dev/tty1 and watching nothing happen — which also meant every scheme had
# been rendering as its ANSI approximation since the beginning, with Deckard's
# amber showing as the console's brown-to-yellow pair.
#
# What does work is the PIO_CMAP ioctl, which is what setvtrgb(1) uses. It
# takes the whole 16-entry table at once as 48 bytes of R,G,B — so the current
# table is read, three entries are replaced, and it goes back.
_GIO_CMAP = 0x4B70
_PIO_CMAP = 0x4B71

# The stock Linux console palette, used when the current table cannot be read.
_VGA = bytes((
    0, 0, 0,        170, 0, 0,      0, 170, 0,      170, 85, 0,
    0, 0, 170,      170, 0, 170,    0, 170, 170,    170, 170, 170,
    85, 85, 85,     255, 85, 85,    85, 255, 85,    255, 255, 85,
    85, 85, 255,    255, 85, 255,   85, 255, 255,   255, 255, 255,
))


def _osc_palette(slot, rrggbb):
    return f"\033]P{slot:X}{rrggbb}"


def _rgb(rrggbb):
    return (int(rrggbb[0:2], 16), int(rrggbb[2:4], 16), int(rrggbb[4:6], 16))


def _read_cmap():
    """The console's current 16-entry palette, or None if unreadable."""
    try:
        return bytearray(fcntl.ioctl(1, _GIO_CMAP, bytes(48), True))
    except (OSError, ValueError, AttributeError):
        return None


def _write_cmap(table):
    try:
        fcntl.ioctl(1, _PIO_CMAP, bytes(table))
        return True
    except (OSError, ValueError, AttributeError):
        return False


def _set_entries(entries):
    """Replace {index: "rrggbb"} in the console palette. True if it took."""
    table = _read_cmap()
    if table is None:
        table = bytearray(_VGA)
    for index, hexrgb in entries.items():
        r, g, b = _rgb(hexrgb)
        table[index * 3:index * 3 + 3] = bytes((r, g, b))
    return _write_cmap(table)


# True when the color pairs address the redefined palette slots directly, and
# the intensity attributes must therefore be left off. See apply().
_direct_palette = False

# The console palette as it was before the first apply(), so it can be put
# back. Without this the deck's hues outlive the deck: quit or crash, and
# whatever uses tty1 next — a login prompt, a traceback, fsck — inherits a
# palette in which entry 5 is the scheme's hue rather than magenta.
_original_cmap = None


def restore():
    """Put the console palette back as it was found. Safe to call twice, and
    safe where no palette was ever changed."""
    global _original_cmap
    if _original_cmap is None:
        return False
    ok = _write_cmap(_original_cmap)
    _original_cmap = None
    return ok


def apply(scheme_key):
    """Set up curses color pairs for a scheme, redefining the console
    palette where that is possible. Returns the scheme dict."""
    global _direct_palette
    scheme = SCHEMES[scheme_key]
    _direct_palette = False

    if on_linux_console():
        global _original_cmap
        if _original_cmap is None:
            _original_cmap = _read_cmap()
        dim_slot, bright_slot = _slots(scheme["ansi"])
        _direct_palette = _set_entries({
            bright_slot: scheme["bright"],
            dim_slot: scheme["dim"],
            _SLOT_BAR: scheme["bright"],
        })
        if not _direct_palette:
            # Harmless where it is ignored, and correct on a console that
            # honors it — a VGA text console, or this code running somewhere
            # other than the deck.
            try:
                os.write(1, (_osc_palette(bright_slot, scheme["bright"])
                             + _osc_palette(dim_slot, scheme["dim"])
                             + _osc_palette(_SLOT_BAR, scheme["bright"])
                             ).encode("ascii"))
            except OSError:
                pass

    # The pair always names the ANSI index, which is all a background can be
    # and all an 8-color terminfo will accept. On a console the palette behind
    # that index now holds the scheme's real hex values; elsewhere it is the
    # terminal's own approximation.
    global _active
    _active = scheme_key
    pair_bright, pair_dim, pair_reverse = _pairs(scheme_key)
    try:
        curses.init_pair(pair_bright, scheme["ansi"], curses.COLOR_BLACK)
        curses.init_pair(pair_dim, scheme["ansi"], curses.COLOR_BLACK)
        # Black ON the hue, defined outright rather than asking the terminal
        # to swap a normal pair: see attr(). On a console the bar gets its own
        # entry carrying the bright hex; elsewhere it falls back to the
        # scheme's ANSI index, since no palette has been redefined.
        bar_bg = _SLOT_BAR if _direct_palette else scheme["ansi"]
        curses.init_pair(pair_reverse, curses.COLOR_BLACK, bar_bg)
    except curses.error:
        pass
    return scheme


def attr(kind):
    """Map a render kind to a curses attribute.

    A_BOLD is what selects the bright half of a scheme, on a console and off
    it. On a console it moves the foreground to the redefined `ansi + 8` entry
    holding the scheme's bright hex value; elsewhere it asks the terminal for
    its own bright variant. Either way it is required, not optional.

    A_DIM is dropped on a console: the Linux console ignores it, and the dim
    hue is already carried by the base palette entry.
    """
    pair_bright, pair_dim, pair_reverse = _pairs()
    if kind == "reverse":
        # No A_REVERSE and no A_BOLD. The pair is already black-on-hue, and
        # asking for both was what made the status bar unreadable: with
        # A_REVERSE the console swaps foreground and background, then applies
        # A_BOLD's intensity to what is now the background, leaving text the
        # same hue as the bar it sits on. A filled bar needs black text in it,
        # so define that directly and let no attribute negotiate it away.
        return curses.color_pair(pair_reverse)
    if kind in ("dim", "note"):
        return curses.color_pair(pair_dim) | (0 if _direct_palette else curses.A_DIM)
    return curses.color_pair(pair_bright) | curses.A_BOLD


def cycle(current):
    return ORDER[(ORDER.index(current) + 1) % len(ORDER)]
