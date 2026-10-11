#!/usr/bin/env python3
"""Log contacts from the command line, over SSH, before the deck has a screen for it.

This is the logging core (`src/qsolog.py`) with a terminal in front of it. It
exists so the storage, the parsing and the ADIF export can be exercised on the
real hardware while the interface in `cyberdeck.py` is still unwritten — and
because it is genuinely usable on its own: SSH in from a phone and log
whatever is being worked.

It reads the same file the deck's screen will, in the same format, so nothing
logged with this has to be migrated later.

    qso.py log  W3ABC 59 57 Bob Pittsburgh   log a contact
    qso.py log  W3ABC 59 57 US-1234           a park reference, recognized by
                                              shape, if that is the operating
    qso.py log --comment "5W to a wire" W3ABC 59 57

The deck's own log screen takes the comment inline after a `;`, which is the
right thing for one typed line. On a command line `;` has to be quoted past
the shell and argparse will not take positional words after an option, so the
comment is a flag here and any options come before the words.
    qso.py list [n]                          the last n (default 20)
    qso.py adif [file]                       export; stdout if no file
    qso.py lotw [file]                       export + the tqsl command for LoTW
    qso.py backfill                          fill in names and grids on WiFi
    qso.py count                             how many, and on what

Frequency and mode come from rigctld and fldigi when they answer and are left
out when they do not, which is the same rule the deck follows: absent hardware
is an ordinary condition and a contact with an unknown frequency beats a lost
contact. `--freq` and `--mode` override either.
"""

import argparse
import datetime
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for candidate in (os.path.join(os.path.dirname(HERE), "src"),   # a checkout
                  HERE):                                        # /opt/cyberdeck
    if os.path.exists(os.path.join(candidate, "qsolog.py")):
        sys.path.insert(0, candidate)
        break

import qsolog                                           # noqa: E402
import activities as activity_mod                       # noqa: E402

try:
    import config                                       # noqa: E402
except Exception:
    config = None


def settings():
    if config is None:
        return {}
    try:
        return config.load()
    except Exception as exc:
        print(f"-- could not read the configuration: {exc}", file=sys.stderr)
        return {}


def radio_state(cfg, operating=""):
    """(freq_hz, adif_mode, tx_watts, back_end, notes). Never raises, never blocks for long.

    The mode comes out of `qsolog.resolve_mode`, so this tool and the deck's
    own screen decide it the same way: on digital the modem fldigi has up is
    the mode, and on voice fldigi is ignored no matter what it has loaded.
    `operating` overrides the configured OPERATING for one entry.

    Imported inside the function so that logging works on a machine with
    neither rigctld nor fldigi — which is most machines, including the one
    this is being written on.
    """
    freq, notes = None, []
    rig_mode, modem, active = "", "", False

    power, backend = 0, ""
    try:
        import rigctld_client
        # `Rigctld`, not `RigctldClient`. The earlier spelling raised an
        # AttributeError that this except swallowed into "rigctld
        # unreachable", so the tool reported a missing radio on a machine
        # where the radio was merely never asked.
        rig = rigctld_client.Rigctld()
        freq = rig.frequency()
        if not freq:
            notes.append("rigctld gave no frequency")
        rig_mode, _width = rig.mode()
        # The configured ceiling first: it is what makes this work on any
        # radio, and on this one it is also what distinguishes a 6 W battery
        # setup from a 10 W external one, which no CAT command reports.
        power = rig.power(max_watts=cfg.get("TX_POWER_MAX", 0),
                          freq_hz=freq, mode=rig_mode)
        if power:
            _w, backend = rig.power_control()
    except Exception as exc:
        notes.append(f"rigctld unreachable ({type(exc).__name__}); "
                     f"frequency unknown")

    try:
        import fldigi_client
        fl = fldigi_client.Fldigi(cfg.get("FLDIGI_URL")
                                  or fldigi_client.DEFAULT_URL)
        if fl.connected:
            modem = fl.modem() or ""
            # `transmitting` is the only positive evidence available over SSH
            # that fldigi is actually in use. It is not much — a digital
            # contact is in RX most of the time — so `auto` here leans mostly
            # on the rig's mode. The deck itself does better, because it sees
            # its own traffic; see qso_log_design.md §6.
            active = bool(fl.transmitting())
    except Exception as exc:
        notes.append(f"fldigi unreachable ({type(exc).__name__})")

    operating = operating or cfg.get("OPERATING", "auto")
    mode, source = qsolog.resolve_mode(operating, rig_mode=rig_mode,
                                       fldigi_modem=modem,
                                       fldigi_active=active)
    if source == "default":
        notes.append(f"mode defaulted to {mode}; use --mode to change it")
    elif source == "fldigi":
        notes.append(f"mode {mode} from fldigi ({modem})")
    elif source == "rig":
        notes.append(f"mode {mode} from the rig ({rig_mode})")
    return freq, mode, power, backend, notes


