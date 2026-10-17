#!/usr/bin/env python3
"""Measure what `wsprd` costs on this machine. Decodes only — never transmits.

Generates a 114-second window holding four of this station's own beacons at
descending levels with noise, then times `wsprd` over it with and without
deep search, and reports peak memory.

Answers open questions 1 and 3 of `docs/wspr_design.md` on the hardware that
has to run it. Nothing here touches a radio, a sound card or the network: it
writes a WAV to a temporary directory and reads it back.

    python3 tools/wspr_bench.py
"""
import array
import os
import random
import shutil
import subprocess
import struct
import sys
import tempfile
import time
import wave

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
import wspr                                                  # noqa: E402

# This station's own call, at four levels. Test traffic uses our own.
SIGNALS = [
    ("KD3CCO", "FN10", 37, 1480.0, 0.030),
    ("KD3CCO", "EM12", 23, 1500.0, 0.008),
    ("KD3CCO", "CN87", 10, 1520.0, 0.003),
    ("KD3CCO", "JO41",  0, 1545.0, 0.0015),
]


def window(path):
    """Write a 114 s window holding four beacons in noise.

    Returns `(render_seconds, harness_seconds)`. **The split matters.** The
    first version of this reported one number for the whole function, and on
    the deck that number was 26.9 s — which read as "the transmit path takes
    a fifth of a slot to build its audio" and is not what it measures. The
    render is a twelfth of it. The rest is this harness fabricating a noise
    floor and packing a WAV, neither of which the deck does when it beacons.
    """
    render = 0.0
    t0 = time.monotonic()

    # int16 throughout, and `.tobytes()` at the end. The original built a
    # 1.37M-element float list and `struct.pack`ed it one sample at a time,
    # which is most of what the deck was waiting for.
    total = wspr.SAMPLE_RATE * 114
    buf = array.array("h", bytes(2 * total))
    rnd = random.Random(7)
    noise = rnd.randint
    for i in range(total):
        buf[i] = noise(-130, 130)

    for call, grid, dbm, hz, amp in SIGNALS:
        t = time.monotonic()
        sig = wspr.samples(call, grid, dbm, base_hz=hz, amplitude=amp)
        render += time.monotonic() - t
        off = wspr.SAMPLE_RATE
        for i, v in enumerate(sig):
            j = off + i
            if j < total:
                mixed = buf[j] + int(v * 32000)
                buf[j] = 32767 if mixed > 32767 else (
                    -32768 if mixed < -32768 else mixed)

    fh = wave.open(path, "w")
    fh.setnchannels(1)
    fh.setsampwidth(2)
    fh.setframerate(wspr.SAMPLE_RATE)
    fh.writeframes(buf.tobytes())
    fh.close()
    return render, time.monotonic() - t0 - render


def main():
    print(f"machine: {' '.join(os.uname())}")
    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, "260616_1400.wav")
        render, harness = window(wav)
        print(f"encoding + rendering 4 transmissions: {render:5.2f} s "
              f"({render / 4:.2f} s each)")
        print(f"   <- THIS is the transmit path. One beacon is one of these.")
        print(f"fabricating noise and packing the WAV: {harness:5.2f} s "
              f"({os.path.getsize(wav) // 1024} KiB)")
        print(f"   <- harness only. The deck does none of this to beacon.")
        print()
        # Memory comes from `/usr/bin/time -v`, NOT from
        # `resource.getrusage(RUSAGE_CHILDREN)`. That reports the peak RSS of
        # the largest child, and a child inherits the parent's address space
        # at `fork()` before it `exec`s -- so it counted the WAV buffer this
        # script had just built and reported 315 MiB for a decoder that uses
        # 22. On a 512 MB board that is the difference between "will not fit"
        # and "fine", which is a wrong answer worth avoiding by construction.
        timer = shutil.which("time") or "/usr/bin/time"
        have_timer = os.path.exists("/usr/bin/time")
        if not have_timer:
            print("NOTE: /usr/bin/time is missing, so no memory figure.")
            print("      install it (dnf install time) and run again.")
        for label, args in (("normal", []), ("deep (-d)", ["-d"])):
            cmd = ["wsprd", "-a", tmp, "-f", "14.0956"] + args + [wav]
            if have_timer:
                cmd = ["/usr/bin/time", "-v"] + cmd
            t = time.monotonic()
            out = subprocess.run(cmd, capture_output=True, text=True)
            took = time.monotonic() - t
            peak = ""
            for line in out.stderr.splitlines():
                if "Maximum resident set size" in line:
                    kb = int(line.rsplit(":", 1)[1].strip())
                    peak = f"peak RSS {kb / 1024:.0f} MiB   "
            spots = wspr.dedupe(wspr.parse_decodes(out.stdout))
            raw = len(wspr.parse_decodes(out.stdout))
            done = wspr.decode_complete(out.stdout)
            dup = f" ({raw} before dedupe)" if raw != len(spots) else ""
            print(f"{label:>10}: {took:6.2f} s   "
                  f"{len(spots)} stations{dup}   {peak}"
                  f"{'complete' if done else 'NO END MARKER'}")
            for s in spots:
                print(f"            {s['snr']:>4} dB  {s['call']} "
                      f"{s.get('grid', '-')} {s['dbm']}")
        print()
        print("the slot is 120 s and a decode may overlap the next capture,")
        print("so the deadline is 120 s, not the 6 s gap between windows.")


if __name__ == "__main__":
    main()
