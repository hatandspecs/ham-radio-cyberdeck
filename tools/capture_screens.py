"""Produce the screens for the documentation.

The chat screen is composed from the same render.* functions the application
calls, in the same order, with a scripted conversation — a real QSO cannot be
staged on the bench, and fldigi with an open squelch fills the transcript with
decoded noise. Everything else here is a live capture of the running
application through a pseudo-terminal.

Regenerate with:  python3 tools/capture_screens.py > docs/screens.md
"""
import calendar, time
import os
import sys

# The application modules live in src/; this tool lives in tools/.
_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT, "src"))
import render, menus
from session import Session

W, H = 66, 20


def compose_chat(session, fields, width=W, height=H, timestamps=True):
    """The chat screen, assembled exactly as Deck._draw_chat assembles it."""
    compose_h = 2
    body_h = height - 1 - 1 - 1 - compose_h - 1
    out = [render.status_line(fields, width), render.rule(width)]
    out += render.transcript_lines(session.entries, width, body_h, timestamps)
    out.append(render.rule(width))
    clines, _ = render.compose_lines(
        session.compose, session.buffer_indicator(), width, compose_h)
    out += clines
    out.append(render.hint_line(width))
    return out


def frame(lines, width=W):
    top = "┌" + "─" * width + "┐"
    body = ["│" + render.plain(l).ljust(width)[:width] + "│" for l in lines]
    return "\n".join([top] + body + ["└" + "─" * width + "┘"])


def scripted_session():
    s = Session(callsign="KD3CCO", scrollback=2000)
    # timegm, not mktime: the transcript displays UTC, so the scripted
    # times have to be built in UTC or they shift by the local offset.
    base = calendar.timegm((2026, 9, 19, 21, 9, 0, 0, 0, 0))
    def at(mins, who, text):
        s.entries.append(type(s.entries[0] if s.entries else None, (), {})) if False else None
        from session import Entry
        e = Entry(who, text, when=base + mins * 60)
        e.closed = True
        s.entries.append(e)
    at(0, "RX", "KD3CCO de NOCALL  good copy, 599 here in State College. "
                "rig is an FTX-1 running 20 watts into a vertical.")
    at(2, "KD3CCO", "NOCALL de KD3CCO  copy 100 percent. this is a pi 3a+ "
                    "running fldigi headless behind a terminal i wrote.")
    at(4, "RX", "that is excellent. what modes does it do?")
    at(5, "--", "mode changed to BPSK63")
    for c in "NOCALL de KD3CCO  all the fldigi keyboard modes — psk, olivia, mfsk, rtty":
        s.type(c)
    return s


FIELDS = dict(call="KD3CCO", freq="14.070.589", sideband="PKTUSB", mode="BPSK63",
              carrier="1500Hz", snr="S/N 18", imd="IMD -24",
              state="RX", clock="2114Z")


def tuning_screen(width=W, height=H):
    """The F2 screen, rendered from the same functions the deck uses.

    Nothing here is hand-copied: render.tune_rows and render.TUNE_HINTS are
    what the panel draws, so a control added to that screen appears in the
    documentation screenshots without anyone remembering to update them.
    """
    lines = [render.status_line({**FIELDS, "call": "TUNING"}, width),
             render.rule(width)]
    rows = render.tune_rows({
        "freq": render.frequency(14070589),
        "rig_mode": "PKTUSB",
        "carrier": 1500,
        "width": render.mode_bandwidth("BPSK63", 0),
        "snr": "S/N 18 dB",
        "imd": "IMD -24 dB",
        "quality": 62,
        "preview": "NOCALL DE KD3CCO  GOOD COPY ON 80M RTTY",
        "afc": True,
        "squelch": True,
        "squelch_level": 5,
        "rsid": True,
        "txid": True,
        "reverse": False,
    }, width)
    for r in rows:
        lines.append([(r[:width - 1], "bright")])
    while len(lines) < height - 4:
        lines.append([("", "bright")])
    lines = lines[:height - 4]
    lines.append(render.rule(width))
    for hint in render.TUNE_HINTS:
        lines.append([(hint[:width - 1], "dim")])
    return lines


# Invented networks. The real ones belong to the operator's neighbours, and a
# screenshot in a public repository is not the place for their names.
WIFI_NETWORKS = [
    ("Fieldhouse", 88, "WPA2", True, True),
    ("Fieldhouse-Guest", 74, "WPA2", False, False),
    ("PARK-WIFI", 51, "", False, False),
    ("Hamshack", 33, "WPA3", False, True),
]


