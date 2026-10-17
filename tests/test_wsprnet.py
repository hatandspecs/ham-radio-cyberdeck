"""Uploading spots to wsprnet — docs/wspr_design.md §9.

**Nothing here touches the network.** The sender is injected, which is the
same seam `callbook.py` uses and for the same reason: a test that needed
wsprnet would be a test that fails on a train, and a test that really posted
would put fabricated spots under this station's callsign into a permanent
public database.

The parameter names are WSJT-X's, read out of its `Network/wsprnet.cpp`
rather than described from memory, because every other WSPR station is
running that code and a client that invents a field name is a client whose
reports are silently discarded.
"""
import os
import sys
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import wspr
import wsprnet

SPOT = wspr.parse_decode("1400  -8 -0.1  14.097147  0  KD3CCO JO41  0")
STRONG = wspr.parse_decode("1400  18 -0.0  14.097082  0  KD3CCO FN10 37")
DIAL = 14_095_600


print("a spot carries both sides of the report")
p = wsprnet.spot_params(SPOT, "KD3CCO", "FN10cs", DIAL, "260616", "1400")
equals("it is a spot report", p["function"], "wspr")
equals("this station's call", p["rcall"], "KD3CCO")
equals("and grid", p["rgrid"], "FN10cs")
# rqrg is where THIS station was listening; tqrg is where the other station
# was found. Reporting one as the other is a wrong report, not a missing one.
equals("the receiver's frequency is the DIAL", p["rqrg"], "14.095600")
equals("the transmitter's is where it was decoded", p["tqrg"], "14.097147")
check("which are not the same number", p["rqrg"] != p["tqrg"], "")
equals("the station heard", p["tcall"], "KD3CCO")
equals("its grid", p["tgrid"], "JO41")
equals("its claimed power", p["dbm"], "0")
equals("the measured SNR, negative as usual", p["sig"], "-8")
equals("the time offset", p["dt"], "-0.1")
equals("the drift", p["drift"], "0")
equals("the slot date", p["date"], "260616")
equals("and time", p["time"], "1400")
equals("WSPR-2 is mode 2", p["mode"], "2")
# It names ITSELF, not WSJT-X: claiming to be software this is not would
# make every bug reported against it somebody else's. Asserted against the
# constant rather than a spelling, so renaming the deck does not need an
# edit here -- and separately that it is not a WSJT-X version.
equals("and it names itself", p["version"], wsprnet.VERSION)
check("which is not a WSJT-X version string",
      not p["version"][0].isdigit(), p["version"])
# **Ten characters, measured:** a reporter calling itself `EasySpotter`
# appears in this station's wsprnet records as `EasySpotte`.
check("and fits the ten the field carries",
      len(p["version"]) <= wsprnet.VERSION_MAX, p["version"])

print("\nmegahertz on the wire, hertz everywhere inside")
# The deck keeps hertz throughout (`HERTZ_FIELDS`) and converts at the edge.
equals("six decimal places, as the field expects",
       wsprnet.spot_params(STRONG, "KD3CCO", "FN10", DIAL, "260616",
                           "1400")["tqrg"], "14.097082")

print("\na compound call has no grid to report, so none is sent")
t2 = wspr.parse_decode("1400  -5  0.1  14.097100  0  KD3CCO/P 37")
p2 = wsprnet.spot_params(t2, "KD3CCO", "FN10", DIAL, "260616", "1400")
equals("the call goes as decoded", p2["tcall"], "KD3CCO/P")
check("and tgrid is absent rather than empty", "tgrid" not in p2, str(p2))
check("so the body does not carry an empty field",
      "tgrid" not in wsprnet.encode(p2), wsprnet.encode(p2))

print("\na slot that heard nothing still reports the station")
# An absent report and a report of silence are different facts: the first
# says nothing about whether anybody was listening on that band.
st = wsprnet.stat_params("KD3CCO", "FN10cs", DIAL, tx_percent=20, dbm=37)
equals("it is a status report", st["function"], "wsprstat")
equals("with this station's call", st["rcall"], "KD3CCO")
equals("the band it was listening on", st["rqrg"], "14.095600")
equals("and the transmit percentage", st["tpct"], "20")
for absent in ("tcall", "tgrid", "sig", "dt", "drift", "date", "time"):
    check(f"no {absent} — nothing was heard", absent not in st, str(st))

