"""The WSPR encoder, checked against `wsprd` itself.

The unit tests below are worth having, but **the test that matters is the
round trip**: encode a message, render the audio, hand the WAV to the real
`wsprd`, and require it to read back the callsign, grid and power that went
in. Nothing else proves an encoder correct. A sync vector with one element
wrong, a convolutional polynomial with one bit wrong, an interleaver running
the wrong direction -- each produces a signal that looks entirely plausible
in source and that nothing in the world can decode.

So the expected values here are not a transcribed table. They are whatever
the reference implementation every other WSPR station runs says they are.

Test traffic uses this station's own callsign. `KD3CCO` throughout, and
nothing is transmitted -- the WAV is handed to a decoder, not to a radio.
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import wave

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import wspr

CALL, GRID, DBM = "KD3CCO", "FN10", 37


print("power to the dBm WSPR can carry")
# Only a handful of wattages land on an encodable value, which is the whole
# reason the screen highlights the exact ones -- §6 of the design.
for watts, want in ((1, 30), (2, 33), (5, 37), (10, 40), (20, 43), (50, 47),
                    (100, 50)):
    dbm, exact = wspr.dbm_for_watts(watts)
    equals(f"{watts} W is {want} dBm", dbm, want)
    check(f"and {watts} W is exact", exact, f"{watts} W -> {dbm}")
for watts, want in ((3, 33), (4, 37), (8, 40), (15, 43), (25, 43)):
    dbm, exact = wspr.dbm_for_watts(watts)
    equals(f"{watts} W snaps to {want} dBm", dbm, want)
    check(f"and {watts} W is NOT exact", not exact, f"{watts} W -> {dbm}")
for bad in (0, -5):
    try:
        wspr.dbm_for_watts(bad)
        check(f"{bad} W is refused", False, "no error raised")
    except wspr.WsprError:
        check(f"{bad} W is refused rather than called 0 dBm", True, "")

print("\nthe callsign's digit is put in the third position")
# A one-letter prefix has its digit SECOND, so it shifts right and the gap
# becomes a space. Without this every call like K3XYZ packs wrongly, and the
# wrongness is invisible until nobody decodes it.
equals("a two-letter prefix is left alone", wspr._call_slot("KD3CCO"),
       "KD3CCO")
equals("a one-letter prefix shifts right", wspr._call_slot("K3XYZ"),
       " K3XYZ")
equals("and is padded to six", len(wspr._call_slot("K3XY")), 6)
for bad in ("", "TOOLONGCALL", "ABCDEF", "K"):
    try:
        wspr.pack_call(bad)
        check(f"{bad!r} is refused", False, "no error raised")
    except wspr.WsprError:
        check(f"{bad!r} is refused", True, "")

print("\nthe grid is four characters and the power must be carryable")
check("a valid grid packs", wspr.pack_grid_power("FN10", 37) > 0, "")
for bad_grid in ("FN10cs", "FN", "1234", ""):
    try:
        wspr.pack_grid_power(bad_grid, 37)
        check(f"{bad_grid!r} is refused", False, "no error raised")
    except wspr.WsprError:
        check(f"{bad_grid!r} is refused", True, "")
try:
    wspr.pack_grid_power("FN10", 38)
    check("38 dBm is refused", False, "no error raised")
except wspr.WsprError:
    check("38 dBm is refused — not a value WSPR carries", True, "")

print("\nthe symbols have the shape the protocol requires")
syms = wspr.symbols(CALL, GRID, DBM)
equals("162 of them", len(syms), wspr.SYMBOL_COUNT)
check("each is 0 to 3", all(0 <= s <= 3 for s in syms), str(set(syms)))
# The low bit of every symbol IS the sync vector, which is what lets a
# decoder find the transmission at all.
equals("their low bits are exactly the sync vector",
       [s & 1 for s in syms], list(wspr.SYNC))
equals("the sync vector is 162 long", len(wspr.SYNC), 162)
equals("with 63 ones, as extracted from the wsprd binary",
       sum(wspr.SYNC), 63)

print("\nthe sample stream is the right length and shape")
sig = wspr.samples(CALL, GRID, DBM)
equals("162 symbols of 8192 samples",
       len(sig), wspr.SYMBOL_COUNT * wspr.SAMPLES_PER_SYMBOL)
check("which is 110.6 seconds",
      abs(len(sig) / wspr.SAMPLE_RATE - 110.6) < 0.1,
      f"{len(sig) / wspr.SAMPLE_RATE:.2f} s")
check("and stays inside the sample range",
      all(-1.0 <= s <= 1.0 for s in sig), "")
equals("the tone spacing is the symbol rate",
       round(wspr.TONE_SPACING, 6), round(12000 / 8192, 6))


# -- the round trip, against the real decoder ---------------------------

def wav_window(path, call, grid, dbm):
    """One 114-second capture window holding our own transmission.

    The transmission starts one second in, because that is where WSPR puts
    it, and the window is padded to 114 s because that is what `wsprd` reads.
    """
    sig = wspr.samples(call, grid, dbm, base_hz=1500.0, amplitude=0.4)
    total = wspr.SAMPLE_RATE * 114
    frames = ([0.0] * wspr.SAMPLE_RATE + sig)[:total]
    frames += [0.0] * (total - len(frames))
    fh = wave.open(path, "w")
    fh.setnchannels(1)
    fh.setsampwidth(2)
    fh.setframerate(wspr.SAMPLE_RATE)
    fh.writeframes(b"".join(
        struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32000))
        for s in frames))
    fh.close()


print("\nwsprd decodes what this encoder produced")
if shutil.which("wsprd") is None:
    # Reported, not silently skipped. A missing decoder means this file did
    # not test the one thing it exists to test, and a run that says ALL PASS
    # without it would be lying by omission.
    check("SKIPPED — wsprd is not on PATH, the round trip did not run",
          False, "install wsjtx to run the test that matters")
else:
    with tempfile.TemporaryDirectory() as tmp:
        # The filename carries the timestamp: wsprd reads the date and time
        # out of it, proven by renaming a file and watching the reported
        # time change. So the capture's name is load-bearing, not tidiness.
        name = os.path.join(tmp, "260616_1200.wav")
        wav_window(name, CALL, GRID, DBM)
        out = subprocess.run(["wsprd", "-a", tmp, "-f", "14.0956", name],
                             capture_output=True, text=True, timeout=120)
        body = out.stdout
        check("wsprd ran", out.returncode == 0, out.stderr[:200])
        check("it terminated with the end marker",
              "<DecodeFinished>" in body, body[:200])
        check("the callsign came back", CALL in body, body[:200])
        check("the grid came back", GRID in body, body[:200])
        check(f"and the power, {DBM} dBm", f"{GRID} {DBM}" in body,
              body[:200])
        # The frequency is the dial plus the audio tone: 14.0956 + 1500 Hz.
        check("at the frequency the audio centre implies",
              "14.0971" in body, body[:200])

        all_wspr = os.path.join(tmp, "ALL_WSPR.TXT")
        check("it wrote ALL_WSPR.TXT", os.path.exists(all_wspr), tmp)
        if os.path.exists(all_wspr):
            line = open(all_wspr).read().strip()
            check("whose date and time come from the filename",
                  line.startswith("260616 1200"), line)
            check("and which names the station", CALL in line, line)

print("\nthe captured fixtures match what wsprd really prints")
# Kept as files so the parser, when it is written, is written against real
# output rather than a remembered format.
for fixture in ("wsprd_stdout.txt", "wsprd_all_wspr.txt"):
    path = os.path.join(_HERE, "fixtures", fixture)
    check(f"{fixture} exists", os.path.exists(path), path)
    if os.path.exists(path):
        check(f"and names {CALL}", CALL in open(path).read(), "")


# -- reading what wsprd says --------------------------------------------

print("\nthe parser reads real wsprd output")
MULTI = open(os.path.join(_HERE, "fixtures",
                          "wsprd_stdout_multi.txt")).read()
spots = wspr.parse_decodes(MULTI)
equals("four decodes in the four-signal window", len(spots), 4)
check("the run completed", wspr.decode_complete(MULTI), "")
equals("the strongest SNR", spots[0]["snr"], 18)
# Negative SNR is the normal case for WSPR, not an error.
equals("and the weakest, which is negative", spots[3]["snr"], -8)
equals("grids come through", [s["grid"] for s in spots],
       ["FN10", "EM12", "CN87", "JO41"])
# 0 dBm prints with an EXTRA space in front of it, so a fixed-column parser
# loses the power field on exactly the weakest signals. This is the case that
# justifies splitting on whitespace.
equals("and 0 dBm survives the extra space it prints with",
       spots[3]["dbm"], 0)
equals("frequencies are hertz, not megahertz", spots[0]["freq"], 14097082)
check("DT parses, including -0.0",
      spots[0]["dt"] == 0.0 and str(spots[0]["dt"]) in ("-0.0", "0.0"),
      repr(spots[0]["dt"]))
equals("drift comes through", spots[0]["drift"], 0)
check("nothing is marked hashed here",
      not any(s["hashed"] for s in spots), "")

print("\nthe end marker is how a finished run is told from a killed one")
check("a run with no decodes still completed",
      wspr.decode_complete("<DecodeFinished>\n"), "")
equals("and yields no spots", wspr.parse_decodes("<DecodeFinished>\n"), [])
check("output cut off mid-run is NOT complete",
      not wspr.decode_complete("1400  18 -0.0  14.097082  0  KD3CCO FN10 37"),
      "a killed decoder must not look like an empty window")

print("\nthe three message shapes")
# Type 1 is what the deck sends and what the fixtures hold. Types 2 and 3
# come off the air from other stations, so the parser has to read them
# though this encoder cannot produce them.
t2 = wspr.parse_decode("1400  -5  0.1  14.097100  0  KD3CCO/P 37")
equals("a compound call parses", t2["call"], "KD3CCO/P")
equals("with its power", t2["dbm"], 37)
check("and no grid field at all, rather than an empty one",
      "grid" not in t2, str(t2))
t3 = wspr.parse_decode("1400  -5  0.1  14.097100  0  <KD3CCO> FN10cs 37")
equals("a hashed call has its brackets stripped", t3["call"], "KD3CCO")
check("and is marked as hashed", t3["hashed"], str(t3))
equals("with its six-character grid", t3["grid"], "FN10cs")

print("\nwhat is not a decode is not parsed as one")
for junk in ("", "   ", "<DecodeFinished>", "garbage",
             "1400  18 -0.0", "not a time  18 -0.0  14.09  0  A B 1"):
    equals(f"{junk!r} yields nothing", wspr.parse_decode(junk), None)

print("\nthe parser attaches nothing the decoder did not say")
# The date, the band and this station's own fields are the deck's to add.
# A parser that invented them would be guessing where a guess cannot be told
# from data.
for absent in ("when", "band", "my_call", "my_grid", "activity"):
    check(f"{absent} is left to the caller", absent not in spots[0],
          str(spots[0]))

print("\none spot per station per window")
# A real finding, not a hypothetical: on a four-signal test window
# `wsprd -d` reported KD3CCO FN10 37 at both +23 dB and -10 dB. One
# transmission, found twice. Logging both puts a station in the log twice
# for one slot; uploading both reports a signal nobody sent.
dupes = wspr.parse_decodes(
    "1400 -10 -0.0  14.097082  0  KD3CCO FN10 37\n"
    "1400  23 -0.0  14.097082  0  KD3CCO FN10 37\n"
    "1400  11  0.0  14.097102  0  KD3CCO EM12 23\n"
    "<DecodeFinished>\n")
equals("three decodes came out of the window", len(dupes), 3)
kept = wspr.dedupe(dupes)
equals("two stations remain", len(kept), 2)
equals("and the STRONGEST copy is the one kept", kept[0]["snr"], 23)
equals("the other station is untouched", kept[1]["snr"], 11)
# Order is the order the decoder found things, so the list still reads the
# way the screen will show it.
equals("in the order they first appeared",
       [s["grid"] for s in kept], ["FN10", "EM12"])
# Keyed on call AND grid: a station that moved is a different report, and
# two stations can share a hashed call.
moved = wspr.dedupe(wspr.parse_decodes(
    "1400  5 0.0  14.097082  0  KD3CCO FN10 37\n"
    "1400  9 0.0  14.097082  0  KD3CCO EM12 37\n"
    "<DecodeFinished>\n"))
equals("the same call in two grids is two spots", len(moved), 2)
equals("nothing to dedupe is nothing changed", wspr.dedupe([]), [])

print("\nreal off-air output, from the deck's own wsprd 2.7.0")
# Captured 2026-10-17 at 0208 UTC on 40 m, real antenna, two stations. This
# is the fixture that matters most: every other one was either hand-written
# or produced by this project's own encoder, so none of them could prove the
# parser reads what a DIFFERENT implementation puts on the air -- nor that
# it reads `wsprd` 2.7.0, which is the deck's version and not the laptop's.
REAL = open(os.path.join(_HERE, "fixtures",
                         "wsprd_stdout_real_40m.txt")).read()
check("the run completed", wspr.decode_complete(REAL), "")
air = wspr.dedupe(wspr.parse_decodes(REAL))
equals("two stations", len(air), 2)
equals("the calls", [s["call"] for s in air], ["WW0WWV", "KC0MVF"])
equals("their grids", [s["grid"] for s in air], ["DN70", "EN13"])
equals("both at 1 W", [s["dbm"] for s in air], [30, 30])
# Weak signals, which is what WSPR is for: both well below the noise.
check("negative SNRs, as real WSPR is",
      all(s["snr"] < -20 for s in air), str([s["snr"] for s in air]))
check("and a positive time offset", all(s["dt"] > 0 for s in air),
      str([s["dt"] for s in air]))

# The decoded frequencies must land in the 1400-1600 Hz window above the
# dial. This checks the band table and the parser's hertz arithmetic against
# the air at once -- and would catch a dial frequency that was wrong by a
# kilohertz, which neither the published list nor the archived spots could.
DIAL_40M = 7_038_600
offsets = [s["freq"] - DIAL_40M for s in air]
equals("the offsets above the dial", offsets, [1453, 1515])
check("both inside the 200 Hz WSPR window",
      all(1400 <= o <= 1600 for o in offsets), str(offsets))
# 30 dBm is 1 W exactly, which is the other end of the power table.
equals("1 W is 30 dBm, exactly", wspr.dbm_for_watts(1), (30, True))

sys.exit(report())
