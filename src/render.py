"""Turning a Session into lines of text.

Kept free of curses so the layout can be tested at any width without a
terminal, which matters because the grid is not fixed: the 800x480 panel gives
66x20 at the proposed 12x24 console font, 80x24 at 10x20, and 50x15 at 16x32
(docs/design_doc.md §3.3). Everything here adapts to the width it is given rather
than assuming one.

A rendered line is a list of (text, kind) segments. The kind names an
appearance — "dim", "bright", "reverse" — and the curses layer decides what
that means in the current color scheme. Nothing here knows about color.
"""

import time

TIME_W = 5          # "2114Z"
WHO_W = 7           # callsign column, left-justified

# Status fields in the order they are dropped when the screen is too narrow.
# Callsign, transmit state and the clock are never dropped: they are the three
# a glance is for.
_DROP_ORDER = ("imd", "snr", "carrier", "freq", "mode")


def _wrap_spans(text, width):
    """Wrap, returning (line, characters consumed from `text`) for each line.

    The count is what makes an exact cursor position possible. A wrapped line
    swallows the space it broke at and a hard break swallows the newline, so
    the sum of the line lengths is smaller than the source and stepping
    through output lines alone puts the caret in the wrong place.

    Newlines are hard breaks. Without that they reach curses as literal
    characters inside a string handed to addstr, which moves the cursor and
    paints the rest of the compose buffer over whatever is below it — the
    compose area is the one place the operator's own newlines are rendered
    before being split into transcript entries.
    """
    if width <= 0:
        return [("", 0)]
    out = []
    paragraphs = text.split("\n")
    for n, para in enumerate(paragraphs):
        hard = 1 if n < len(paragraphs) - 1 else 0   # the newline that ended it
        lines, line = [], ""
        for word in para.split(" "):
            while len(word) > width:
                if line:
                    lines.append((line, len(line))); line = ""
                lines.append((word[:width], width)); word = word[width:]
            if not line:
                line = word
            elif len(line) + 1 + len(word) <= width:
                line += " " + word
            else:
                lines.append((line, len(line) + 1)); line = word   # +1: the space
        lines.append((line, len(line) + hard))
        out.extend(lines)
    return out


def _wrap(text, width):
    """Wrap on spaces and newlines, breaking long runs rather than overflowing.

    Received text can contain a hundred characters with no space in it when a
    signal is marginal, and a line that overflows the screen is worse than one
    broken mid-word.
    """
    if width <= 0:
        return [""]
    return [line for line, _used in _wrap_spans(text, width)]


def entry_lines(entry, width, timestamps=True, utc=True):
    """One transcript entry as rendered lines."""
    gutter = (TIME_W + 1 if timestamps else 0) + WHO_W + 1
    body_w = max(8, width - gutter - 1)
    stamp = ""
    if timestamps:
        t = time.gmtime(entry.when) if utc else time.localtime(entry.when)
        stamp = time.strftime("%H%M", t) + "Z"

    out = []
    for i, text in enumerate(_wrap(entry.text, body_w)):
        segs = [(" ", "dim")]
        if timestamps:
            segs.append(((stamp if i == 0 else "").ljust(TIME_W) + " ", "dim"))
        segs.append(((entry.who if i == 0 else "").ljust(WHO_W) + " ", "dim"))
        segs.append((text, "note" if entry.who == "--" else "bright"))
        out.append(segs)
    return out


def transcript_lines(entries, width, height, timestamps=True, scroll=0):
    """The last `height` lines of the transcript, oldest first.

    `scroll` counts lines back from the live tail, for PgUp review.
    """
    rendered = []
    for entry in entries:
        rendered.extend(entry_lines(entry, width, timestamps))
    if height <= 0:
        return []
    end = len(rendered) - scroll
    end = max(0, min(end, len(rendered)))
    start = max(0, end - height)
    window = rendered[start:end]
    return window + [[("", "bright")]] * (height - len(window))


def frequency(hz):
    """A VFO reading at the radio's own resolution: 14.070.589

    Megahertz, kilohertz, hertz, grouped with dots. Digital work is done in
    tens of hertz inside a 31 Hz-wide signal, so rounding to three decimals
    throws away the part of the number that matters when comparing the deck's
    reading against the radio's display.
    """
    try:
        hz = int(round(float(hz)))
    except (TypeError, ValueError):
        return ""
    if hz <= 0:
        return ""
    mhz, rest = divmod(hz, 1_000_000)
    khz, rest = divmod(rest, 1_000)
    return f"{mhz}.{khz:03d}.{rest:03d}"


# Nominal bandwidths for modes whose name defines the number, used when
# fldigi reports 0. It reports a figure only where bandwidth is a settable
# parameter of the modem — Hell, for instance — and 0 for everything fixed,
# which is most of what gets used. Displaying that 0 says BPSK31 is zero hertz
# wide, which is worse than saying nothing.
_NOMINAL_BW = {
    "BPSK31": 31, "QPSK31": 31, "PSK31": 31,
    "BPSK63": 63, "QPSK63": 63, "PSK63": 63,
    "BPSK125": 125, "PSK125": 125,
}


def mode_bandwidth(name, reported=0):
    """Signal bandwidth in Hz as a string, or an em dash when unknown.

    Only figures that are definitional are asserted: the PSK family from its
    symbol rate, and Olivia and Contestia from the name itself, where the
    second number IS the bandwidth. Anything else falls back to whatever
    fldigi reports, and to nothing at all when it reports zero.
    """
    try:
        reported = int(reported)
    except (TypeError, ValueError):
        reported = 0
    if reported > 0:
        return f"{reported} Hz"

    name = (name or "").upper()
    if name in _NOMINAL_BW:
        return f"{_NOMINAL_BW[name]} Hz"

    # OLIVIA-8/250, CONTESTIA-8/500: tones/bandwidth.
    if "/" in name and name.split("-")[0] in ("OLIVIA", "CONTESTIA"):
        tail = name.rsplit("/", 1)[-1]
        if tail.isdigit():
            return f"{tail} Hz"
    return "\u2014"


# The tuning screen's readouts and key hints. These live here, not in the
# terminal, so that the documentation screenshots render from the same source
# as the panel — the hand-copied version in tools/capture_screens.py drifted
# every time a control was added, and the published screenshot quietly stopped
# matching the deck.
TUNE_HINTS = (
    "  \u2190 \u2192   carrier \u00b110 Hz        \u2191 \u2193   search signal",
    "  ,  .   VFO \u00b1100 Hz          <  >   VFO \u00b11 kHz",
    "  a AFC    s squelch    + - level    r RSID    t TXID    v REV",
)


def tune_rows(fields, width):
    """The body of the F2 screen as plain strings.

    `fields` carries already-formatted values so this stays free of fldigi:
    freq, rig_mode, carrier, width, snr, imd, quality, afc, squelch,
    squelch_level, rsid, txid, reverse.
    """
    def onoff(v, pad=True):
        return ("on " if pad else "on") if v else "off"

    q = float(fields.get("quality", 0) or 0)
    bar_w = max(10, width - 22)
    filled = int(bar_w * min(max(q, 0), 100) / 100)
    return [
        f"  rig      {fields.get('freq', '')}  {fields.get('rig_mode', '')}",
        f"  carrier  {fields.get('carrier', 0)} Hz        width  "
        f"{fields.get('width', '')}",
        # Not labeled here. fldigi's two status strings carry their own
        # labels and change meaning with the mode: under PSK they read
        # "S/N 6 dB" and "IMD ---", under RTTY the first becomes "45 /170" —
        # baud and shift — and the second becomes the S/N. Prefixing them
        # printed "S/N   S/N 6 dB" and lied outright on RTTY.
        f"  signal   {(fields.get('snr') or '').strip()}"
        f"   {(fields.get('imd') or '').strip()}",
        "",
        f"  quality  {'\u2588' * filled}{'\u2591' * (bar_w - filled)}  {q:.0f}",
        "",
        f"  AFC {onoff(fields.get('afc'))}  squelch {onoff(fields.get('squelch'))}"
        f" ({float(fields.get('squelch_level', 0)):.0f})"
        f"  RSID {onoff(fields.get('rsid'))}"
        f"  TXID {onoff(fields.get('txid'))}"
        f"  REV {onoff(fields.get('reverse'), pad=False)}",
        "",
    ] + [f"  {'decode' if i == 0 else '      '}   {line}"
         for i, line in enumerate(
             preview_lines(fields.get("preview", ""), width - 12, 2))] + [
        "",
        # The last transcript marker, repeated here because this screen hides
        # the transcript — and a search that found nothing has to say so
        # somewhere the operator is looking when they press the key.
        f"  {(fields.get('note') or '')[:width - 4]}",
    ]