def cmd_log(args, cfg, path):
    text = " ".join(args.words)
    freq, mode, power, backend, notes = (
        (None, args.mode, 0, "", []) if args.mode
        else radio_state(cfg, args.operating))
    if args.freq:
        freq = int(float(args.freq) * (1000 if args.freq.find(".") >= 0 else 1))

    table = activity_mod.load()
    act = activity_mod.get(args.activity or cfg.get("ACTIVITY", ""), table)
    if args.activity and act.name == "GENERAL" and \
            args.activity.strip().upper() != "GENERAL":
        notes.append(f"no activity named {args.activity!r}; logging generally "
                     f"(known: {', '.join(sorted(table))})")

    try:
        parsed = qsolog.parse_entry(text, mode, act)
    except qsolog.ParseError as exc:
        print(f"-- {exc}", file=sys.stderr)
        return 1

    # An inline `;` wins if one survived the shell, so the two syntaxes agree
    # when both are used and neither silently discards the other.
    if args.comment and not parsed.get("comment"):
        parsed["comment"] = args.comment.strip()

    # POTA mode decides whether this station's own park goes on the record.
    # Off — the default — a general log gets no MY_SIG fields even if MY_PARK
    # is still sitting in the configuration from the last activation.
    pota = args.pota or cfg.get("POTA") == "yes"
    my_park = ""
    if pota:
        my_park = (args.my_park or cfg.get("MY_PARK")
                   or os.environ.get("CYBERDECK_MY_PARK", ""))
    elif args.my_park:
        notes.append("--my-park ignored: POTA mode is off; add --pota")

    # Printed here, after every note has been collected. Printing them where
    # radio_state returned meant the POTA note below was appended to a list
    # that had already been flushed, and never appeared.
    for note in notes:
        print(f"-- {note}")

    # This station's serial comes from the log, not a counter file, so it
    # survives a power pull and cannot disagree with what was actually sent.
    serial_tx = ""
    if act.serial:
        serial_tx = qsolog.next_serial(qsolog.read(path), act.name,
                                       act.serial_start)

    exchange_tx = args.exchange_tx or cfg.get("EXCHANGE_TX", "")

    rec = qsolog.make_record(
        parsed, datetime.datetime.now(datetime.timezone.utc),
        freq_hz=freq, mode=mode,
        my_call=cfg.get("CALLSIGN", ""), my_grid=cfg.get("LOCATOR", ""),
        my_park=my_park, activity=act, serial_tx=serial_tx,
        exchange_tx=exchange_tx,
        my_rig=cfg.get("RIG", ""), my_antenna=cfg.get("ANTENNA", ""),
        # The radio's actual power when it answered, the configured wattage
        # when it did not. What was logged should be what the radio was doing.
        tx_power=(int(args.power) if args.power
                  else power or cfg.get("TX_POWER", 0)),
        tx_backend=("" if args.power else backend))

    if args.lookup:
        import callbook
        chain = callbook.providers_from(cfg)
        cache = callbook.Cache(callbook.cache_path())
        info = callbook.lookup(rec["call"], cache=cache, providers=chain)
        if info:
            rec = callbook.merge(rec, info)
            print(f"-- callbook: {', '.join(f'{k}={v}' for k, v in info.items())}")
        else:
            errors = [p.last_error for p in chain if getattr(p, "last_error", "")]
            print("-- callbook: nothing known"
                  + (f" ({'; '.join(errors)})" if errors else ""))

    qsolog.append(path, rec)

    band = rec.get("band") or "band unknown"
    extra = "".join(f" {rec[k]}" for k in
                    ("serial_rx", "exchange_rx", "park", "name")
                    if rec.get(k))
    if rec.get("serial_tx"):
        extra += f" (sent #{rec['serial_tx']})"
    print(f"-- logged {rec['call']} {band} {rec.get('mode','')} "
          f"{rec['rst_s']}/{rec['rst_r']}{extra}")
    return 0


