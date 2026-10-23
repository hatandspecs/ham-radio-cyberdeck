"""WSPR message encoding and tone generation. Pure: no audio, no radio, no clock.

A WSPR transmission is 162 four-level symbols sent over 110.6 seconds. This
module turns a callsign, a grid square and a power in dBm into those symbols,
and the symbols into samples. What plays them, what keys the radio and what
decides when to transmit all live elsewhere; see `docs/wspr_design.md`.

**`wsprd` decodes, and nothing shipped with it encodes.** WSJT-X installs
`wsprd` and no `wsprsim`, so the encoder is this project's own. That makes
getting it exactly right the whole job, and there is one way to be sure:
**encode a message, render the audio, and hand it to `wsprd`.** If the
reference decoder reads back the callsign, grid and power that went in, the
encoder agrees with the implementation every other WSPR station is running.
That is what `tests/test_wspr.py` does, and it is worth more than any table
of expected symbols -- a table can be transcribed wrong and still look
authoritative.

The sync vector below was **extracted from the `wsprd` binary**, not written
from memory: two independent copies of it inside `/usr/bin/wsprd` agree
byte for byte on all 162 values. A sync vector with one element wrong
produces a signal nothing in the world can decode, and it would look
perfectly reasonable in source.
"""

# Characters allowed in a packed callsign, in the order their values run.
# A space is the padding character and sorts last, which is why it is value
# 36 rather than being stripped: a short call is a call with spaces in it.
_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ "

# The power levels WSPR can carry. Not every integer: the field holds a value
# that must round-trip through the protocol, so a reading off the radio is
# snapped to one of these. 5 W is 37 and 10 W is 40; see §6 of the design for
# why only a handful of wattages land exactly.
POWERS = (0, 3, 7, 10, 13, 17, 20, 23, 27, 30, 33, 37, 40, 43, 47, 50, 53,
          57, 60)

# The two generator polynomials of the rate-1/2, constraint-length-32
# convolutional code.
_POLY = (0xf2d05351, 0xe4613c47)

# 162 symbols, 0.6827 s each.
SYMBOL_COUNT = 162

# The tone spacing and symbol length are both 12000/8192, which is why the
# sample rate is 12 kHz and not something rounder: one symbol is exactly
# 8192 samples and the tones are exactly one symbol-rate apart.
SAMPLE_RATE = 12000
SAMPLES_PER_SYMBOL = 8192
TONE_SPACING = SAMPLE_RATE / SAMPLES_PER_SYMBOL        # 1.46484375 Hz

# Extracted from /usr/bin/wsprd (wsjtx 3.0.1), cross-checked against a second
# copy of the same table in the same binary. 63 ones of 162.
SYNC = (
    1, 1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 1, 1, 0, 0, 0, 1, 0, 0, 1, 0, 1, 1, 1, 1,
    0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 1, 0, 1, 1, 0, 0, 1, 1,
    0, 1, 0, 0, 0, 1, 1, 0, 1, 0, 0, 0, 0, 1, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 0, 1, 0,
    0, 1, 0, 1, 1, 0, 0, 0, 1, 1, 0, 1, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 1,
    0, 0, 1, 1, 1, 0, 1, 1, 0, 0, 1, 1, 0, 1, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 1, 0,
    1, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 1, 0, 1, 1, 0, 0, 0, 1, 1, 0, 0, 0,
)


class WsprError(ValueError):
    """A message that cannot be encoded, with the reason an operator can act on."""


def dbm_for_watts(watts):
    """The WSPR power field for a wattage, and whether it is exact.

    Returns `(dbm, exact)`. `dbm = 10*log10(watts) + 30`, snapped to the
    nearest value the protocol can carry; `exact` is whether the snap moved
    it, which is what the screen highlights. Only 1, 2, 5, 10, 20, 50 and
    100 W land exactly -- 3 W is 34.77 dBm and goes out as 33.

    Zero or negative watts has no logarithm and no honest answer, so it
    raises rather than reporting 0 dBm, which would be a 1 mW claim.
    """
    import math
    try:
        watts = float(watts)
    except (TypeError, ValueError):
        raise WsprError("power is not a number")
    if watts <= 0:
        raise WsprError("power must be greater than zero")
    exact_dbm = 10.0 * math.log10(watts) + 30.0
    best = min(POWERS, key=lambda p: abs(p - exact_dbm))
    return best, abs(exact_dbm - best) < 0.05