def preview_lines(text, width, lines=2):
    """The tail of what is being decoded, as `lines` rows.

    Text fills the bottom row; when it reaches the right-hand edge the row
    above takes what came before and the bottom starts again empty. That is
    just the last N lines of the wrapped text, but it reads as a two-line
    window scrolling under the operator, which is what makes it usable while
    tuning: a full line of words is a clear result, half a line is not.
    """
    flat = _flatten(text)
    if not flat:
        return [""] * (lines - 1) + ["\u2014"]
    wrapped = _wrap(flat, max(1, width)) or [""]
    out = wrapped[-lines:]
    return [""] * (lines - len(out)) + out


def _flatten(text):
    """One line of printable characters, runs of whitespace collapsed."""
    printable = "".join(c if 32 <= ord(c) < 127 else " " for c in (text or ""))
    return " ".join(printable.split())


def preview(text, width):
    """The tail of what is being decoded, as one line.

    This is the instrument for two questions the numbers cannot answer: is the
    carrier actually on a signal, and — on RTTY — is the mark/space sense
    right. Plausible letters that never form words mean `v`; noise means the
    carrier is not on anything. Both are invisible in S/N and the quality bar.
    """
    if width < 4:
        return ""
    flat = _flatten(text)
    return flat[-width:] if flat else "\u2014"


EDIT_HINT = "  Enter save   Esc cancel   ^U clear the line"
# Only shown when editing a message memory: the tokens mean nothing when the
# field being edited is the callsign they would be filled in from.
# 62 characters, against the panel's 66. Adding another token means shortening
# the tail, not letting it wrap.
EDIT_TOKENS_HINT = ("  {call} {name} {qth} {grid} {rig} {ant} {power};"
                    "  \\n new line")


def edit_hint(secret=False, revealed=False):
    """The key line under the editor.

    A masked field gets its own, because the keys differ and because the one
    that matters is not guessable. A WiFi passphrase is long, typed on a
    keyboard the operator may be holding, onto a panel showing nothing back —
    and a single wrong character returns as "wrong passphrase" a minute later
    with no way to tell which character it was.

    It says "show" or "hide" according to the current state rather than naming
    the key twice, so the line describes what pressing it will do.
    """
    if not secret:
        return EDIT_HINT
    return "  Enter join   Esc cancel   ^U clear   ^R " + (
        "hide it again" if revealed else "show the passphrase")


def status_line(fields, width):
    """The top line: one row, always visible, reverse video.

    Fields are dropped from the least useful end when the width will not take
    them all, so a 50-column deck still shows callsign, state and clock.

    The radio's own mode (PKTUSB and friends) is deliberately absent. It is
    legible at a glance on the radio's front panel, it changes about twice a
    session, and at 66 columns the seven columns it cost were the difference
    between fldigi's second status field fitting and not. That field is worth
    more: under PSK it is IMD, which says whether the transmitter is being
    driven too hard, and under RTTY it carries the signal-to-noise reading.
    It is still on the F2 tuning screen, one keystroke away.
    """
    parts = {
        "call":     fields.get("call", ""),
        "freq":     fields.get("freq", ""),
        "mode":     fields.get("mode", ""),
        "carrier":  fields.get("carrier", ""),
        "snr":      fields.get("snr", ""),
        "imd":      fields.get("imd", ""),
    }
    order = ["call", "freq", "mode", "carrier", "snr", "imd"]
    shown = [k for k in order if parts[k]]
    clock = fields.get("clock", "")
    state = fields.get("state", "")

    def build(keys):
        left = "  ".join(parts[k] for k in keys)
        right = f"{state}  {clock}".strip()
        pad = width - len(left) - len(right) - 2
        if pad < 1:
            return None
        return " " + left + " " * pad + right + " "

    for _ in range(len(_DROP_ORDER) + 1):
        line = build(shown)
        if line is not None:
            return [(line, "reverse")]
        for candidate in _DROP_ORDER:
            if candidate in shown:
                shown.remove(candidate)
                break
        else:
            break
    # Nothing fits: show the irreducible minimum, truncated.
    return [((" " + parts["call"] + " " + state).ljust(width)[:width], "reverse")]


def compose_lines(text, indicator, width, height, cursor=None):
    """The bottom region: what is being typed, with the buffer indicator
    right-aligned on the last line. Returns lines and the cursor position
    within them as (row, col).

    `cursor` is an index into `text`; None means the end, which is where it
    sits unless the line is being edited.
    """
    body_w = max(8, width - 2)
    spans = _wrap_spans(text, body_w) or [("", 0)]
    wrapped = [line for line, _used in spans]
    shown = wrapped[-height:] if height else wrapped

    if cursor is None:
        cursor = len(text)
    cursor = max(0, min(len(text), cursor))
    # Walk the wrapped lines counting SOURCE characters until the cursor index
    # is reached, so the caret lands where the character actually is. Each
    # line reports what it consumed, which is more than it displays wherever a
    # space or a newline was swallowed by the break.
    remaining, row, col = cursor, 0, 0
    for i, (line, used) in enumerate(spans):
        if remaining <= len(line):
            row, col = i, remaining
            break
        remaining -= used
        row, col = i, len(line)
    else:
        row, col = len(spans) - 1, len(spans[-1][0])

    hidden = len(wrapped) - len(shown)
    cursor_row = max(0, row - hidden)
    cursor_col = 1 + col
    wrapped = shown

    out = []
    for i, line in enumerate(wrapped):
        if i == len(wrapped) - 1:
            pad = width - len(line) - len(indicator) - 2
            if pad >= 1:
                out.append([(" " + line + " " * pad, "bright"), (indicator + " ", "dim")])
            else:
                out.append([(" " + line, "bright")])
        else:
            out.append([(" " + line, "bright")])
    while len(out) < height:
        out.append([("", "bright")])
    return out, (cursor_row, min(cursor_col, width - 1))


def rule(width):
    return [("─" * width, "dim")]


def plain(segments):
    """A rendered line as a plain string, for tests."""
    return "".join(text for text, _ in segments)


# Key hints, longest first. The deck's grid is 66 columns at the proposed font
# and 50 at the largest one, so the line has to shed bindings rather than be
# truncated mid-word — a hint that reads "^C abor" is worse than no hint.
_HINT_TIERS = (
    # The two widest carry `^O ^P screen`, which is the only place the ring is
    # taught. At 66 columns -- the deck -- that costs `F5+ memory`, which the
    # digimode menu still lists; `^C abort` stays, because a key that stops the
    # transmitter is worth more on a footer than one that inserts a macro.
    " F1 menu  F2 tune  F3 mode  F5+ memory  ^T over  ^Y hand  ^O ^P screen",
    " F1 menu  F2 tune  ^T over  ^Y hand  ^C abort  ^O ^P screen",
    " F1 menu    F2 tune    F5+ memory    ^T over    ^Y hand    ^C abort",
    " F1 menu   F2 tune   F5+ memory   ^T over   ^Y hand   ^C abort",
    " F1 menu  F2 tune  F5+ memory  ^T over  ^Y hand  ^C abort",
    " F1 menu  F2 tune  ^T over  ^Y hand  ^C abort",
    " F1 menu  F2 tune  ^T over  ^Y hand",
    " F1 menu  F2 tune  F3 mode  F4 color  ^T over  ^Y hand",
    " F2 tune  F3 mode  F4 color  ^T over  ^Y hand",
    " F2 tune  ^T over  ^Y hand  ^C abort",
    " ^T over  ^Y hand  ^C abort",
    " ^T/^K/^C",
)


