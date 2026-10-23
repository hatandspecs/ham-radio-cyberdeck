"""The WSPR screens for the documentation, built from the real renderers.

Separate from `capture_png.py` only to keep that file's main block readable.
Every screen here is what `Deck._draw_wspr` and `menus` actually produce --
no hand-drawn mockups, so a change to the layout shows up in the next
regeneration rather than silently diverging from the documentation.

The spots are real ones received by this station on 20 m. Other operators'
callsigns and grid squares are already published on wsprnet; that is what
the mode is for.
"""
import os
import sys

_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT, "src"))
import menus
import render

SPOTS = [
    {"when": "2026-10-17T17:46:00Z", "snr": -19, "call": "KD1SQ",
     "grid": "FN67", "dbm": 23, "band": "20 m", "km": 1139, "az": 45},
    {"when": "2026-10-17T17:46:00Z", "snr": -28, "call": "N9JNQ",
     "grid": "EN34", "dbm": 23, "band": "20 m", "km": 1309, "az": 293},
    {"when": "2026-10-17T17:46:00Z", "snr": -13, "call": "N4DPH",
     "grid": "EM64", "dbm": 23, "band": "20 m", "km": 1565, "az": 258},
    {"when": "2026-10-17T17:46:00Z", "snr": -17, "call": "W9LK",
     "grid": "EM26", "dbm": 23, "band": "20 m", "km": 1203, "az": 272},
    {"when": "2026-10-17T17:46:00Z", "snr": -14, "call": "G4HSB",
     "grid": "IO94", "dbm": 23, "band": "20 m", "km": 5648, "az": 47},
    {"when": "2026-10-17T17:44:00Z", "snr": -23, "call": "KD1SQ",
     "grid": "FN67", "dbm": 23, "band": "20 m", "km": 1139, "az": 45},
    {"when": "2026-10-17T17:44:00Z", "snr": -15, "call": "W9RAG",
     "grid": "EN54", "dbm": 23, "band": "20 m", "km": 1005, "az": 298},
    {"when": "2026-10-17T17:44:00Z", "snr": -29, "call": "K0PCG",
     "grid": "JN49", "dbm": 23, "band": "20 m", "km": 6452, "az": 50},
]

RUNNING = {
    "session": "general", "band": "20 m", "dial_hz": 14095600,
    "hopping": False, "hop_count": 1, "clock": "1748Z", "wspr": True,
    "decode": True, "transmit": False, "tx_next": False, "slot_in": 5,
    "slot_to_next": 114, "in_capture": True, "next_tx": False,
    "tx_level": 35, "rx_gain": 100, "dbfs": -37.0, "watts": "5",
    "dbm": 37, "dbm_exact": True, "ceiling": 100, "heard": 455, "sent": 1,
    "upload": "on", "timeout_left": 2802, "decoding": True,
    "inhibited": False, "measuring": False,
}

MENU_STATE = {
    "wspr": True, "decode": True, "transmit": False, "tx_next": False,
    "session": "general", "band": "20 m", "hopping": False, "hop_count": 1,
    "tx_percent": 20, "timeout_minutes": 60, "upload": "on",
    "log_name": "wspr.log", "heard": 455, "sent": 1,
    "tx_level": 35, "rx_gain": 100, "dbfs": -37.0,
}


def screens(cols, rows):
    """`[(name, lines), ...]` for every WSPR screen worth documenting."""
    return [
        ("wspr", render.wspr_screen(
            SPOTS, cols, rows, state=RUNNING,
            message="WSPR started on 20 m — ^O ^P are locked until it stops",
            footer=" F1 menu F2 session F3 band ↑↓ spots ^B inhibit ^C stop")),
        ("wspr-menu", menus.render(
            menus.wspr_menu(MENU_STATE), cols, rows, selected=0)),
        ("wspr-band", menus.render(
            menus.wspr_band_menu(["20 m"], "20 m"), cols, rows, selected=3)),
        ("wspr-audio", menus.render(
            menus.wspr_audio_menu(
                {"tx_level": 35, "rx_gain": 100, "dbfs": -37.0}),
            cols, rows, selected=2)),
        ("wspr-calibrate-tx", render.wspr_cal_screen(
            cols, rows,
            state={"kind": "tx", "band": "20 m", "level": 35, "watts": "5",
                   "dbm": 37, "dbm_exact": True, "ceiling": 100,
                   "keyed": True},
            message="test tone transmitting",
            footer="  + - level  Enter send a tone  ^B inhibit  ^C stop  "
                   "Esc back")),
        ("wspr-calibrate-rx", render.wspr_cal_screen(
            cols, rows,
            state={"kind": "rx", "band": "20 m", "level": 100,
                   "dbfs": -37.0, "listening": True},
            message="",
            footer="  + - level   ^B inhibit   Esc back")),
    ]