def _call_slot(call):
    """A callsign laid out in the six positions the protocol packs.

    The third position must hold the digit, so a call whose digit is second
    -- every one-letter prefix, `K3XYZ` -- is shifted right by one and the
    gap filled with a space. Without this the packing of a perfectly ordinary
    US call is silently wrong.
    """
    call = str(call or "").strip().upper()
    if not call or len(call) > 6:
        raise WsprError("a callsign is 1 to 6 characters")
    for ch in call:
        if ch not in _CHARS or ch == " ":
            raise WsprError(f"{ch!r} cannot go in a WSPR callsign")
    if len(call) > 2 and call[1].isdigit():
        call = " " + call                      # K3XYZ -> ' K3XYZ'
    if len(call) < 3 or not call[2].isdigit():
        raise WsprError(f"{call.strip()} has no digit in the third position")
    return call.ljust(6)


def pack_call(call):
    """A callsign as the protocol's 28-bit integer."""
    c = _call_slot(call)
    if not (c[0] in _CHARS and c[1] != " "):
        raise WsprError("a callsign needs a prefix character")
    n = _CHARS.index(c[0])
    n = n * 36 + _CHARS.index(c[1])
    n = n * 10 + _CHARS.index(c[2])
    for ch in c[3:6]:
        # Positions four to six are letters or space, so their values start
        # at 'A' -- hence the shift past the ten digits.
        n = n * 27 + (_CHARS.index(ch) - 10)
    return n


def pack_grid_power(grid, dbm):
    """A four-character grid square and a power as the protocol's 22 bits."""
    g = str(grid or "").strip().upper()
    if len(g) != 4 or not ("A" <= g[0] <= "R") or not ("A" <= g[1] <= "R") \
            or not g[2].isdigit() or not g[3].isdigit():
        raise WsprError("a WSPR grid is four characters, like FN10")
    if dbm not in POWERS:
        raise WsprError(f"{dbm} dBm is not a power WSPR can carry")
    lon = 179 - 10 * (ord(g[0]) - ord("A")) - int(g[2])
    lat = 10 * (ord(g[1]) - ord("A")) + int(g[3])
    return (lon * 180 + lat) * 128 + dbm + 64


def _message_bits(call, grid, dbm):
    """The 50-bit message, then 31 zeros to flush the encoder: 81 bits."""
    n, m = pack_call(call), pack_grid_power(grid, dbm)
    bits = [(n >> (27 - i)) & 1 for i in range(28)]
    bits += [(m >> (21 - i)) & 1 for i in range(22)]
    return bits + [0] * 31


def _convolve(bits):
    """Rate 1/2, constraint length 32. Two output bits per input bit."""
    out, reg = [], 0
    for bit in bits:
        reg = ((reg << 1) | bit) & 0xffffffff
        for poly in _POLY:
            out.append(bin(reg & poly).count("1") & 1)
    return out


def _interleave(bits):
    """Bit-reversal interleaving over 256 slots, of which 162 are used.

    The source bits are taken in order and placed at the bit-reversed
    position of a counter, skipping the reversals that land past 161. That
    scatters a burst of channel errors across the codeword, which is the
    whole purpose.
    """
    out = [0] * SYMBOL_COUNT
    taken = 0
    for i in range(256):
        rev = int(f"{i:08b}"[::-1], 2)
        if rev < SYMBOL_COUNT:
            out[rev] = bits[taken]
            taken += 1
    if taken != SYMBOL_COUNT:
        raise WsprError("interleaver did not consume the whole codeword")
    return out


def symbols(call, grid, dbm):
    """The 162 symbols, each 0 to 3, for one transmission.

    `symbol = sync + 2 * data`: the low bit carries the sync vector that lets
    a decoder find the transmission in time and frequency, and the high bit
    carries the message. Which is why a wrong sync vector is undecodable
    rather than merely wrong -- half the information in every symbol is it.
    """
    data = _interleave(_convolve(_message_bits(call, grid, dbm)))
    return [SYNC[i] + 2 * data[i] for i in range(SYMBOL_COUNT)]


