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