# -- the log screens the articles use, which were ASCII mockups before ----

def log_extras(cols, rows):
    """`[(name, lines), ...]` for the log screens not already captured.

    The field selector, one contact in full, and the deck & rig screen. They
    were hand-drawn in the write-ups; drawn here they cannot drift.
    """
    import activities
    import qsolog

    # The REAL field set and the real POTA selection. The renderer looks the
    # description up from `activities.FIELD_HELP` by field name, so the row
    # carries the bare label -- passing label-plus-description printed it
    # twice, which is what the first version of this fixture did.
    on = set(activities.BUILTIN["POTA"].entry)
    # ENTRY_FIELDS maps a field name to (kind, label); the label is index 1.
    picker = [(n, activities.ENTRY_FIELDS.get(n, ("", n))[1], n in on)
              for n in activities.FIELD_HELP]

    record = {
        "when": "2026-10-15T14:09:00Z", "call": "KD3CCP", "band": "40m",
        "mode": "SSB", "freq": "7185000", "rst_s": "59", "rst_r": "57",
        "name": "Ryan", "qth": "State College", "state": "PA",
        "my_park": "US-5678", "activity": "Bald Eagle SP",
        "activity_type": "POTA", "my_call": "KD3CCO",
    }
    station = [
        ("Callsign", "{call}", "KD3CCO", "CALLSIGN"),
        ("Name", "{name}", "Don", "NAME"),
        ("QTH", "{qth}", "State College, PA", "QTH"),
        ("Locator", "{grid}", "FN10cs", "LOCATOR"),
        ("Rig", "{rig}", "FTX-1", "RIG"),
        ("Antenna", "{ant}", "EFHW", "ANTENNA"),
        ("Max power (W)", "", "100", "TX_POWER_MAX"),
    ]
    return [
        ("log-fields", render.field_select_screen(
            picker, 0, cols, rows, title="SELECT FIELDS — from POTA",
            footer=" Esc cancel  ↑↓ move  ←→ page  Space toggle  "
                   "Enter order")),
        ("log-contact", render.entry_screen(
            qsolog.detail_rows(record), 0, cols, rows, call="KD3CCP",
            when="2026-10-15 14:09Z", position="2 of 2")),
        ("deck-rig", render.settings_screen(
            station, cols, rows, selected=0, state="TX INHIBITED",
            footer=" ↑↓ pick  Enter edit  F1 menu  F4 color  ^O ^P screen")),
    ]


# -- the seven screens added 2026-10-22 ------------------------------------

def new_screens(cols, rows):
    """`[(name, lines), ...]` for the band plan, the tuner, the ring editor,
    the export page and the two maps' overlay.

    `KD3CCP` stands in for a worked station, as it does in `log_extras`: it
    is this station's own callsign with the last letter moved, so nothing in
    the documentation is attributed to an operator who did not agree to it.
    The WSPR map's bands and counts are from the October capture on the
    75-10 m EFHW.
    """
    import bandplan
    import cyberdeck
    import export

    segs = bandplan.segments("us_general")
    sel = bandplan.Selection(segs)
    sel.select_phone()
    # The locks the operator actually asked for: 160 m, 12 m, 10 m and 6 m
    # off the sweep, because those are the bands this station does not work
    # phone on. A locked segment is `[x]` and no bulk selection can turn it
    # back on, which is the point of the lock rather than a second way to
    # deselect.
    for key in ("160m:All Modes", "12m:All Modes", "10m:SSB",
                "10m:AM / misc", "10m:FM / repeaters", "6m:SSB",
                "6m:FM simplex"):
        sel.toggle_lock(key)

    # The ring as an operator might set it: the band plan moved to the front,
    # WSPR left off.
    ring = [(1, cyberdeck.AREA_ALLOC, "Band plan", True, False),
            (2, cyberdeck.AREA_SETTINGS, "Deck & rig", True, True),
            (3, cyberdeck.AREA_LOG, "Logging", True, False),
            (4, cyberdeck.AREA_DIGI, "Digimodes", True, False),
            (0, cyberdeck.AREA_WSPR, "WSPR", False, False)]

    files = [("qso.adi", "4.2 kB"), ("qso.log", "18.4 kB"),
             ("wspr.log", "1.1 MB"), ("transcript.txt", "3.6 kB"),
             ("cyberdeck.conf", "2.9 kB")]

    bands = ["80m", "40m", "30m", "20m", "17m", "15m", "12m", "10m"]

    return [
        ("alloc", render.allocation_screen(segs, 6, cols, rows,
                                           license_name="General")),
        ("tuner", render.tuner_screen(sel, 2, cols, rows,
                                      license_name="General", dwell_s=2.5,
                                      message="")),
        ("tuner-running", render.tuner_screen(
            sel, 2, cols, rows, license_name="General", dwell_s=2.5,
            running=(7, 24, 14_326_000),
            message="sweeping — ^X stops it before the next key-down")),
        ("ringed", render.ring_screen(ring, 0, cols, rows,
                                      message="")),
        ("export", render.export_screen(
            ("http://192.168.1.47:8080/a7f3",
             f"http://{export.HOSTNAME}:8080/a7f3"),
            files, cols, rows, remaining=252.0, downloads=2)),
    ]