def tones(call, grid, dbm, base_hz=1500.0):
    """The frequency of each symbol, in Hz, for a given audio center."""
    return [base_hz + sym * TONE_SPACING for sym in symbols(call, grid, dbm)]


def samples(call, grid, dbm, base_hz=1500.0, amplitude=0.5):
    """The transmission as floats in -1.0 to 1.0, 12 kHz mono.

    Continuous phase across symbol boundaries. A phase discontinuity at every
    symbol would splatter a signal whose whole virtue is occupying 6 Hz, and
    WSPR is constant envelope for the same reason -- there is no amplitude
    shaping here and there should not be.
    """
    import math
    out = []
    phase = 0.0
    for hz in tones(call, grid, dbm, base_hz):
        step = 2.0 * math.pi * hz / SAMPLE_RATE
        for _ in range(SAMPLES_PER_SYMBOL):
            out.append(amplitude * math.sin(phase))
            phase += step
            if phase > 2.0 * math.pi:
                phase -= 2.0 * math.pi
    return out


# -- reading what `wsprd` says -------------------------------------------
#
# The format below is not described from memory. It is what the real decoder
# printed, captured into `tests/fixtures/wsprd_stdout*.txt` and parsed
# against those files:
#
#   1400  18 -0.0  14.097082  0  KD3CCO FN10 37
#   1400   7  0.0  14.097102  0  KD3CCO EM12 23
#   1400  -2 -0.1  14.097122  0  KD3CCO CN87 10
#   1400  -8 -0.1  14.097147  0  KD3CCO JO41  0
#   <DecodeFinished>
#
# Four things in there that a parser written from a guess gets wrong:
#
#   * the columns are WHITESPACE-separated and not fixed width -- `0` dBm
#     prints with an extra space in front of it, so splitting on columns
#     loses the last field on exactly the weakest signals,
#   * the SNR is routinely negative, which is the normal case and not an
#     error,
#   * `DT` appears as `-0.0`, which is a float and not a typo,
#   * every line has a trailing space, and the terminator is its own line.

DECODE_END = "<DecodeFinished>"

# WSPR carries three message shapes. Type 1 is a plain call, a four-character
# grid and a power. Type 2 is a compound call -- `KD3CCO/P`, `PJ4/K1ABC` --
# with a power and NO grid. Type 3 is a hashed call in angle brackets with a
# six-character grid. The deck transmits type 1; it must READ all three,
# because other stations send them.
_HASHED = ("<", ">")


def parse_decode(line):
    """One `wsprd` stdout line as a dict, or None if it is not a decode.

    Reports only what the decoder said. The date, the band, the session and
    this station's own fields are the caller's to attach -- the deck knows
    them and `wsprd` does not, and a parser that invented them would be
    guessing in a place where guesses are indistinguishable from data.
    """
    line = str(line or "").strip()
    if not line or line == DECODE_END:
        return None
    parts = line.split()
    if len(parts) < 6:
        return None
    try:
        spot = {
            "hhmm": parts[0],
            "snr": int(parts[1]),
            "dt": float(parts[2]),
            # Hertz, not megahertz, following the log's `HERTZ_FIELDS`
            # convention -- one unit for frequency everywhere on the deck.
            "freq": int(round(float(parts[3]) * 1_000_000)),
            "drift": int(parts[4]),
        }
    except (ValueError, IndexError):
        return None
    if len(parts[0]) != 4 or not parts[0].isdigit():
        return None

    message = parts[5:]
    spot["message"] = " ".join(message)
    call = message[0]
    spot["hashed"] = call.startswith(_HASHED[0]) and call.endswith(_HASHED[1])
    spot["call"] = call.strip("<>") if spot["hashed"] else call
    if len(message) >= 3:
        # Type 1 or type 3: call, grid, power.
        spot["grid"] = message[1]
        try:
            spot["dbm"] = int(message[2])
        except ValueError:
            return None
    elif len(message) == 2:
        # Type 2: a compound call and a power, with no grid to report. The
        # grid is absent rather than empty, so a record built from this
        # carries no `grid` field at all -- which the key=value format
        # handles by leaving it out.
        try:
            spot["dbm"] = int(message[1])
        except ValueError:
            return None
    else:
        return None
    return spot