# Three states of the log screen, because the whole point of the design is
# that the same screen shows different fields depending on the activity, and
# one screenshot cannot show that.
def _log_records(kind):
    if kind == "general":
        return [
            {"when": "2026-10-11T16:04:00Z", "call": "W3ABC", "rst_s": "59",
             "rst_r": "57", "name": "Bob", "qth": "Pittsburgh, PA"},
            {"when": "2026-10-11T16:11:00Z", "call": "K2XYZ", "rst_s": "59",
             "rst_r": "59", "name": "Jim", "comment": "running 5W to a wire"},
            {"when": "2026-10-11T16:19:00Z", "call": "OK2CQR", "rst_s": "59",
             "rst_r": "55", "name": "Petr", "qth": "Neratovice, Czech Rep"},
            {"when": "2026-10-11T16:26:00Z", "call": "N3QQQ/P", "rst_s": "59",
             "rst_r": "59", "name": "Dave"},
        ]
    if kind == "pota":
        return [
            {"when": "2026-10-11T14:02:00Z", "call": "W3ABC", "rst_s": "59",
             "rst_r": "57", "park": "US-1234", "name": "Bob"},
            {"when": "2026-10-11T14:06:00Z", "call": "K2XYZ", "rst_s": "59",
             "rst_r": "59", "name": "Jim", "qth": "Albany, NY"},
            {"when": "2026-10-11T14:09:00Z", "call": "N3QQQ", "rst_s": "59",
             "rst_r": "55", "park": "US-0042", "comment": "park to park"},
            {"when": "2026-10-11T14:14:00Z", "call": "KD8SLG", "rst_s": "59",
             "rst_r": "59", "name": "Ann"},
        ]
    return [
        {"when": "2026-10-11T18:31:00Z", "call": "W3ABC", "activity": "CONTEST", "rst_s": "59",
         "rst_r": "59", "serial_tx": "55", "serial_rx": "101",
         "exchange_rx": "MONT"},
        {"when": "2026-10-11T18:32:00Z", "call": "K2XYZ", "activity": "CONTEST", "rst_s": "59",
         "rst_r": "59", "serial_tx": "56", "serial_rx": "17",
         "exchange_rx": "ALLE"},
        {"when": "2026-10-11T18:33:00Z", "call": "N3QQQ", "activity": "CONTEST", "rst_s": "59",
         "rst_r": "59", "serial_tx": "57", "serial_rx": "212",
         "exchange_rx": "BUCK"},
        {"when": "2026-10-11T18:34:00Z", "call": "W3YA", "activity": "CONTEST", "rst_s": "59",
         "rst_r": "59", "serial_tx": "58", "serial_rx": "9",
         "exchange_rx": "CENT", "comment": "club station"},
    ]


def log_screen(kind="general", width=W, height=H):
    """One of the log screen's three states, drawn as the deck draws it.

    Built through `logform.LogForm` rather than by hand, so these are the real
    field order, the real prefills and the real sticky marks — a screenshot
    assembled separately from the thing it depicts drifts from it silently.
    """
    import activities, logform

    setup = {
        "general": ("GENERAL", "7.185", "SSB", "40m", "1627Z", "W1AW"),
        "pota":    ("POTA",    "14.285", "SSB", "20m", "1415Z", "W3YA"),
        "contest": ("CONTEST", "3.820", "SSB", "80m", "1835Z", "K3PP"),
    }[kind]
    name, freq, mode, band, clock, typed = setup

    act = activities.get(name, activities.BUILTIN)
    records = _log_records(kind)

    form = logform.LogForm(act)
    form.from_radio(freq=freq, mode=mode)
    form.advance_serial(records, act.serial_start)
    if form.field("exchange_tx"):
        form.set("exchange_tx", "CENT")
    if form.field("my_park"):
        form.set("my_park", "US-5678")
    form.set("comment", "5W to a wire")
    form.focus("call")
    form.type(typed)
    # Part-way through a contact, which is what the screen looks like in use:
    # the callsign taken and the cursor moved on to what they are sending.
    form.tab()
    if kind == "contest":
        form.type("44")

    header = {"band": band, "mode": mode, "freq": freq,
              "count": len(records), "clock": clock}
    if act.name != "GENERAL":
        header["activity"] = act.name
    if form.value("my_park"):
        header["my_park"] = form.value("my_park")
    return render.log_screen(records, "", width, height, header=header,
                             form=form)


def wifi_screen():
    import wifi
    nets = [wifi.Network(*n) for n in WIFI_NETWORKS]
    return render.wifi_screen("list", nets, W, H, radio="on")


