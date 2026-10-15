#!/usr/bin/env python3
"""Draw the log screen to this terminal, in whatever state you ask for.

For looking at the layout without a deck, a radio, or a rebuild. It uses the
same `render.log_screen` the deck calls, at the panel's real 66x20, so what
appears here is what appears there — in plain text rather than the console
font and palette.

    tools/preview_log.py                     general logging
    tools/preview_log.py --activity POTA     a park activation
    tools/preview_log.py --activity CONTEST  serial and exchange
    tools/preview_log.py --all               every activity in turn

    tools/preview_log.py --focus exchange_rx     put the cursor somewhere
    tools/preview_log.py --columns 1             one field per row
    tools/preview_log.py --width 80 --height 24  a different screen

Edit the fixtures at the bottom to try other content. Nothing here touches
the deck or the log file.
"""

import argparse
import os
import sys

_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT, "src"))

import activities                                    # noqa: E402
import logform                                       # noqa: E402
import render                                        # noqa: E402


CONTACTS = {
    "GENERAL": [
        {"when": "2026-10-11T16:04:00Z", "call": "W3ABC", "rst_s": "59",
         "rst_r": "57", "name": "Bob", "qth": "Pittsburgh, PA"},
        {"when": "2026-10-11T16:11:00Z", "call": "K2XYZ", "rst_s": "59",
         "rst_r": "59", "name": "Jim", "comment": "running 5W to a wire"},
        {"when": "2026-10-11T16:19:00Z", "call": "OK2CQR", "rst_s": "59",
         "rst_r": "55", "name": "Petr", "qth": "Neratovice, Czech Rep"},
    ],
    "POTA": [
        {"when": "2026-10-11T14:02:00Z", "call": "W3ABC", "rst_s": "59",
         "rst_r": "57", "park": "US-1234", "name": "Bob"},
        {"when": "2026-10-11T14:06:00Z", "call": "K2XYZ", "rst_s": "59",
         "rst_r": "59", "name": "Jim"},
        {"when": "2026-10-11T14:09:00Z", "call": "N3QQQ", "rst_s": "59",
         "rst_r": "55", "park": "US-0042", "comment": "park to park"},
    ],
    "CONTEST": [
        {"when": "2026-10-11T18:31:00Z", "call": "W3ABC", "rst_s": "59",
         "rst_r": "59", "activity": "CONTEST", "serial_tx": "55",
         "serial_rx": "101", "exchange_rx": "MONT"},
        {"when": "2026-10-11T18:32:00Z", "call": "K2XYZ", "rst_s": "59",
         "rst_r": "59", "activity": "CONTEST", "serial_tx": "56",
         "serial_rx": "17", "exchange_rx": "ALLE"},
        {"when": "2026-10-11T18:33:00Z", "call": "N3QQQ", "rst_s": "59",
         "rst_r": "59", "activity": "CONTEST", "serial_tx": "57",
         "serial_rx": "212", "exchange_rx": "BUCK"},
    ],
}

RADIO = {
    "GENERAL": ("7.185", "SSB", "40m"),
    "POTA": ("14.285", "SSB", "20m"),
    "CONTEST": ("3.820", "SSB", "80m"),
}

HALF_TYPED = {"GENERAL": "W1AW", "POTA": "W3YA", "CONTEST": "K3PP"}


def build(name, table, focus="", columns=2):
    act = activities.get(name, table)
    key = name.upper() if name.upper() in RADIO else "GENERAL"
    freq, mode, band = RADIO[key]
    contacts = CONTACTS.get(key, CONTACTS["GENERAL"])

    form = logform.LogForm(act)
    form.from_radio(freq=freq, mode=mode)
    form.advance_serial(contacts, act.serial_start)
    if form.field("exchange_tx"):
        form.set("exchange_tx", "CENT")
    if form.field("my_park"):
        form.set("my_park", "US-5678")
    form.set("comment", "5W to a wire")

    form.focus("call")
    form.type(HALF_TYPED.get(key, "W1AW"))
    if focus and not form.focus(focus):
        print(f"-- no field called {focus!r}; it is one of: "
              f"{', '.join(f.name for f in form.fields)}", file=sys.stderr)

    header = {"band": band, "mode": mode, "freq": freq,
              "count": len(contacts), "clock": "1627Z"}
    if act.name != "GENERAL":
        header["activity"] = act.name
    if form.value("my_park"):
        header["my_park"] = form.value("my_park")
    return contacts, form, header


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--activity", default="GENERAL")
    ap.add_argument("--all", action="store_true", help="every activity")
    ap.add_argument("--focus", default="", help="field to put the cursor in")
    ap.add_argument("--columns", type=int, default=2)
    ap.add_argument("--width", type=int, default=66)
    ap.add_argument("--height", type=int, default=20)
    ap.add_argument("--fields", action="store_true",
                    help="list the tab order instead of drawing")
    args = ap.parse_args(argv)

    table = activities.load()
    wanted = (sorted(table) if args.all else [args.activity])

    for name in wanted:
        contacts, form, header = build(name, table, args.focus, args.columns)
        act = activities.get(name, table)
        print(f"=== {act.name} — {act.label} ===")
        if args.fields:
            for i, f in enumerate(form.fields):
                mark = " <- cursor" if i == form.index else ""
                tag = []
                if f.sticky:
                    tag.append("sticky")
                if f.from_radio:
                    tag.append("from radio")
                print(f"  {i + 1}. {f.name:12} {f.label:10} "
                      f"{('(' + ', '.join(tag) + ')') if tag else '':<22}"
                      f"{f.value!r}{mark}")
            print()
            continue

        # The renderer takes its column count from form_rows; patch it for
        # the preview rather than threading an argument nothing else needs.
        original = render.form_rows
        if args.columns != 2:
            render.form_rows = (
                lambda fm, w, columns=args.columns, focus_cursor=True:
                original(fm, w, columns=columns, focus_cursor=focus_cursor))
        try:
            lines = render.log_screen(contacts, "", args.width, args.height,
                                      header=header, form=form)
        finally:
            render.form_rows = original

        print("+" + "-" * args.width + "+")
        for line in lines:
            print("|" + render.plain(line) + "|")
        print("+" + "-" * args.width + "+")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