def parse_decodes(text):
    """Every decode in a `wsprd` run, in the order printed."""
    out = []
    for line in str(text or "").splitlines():
        spot = parse_decode(line)
        if spot is not None:
            out.append(spot)
    return out


def decode_complete(text):
    """Whether `wsprd` finished rather than being cut off.

    It prints the marker whether or not anything decoded, so its ABSENCE
    means the run died -- killed, crashed, or still going. A caller that
    treated "no decodes" and "no marker" alike would record an empty window
    for a decoder that never ran.
    """
    return DECODE_END in str(text or "")


def dedupe(spots):
    """One spot per station per window, keeping the strongest.

    **A window can decode the same transmission twice**, and deep search
    makes it likelier: on a four-signal test window `wsprd -d` reported
    `KD3CCO FN10 37` at both +23 dB and -10 dB -- one transmission, found
    twice, once as an artifact of the strong one. Logging both would put a
    station in the log twice for one two-minute slot, and uploading both
    would report a signal to wsprnet that nobody sent.

    Keyed on the call and the grid rather than the call alone, because two
    stations can share a hashed call and because a station that moved
    between slots is genuinely a different report. Strongest SNR wins, which
    is the real measurement -- the weak copy is the artifact.

    Order is preserved: the first appearance of each station keeps its place,
    so the list still reads in the order the decoder found things.
    """
    best = {}
    order = []
    for spot in spots:
        key = (str(spot.get("call", "")).upper(), str(spot.get("grid", "")))
        if key not in best:
            best[key] = spot
            order.append(key)
        elif spot.get("snr", -99) > best[key].get("snr", -99):
            best[key] = spot
    return [best[k] for k in order]


# -- how loud the captured audio is --------------------------------------
#
# **Not `audioop`.** It was removed from the standard library in Python 3.13,
# and the deck's Python is newer than that while the development laptop's
# still has it -- so an implementation built on `audioop` passes every test
# here and raises `ModuleNotFoundError` on the panel. That is the same shape
# as the `kspd=^Z` key fault and the console-font glyphs: correct on the
# laptop, dead on the deck, invisible from here.

#: Every Nth sample, for the level meter only. A 114-second window is 1.37M
#: samples and a level meter does not need all of them -- the figure is for a
#: human turning a gain control, and a tenth of a dB either way changes
#: nothing. Measured in full it costs about a second of a Pi's time per slot,
#: which is a second better spent decoding.
LEVEL_STRIDE = 16


def audio_level(frames, stride=LEVEL_STRIDE):
    """`(rms, peak, dbfs)` for signed 16-bit little-endian mono audio.

    `dbfs` is relative to full scale and is therefore negative, or None for
    digital silence -- which has no logarithm and is a real condition, not an
    error: a radio switched off, a cable out, or the wrong card.

    Roughly -30 to -20 dBFS is a healthy WSPR input. Loud enough to hear is
    far too loud: the decoder wants headroom, and a clipped window decodes
    worse than a quiet one.
    """
    import array
    import math
    buf = array.array("h")
    usable = (len(frames) // 2) * 2
    if not usable:
        return 0, 0, None
    buf.frombytes(bytes(frames[:usable]))
    if sys_byteorder_is_big():
        buf.byteswap()
    stride = max(1, int(stride))
    total = 0
    peak = 0
    count = 0
    for i in range(0, len(buf), stride):
        v = buf[i]
        total += v * v
        if v > peak:
            peak = v
        elif -v > peak:
            peak = -v
        count += 1
    if not count:
        return 0, 0, None
    rms = int(math.sqrt(total / count))
    if rms <= 0:
        return 0, peak, None
    return rms, peak, 20.0 * math.log10(rms / 32768.0)


def sys_byteorder_is_big():
    """Whether this machine stores integers big-endian.

    The WAV is little-endian by definition; `array` uses the machine's own
    order. The deck is ARM running little-endian and so is the laptop, so
    this is always False in practice -- which is exactly why it is a named
    function and not an assumption buried in a loop.
    """
    import sys
    return sys.byteorder == "big"