if __name__ == "__main__":
    s = scripted_session()
    print("## The conversation screen\n")
    print("```")
    print(frame(compose_chat(s, FIELDS)))
    print("```\n")

    print("## The tuning screen — F2\n")
    print("```")
    print(frame(tuning_screen()))
    print("```\n")

    print("## The menu — F1\n")
    print("```")
    print(frame(menus.render(menus.ROOT, W, H, selected=2)))
    print("```\n")

    print("## Tune Settings — F1 then 2\n")
    print("```")
    print(frame(menus.render(
        menus.tuning_menu(afc=True, squelch=True, level=15.0, rsid=True,
                          txid=False, reverse=False, rx_hold=1000,
                          rx_hold_max=4000),
        W, H)))
    print("```\n")

    print("## The mode picker — F3\n")
    print("```")
    print(frame(menus.render(menus.mode_menu("BPSK63"), W, H)))
    print("```\n")

    print("## WiFi — F1 then 7 then w\n")
    print("```")
    print(frame(wifi_screen()))
    print("```\n")

    names = menus.keyboard_modes([n for _, n in menus.MODE_TIER1] + [
        "BPSK125", "BPSK250", "BPSK500", "QPSK63", "QPSK125", "QPSK250",
        "OLIVIA-4/250", "OLIVIA-16/500", "OLIVIA-32/1K", "MFSK8", "MFSK32",
        "MFSK64", "THOR16", "THOR25", "THOR50x1", "DOMEX4", "DOMEX5",
        "DOMEX11", "DOMEX16", "DOMEX22", "CONTESTIA", "RTTY"])
    menu, *_ = menus.paged_menu("ALL MODES", names, 0, W, H)
    print("## The full modem list — F3 then m\n")
    print("```")
    print(frame(menus.render(menu, W, H)))
    print("```")

    # The WSPR area, with its prose. `docs/screens.md` is generated by this
    # tool, so anything written into that file by hand is destroyed on the
    # next run -- which is why these sections live here.
    import wsprgrid_fixture as _w
    PROSE = {
        "wspr": ("## The WSPR screen — `^O` from the deck & rig screen",
                 "The fourth area, and the only one that is exclusive: while"
                 " it runs, the ring\ndoes not leave it and fldigi is"
                 " stopped, because the USB codec takes one\ncapture client."
                 "\n\n`KM` and `AZ` are computed from the two grid squares."
                 " Neither is stored in\nthe spot log, because both are"
                 " derivable from the grids that are."),
        "wspr-menu": ("## The WSPR menu — F1 from the WSPR screen",
                      "Thirteen items, and that is a constraint rather than a"
                      " count: `menus.render`\ngoes to two columns above"
                      " `height - 6` items, and the second column has no\n"
                      "room for the values this menu exists to show."),
        "wspr-band": ("## The band picker — F3, or `b` from the WSPR menu",
                      "A number or Enter selects that band alone and tunes to"
                      " its WSPR dial.\nSpace toggles the highlighted band in"
                      " and out of the hop rotation; `[*]`\nmarks the bands"
                      " in it and `<` the one in use.\n\nSelecting a band"
                      " also reads the radio's mode and sets DATA-U if it is"
                      "\nnot, remembering what was found — the radio keeps a"
                      " mode per band."),
        "wspr-audio": ("## The audio menu — `a` from the WSPR menu",
                       "The levels are reported here and changed in the"
                       " calibration screens, where\nthere is a meter to"
                       " watch. Both are refused while WSPR is off, with the"
                       "\nreason given: they open the sound card, and fldigi"
                       " holds it until WSPR\ntakes it."),
        "wspr-calibrate-tx": ("## Calibrating transmit — `c` from the audio menu",
                              "`+` and `-` step the level while the tone is"
                              " playing. The instrument is the\nradio's own"
                              " power meter; the dBm is highlighted when the"
                              " wattage lands\nexactly on a value WSPR can"
                              " encode."),
        "wspr-calibrate-rx": ("## Calibrating receive — `m` from the audio menu",
                              "The marked stretch of the meter is roughly what"
                              " `wsprd` wants. The gain is\nthe capture mixer,"
                              " which fldigi shares — safe to set only because"
                              " WSPR\nowns the codec while it runs, and put"
                              " back when the session ends."),
    }
    for name, lines in _w.screens(W, H):
        heading, prose = PROSE[name]
        print(heading + "\n")
        print(prose + "\n")
        print("```")
        print(frame(lines))
        print("```\n")