print("\nthe body is form-encoded")
body = wsprnet.encode(p)
check("it is urlencoded", "function=wspr" in body, body)
check("and drops empty fields",
      "=&" not in body and not body.endswith("="), body)
equals("the endpoint is wsprnet's post path",
       wsprnet.URL, "http://wsprnet.org/post/")


# -- the sender, with no network ----------------------------------------

class FakePost:
    """Records what would have been sent. Can be told to fail."""

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail
        self.lock = threading.Lock()

    def __call__(self, url, body, timeout=None):
        with self.lock:
            self.calls.append((url, body))
        if self.fail:
            raise OSError("no route to host")
        return "OK"


print("\nnothing is sent unless it is armed")
fake = FakePost()
up = wsprnet.Uploader(post=fake, spacing=0)
equals("an unarmed submit is declined", up.submit(p, armed=False), False)
up.wait(1.0)
equals("and nothing was sent", len(fake.calls), 0)
equals("which is not counted as a drop", up.dropped, 0)
check("nor as a failure", up.failed == 0, "")

print("\narmed, it sends on a worker thread")
fake = FakePost()
up = wsprnet.Uploader(post=fake, spacing=0)
equals("the submit is taken", up.submit(p, armed=True), True)
check("and it drains", up.wait(5.0), f"{up.pending} left")
equals("one request went out", len(fake.calls), 1)
equals("to wsprnet", fake.calls[0][0], wsprnet.URL)
check("carrying the spot", "tcall=KD3CCO" in fake.calls[0][1],
      fake.calls[0][1])
equals("and it is counted", up.sent, 1)

print("\nseveral spots go one at a time")
fake = FakePost()
up = wsprnet.Uploader(post=fake, spacing=0)
for i in range(5):
    up.submit(p, armed=True)
check("all drain", up.wait(5.0), f"{up.pending} left")
equals("five requests", len(fake.calls), 5)
equals("five counted", up.sent, 5)

print("\na failing network is an ordinary condition")
fake = FakePost(fail=True)
up = wsprnet.Uploader(post=fake, spacing=0)
up.submit(p, armed=True)
check("it still drains rather than hanging", up.wait(5.0), "")
equals("the failure is counted", up.failed, 1)
equals("nothing is counted as sent", up.sent, 0)
check("and the reason is kept for the screen",
      "no route to host" in up.last_error, up.last_error)

print("\na backlog is dropped rather than kept forever")
# A queue that survived an afternoon off-grid would upload a thousand spots
# hours late the moment WiFi returned, which is worse for the database than
# not reporting them -- and the deck's own log has them all regardless.
fake = FakePost(fail=True)
up = wsprnet.Uploader(post=fake, spacing=0)
for i in range(wsprnet.Uploader.MAX_PENDING + 50):
    up.submit(p, armed=True)
check("the queue is bounded",
      up.pending <= wsprnet.Uploader.MAX_PENDING,
      f"{up.pending} pending")
check("and the drops are counted", up.dropped > 0, str(up.dropped))
up.wait(5.0)

print("\nthe three-state word tells off apart from cannot")
equals("toggle off", wsprnet.upload_state(False, True, True), "off")
equals("no network", wsprnet.upload_state(True, False, True), "no wifi")
equals("armed and running", wsprnet.upload_state(True, True, True), "on")
equals("armed, online, but WSPR stopped",
       wsprnet.upload_state(True, True, False), "off")
# The same three the callbook reports, so one habit covers both.
equals("no network wins over not running",
       wsprnet.upload_state(True, False, False), "no wifi")

print("\nthe spacing matches WSJT-X's, which is not an accident")
equals("200 ms", wsprnet.SPACING_S, 0.2)

sys.exit(report())
