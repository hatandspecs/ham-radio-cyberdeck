#!/usr/bin/env python3
"""Capture one real WSPR window and decode it. RECEIVE ONLY — never keys.

    python3 tools/wspr_rx.py --band 40m

What it does, in order:

  1. stops `cyberdeck-fldigi`, because the USB codec is exclusive — measured:
     `arecord` with fldigi up fails "Device or resource busy",
  2. waits for the next even UTC minute, which is where a WSPR slot starts,
  3. captures 114 seconds with `arecord` into `YYMMDD_HHMM.wav` — the name
     carries the timestamp and `wsprd` reads it from there, proven by
     renaming a file and watching the reported time follow,
  4. reports the audio level, so a gain problem is distinguishable from a
     dead band,
  5. runs `wsprd` and reports the decodes, deduplicated,
  6. **puts fldigi back**, in a `finally`, whatever happened.

Nothing here transmits: no PTT, no playback, no tone. The radio needs to be
ON, on an ANTENNA, and tuned to the band's WSPR dial frequency in USB.

This is the receive path the deck will run, in a form that can be run once by
hand — so a slot captured here is also the fixture the parser gets tested
against.
"""
import argparse
import datetime
import os
import subprocess
import sys
import time
import wave

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
import wspr                                                  # noqa: E402
import wsprbands                                             # noqa: E402

FLDIGI_UNIT = "cyberdeck-fldigi"
CAPTURE_SECONDS = 114
SLOT_SECONDS = 120


def say(text=""):
    print(text, flush=True)


def service(action, unit=FLDIGI_UNIT):
    """systemctl, reporting rather than raising."""
    try:
        r = subprocess.run(["sudo", "systemctl", action, unit],
                           capture_output=True, text=True, timeout=60)
        return r.returncode == 0
    except Exception as exc:
        say(f"  systemctl {action} {unit}: {exc}")
        return False


def is_active(unit=FLDIGI_UNIT):
    r = subprocess.run(["systemctl", "is-active", unit],
                       capture_output=True, text=True)
    return r.stdout.strip() == "active"


def radio_state():
    """`(hertz, mode)` as the radio reports them, or `(0, "")`. Read-only.

    The MODE matters as much as the frequency. WSPR wants **upper** sideband:
    on LSB the 1400-1600 Hz window lands 1.5 kHz BELOW the dial and inverted,
    so a correctly tuned radio on the wrong sideband decodes nothing and
    looks exactly like a dead band.
    """
    try:
        import rigctld_client
        rig = rigctld_client.Rigctld()
        hz = int(rig.frequency() or 0)
        try:
            mode = (rig.mode() or ("", 0))[0]
        except Exception:
            mode = ""
        return hz, str(mode or "")
    except Exception:
        return 0, ""


def wait_for_slot():
    """Sleep until the next even UTC minute. Returns that datetime."""
    now = time.time()
    target = now - (now % SLOT_SECONDS) + SLOT_SECONDS
    while True:
        left = target - time.time()
        if left <= 0:
            break
        say(f"  waiting {left:4.0f} s for the next even minute...")
        time.sleep(min(left, 10.0))
    return datetime.datetime.now(datetime.timezone.utc)


