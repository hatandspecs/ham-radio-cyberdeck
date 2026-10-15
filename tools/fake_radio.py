#!/usr/bin/env python3
"""A pretend fldigi and a pretend rigctld, for driving the deck on a laptop.

    python3 tools/fake_radio.py                  PSK31 on 3.580 MHz, forever
    python3 tools/fake_radio.py --mode BPSK63 --freq 7074000

`tools/deck_local.py` starts both of these in threads, so the deck on a laptop
reads a mode and a frequency instead of blanks. Run it standalone to point a
real `src/cyberdeck.py` at it, or to poke the fakes with `rigctl`/`curl`.

Two separate protocols, because the deck reads two separate things:

  * **fldigi, XML-RPC on 7362.** The modem (PSK31), the carrier, the audio
    passband, the transmit state, and the RIG's mode as fldigi's own rig
    control reports it. `qsolog.resolve_mode` prefers fldigi's modem for a
    digital contact, so this is what decides the mode that gets logged.
  * **rigctld, a line protocol on 4532.** The VFO frequency (`f`), the rig's
    mode and passband (`m`), the power control as a normalized level
    (`l RFPOWER`), and raw CAT pass-through (`w PC;`).

Both are deliberately shallow. They answer what `fldigi_client.py` and
`rigctld_client.py` actually ask and nothing else, and an unknown request gets
the same answer the real thing gives when it cannot help: a fault string from
rigctld, a fault from XML-RPC. **A fake that answers more than the real one
would let the deck depend on something that is not there.**

What they do NOT simulate: decoded text arriving, a transmission actually
going out, or any timing. `text.get_rx` is always empty, so the transcript
stays quiet — that is honest rather than lazy, since a fake conversation would
be indistinguishable on screen from a real one and this exists to test the
interface, not to stage a QSO.
"""

import argparse
import socket
import sys
import threading
from xmlrpc.server import SimpleXMLRPCServer, SimpleXMLRPCRequestHandler


class Radio:
    """The one piece of state both fakes read, so they cannot disagree.

    A real station has one radio. Serving the frequency from the rigctld fake
    and the mode from the fldigi fake out of separate variables would let them
    drift, and then the deck would be reading something no radio could
    produce.
    """

    def __init__(self, mode="PSK31", freq=3_580_000, rig_mode="PKTUSB",
                 carrier=1500, power=0.6, max_watts=10):
        self.lock = threading.Lock()
        self.mode = mode                # fldigi's modem, e.g. PSK31
        self.freq = int(freq)           # VFO in Hz
        self.rig_mode = rig_mode        # the radio's own mode, e.g. PKTUSB
        self.carrier = int(carrier)     # audio Hz inside the passband
        self.power = float(power)       # hamlib's normalized 0.0-1.0
        self.max_watts = int(max_watts)
        self.trx = "RX"
        self.rsid = False
        self.rx_only = False
        self.afc = True
        self.squelch = False
        self.squelch_level = 5.0
        self.txid = False
        self.reverse = False
        self.tx_text = ""

    # Modems fldigi would offer. Short list on purpose: the mode menu pages
    # from this, and a realistic subset exercises the paging.
    MODEMS = ["BPSK31", "BPSK63", "BPSK125", "PSK31", "QPSK31", "RTTY",
              "MFSK16", "MFSK32", "THOR22", "Olivia-8-250", "CW", "NULL"]

    RIG_MODES = ["LSB", "USB", "CW", "CWR", "AM", "FM", "RTTY", "RTTYR",
                 "PKTLSB", "PKTUSB", "PKTFM"]

    # Nominal audio passband per modem, for modem.get_bandwidth.
    WIDTH = {"BPSK31": 31, "PSK31": 31, "QPSK31": 31, "BPSK63": 63,
             "BPSK125": 125, "RTTY": 270, "MFSK16": 316, "MFSK32": 630,
             "THOR22": 262, "CW": 50}


