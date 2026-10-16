"""A stand-in for fldigi's XML-RPC server, so a test can control when it exists.

The deck's startup depends on whether fldigi is answering at the moment the
terminal comes up, and that is not something a test can arrange against the
real fldigi: it is either running for the whole suite or not running at all.
The fault this exists to catch only appears in the gap — the terminal drawing
its first screen while fldigi is still opening its port, which is every cold
boot of the deck and no restart of the terminal.

It holds mode and carrier because those are what the fault destroys. Everything
else answers with something harmless of the right type; the deck's client
treats any failure as "not connected", so a method that raised would look like
the very condition under test.
"""
import threading
from xmlrpc.server import SimpleXMLRPCServer


class _Fldigi:
    def __init__(self, modem="CW", carrier=1000, rig_mode="USB"):
        self.modem = modem
        self.carrier = carrier
        self.trx = "RX"
        # Settable, so a test can move the radio out of a data mode and watch
        # the deck inhibit transmit and park the decoder. A fixed "USB" could
        # only ever test one side of that.
        self.rig_mode = rig_mode
        self.calls = []

    # SimpleXMLRPCServer asks the registered instance to resolve dotted names
    # itself, which is what lets one function stand in for the whole API.
    def _dispatch(self, method, params):
        self.calls.append((method, params))
        if method == "fldigi.name_version":
            return "fldigi 4.2.06"
        if method == "modem.get_name":
            return self.modem
        if method == "modem.set_by_name":
            self.modem = params[0]
            return 0
        if method == "modem.get_carrier":
            return self.carrier
        if method == "modem.set_carrier":
            self.carrier = int(params[0])
            return 0
        if method == "modem.inc_carrier":
            self.carrier += int(params[0])
            return self.carrier
        if method == "modem.get_names":
            # NULL is in the real list and is what `park_decoder` loads to
            # stop the DSP. Without it here the park silently does nothing,
            # which is exactly the condition it is supposed to detect.
            return ["NULL", "CW", "BPSK31", "BPSK63", "RTTY"]
        if method == "main.get_trx_state":
            return self.trx
        if method in ("text.get_rx", "text.get_rx_length"):
            return "" if method == "text.get_rx" else 0
        if method == "main.get_rig_modes":
            return ["USB", "LSB", "CW"]
        if method == "main.get_rig_mode":
            return self.rig_mode
        if method == "main.set_rig_mode":
            self.rig_mode = params[0]
            return 0
        if method == "main.get_frequency":
            return 14070000.0
        if method in ("modem.get_bandwidth", "modem.get_quality"):
            return 0
        if method.startswith("main.get_squelch_level"):
            return 0.0
        if method.startswith("main.get_"):
            return False          # afc, reverse, rsid, txid, squelch
        return 0                  # every setter and the text/abort calls


class FakeFldigi:
    """Start and stop the stand-in. `url` is what FLDIGI_URL should be set to."""

    def __init__(self, modem="CW", carrier=1000, port=0, rig_mode="USB"):
        self.state = _Fldigi(modem, carrier, rig_mode)
        self._server = None
        self._thread = None
        # A port chosen in advance, so a test can write it into a config file
        # and only then start answering on it. 0 lets the kernel pick.
        self.port = port or None
        self._want_port = port

    def start(self):
        # Never 7362: a suite running beside a real fldigi must not collide
        # with it, and must not be rescued by it either.
        self._server = SimpleXMLRPCServer(("127.0.0.1", self._want_port),
                                          logRequests=False, allow_none=True)
        self._server.register_instance(self.state, allow_dotted_names=True)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.05},
                                        daemon=True)
        self._thread.start()
        return self

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/RPC2"

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


def free_port():
    """A port number nothing is listening on, for the never-answers case."""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port