def cmd_list(args, cfg, path):
    records = enrich(qsolog.read(path), cfg)
    if not records:
        print(f"-- nothing logged yet ({path})")
        return 0
    # Columns are only reserved when something in the window uses them, so an
    # ordinary log does not get a screenful of empty exchange fields.
    window = records[-args.n:]
    has = {k: any(r.get(k) for r in window)
           for k in ("serial_rx", "exchange_rx", "park", "serial_tx")}
    for rec in window:
        when = rec.get("when", "")[11:16]
        line = (f"{when}  {rec.get('call',''):<10} "
                f"{rec.get('band',''):<5} {rec.get('mode',''):<5} "
                f"{rec.get('rst_s','')}/{rec.get('rst_r',''):<4} ")
        if has["serial_tx"]:
            line += f"#{rec.get('serial_tx',''):<5}"
        if has["serial_rx"]:
            line += f"{rec.get('serial_rx',''):<6}"
        if has["exchange_rx"]:
            line += f"{rec.get('exchange_rx',''):<10}"
        if has["park"]:
            line += f"{rec.get('park',''):<10}"
        line += f"{rec.get('name','')} {rec.get('qth','')} {rec.get('comment','')}"
        print(line.rstrip())
    print(f"-- {len(records)} total in {path}")
    return 0


def cmd_adif(args, cfg, path):
    records = enrich(qsolog.read(path), cfg)
    text = qsolog.adif_export(records)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        print(f"-- {len(records)} contacts to {args.out}")
    else:
        sys.stdout.write(text)
    return 0


def enrich(records, cfg):
    """Fill blank name/QTH/grid from the callbook cache. Never touches the log.

    This is the "fill it in later, on WiFi" path, and it works by **not**
    rewriting anything. The log is append-only — that is what makes it safe
    across a power pull — so a backfill that edited it in place would trade
    the one property worth having for a convenience.

    Instead the cache is the backfill. `qso.py backfill` looks up every call
    in the log that is missing something and stores the answers; every export
    after that merges them in. Nothing is lost if the cache is deleted, and
    the log on disk stays byte-for-byte what was logged at the time.
    """
    try:
        import callbook
    except Exception:
        return records
    cache = callbook.Cache(callbook.cache_path())
    out = []
    for rec in records:
        if all(rec.get(f) for f in callbook.WANTED):
            out.append(rec)
            continue
        known = cache.get(rec.get("call", ""))
        out.append(callbook.merge(rec, known) if known else rec)
    return out


def cmd_backfill(args, cfg, path):
    """Look up every call in the log that is still missing something.

    Run it when there is a network. It writes to the callbook cache, not to
    the log, so it can be run as often as you like and interrupting it loses
    nothing but the lookups it had not reached.
    """
    import callbook

    records = qsolog.read(path)
    if not records:
        print(f"-- nothing logged yet ({path})")
        return 0

    cache = callbook.Cache(callbook.cache_path())
    chain = callbook.providers_from(cfg)

    wanted = []
    for rec in records:
        call = rec.get("call", "")
        if not call or call in wanted:
            continue
        merged = callbook.merge(rec, cache.get(call) or {})
        if not all(merged.get(f) for f in callbook.WANTED):
            wanted.append(call)

    if not wanted:
        print(f"-- nothing to look up; all {len(records)} contacts are complete")
        return 0

    print(f"-- {len(wanted)} call{'' if len(wanted) == 1 else 's'} to look up")
    found = 0
    for i, call in enumerate(wanted):
        if args.limit and i >= args.limit:
            print(f"-- stopped at {args.limit}")
            break
        info = callbook.lookup(call, cache=cache, providers=chain)
        if info:
            found += 1
            print(f"   {call:10} {', '.join(f'{k}={v}' for k, v in info.items())}")
        else:
            print(f"   {call:10} nothing known")
    print(f"-- {found} filled in; they appear in the next list or export")
    return 0


def cmd_activities(args, cfg, path):
    """What activities exist, what each one types, and which is selected."""
    table = activity_mod.load()
    current = activity_mod.get(cfg.get("ACTIVITY", ""), table).name
    print("fields an entry list may name:")
    for name, label, kind in activity_mod.field_choices():
        print(f"  {name:12} {label:22} {kind}")
    print("\nactivities:")
    for name in sorted(table):
        act = table[name]
        mark = "*" if name == current else " "
        bits = [f"entry={', '.join(act.entry) or '(none)'}"]
        if act.serial:
            bits.append(f"serial from {act.serial_start}")
        if act.contest_id:
            bits.append(f"contest_id={act.contest_id}")
        print(f" {mark} {name:13} {act.label}")
        print(f"     {'; '.join(bits)}")
    print(f"\n* = selected (ACTIVITY in cyberdeck.conf)")
    return 0


