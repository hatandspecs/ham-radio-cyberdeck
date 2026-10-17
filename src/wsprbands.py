"""WSPR dial frequencies for the bands this deck offers. Pure data.

The keys match `menus.BANDS` -- same eleven bands, same digits, `a` for
70 cm -- so a band key an operator already knows means the same band on the
WSPR screen. The FREQUENCIES differ, because that table holds digimode
calling frequencies and this one holds WSPR dial frequencies.

A WSPR signal sits 1400-1600 Hz above the dial, inside a 200 Hz window.

**Confirmed twice.** The published list at sigidwiki.com/wiki/WSPR gives
every one of these, and the eight HF figures were independently derived from
8,111 real spots: observed signal frequencies sit 1.39-1.62 kHz above each
dial frequency, which is the WSPR window.

Bands deliberately absent, though the published list carries them: 2200 m,
630 m, 160 m, 4 m and 23 cm. These eleven are the bands this station works,
and a picker padded with bands the radio cannot reach is a list to scroll
past forever.
"""

#: `(key, label, dial hertz)`. Order is the band order, low to high, which is
#: the order the digimode band menu uses.
BANDS = (
    ("1", "80 m", 3_568_600),
    ("2", "40 m", 7_038_600),
    ("3", "30 m", 10_138_700),
    ("4", "20 m", 14_095_600),
    ("5", "17 m", 18_104_600),
    ("6", "15 m", 21_094_600),
    ("7", "12 m", 24_924_600),
    ("8", "10 m", 28_124_600),
    ("9", "6 m", 50_293_000),
    ("0", "2 m", 144_489_000),
    ("a", "70 cm", 432_300_000),
)

DIAL_BY_KEY = {key: hz for key, _label, hz in BANDS}
DIAL_BY_LABEL = {label: hz for _key, label, hz in BANDS}

#: Where in the 200 Hz window the deck's own transmission sits. 1500 Hz is
#: the middle and what WSJT-X uses by default.
TX_AUDIO_HZ = 1500.0


def normalise(name):
    """A band label from anything an operator or a config might write.

    `40m`, `40 m`, `40`, `7.0386` and `7038600` all mean the same band, and a
    tool that accepted only one spelling would be a tool with a footnote.
    """
    text = str(name or "").strip().lower().replace(" ", "")
    for _key, label, hz in BANDS:
        flat = label.lower().replace(" ", "")
        if text in (flat, flat.rstrip("m").rstrip("c"), label.lower()):
            return label
        if text == str(hz) or text == f"{hz / 1_000_000:.6f}".rstrip("0"):
            return label
    # A bare number: 40 means 40 m, 70 means 70 cm.
    for _key, label, _hz in BANDS:
        if text and text == label.split()[0]:
            return label
    return ""


def dial_hz(name):
    """The dial frequency for a band, or 0 when the name means nothing."""
    label = normalise(name)
    return DIAL_BY_LABEL.get(label, 0)


def band_for_dial(hz, tolerance=500):
    """Which band a dial frequency belongs to, or "".

    Tolerant, because a radio reads back what it actually tuned to and that
    is not always the digit-for-digit value it was sent.
    """
    try:
        hz = int(hz)
    except (TypeError, ValueError):
        return ""
    for _key, label, dial in BANDS:
        if abs(hz - dial) <= tolerance:
            return label
    return ""
