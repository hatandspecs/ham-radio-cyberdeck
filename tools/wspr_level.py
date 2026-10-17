#!/usr/bin/env python3
"""Report the audio level of a captured WAV. Reads only; changes nothing.

    python3 tools/wspr_level.py /tmp/free.wav

Roughly -30 to -20 dBFS is a healthy WSPR input. Loud enough to hear on a
speaker is far too loud: `wsprd` wants headroom, and a clipped window
decodes worse than a quiet one.

Deliberately not using `audioop`: it was removed from the standard library
in Python 3.13, and the deck's Python is newer than that. A tool built on it
runs on the development laptop and raises `ModuleNotFoundError` on the panel.
"""
import os
import sys
import wave

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
import wspr                                                  # noqa: E402


def main(paths):
    if not paths:
        print(__doc__.strip().splitlines()[2].strip())
        return 1
    for path in paths:
        try:
            with wave.open(path) as w:
                rate, chans, width = (w.getframerate(), w.getnchannels(),
                                      w.getsampwidth())
                frames = w.readframes(w.getnframes())
        except Exception as exc:
            print(f"{path}: cannot read: {exc}")
            continue
        secs = len(frames) / max(1, rate * chans * width)
        print(f"{os.path.basename(path)}: {rate} Hz, {chans} ch, "
              f"{width * 8}-bit, {secs:.1f} s")
        if width != 2 or chans != 1:
            print("  NOTE: not 16-bit mono, which is what wsprd needs")
        rms, peak, dbfs = wspr.audio_level(frames)
        if dbfs is None:
            print("  SILENCE — radio off, cable out, or the wrong card")
            continue
        headroom = 20.0 * __import__("math").log10(
            32768.0 / peak) if peak else 99.0
        verdict = ("too hot, back it off" if dbfs > -12 else
                   "healthy" if dbfs > -40 else
                   "very quiet, wsprd may still manage it")
        print(f"  RMS {rms:6d}  peak {peak:6d}  {dbfs:6.1f} dBFS  "
              f"{headroom:.1f} dB headroom  -> {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