def fldigi_server(radio, host="127.0.0.1", port=7362, quiet=True):
    """An XML-RPC server answering the subset fldigi_client.py calls."""

    class Handler(SimpleXMLRPCRequestHandler):
        rpc_paths = ("/", "/RPC2")

        def log_message(self, *a):                      # silence the server
            if not quiet:
                SimpleXMLRPCRequestHandler.log_message(self, *a)

    srv = SimpleXMLRPCServer((host, port), requestHandler=Handler,
                             allow_none=True, logRequests=not quiet)

    def get(name):
        with radio.lock:
            return getattr(radio, name)

    def setter(name, cast=None):
        def fn(value):
            with radio.lock:
                setattr(radio, name, cast(value) if cast else value)
            return 0
        return fn

    srv.register_function(lambda: "fldigi 4.2.06 (fake_radio.py)",
                          "fldigi.name_version")
    srv.register_function(lambda: get("mode"), "modem.get_name")
    srv.register_function(lambda: list(Radio.MODEMS), "modem.get_names")
    srv.register_function(lambda: get("carrier"), "modem.get_carrier")
    srv.register_function(lambda: Radio.WIDTH.get(get("mode"), 0),
                          "modem.get_bandwidth")
    srv.register_function(lambda: 85, "modem.get_quality")
    srv.register_function(setter("carrier", int), "modem.set_carrier")

    def set_by_name(name):
        with radio.lock:
            radio.mode = str(name)
            # Real fldigi moves the carrier to the modem's sweet spot on a
            # mode change, which is exactly the behaviour _set_mode works
            # around by reading the carrier and writing it back.
            radio.carrier = 1000
        return 0
    srv.register_function(set_by_name, "modem.set_by_name")

    def inc_carrier(delta):
        with radio.lock:
            radio.carrier = max(0, radio.carrier + int(delta))
        return radio.carrier
    srv.register_function(inc_carrier, "modem.inc_carrier")

    def search(_=None):
        # No signals here, so searching finds nothing and leaves the carrier
        # where it was. Reporting a find would be a lie the deck would then
        # display as a tuned signal.
        return get("carrier")
    srv.register_function(search, "modem.search_up")
    srv.register_function(search, "modem.search_down")

    srv.register_function(lambda: get("freq"), "main.get_frequency")
    srv.register_function(setter("freq", lambda v: int(float(v))),
                          "main.set_frequency")
    srv.register_function(lambda: get("rig_mode"), "main.get_rig_mode")
    srv.register_function(lambda: list(Radio.RIG_MODES), "main.get_rig_modes")
    srv.register_function(setter("rig_mode", str), "main.set_rig_mode")
    srv.register_function(lambda: get("trx"), "main.get_trx_state")
    srv.register_function(lambda: get("rsid"), "main.get_rsid")
    srv.register_function(setter("rsid", bool), "main.set_rsid")
    srv.register_function(lambda: get("txid"), "main.get_txid")
    srv.register_function(setter("txid", bool), "main.set_txid")
    srv.register_function(lambda: get("afc"), "main.get_afc")
    srv.register_function(setter("afc", bool), "main.set_afc")
    srv.register_function(lambda: get("reverse"), "main.get_reverse")
    srv.register_function(setter("reverse", bool), "main.set_reverse")
    srv.register_function(lambda: get("squelch"), "main.get_squelch")
    srv.register_function(setter("squelch", bool), "main.set_squelch")
    srv.register_function(lambda: get("squelch_level"),
                          "main.get_squelch_level")
    srv.register_function(setter("squelch_level", float),
                          "main.set_squelch_level")
    srv.register_function(setter("rx_only", bool), "main.rx_only")
    srv.register_function(lambda: "", "main.get_status1")
    srv.register_function(lambda: "", "main.get_status2")

    def to_tx():
        with radio.lock:
            radio.trx = "TX"
        return 0

    def to_rx():
        with radio.lock:
            radio.trx = "RX"
            radio.tx_text = ""
        return 0
    srv.register_function(to_tx, "main.tx")
    srv.register_function(to_rx, "main.rx")
    srv.register_function(to_rx, "main.abort")

    def add_tx(text):
        with radio.lock:
            radio.tx_text += str(text)
        return 0
    srv.register_function(add_tx, "text.add_tx")
    srv.register_function(lambda: 0, "text.clear_tx")
    srv.register_function(lambda: 0, "text.clear_rx")
    # Always empty. See the module docstring: a staged conversation would be
    # indistinguishable from a real one on screen.
    srv.register_function(lambda: 0, "text.get_rx_length")
    srv.register_function(lambda *a: "", "text.get_rx")

    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _rigctld_reply(radio, line):
    """One rigctld answer. `line` is a single command as the client sends it.

    Anything not implemented gets `RPRT -1`, which is what hamlib says when a
    backend cannot do something — and is exactly what the FTX-1 returns for
    `power2mW`, the call this project found unimplemented on the real radio.
    """
    line = line.strip()
    with radio.lock:
        if line == "f":
            return f"{radio.freq}\n"
        if line == "m":
            width = 3000 if radio.rig_mode.startswith("PKT") else 2400
            return f"{radio.rig_mode}\n{width}\n"
        if line == "l RFPOWER":
            return f"{radio.power}\n"
        if line.startswith("F "):
            try:
                radio.freq = int(float(line.split(None, 1)[1]))
                return "RPRT 0\n"
            except (ValueError, IndexError):
                return "RPRT -1\n"
        if line.startswith("w "):
            cat = line.split(None, 1)[1].strip()
            # The FTX-1's PC; answers in WATTS and names the back end:
            # P1=1 field head, P1=2 with the amplifier. Measured on the real
            # radio 2026-10-11, where the manual is wrong -- at 0.5 W it
            # answers PC10.5;, a decimal where the manual promises three
            # digits. The fake reproduces that, including the trailing NUL
            # hamlib passes through.
            if cat.upper().startswith("PC"):
                watts = radio.power * radio.max_watts
                body = (f"{watts:.1f}" if watts < 1 else f"{int(round(watts)):03d}")
                return f"PC1{body};\0"
            if cat.upper().startswith("FA"):
                digits = "".join(c for c in cat if c.isdigit())
                if digits:
                    radio.freq = int(digits)
                return ""
            return ""
    return "RPRT -1\n"