def hint_line(width):
    for tier in _HINT_TIERS:
        if len(tier) <= width:
            return [(tier, "dim")]
    return [(_HINT_TIERS[-1][:width], "dim")]

# Block digits for the pairing passkey (§5.9's aesthetic, and legibility).
#
# The passkey is the one number on this deck that has to be read off the
# screen and typed somewhere else, by someone leaning over a 5" panel, often
# in a hurry before the pairing attempt times out. Six characters of body text
# is the wrong size for that job. Five rows of block characters is the size a
# terminal of the period would have used for exactly the same reason — it is
# the one place where the vintage treatment and the practical answer are the
# same thing.
_DIGITS = {
    "0": ("███", "█ █", "█ █", "█ █", "███"),
    "1": ("  █", "  █", "  █", "  █", "  █"),
    "2": ("███", "  █", "███", "█  ", "███"),
    "3": ("███", "  █", "███", "  █", "███"),
    "4": ("█ █", "█ █", "███", "  █", "  █"),
    "5": ("███", "█  ", "███", "  █", "███"),
    "6": ("███", "█  ", "███", "█ █", "███"),
    "7": ("███", "  █", "  █", "  █", "  █"),
    "8": ("███", "█ █", "███", "█ █", "███"),
    "9": ("███", "█ █", "███", "  █", "███"),
    " ": ("   ", "   ", "   ", "   ", "   "),
}
BIG_ROWS = 5


def big_number(text, width):
    """`text` as five rows of block characters, centred in `width`.

    Anything without a glyph falls back to the plain string rather than
    disappearing: a passkey BlueZ sends in an unexpected shape must still be
    readable, even if it is not beautiful.
    """
    glyphs = [_DIGITS.get(ch) for ch in text]
    if not text or any(g is None for g in glyphs):
        return [text.center(width)[:width]]
    rows = []
    for i in range(BIG_ROWS):
        line = "  ".join(g[i] for g in glyphs)
        rows.append(line.center(width)[:width] if len(line) <= width
                    else line[:width])
    return rows


def frame(title, body, width, height, footer=""):
    """A boxed panel, drawn with the terminal's own line characters.

    Used by the pairing screen rather than the menu renderer. Pairing is the
    one screen that interrupts operating to do something else entirely, and
    giving it a border says so — the same reason a period terminal drew a box
    around anything modal.
    """
    inner = max(4, width - 2)
    out = ["┌" + "─" * inner + "┐"]
    head = f" {title} ".center(inner, "─") if title else "─" * inner
    out.append("├" + head + "┤") if title else None
    for line in body:
        out.append("│" + line[:inner].ljust(inner) + "│")
    while len(out) < max(2, height - (2 if footer else 1)):
        out.append("│" + " " * inner + "│")
    out.append("└" + "─" * inner + "┘")
    if footer:
        out.append(" " + footer[:width - 1])
    return out[:height]


# Screen row of the first device on the pairing screen: the title bar, the top
# border and one blank line come first. A tap is turned into a device index
# with this, so it has to track pair_screen() rather than be guessed at.
PAIR_ROW0 = 3


def pair_screen(state, devices, width, height, passkey="", error="",
                selected=0, tick=0):
    """The pairing screen, drawn as a framed panel.

    Given its own renderer rather than going through the menu one. Pairing
    interrupts operating to do something else entirely, and a border says so —
    the same reason a terminal of the period drew a box around anything modal.
    The passkey inside it is set in block characters because it is the one
    number on this deck that has to be read off the panel and typed somewhere
    else, against a timeout, by someone leaning over a five inch screen.
    """
    inner = max(20, width - 2)
    body = []

    def line(text="", kind="bright"):
        body.append([("│", "dim"), (text[:inner].ljust(inner), kind),
                     ("│", "dim")])

    out = [[(" PAIR A KEYBOARD".ljust(width), "reverse")]]
    out.append([("┌" + "─" * inner + "┐", "dim")])

    if state == "passkey":
        line()
        line("  TYPE THIS ON THE KEYBOARD BEING PAIRED,")
        line("  THEN PRESS ITS ENTER KEY:")
        line()
        for row in big_number(passkey, inner):
            line(row)
        line()
        line("  It will not respond until the bond is made.", "dim")
    elif state == "pairing":
        line()
        line("  Pairing" + "." * (1 + tick % 3))
        line()
        line("  Waiting for the keyboard to answer.", "dim")
    elif state == "paired":
        line()
        line("  ✓  PAIRED, AND TRUSTED.")
        line()
        line("  It will reconnect by itself from now on.", "dim")
        line("  Try typing on it.", "dim")
        if error:
            line()
            line("  " + error[:inner - 2], "dim")
    elif state == "failed":
        line()
        line("  ✗  PAIRING FAILED")
        line()
        line("  " + (error or "no reason given")[:inner - 2], "dim")
        line()
        line("  Hold the keyboard's pairing key until its light", "dim")
        line("  blinks quickly, then try again.", "dim")
    else:
        line()
        if not devices:
            line("  No keyboards found yet.")
            line()
            line("  Hold the keyboard's pairing key until its", "dim")
            line("  light blinks quickly, then wait a few seconds.", "dim")
        else:
            for n, dev in enumerate(devices[:9], start=1):
                mark = "▸" if n - 1 == selected else " "
                marks = []
                if dev.rssi is not None:
                    marks.append("here")
                if dev.paired:
                    marks.append("paired")
                name = (dev.name or "(unnamed)")[:24]
                line(f" {mark} {n}  {name:<24} {dev.tail:<6} "
                     f"{' '.join(marks)}")
            line()
            line("  Two entries, one name? A keyboard with channel", "dim")
            line("  buttons shows one per channel; the address differs.", "dim")
        line()
        line("  " + "·" * (1 + tick % 4) + " scanning", "dim")

    out.extend(body)
    while len(out) < height - 2:
        out.append([("│", "dim"), (" " * inner, "bright"), ("│", "dim")])
    out.append([("└" + "─" * inner + "┘", "dim")])

    footers = {"passkey": "Esc cancel", "pairing": "Esc cancel",
               "paired": "Esc back", "failed": "Esc back"}
    footer = footers.get(state,
                         "Esc back   ↑↓ move   Enter pair   f forget   tap to choose")
    out.append([(" " + footer[:width - 1], "dim")])
    return out[:height]


# Screen row of the first network on the WiFi screen: the title bar, the top
# border, the radio line and one blank line come first. A tap becomes an index
# through this, so it has to track wifi_screen() rather than be guessed at —
# and it was guessed at first, one row out, which is a tap selecting the wrong
# network and reads as a broken touchscreen. test_wifi.py asserts it against
# the renderer instead.
WIFI_ROW0 = 4