def capture(device, path, seconds=CAPTURE_SECONDS):
    """arecord one window. Returns (ok, message)."""
    cmd = ["arecord", "-D", device, "-f", "S16_LE", "-r",
           str(wspr.SAMPLE_RATE), "-c", "1", "-d", str(seconds), path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=seconds + 30)
    except Exception as exc:
        return False, str(exc)
    if r.returncode != 0:
        return False, (r.stderr or "").strip().splitlines()[-1:] and \
            (r.stderr or "").strip().splitlines()[-1] or "arecord failed"
    return True, ""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--band", default="40m",
                    help="which band's WSPR dial frequency (default 40m)")
    ap.add_argument("--device", default="plughw:1,0",
                    help="ALSA capture device (default plughw:1,0)")
    ap.add_argument("--dir", default="/tmp/wsprrx",
                    help="where to put the WAV and wsprd's own files")
    ap.add_argument("--deep", action="store_true",
                    help="wsprd -d, slower and a few more decodes")
    ap.add_argument("--keep-fldigi", action="store_true",
                    help="do not stop fldigi (the capture will likely fail)")
    args = ap.parse_args(argv)

    label = wsprbands.normalise(args.band)
    dial = wsprbands.dial_hz(args.band)
    if not dial:
        say(f"'{args.band}' is not a band this deck knows. One of: "
            + ", ".join(l for _k, l, _h in wsprbands.BANDS))
        return 2
    os.makedirs(args.dir, exist_ok=True)

    say(f"band        {label}, WSPR dial {dial / 1_000_000:.6f} MHz")
    say(f"device      {args.device}")
    say(f"RECEIVE ONLY — nothing here keys the transmitter.")
    say()

    tuned, mode = radio_state()
    if tuned:
        off = tuned - dial
        agrees = abs(off) <= 500
        say(f"radio reads  {tuned / 1_000_000:.6f} MHz "
            f"({'matches' if agrees else f'OFF BY {off:+d} Hz'})"
            + (f", mode {mode}" if mode else ""))
        if not agrees:
            say(f"  -> tune the radio to {dial / 1_000_000:.6f} MHz USB, "
                f"or pass --band for the band it is on")
        # Upper sideband or a data mode built on it. On LSB the WSPR window
        # lands 1.5 kHz below the dial and inverted: nothing decodes, and it
        # looks precisely like a dead band.
        up = mode.upper()
        if up and not any(k in up for k in ("USB", "PKTUSB", "DATA-U",
                                            "DIGU", "USB-D", "RTTY")):
            say(f"  *** mode is {mode}. WSPR needs UPPER sideband — on LSB")
            say(f"      the window is 1.5 kHz low and inverted, and nothing")
            say(f"      will decode. Set USB (or a USB-based data mode).")
    else:
        say("radio       could not be read (rigctld down, or no CAT)")
        say(f"  -> make sure it is on {dial / 1_000_000:.6f} MHz USB")
    say()

    stopped = False
    try:
        if not args.keep_fldigi and is_active():
            say(f"stopping {FLDIGI_UNIT} — the USB codec is exclusive")
            stopped = service("stop")
            time.sleep(2)

        started = wait_for_slot()
        name = started.strftime("%y%m%d_%H%M") + ".wav"
        path = os.path.join(args.dir, name)
        say(f"capturing {CAPTURE_SECONDS} s into {name} "
            f"(the name carries the slot; wsprd reads it)")
        t0 = time.monotonic()
        ok, why = capture(args.device, path)
        say(f"  arecord took {time.monotonic() - t0:.1f} s")
        if not ok:
            say(f"  FAILED: {why}")
            return 1
        say(f"  {os.path.getsize(path)} bytes")

        with wave.open(path) as w:
            frames = w.readframes(w.getnframes())
        rms, peak, dbfs = wspr.audio_level(frames)
        if dbfs is None:
            say("  level: SILENCE — nothing is reaching the codec")
        else:
            verdict = ("TOO HOT, back it off" if dbfs > -12 else
                       "healthy" if dbfs > -40 else
                       "quiet; fine on a dead band, low on a live one")
            say(f"  level: {dbfs:6.1f} dBFS  (rms {rms}, peak {peak})"
                f"  -> {verdict}")
        say()

        cmd = ["wsprd", "-a", args.dir, "-f", f"{dial / 1_000_000:.6f}"]
        if args.deep:
            cmd.append("-d")
        cmd.append(path)
        say(f"decoding: {' '.join(cmd)}")
        t0 = time.monotonic()
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        took = time.monotonic() - t0
        raw = wspr.parse_decodes(r.stdout)
        spots = wspr.dedupe(raw)
        done = wspr.decode_complete(r.stdout)
        say(f"  {took:.1f} s, {len(spots)} stations"
            + (f" ({len(raw)} before dedupe)" if len(raw) != len(spots) else "")
            + (" " if done else "  *** NO END MARKER — wsprd did not finish"))
        say()
        if spots:
            for s in spots:
                say(f"  {s['snr']:>4} dB  {s['dt']:+.1f} s  "
                    f"{s['freq'] / 1_000_000:.6f}  drift {s['drift']:>2}  "
                    f"{s['call']:<9} {s.get('grid', '-'):<7} {s['dbm']:>2} dBm"
                    + ("  <hashed>" if s.get("hashed") else ""))
        else:
            say("  nothing decoded. On a live band that is a gain or a")
            say("  tuning problem; on a dead one it is just a dead one.")
        say()
        say("RAW wsprd stdout, which is what the parser is written against:")
        for line in r.stdout.splitlines():
            say(f"  |{line}")
        say()
        say(f"the WAV is kept at {path}")
        say("ALL_WSPR.TXT and the rest of wsprd's files are in "
            f"{args.dir}")
        return 0
    finally:
        # Always, whatever happened above. A tool that leaves the deck
        # without its digimode decoder is a tool nobody runs twice.
        if stopped:
            say(f"restarting {FLDIGI_UNIT}")
            service("start")
            time.sleep(3)
            say(f"  {FLDIGI_UNIT} is "
                f"{'active' if is_active() else 'NOT ACTIVE — check it'}")


if __name__ == "__main__":
    sys.exit(main())