def rigctld_server(radio, host="127.0.0.1", port=4532):
    """A line-protocol server on 4532, one short-lived connection per command.

    `rigctld_client._talk` opens a connection, writes one line, reads one
    reply and closes — so this accepts, answers, and closes rather than
    holding a session.
    """
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(8)

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            with conn:
                try:
                    conn.settimeout(2.0)
                    data = conn.recv(4096).decode("ascii", "replace")
                except OSError:
                    continue
                for cmd in data.splitlines():
                    if not cmd.strip():
                        continue
                    reply = _rigctld_reply(radio, cmd)
                    if reply:
                        try:
                            conn.sendall(reply.encode("ascii", "replace"))
                        except OSError:
                            break

    threading.Thread(target=serve, daemon=True).start()
    return srv


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", default="PSK31", help="fldigi modem")
    ap.add_argument("--rig-mode", default="PKTUSB", dest="rig_mode",
                    help="the radio's own mode")
    ap.add_argument("--freq", type=int, default=3_580_000, help="VFO in Hz")
    ap.add_argument("--carrier", type=int, default=1500)
    ap.add_argument("--power", type=float, default=0.6,
                    help="hamlib's normalized level, 0.0-1.0")
    ap.add_argument("--max-watts", type=int, default=10, dest="max_watts")
    ap.add_argument("--fldigi-port", type=int, default=7362, dest="fldigi_port")
    ap.add_argument("--rigctld-port", type=int, default=4532,
                    dest="rigctld_port")
    args = ap.parse_args(argv)

    radio = Radio(mode=args.mode, freq=args.freq, rig_mode=args.rig_mode,
                  carrier=args.carrier, power=args.power,
                  max_watts=args.max_watts)
    fldigi_server(radio, port=args.fldigi_port, quiet=False)
    rigctld_server(radio, port=args.rigctld_port)
    mhz = args.freq / 1_000_000
    print(f"fake fldigi on {args.fldigi_port}, fake rigctld on "
          f"{args.rigctld_port}")
    print(f"  modem {args.mode}, rig {args.rig_mode}, VFO {mhz:.6f} MHz, "
          f"power {args.power} of {args.max_watts} W")
    print("Ctrl-C to stop.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