def cmd_lotw(args, cfg, path):
    """Export ADIF and print the tqsl command, or run it with --upload.

    Printing by default is the point, not a limitation. tqsl needs a callsign
    certificate, and without one it blocks instead of failing — so the honest
    default is to hand over a command to run where the certificate lives,
    which is also where a private key belongs. See qso_log_design.md §11.
    """
    import lotw

    records = qsolog.read(path)
    if not records:
        print(f"-- nothing logged yet ({path})")
        return 0

    out = args.out or os.path.splitext(path)[0] + ".adi"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(qsolog.adif_export(records))
        fh.flush()
        os.fsync(fh.fileno())
    print(f"-- {len(records)} contacts to {out}")

    location = args.location or cfg.get("LOTW_LOCATION", "")
    if not location:
        print("-- no LOTW_LOCATION set; tqsl will ask which station location "
              "to use, which it cannot do in batch mode")

    if not args.upload:
        print("-- sign and upload it with:")
        print("   " + lotw.quoted_command(out, location=location, upload=True))
        if not lotw.available():
            print("-- tqsl is not installed here; run that on a machine that "
                  "has it and holds your callsign certificate")
        return 0

    found = lotw.version()
    if not found:
        print("-- tqsl is not installed or did not answer", file=sys.stderr)
        return 1
    print(f"-- {found}")
    outcome, detail = lotw.upload(out, location=location)
    print(f"-- {outcome}" + (f": {detail}" if detail else ""))
    return 0 if outcome == lotw.OK else 1


def cmd_count(args, cfg, path):
    records = qsolog.read(path)
    bands, modes = {}, {}
    for rec in records:
        bands[rec.get("band", "?")] = bands.get(rec.get("band", "?"), 0) + 1
        modes[rec.get("mode", "?")] = modes.get(rec.get("mode", "?"), 0) + 1
    print(f"{len(records)} contacts in {path}")
    if records:
        print("  bands: " + ", ".join(f"{k} {v}" for k, v in sorted(bands.items())))
        print("  modes: " + ", ".join(f"{k} {v}" for k, v in sorted(modes.items())))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", default="", help="log file (default ~/.local/share/cyberdeck/qso.log)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("log", help="log a contact")
    p.add_argument("words", nargs="+",
                   metavar="CALL [RST_S] [RST_R] [NAME] [QTH] [; COMMENT]")
    p.add_argument("--freq", default="", help="kHz if it has a decimal point, else Hz")
    p.add_argument("--mode", default="", help="USB, LSB, CW, BPSK31 ...")
    p.add_argument("--my-park", default="", help="this station's POTA reference (needs --pota)")
    p.add_argument("--pota", action="store_true", help="POTA mode for this entry")
    p.add_argument("--operating", default="", choices=("", "auto", "digital", "voice"),
                   help="where the mode comes from; overrides OPERATING")
    p.add_argument("--activity", default="",
                   help="activity type, e.g. POTA or PAQP; overrides ACTIVITY")
    p.add_argument("--exchange-tx", default="",
                   help="this station's exchange; overrides EXCHANGE_TX")
    p.add_argument("--power", default="", help="transmit watts; overrides CAT and TX_POWER")
    p.add_argument("--lookup", action="store_true",
                   help="look the call up (callook, HamQTH, QRZ) before logging")
    p.add_argument("--comment", default="", help="free text; the deck's screen takes this after a ';'")
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("list", help="recent contacts")
    p.add_argument("n", nargs="?", type=int, default=20)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("adif", help="export ADIF")
    p.add_argument("out", nargs="?", default="")
    p.set_defaults(func=cmd_adif)

    p = sub.add_parser("lotw", help="export ADIF and the tqsl command for LoTW")
    p.add_argument("out", nargs="?", default="", help="ADIF file to write")
    p.add_argument("--location", default="", help="tqsl Station Location name")
    p.add_argument("--upload", action="store_true",
                   help="actually run tqsl here (needs a callsign certificate)")
    p.set_defaults(func=cmd_lotw)

    p = sub.add_parser("count", help="how many, and on what")
    p.set_defaults(func=cmd_count)

    p = sub.add_parser("backfill",
                       help="look up calls still missing a name or grid")
    p.add_argument("--limit", type=int, default=0, help="stop after this many")
    p.set_defaults(func=cmd_backfill)

    p = sub.add_parser("activities", help="list activity types and their fields")
    p.set_defaults(func=cmd_activities)

    args = ap.parse_args(argv)
    cfg = settings()
    path = qsolog.log_path(args.file)
    return args.func(args, cfg, path)


if __name__ == "__main__":
    sys.exit(main())