def wifi_screen(state, networks, width, height, radio="on", selected=0,
                message="", error="", tick=0, ssid="", retry=False):
    """The WiFi screen, framed like the pairing screen and for the same reason.

    Joining a network interrupts operating to do something else entirely, and
    a border says so. It shares the pairing screen's shape deliberately: the
    two are the same task from the operator's side — find a thing that is
    nearby, choose it, prove you are allowed to use it — and a deck with two
    unrelated-looking screens for that would be teaching two lessons where one
    will do.

    Signal is drawn as four blocks rather than a percentage. At arm's length
    on a five inch panel the question is never "is this 58 or 62" but "is this
    one of the strong ones".
    """
    inner = max(20, width - 2)
    body = []

    def line(text="", kind="bright"):
        body.append([("│", "dim"), (text[:inner].ljust(inner), kind),
                     ("│", "dim")])

    out = [[(" WIFI".ljust(width), "reverse")]]
    out.append([("┌" + "─" * inner + "┐", "dim")])

    if state == "unavailable":
        line()
        line("  WiFi cannot be controlled from here.")
        line()
        line("  " + (error or "NetworkManager is not answering")[:inner - 2], "dim")
        line()
        line("  The deck's own networks still work; they are set", "dim")
        line("  in deck.secrets when the card is built.", "dim")
    elif state == "working":
        line()
        line("  " + (message or "working") + "." * (1 + tick % 3))
        line()
        line("  This can take most of a minute on a weak signal.", "dim")
    elif state == "joined":
        line()
        line(f"  ✓  JOINED {ssid}"[:inner])
        line()
        line("  It will reconnect by itself from now on.", "dim")
    elif state == "failed":
        line()
        line(f"  ✗  COULD NOT JOIN {ssid}"[:inner])
        line()
        line("  " + (error or "no reason given")[:inner - 2], "dim")
        if retry:
            line()
            line("  Enter types the passphrase again.", "dim")
            line()
            line("  Nothing was kept: a wrong passphrase would", "dim")
            line("  otherwise be saved and reused silently.", "dim")
    else:
        radio_text = {"on": "RADIO ON", "off": "RADIO OFF"}.get(
            radio, "RADIO STATE UNKNOWN")
        line(f"  {radio_text}        r turns it {'off' if radio == 'on' else 'on'}")
        line()
        if radio == "off":
            line("  The radio is off, so nothing can be seen.")
            line()
            line("  Off is a legitimate way to run: the deck keeps", "dim")
            line("  time on its own clock and the radio saves power.", "dim")
        elif not networks:
            line("  Nothing found yet.")
            line()
            line("  s scans again. A scan takes a few seconds and", "dim")
            line("  finds nothing at all indoors surprisingly often.", "dim")
        else:
            for n, net in enumerate(networks[:8], start=1):
                mark = "▸" if n - 1 == selected else " "
                line(f" {mark} {n}  {net.label(inner - 6)}")
            line()
            line("  ✓ connected   · known   WPA2 etc = needs a passphrase", "dim")
        if error:
            line()
            line("  " + error[:inner - 2], "dim")

    out.extend(body)
    while len(out) < height - 2:
        out.append([("│", "dim"), (" " * inner, "bright"), ("│", "dim")])
    out.append([("└" + "─" * inner + "┘", "dim")])

    footers = {
        "working": "Esc cancel",
        "joined": "Esc back",
        "failed": "Enter try the passphrase again   Esc back" if retry else "Esc back",
        "unavailable": "Esc back",
    }
    # 65 characters at most, because the panel is 66 wide and the footer is
    # drawn with a leading space. The obvious wording ran to 68 and was
    # silently clipped to "w rad", losing the one key that is not guessable.
    footer = footers.get(
        state, "Esc back  ↑↓ move  Enter join  n name  f forget  s scan  r radio")
    out.append([(" " + footer[:width - 1], "dim")])
    return out[:height]


# Screen row of the first contact on the log screen: the header, the rule
# under it, and the column heading come first. Kept as a constant for the same
# reason PAIR_ROW0 is — anything that turns a row number back into a record has
# to track this function rather than guess at it. It was 2 before the column
# heading existed, and the heading moving it is exactly the kind of change
# this constant is here to absorb.
LOG_ROW0 = 3

# Screen row of the column heading, one above the first contact.
LOG_HEADING_ROW = LOG_ROW0 - 1


# On and off, in glyphs the shipped console font is known to have. `■`/`□`
# are not among them (AGENTS.md); `█` is a filled cell in a console font,
# which is what a filled square means here, and `·` is the lightest mark that
# still reads as a place where something could be.
FIELD_ON, FIELD_OFF = "\u2588", "\u00b7"


def confirm_screen(title, lines, width, height, footer=""):
    """A question that has to be answered before something is destroyed.

    Its own screen rather than a line on another one: deleting a log deletes
    contacts, and a prompt that shares a screen with the thing being deleted
    is a prompt that gets answered by reflex. The default is to keep -- Esc
    and every key but Enter cancel.
    """
    out = [[((" " + title).ljust(width)[:width], "reverse")], rule(width)]
    out.append([(" " * width, "")])
    for line in lines:
        out.append([(("  " + line).ljust(width)[:width], "bright")])
    while len(out) < height - 2:
        out.append([(" " * width, "")])
    out.append(rule(width))
    out.append([((" " + (footer or
                 "Enter delete   Esc keep   (any other key keeps it)"))
                 .ljust(width)[:width], "dim")])
    return out[:height]


ACTIVITY_ROW0 = 2


def activity_screen(rows, selected, width, height, current="", message=""):
    """The sessions in the log: resume one, start one, rename or forget one.

    `rows` is `Deck._activity_choices()` output -- the master log first, then
    a row per session. The one in use is marked, the contact count is shown
    because it is what makes forgetting one consequential, and the date is
    shown because it is what tells two activations of the same park apart.

    The SCHEMA each session was logged under is shown too, because §7i makes
    resuming one apply that schema: a list that did not say which would leave
    the operator unable to predict what resuming does. Blank for the master
    log, which spans every schema there has ever been and so has none of its
    own, and `general` for a session whose contacts carry no schema at all.
    """
    out = [[(" ACTIVITIES".ljust(width)[:width], "reverse")], rule(width)]
    if not rows:
        out.append([("  nothing logged under an activity yet"
                     .ljust(width)[:width], "dim")])
    for i, row in enumerate(rows):
        mark = "\u25b8" if i == selected else " "
        star = "*" if row["name"] == current else " "
        count = f"{row['contacts']} QSO{'' if row['contacts'] == 1 else 's'}"
        # The master log gets no schema word: it holds every contact under
        # every schema, so naming one would be wrong rather than missing.
        kind = "" if row.get("master") else (row.get("type") or "general")
        line = (f"{mark}{star} {row['name'][:20]:<20} "
                f"{kind.lower()[:8]:<8} "
                f"{row['date'] or '':<10}  {count}")
        out.append([(line.ljust(width)[:width],
                     "bright" if i == selected else "")])
    while len(out) < height - 3:
        out.append([(" " * width, "")])
    out.append(rule(width))
    out.append([((" " + message).ljust(width)[:width],
                 "dim" if message else "")])
    # 63 of 66. `r` is here because renaming is the one correction this
    # screen can make to a session, and a key nobody can see is a key nobody
    # uses -- the schema picker's `e` was invisible for the same reason.
    out.append([((" Esc back  \u2191\u2193 move  Enter resume  "
                  "n new  r rename  d forget").ljust(width)[:width], "dim")])
    return out[:height]


# How many fields fit on one selection page. The list outgrew both the screen
# and the seventeen keys that can jump to a row, so it pages -- and the page is
# derived from where the cursor is rather than held separately, which means
# walking off the bottom of one page simply arrives at the top of the next.
# Fourteen, so that page one holds QRZ's whole QSO record -- see the comment
# over `activities.ENTRY_FIELDS`, which is where the order comes from. The
# ceiling is `len(activities.PICK_KEYS)`, since every row on a page has a key
# printed beside it, and the screen itself fits `height - 4`.
FIELDS_PER_PAGE = 14