# The grids these spots came from, with the band each was heard on. Real
# decodes from the October capture on the 75-10 m EFHW -- other operators'
# callsigns and grids are published on wsprnet, which is what the mode is
# for. `HEARD_BY` is a station that heard this one, `HEARD` one this station
# heard, and the pairs that are both are what the `t` key exists to show.
MAP_SPOTS = [
    ("FN67", "20m", "by"), ("EN34", "20m", "by"), ("EM64", "20m", "by"),
    ("EM26", "20m", "by"), ("IO94", "20m", "by"), ("EN54", "20m", "by"),
    ("JN49", "20m", "by"), ("DM79", "20m", "heard"), ("CN87", "15m", "by"),
    ("EL96", "40m", "by"), ("FN42", "40m", "heard"), ("EM12", "40m", "by"),
    ("DM13", "15m", "by"), ("IO83", "15m", "heard"), ("JO21", "17m", "by"),
    ("KP20", "17m", "by"), ("FM19", "30m", "heard"), ("EN61", "30m", "by"),
    ("QF56", "10m", "by"), ("GG66", "10m", "heard"), ("IM58", "12m", "by"),
    ("FK68", "80m", "by"), ("EN90", "80m", "heard"), ("DN31", "40m", "by"),
    ("EM73", "20m", "heard"), ("IO91", "20m", "by"), ("JN88", "20m", "by"),
    ("LG13", "15m", "by"), ("PM95", "15m", "heard"), ("GF05", "10m", "by"),
    ("IB59", "10m", "by"), ("RE78", "20m", "by"), ("OF78", "17m", "by"),
]

# The contact log's grids, which is a far smaller and more local set -- a
# weekend of SSB rather than a week of beacons.
LOG_SPOTS = [("FN42", "40m"), ("EM12", "20m"), ("EN54", "40m"),
             ("FN31", "20m"), ("EM64", "20m"), ("DM79", "15m"),
             ("EL96", "40m"), ("EN90", "20m"), ("FN67", "40m"),
             ("EM73", "15m"), ("DN31", "20m")]

HOME = "FN10"


def maps(cols, rows):
    """`[(name, spotmap, overlay)]` -- the picture and the rows over it.

    The map is a framebuffer picture and the two rows are curses, so a
    capture that drew only the curses half showed an empty screen. Both
    halves come from the real code: `wsprmap.SpotMap` projects the grids and
    `render.map_overlay` builds the rows, and the summary line is taken FROM
    the map rather than written beside it, so the count and the picture
    cannot disagree.
    """
    import grid
    import wsprmap

    def built(view, spots, directions):
        base = wsprmap.load(view=view)
        sm = wsprmap.SpotMap(base, home=grid.to_latlon(HOME))
        for locator, band, kind in spots:
            sm.add_grid(locator, band,
                        wsprmap.HEARD if kind == "heard"
                        else wsprmap.HEARD_BY)
        return sm, render.map_overlay(sm.summary(), sm.bands(), None, view,
                                      cols, directions=directions)

    wspr_sm, wspr_rows = built(
        "global", MAP_SPOTS,
        [("heard", "+", True), ("by me", "x", True)])
    log_sm, log_rows = built(
        "focus", [(g, b, "by") for g, b in LOG_SPOTS],
        [("worked", "+", True)])
    # The contacts with no grid, which the log map counts rather than drops.
    log_sm.ungridded = 4
    log_rows = render.map_overlay(log_sm.summary(), log_sm.bands(), None,
                                  "focus", cols,
                                  directions=[("worked", "+", True)])
    return [("wspr-map", wspr_sm, wspr_rows),
            ("log-map", log_sm, log_rows)]