def field_select_screen(rows, selected, width, height, title="SELECT FIELDS",
                        footer="", per_page=FIELDS_PER_PAGE):
    """Which fields an activity uses. `rows` is [(name, label, on), ...].

    One screen for one question. The ordering is asked separately, because
    answering both at once means every keystroke has to say which it meant.
    """
    out = []
    chosen = sum(1 for _n, _l, on in rows if on)
    pages = max(1, (len(rows) + per_page - 1) // per_page)
    page = min(max(0, selected // per_page), pages - 1)
    shown = rows[page * per_page:(page + 1) * per_page]

    head = f" {title}"
    if pages > 1:
        head += f"  {page + 1}/{pages}"
    right = f"{chosen} of {len(rows)} chosen "
    pad = max(1, width - len(head) - len(right))
    out.append([((head + " " * pad + right)[:width].ljust(width), "reverse")])
    out.append(rule(width))

    for i, (name, label, on) in enumerate(shown, start=page * per_page):
        mark = "\u25b8" if i == selected else " "
        box = FIELD_ON if on else FIELD_OFF
        help_text = ""
        try:
            import activities
            help_text = activities.FIELD_HELP.get(name, "")
        except Exception:
            help_text = ""
        # The jump key is the row's position ON THIS PAGE, so the keys read
        # 1..9,a.. on every page rather than running out after the first.
        key = ""
        try:
            import activities as _acts
            key = _acts.pick_key(i - page * per_page)
        except Exception:
            key = ""
        line = f"{mark} {key or ' '}  {box}  {label:<9} {help_text}"
        out.append([(line[:width].ljust(width),
                     "bright" if i == selected else "")])

    while len(out) < height - 2:
        out.append([(" " * width, "")])
    out.append(rule(width))
    default = ("Esc cancel  \u2191\u2193 move  Space toggle  Enter order")
    if pages > 1:
        default = ("Esc cancel  \u2191\u2193 move  \u2190\u2192 page  "
                   "Space toggle  Enter order")
    out.append([((" " + (footer or default))[:width].ljust(width), "dim")])
    return out[:height]


def field_order_screen(order, selected, width, height, title="ORDER FIELDS",
                       footer="", message="", fixed="Call"):
    """The chosen fields, numbered. `order` is [(n, name, label), ...].

    Typing a number moves the highlighted row to it and renumbers everything,
    so the list always reads 1..N with no gaps — which is what makes it safe
    to keep typing numbers until the order looks right.

    `fixed` is drawn above them as row 0 and cannot be selected or moved. It
    is the callsign: it is always the first field on the form, it is not part
    of any activity's `entry` list, and a screen that numbered the others
    1..N without it invited the question of where the callsign had gone — or
    worse, suggested that field 1 is what the operator types first. Passing
    `fixed=""` leaves it out.
    """
    out = []
    head = f" {title}"
    right = "type a number to move a row "
    pad = max(1, width - len(head) - len(right))
    out.append([((head + " " * pad + right)[:width].ljust(width), "reverse")])
    out.append(rule(width))

    if fixed:
        # Dim, unmarked and unnumbered-past-zero: it has to read as part of
        # the list to be useful and as something that cannot be moved to be
        # honest.
        out.append([(f"  0.  {fixed}".ljust(width)[:width], "dim")])
    for i, (number, _name, label) in enumerate(order):
        mark = "\u25b8" if i == selected else " "
        line = f"{mark} {number}.  {label}"
        out.append([(line[:width].ljust(width),
                     "bright" if i == selected else "")])

    while len(out) < height - 3:
        out.append([(" " * width, "")])
    out.append(rule(width))
    out.append([((" " + message)[:width].ljust(width),
                 "dim" if message else "")])
    out.append([((" " + (footer or
                 "Esc back   \u2191\u2193 move   1-9 renumber   "
                 "Enter name it"))[:width].ljust(width), "dim")])
    return out[:height]


def form_rows(form, width, columns=2, focus_cursor=True):
    """The entry form as lines of (text, attr) segments.

    Two columns by default, because one field per row would eat nine of the
    panel's twenty rows and leave nothing for the contacts already logged —
    and seeing the last few is what tells an operator the log is working.

    The focused field is drawn in reverse with a block cursor at the insertion
    point, the same convention the transcript's compose line uses, so there is
    only one thing on this deck that means "you are typing here".
    """
    if form is None:
        return []
    label_w = max([len(f.label) for f in form.fields] + [4])
    cell = max(12, (width - 2) // columns - label_w - 2)
    rows, line = [], []

    for i, field in enumerate(form.fields):
        focused = i == form.index
        text = field.value
        if focused and focus_cursor:
            pos = min(form.cursor, len(text))
            shown = text[:pos] + "\u2588" + text[pos:] if pos >= len(text) \
                else text
        else:
            shown = text
        shown = shown[:cell]
        # A sticky field that is set carries a mark, so "why is this still
        # here" has an answer on the screen rather than in the documentation.
        mark = "*" if field.sticky and field.value else " "
        label = f"{field.label:>{label_w}}"
        value = f"{shown:<{cell}}"
        line.append((label, "dim"))
        line.append((" ", ""))
        line.append((value, "reverse" if focused else ""))
        line.append((mark, "dim"))
        if len(line) >= columns * 4:
            rows.append([(" ", "")] + line)
            line = []
    if line:
        rows.append([(" ", "")] + line)
    return rows


def log_body_rows(height, form=None, width=66, lines=1):
    """How many CONTACTS the list can show, given the form below it.

    Contacts, not rows, because a contact is `lines` rows tall. Shared with the
    deck so that clamping a scroll position and drawing it agree. When they did
    not, the list could be scrolled to an offset that drew nothing and looked
    like a hang.
    """
    entry_rows = len(form_rows(form, width)) if form is not None else 0
    rows = max(1, height - 6 - max(1, entry_rows))
    per = max(LOG_LINES_MIN, min(int(lines or 1), LOG_LINES_MAX))
    return max(1, rows // per)


def log_scroll_max(records, height, form=None, width=66, lines=1):
    """The furthest back the list can be scrolled: 0 when it all fits."""
    return max(0, len(records) - log_body_rows(height, form, width, lines))


def log_screen(records, entry, width, height, header=None, message="",
               cursor=None, form=None, scroll=0, lines=1, selected=None):
    """The log screen: what has been worked, and the line being typed.

    Given the whole display rather than a prompt under the transcript, because
    on SSB the transcript has nothing on it worth reading. The header carries
    what the operator is about to say out loud — band, mode, frequency — which
    is exactly what the status line was showing and is no longer visible.

    Every optional field is absent rather than blank when unset: no `my_park`
    in the header and no park column in the body unless a park is actually in
    use. A log of ordinary contacts shows no trace of the activity fields.

    A `my_park` in the header reserves the reference column even while the
    contacts have none. That is the one case where a blank field is the right
    thing to draw: during an activation the column being there is what makes
    the list scannable, and a column that appears on the first park-to-park
    and shifts every row under it is worse than an empty one.

    `records` are oldest first, as they come out of the log file; the newest
    are shown, because during an activation the question is always "did that
    last one go in" and never "what did I work an hour ago".

    Pure, like every other screen in this module: a list of lines, each a list
    of (text, attr) segments, and nothing about curses.
    """
    head = header or {}
    out = []

    # Header. Fields are dropped from the right when the width will not take
    # them, same contract as status_line: the count is the last thing to go
    # because it is the one number that says the log is working.
    # The activity is named on the header so the operator can see which
    # grammar the entry line is being read with — the one thing that changes
    # what their typing means (§6b).
    # The ACTIVITY is what the operator is doing -- this park, this contest
    # weekend -- and is their own name for it, so it is shown as typed rather
    # than upper-cased. The TYPE is what the fields on screen mean and comes
    # after it in parentheses, because it answers a different question and is
    # the one that is usually already known.
    # Built as a LIST of whole fields, least important last, so that a header
    # too long for the width loses a field rather than losing the end of one.
    # It used to be one concatenated string cut with a slice, which on an
    # activation at 66 columns produced ` LOG  Bald Eagle SP  (POTA)  40m  SSB
    # 7.185.000  U` -- the `U` being what was left of `US-5678`, reading as a
    # field of its own. The docstring promised dropping; the code truncated.
    activity = str(head.get("activity") or "").strip()
    kind = str(head.get("activity_type") or "").strip().upper()
    # The file is named when it is not the default one: a deck writing
    # somewhere unexpected must never do it silently. An activity already
    # names its own file, so this is only for casual logging.
    name = (f" LOG:{head['log_name']}"
            if not activity and head.get("log_name") else " LOG")
    # Named either way. With an activity this is its name; without one it is
    # the MASTER LOG, which is a place rather than an absence -- every contact
    # ever made is in it, whatever activity made it. The caller passes the
    # name, so the header, the logging menu and the activities list all say
    # the same word.
    #
    # It used to go blank here, which left the operator unable to tell "no
    # activity in progress" from "the activity name is not being displayed",
    # and those want opposite responses.
    parts = [activity or "master log"]
    if kind and kind != "GENERAL":
        parts.append(f"({kind})" if activity else kind)
    # In POTA mode the reference is drawn whether or not it is set, so that
    # starting an activation without one is visible rather than silently
    # absent from every record of it. It comes before the radio's readings
    # because it is the one an activation is wrong without.
    if head.get("my_park"):
        parts.append(str(head["my_park"]))
    elif activity and kind and kind != "GENERAL" and head.get("needs_ref"):
        # Only while an ACTIVITY is named. A named activity with a reference
        # field and no reference is an activation that will record none on any
        # of its contacts, which is worth saying on every one of them.
        #
        # With no activity it means the opposite: POTA without a reference of
        # your own is HUNTING, which is half of what the type is for. Nagging
        # about it there told a hunter their correct setup was wrong.
        parts.append("(no reference set)")
    for key in ("band", "mode", "freq"):
        value = head.get(key)
        if value:
            parts.append(str(value))

    count = head.get("count")
    right = ""
    if count is not None:
        right = f"{count} QSO{'' if count == 1 else 's'} "
    if head.get("clock"):
        right = f"{right} {head['clock']} " if right else f" {head['clock']} "

    # Drop from the end until it fits. The count and the clock on the right are
    # never dropped: the count is the one number that says the log is working.
    while parts:
        left = name + "  " + "  ".join(parts)
        if len(left) + len(right) + 1 <= width:
            break
        parts.pop()
    else:
        left = name
    pad = max(1, width - len(left) - len(right))
    out.append([((left + " " * pad + right)[:width], "reverse")])
    out.append(rule(width))

    # Contacts. Columns are sized so a callsign never truncates: a log you
    # cannot read back is not a log. The free text at the end is what gets cut
    # when the screen is narrow, because it is the one field nobody reads back.
    #
    # A column is reserved only when something on screen uses it, so an
    # ordinary log is not padded out with blank exchange fields it will never
    # fill — except the park column in POTA mode, where a column appearing on
    # the first park-to-park would shift every row under it (§6a).
    # The form takes as many rows as it needs and the contact list gets the
    # rest. Whatever is left, at least one contact is shown: seeing the last
    # one land is what tells an operator the log is working.
    entry_rows = form_rows(form, width) if form is not None else []
    # One row less than before: the column heading takes it.
    body_rows = max(1, height - 6 - max(1, len(entry_rows)))
    # Capacity in CONTACTS, not rows. At two or three lines each, a contact is
    # several rows, and every count below it -- the scroll clamp, the page step,
    # which contacts are on screen -- is about contacts.
    per = max(LOG_LINES_MIN, min(int(lines or 1), LOG_LINES_MAX))
    body_entries = max(1, body_rows // per)
    # `scroll` counts contacts back from the newest, the same direction the
    # transcript scrolls, so one drag gesture means the same thing on both
    # screens. Clamped here as well as by the caller: a draw must be sane
    # whatever it is handed.
    back = max(0, min(int(scroll or 0), max(0, len(records) - body_entries)))
    end = len(records) - back
    first = max(0, end - body_entries)
    shown = records[first:end] if records else []

    # A column is drawn when THE SCHEMA IN USE asks for it. Not when a
    # contact on screen happens to carry the field: the schema is the
    # operator's statement about what this log is for, so switching schemas
    # has to change the columns or switching is not something you can see.
    #
    # It used to be "the schema asks for it OR some visible contact has it",
    # which failed in both directions. The columns changed as the list
    # scrolled, and they did NOT change when the schema did -- a contest
    # session logged under the master log kept its serial and exchange
    # columns after switching back to general logging, because the contacts
    # still carried them.
    #
    # A field the schema does not ask for is therefore not shown, even when
    # the record holds it. Nothing is lost: the contact screen lists every
    # field a record carries, and switching back to the schema that asked for
    # them brings the columns back. Blank where a contact of this schema
    # never captured the field, which is the other half of the same rule.
    #
    # With no schema at all -- `form=None`, which is how the unit tests call
    # this -- the records decide, because there is nothing else to ask.
    def _wanted(field):
        if form is None:
            return any(r.get(field) for r in shown)
        if field == "serial_tx":
            return bool(form.activity_type.serial)
        return form.activity_type.wants(field)

    used = {field: _wanted(field)
            for field in ("rst_s", "rst_r", "serial_tx", "serial_rx",
                          "exchange_rx", "park", "name", "qth")}
    # One column for both reports, so it is there if either is asked for. A
    # contest schema asks for neither -- in a contest the report is 59 every
    # time -- and a column of bare `/` down the screen says nothing.
    used["rst"] = used["rst_s"] or used["rst_r"]
    used["park"] = used["park"] or bool(head.get("my_park"))

    # Column headings, built from the same `used` and the same widths as the
    # rows below, so a heading can never name a column that is not there.
    #
    # Built as a LIST of whole columns rather than one concatenated string
    # cut with a slice, the same contract the header line above follows. A
    # custom schema can ask for more columns than 66 will take -- reports,
    # both serials, an exchange, a reference, a name, a QTH and a comment
    # come to 71 -- and the slice produced `QTH        COM`: a heading
    # naming a column that was not there and a word cut in half.
    #
    # A column that will not fit WHOLE is turned off in `used`, so the rows
    # below lose it too and cannot drift out of step with the headings. The
    # loop goes on rather than stopping, so a narrow column is not lost
    # along with a wide one in front of it -- a comment still fits in the 8
    # columns a dropped QTH would have needed 10 for, and the comment is the
    # field general logging is most likely to have something in.
    COLUMNS = (("rst", "RST", 7), ("serial_tx", "MY#", 5),
               ("serial_rx", "NR", 5), ("exchange_rx", "EXCH", 8),
               ("park", "REF", 9), ("name", "NAME", 9),
               ("qth", "QTH", 10))
    # The LAST column drawn takes whatever is left instead of its fixed
    # width, so a QTH at the end of the row is not clipped to ten characters
    # when there is half a screen free after it.
    free = max((i for i, (f, _t, _w) in enumerate(COLUMNS) if used.get(f)),
               default=-1)
    heading = f" {'UTC':<5}  {'CALL':<10}"
    for i, (field, title, pad) in enumerate(COLUMNS):
        if not used.get(field):
            continue
        chunk = f" {title}" if i == free or not pad else f" {title:<{pad}}"
        if len(heading) + len(chunk) > width:
            used[field] = False
            continue
        heading += chunk
    if back:
        # Otherwise a scrolled list looks like a log that has stopped taking
        # contacts -- the one thing this screen exists to disprove.
        tag = f"-{back} "
        heading = heading[:max(0, width - len(tag))].ljust(
            max(0, width - len(tag))) + tag
    out.append([(heading[:width].ljust(width), "dim")])

    for offset, rec in enumerate(shown):
        # `selected` indexes `records`, not the window, so it survives
        # scrolling: the contact stays selected while the list moves under it.
        picked = selected is not None and (first + offset) == selected
        when = (rec.get("when", "") or "")[11:16]
        line = f" {when}  {rec.get('call', ''):<10}"
        if used["rst"]:
            sent, got = rec.get("rst_s", ""), rec.get("rst_r", "")
            # Blank, not a bare `/`, on a contact that captured neither. The
            # slash is a separator between two reports and means nothing with
            # no report on either side of it -- and the column is there under
            # this schema whether or not this particular contact filled it.
            rst = f"{sent}/{got}" if (sent or got) else ""
            line += f" {rst:<7}"
        # Sent serial first, then received: the same order they are said on
        # the air, and the same order they sit in the ADIF record.
        if used["serial_tx"]:
            sent = rec.get("serial_tx", "")
            line += f" {('#' + sent) if sent else '':<5}"
        if used["serial_rx"]:
            line += f" {rec.get('serial_rx', ''):<5}"
        if used["exchange_rx"]:
            line += f" {rec.get('exchange_rx', ''):<8}"
        if used["park"]:
            line += f" {rec.get('park', ''):<9}"

        # Name and QTH each get their OWN column under their own heading.
        # They used to share one with the comment: the name padded to a fixed
        # width, then the QTH and the comment joined with a space and drawn
        # together under a heading reading `QTH`. On general logging, which
        # had no QTH field at all then, that put every typed comment in a
        # column labeled QTH -- the heading naming one field and the column
        # holding another.
        if used["name"]:
            line += f" {rec.get('name', ''):<9}"
        if used["qth"]:
            # Clipped with `...`, not cut by the row width. A value that ran
            # off the end used to stop mid-word -- "State Colleg" -- which
            # reads as a rendering fault rather than as text that did not
            # fit, and leaves the operator unsure whether there is more of it
            # or the log is damaged. The dots say there is more, and the
            # contact screen is where to read it.
            line += " " + clip(rec.get("qth", ""),
                               max(0, width - len(line) - 1))
        out.append([(line[:width].ljust(width),
                     "reverse" if picked else "")])

        # The continuation rows, carrying on down the activity's field order
        # from where the first row stopped. Always exactly `per - 1` of them
        # whether or not there is anything to put on them, so a contact is a
        # fixed height and the arrows can walk the list predictably.
        for extra in log_extra_rows(
                rec, log_extra_fields(
                    form.activity_type if form is not None else None, rec),
                width, per - 1):
            out.append([(extra[:width].ljust(width),
                         "reverse" if picked else "dim")])

    # Padded, not empty. An unpadded blank line leaves whatever the previous
    # screen drew in those columns, and the log screen is reached from the
    # transcript, which has text all the way across.
    while len(out) < height - 3 - max(1, len(entry_rows)):
        out.append([(" " * width, "")])

    out.append(rule(width))

    if entry_rows:
        for row in entry_rows:
            used = sum(len(t) for t, _ in row)
            if used < width:
                row = row + [(" " * (width - used), "")]
            out.append(row)
        out.append([((" " + message)[:width].ljust(width),
                     "dim" if message else "")])
        # F1 is the menu everywhere else on the deck and was unlabeled
        # here, so the one screen with its own menu was the one screen
        # that did not say so.
        # What the footer says depends on whether a contact is selected,
        # because the two most important keys mean different things then. A
        # footer that always claimed "Enter log" would be wrong exactly when
        # the operator was about to press it on a selected contact.
        if selected is not None:
            footer = (" \u2191\u2193 pick  Enter open  Esc deselect"
                      "  typing returns to the form")
        else:
            # 61 of 66. Four keys nobody guesses, and the two that are
            # guessable are the ones left off: Tab also moves between fields
            # and Esc also goes back, but the arrows are what this screen
            # gives those jobs to now, and Esc means the same thing on every
            # screen of this deck. The selected-state footer above names Esc
            # anyway, which is where it matters.
            # Seven hints in 66 columns, so the separators are single
            # spaces and `F3 type` is the one left off -- the type picker is
            # on this screen's own F1 menu as "Activity type", which none of
            # the others are. With two-space separators and all eight this
            # line came to 68 and was silently cut mid-word at `^O ^P ar`,
            # which is worse than any of them being absent.
            footer = (" F1 menu F2 acts \u2191\u2193 pick"
                      " \u2190\u2192 field Enter log ^X clear ^O ^P screen")
        if head.get("hint"):
            footer += f"   {head['hint']}"
        out.append([(footer[:width].ljust(width), "dim")])
        return out[:height]

    # The one-line entry, still used by `tools/qso.py` and by the tests that
    # predate the form. The cursor is drawn as a block rather than left to the
    # terminal, because this screen hides the compose area and the real cursor
    # is parked somewhere else entirely.
    text = entry or ""
    if cursor is None:
        cursor = len(text)
    before, after = text[:cursor], text[cursor:]
    seg = [(" > ", "dim"), (before, "bright")]
    seg.append(("█", "bright") if not after else (after[0], "reverse"))
    if after[1:]:
        seg.append((after[1:], "bright"))
    used = sum(len(t) for t, _ in seg)
    if used < width:
        seg.append((" " * (width - used), ""))
    out.append(seg)

    out.append([((" " + message)[:width].ljust(width),
                 "dim" if message else "")])

    footer = " Esc back   Enter log"
    if head.get("hint"):
        footer += f"   {head['hint']}"
    out.append([(footer[:width].ljust(width), "dim")])
    return out[:height]


def settings_screen(rows, width, height, selected=None, message="",
                    footer="", state=""):
    """The station, as a screen rather than a menu.

    `rows` is `[(label, token, value, config key), ...]` — every row editable,
    so the cursor lands on all of them and there is nothing to skip.

    A screen because the settings are one of the deck's three applications,
    and an application needs somewhere to BE: the ring lands here. A menu
    could not be landed on — it is drawn over whatever screen was current, so
    arriving at "the settings" meant arriving at the digimode screen with a
    menu on top of it.

    The token is shown beside each label because the moment an operator wants
    to know that `{qth}` exists is the moment they are looking at what QTH is
    set to. That is what the Station menu did, and this replaced it rather than
    sitting beside it showing the same eight settings again.
    """
    body = max(1, height - 4)
    pages = max(1, (len(rows) + body - 1) // body)
    page = min(max(0, int(selected or 0)) // body, pages - 1)
    shown = rows[page * body:(page + 1) * body]

    head = " DECK & RIG"
    if pages > 1:
        head += f"  {page + 1}/{pages}"
    # `state` on the right, because this is the screen the deck OPENS on and
    # the messages that used to greet an operator there -- no connection to
    # fldigi, transmit inhibited at startup -- go to the transcript, which is
    # no longer what they are looking at. Without this, a deck with no modem
    # and a deck working perfectly look identical on power-on.
    if state:
        right = f"{state} "
        pad = max(1, width - len(head) - len(right))
        head = head + " " * pad + right
    out = [[(head.ljust(width)[:width], "reverse")], rule(width)]
    label_w, token_w = 14, 8
    for i, (label, token, value, _key) in enumerate(shown,
                                                    start=page * body):
        mark = "\u25b8" if i == selected else " "
        text = f"{mark}{str(label):<{label_w}}{str(token or ''):<{token_w}}{value}"
        out.append([(text[:width].ljust(width),
                     "bright" if i == selected else "")])

    while len(out) < height - 2:
        out.append([(" " * width, "")])
    out.append(rule(width))
    out.append([((" " + (message or footer or
                 "\u2191\u2193 pick  Enter edit  F1 menu  F4 color"
                 "  ^O ^P screen"))[:width].ljust(width), "dim")])
    return out[:height]


ENTRY_ROW0 = 2


def entry_screen(rows, selected, width, height, call="", when="",
                 message="", position=""):
    """One logged contact, field by field, so it can be read and corrected.

    `rows` is `qsolog.detail_rows()` output: `(name, label, value, editable)`.
    The order is the stored line's order, so this screen and a line read over
    SSH put the same field in the same place.

    Exists because the list cannot show everything. A contact has up to forty
    fields and the list has one row for it, so the fields that did not fit were
    unreadable on the deck and unfixable anywhere but over SSH -- which is no
    use from a park bench, which is where the mistakes get made.

    A locked field is drawn dim and skipped by the cursor rather than hidden.
    Hiding `when` would leave the operator wondering where the timestamp went;
    showing it greyed says it is there and is not theirs to retype.
    """
    out = []
    left = " CONTACT"
    if call:
        left += f"  {call}"
    if when:
        # "2026-10-14T14:05:00Z" -> "2026-10-14 14:05Z". The seconds are in the
        # field list below; up here they are noise.
        left += f"  {when[:10]} {when[11:16]}Z" if len(when) >= 16 else f"  {when}"
    right = f"{position} " if position else ""
    pad = max(1, width - len(left) - len(right))
    if len(left) + len(right) + 1 > width:
        left = left[:max(0, width - len(right) - 1)]
        pad = 1
    out.append([((left + " " * pad + right)[:width].ljust(width), "reverse")])
    out.append(rule(width))

    # The cursor is an index into `rows`; the caller keeps it on an editable
    # one. Paged by the cursor, like the field selector, so walking off the
    # bottom arrives at the top of the next page instead of stopping.
    body = max(1, height - 4)
    page = max(0, int(selected or 0)) // body if rows else 0
    shown = rows[page * body:(page + 1) * body]
    for i, (_name, label, value, editable) in enumerate(shown,
                                                        start=page * body):
        mark = "\u25b8" if i == selected else " "
        line = f"{mark} {label:<9} {value}"
        if not editable:
            out.append([(line[:width].ljust(width), "dim")])
        else:
            out.append([(line[:width].ljust(width),
                         "bright" if i == selected else "")])

    while len(out) < height - 2:
        out.append([(" " * width, "")])
    out.append(rule(width))
    footer = message or "Esc back  \u2191\u2193 field  Enter edit  d delete"
    if not message and len(rows) > body:
        footer = ("Esc back  \u2191\u2193 field  Enter edit  d delete  "
                  f"{page + 1}/{(len(rows) + body - 1) // body}")
    out.append([((" " + footer)[:width].ljust(width), "dim")])
    return out[:height]


# How many lines each contact takes in the list. One is the whole contact on a
# row; two adds where they are; three adds this station's side and the notes.
# A contact always takes exactly this many rows, blank ones included, because
# the arrows select whole contacts and a list whose row height varied with how
# much was filled in could not be walked predictably.
LOG_LINES_MIN, LOG_LINES_MAX = 1, 3

# What the first row already shows, so the continuation rows carry on from
# there instead of repeating it. These are the columns the heading names.
# `comment` is NOT here, so it falls to the continuation rows. It is the one
# field whose length is unbounded, so on the first row it was always the one
# clipped, and it took the last column -- the one that can use what is left
# -- away from the QTH, which is short, scannable and what an operator
# actually reads back beside a name. A one-line list therefore shows no
# comment; two lines show it under its own label, and the contact screen
# always does.
_LINE1_FIELDS = ("when", "call", "rst_s", "rst_r", "serial_tx", "serial_rx",
                 "exchange_rx", "park", "name", "qth")

# Filled in without being typed, so no schema lists them, and shown on every
# contact whatever its schema: the band, frequency and mode read off the radio
# and the rig and antenna read off the Station settings. In the order the
# operator reads them back -- what band, then where on it, then how.
_AUTOMATIC = ("band", "freq", "mode", "tx_power", "my_rig", "my_antenna")

# Never shown on a continuation row. The station's own call is the same on
# every contact in the file, and the activity and its type are named in the
# header above the list -- a column repeating any of them down the screen
# spends rows on what the operator already knows.
_LINE_SKIP = ("my_call", "activity", "activity_type", "contest_id")

# Three ASCII dots, deliberately, NOT U+2026. The panel's console font is
# Uni3-TerminusBold24x12 and its glyph coverage is known and small; an ellipsis
# character is not in it, so it would look correct on a laptop and draw as a
# blank box on the deck. The same trap has caught this project before.
ELLIPSIS = "..."

# How wide one field's value may be on a continuation row. Free text needs a
# cap or a single long comment takes the whole row and shoves every other field
# onto the next one -- and the comment is the field most likely to be long and
# least likely to be read back. Anything not named here is shown in full.
_VALUE_CAP = {"comment": 24}


def clip(text, limit):
    """`text`, or as much of it as fits in `limit` with `...` on the end."""
    text = str(text or "")
    if limit <= 0 or len(text) <= limit:
        return text
    if limit <= len(ELLIPSIS):
        return text[:limit]
    return text[:limit - len(ELLIPSIS)] + ELLIPSIS


def log_extra_fields(activity_type, rec):
    """Which fields the continuation rows show, in the order they show them.

    THE ACTIVITY'S OWN ORDER, continuing where the first row stopped. Not a
    fixed list: the activity type's field order is the operator's statement
    about what matters on this contact, and a hardcoded "line two is where they
    are" is wrong for every custom type. A county-hunting type puts county
    second and a satellite type puts the bird second, and neither wants a row
    spent on a grid square it never asks for.

    Then the AUTOMATIC fields, in `_AUTOMATIC` order. No schema lists them
    because nobody types them, and every schema has them: the band, frequency
    and mode come off the radio and the rig and antenna come off the Station
    settings. Leaving them out would have dropped them from the display
    entirely, since they are not in any schema's `entry`.

    Nothing else. A field the schema does not ask for is not shown, for the
    same reason the first row's columns are schema-driven: switching schemas
    has to change what the display shows. This used to append everything the
    record carried in stored order, which meant a contest contact kept
    showing its exchange after the operator switched back to general logging.
    The contact screen is where every field of a record is listed.

    With no schema -- `activity_type=None` -- the record decides, because
    there is nothing else to ask.
    """
    import qsolog as _q
    out, seen = [], set(_LINE1_FIELDS) | set(_LINE_SKIP)
    for name in (getattr(activity_type, "entry", ()) or ()):
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    for name in _AUTOMATIC:
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    if activity_type is not None:
        return out
    for name in _q._FIELD_ORDER:
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    for name in sorted(rec):
        if name not in seen:
            out.append(name)
    return out


def log_extra_rows(rec, fields, width, rows):
    """`rows` continuation lines of `label value` pairs, wrapped and padded.

    Labelled rather than columnar: rows of different shapes cannot share one
    set of column headings, and an unlabeled `PA Centre FN10` stops being
    readable the moment one of the three is missing.

    **A field is never split across two rows.** One that does not fit in what
    is left of a row starts the next one instead, which is what makes the rows
    readable at a glance -- a `Coun` at the end of one row and `ty Centre` at
    the start of the next is worse than a short row. A field too wide for a
    whole row is clipped with `...`, because it can never fit anywhere and
    dropping it silently would hide what is in the log.

    Always exactly `rows` strings, blank ones included. A contact has to be the
    same height whatever is filled in, because the arrows select whole contacts
    and a list whose row height moved could not be walked predictably.
    """
    import qsolog as _q
    indent = "      "
    room = max(10, width - len(indent))
    parts = []
    for name in fields:
        value = _q.display_value(name, rec.get(name, ""))
        if not value:
            continue
        value = clip(value, _VALUE_CAP.get(name, 0))
        parts.append(clip(f"{_q.field_label(name)} {value}", room))

    out, line = [], ""
    for part in parts:
        if not line:
            line = part
        elif len(line) + 3 + len(part) <= room:
            line += "   " + part
        else:
            out.append(indent + line)
            if len(out) >= rows:
                line = ""
                break
            line = part
    if line and len(out) < rows:
        out.append(indent + line)
    while len(out) < rows:
        out.append("")
    return out[:rows]


def no_keyboard_screen(bonded, width, height, tick=0, can_pair=True):
    """Shown when the deck has no keyboard, which is also when it cannot be
    told anything.

    Two different problems look identical from here — a bonded keyboard that
    is switched off or asleep, and no bond at all — and the common one by far
    is the first. So this does not jump into pairing. It names the keyboards
    already bonded, says to switch one on, and offers pairing as the second
    answer rather than the only one.

    It clears itself the moment a key arrives, because a keystroke is proof
    the problem is solved.
    """
    inner = max(20, width - 2)
    out = [[(" NO KEYBOARD".ljust(width), "reverse")],
           [("┌" + "─" * inner + "┐", "dim")]]

    def line(text="", kind="bright"):
        out.append([("│", "dim"), (text[:inner].ljust(inner), kind),
                    ("│", "dim")])

    line()
    line("  No keyboard is connected" + "." * (1 + tick % 3))
    line()
    if bonded:
        line("  Already paired:", "dim")
        for d in bonded[:4]:
            line(f"    {(d.name or '(unnamed)')[:28]:<28} {d.tail}")
        line()
        line("  Switch it on, or press its channel button.")
        line("  This screen clears by itself when it answers.", "dim")
    else:
        line("  Nothing is paired with this deck yet.")
        line()
        line("  Hold the keyboard's pairing key until its", "dim")
        line("  light blinks quickly.", "dim")
    line()
    if can_pair:
        line("  ▸  TAP THE SCREEN TO PAIR A KEYBOARD")
    else:
        line("  Pairing is not available on this machine.", "dim")

    while len(out) < height - 2:
        out.append([("│", "dim"), (" " * inner, "bright"), ("│", "dim")])
    out.append([("└" + "─" * inner + "┘", "dim")])
    out.append([(" " + ("tap to pair   any key dismisses" if can_pair
                        else "any key dismisses")[:width - 1], "dim")])
    return out[:height]
