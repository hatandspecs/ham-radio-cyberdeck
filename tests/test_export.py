"""The export server — `src/export.py`.

A read-only HTTP server over five named files, up for a few minutes, at a path
with a random token in it. What has to hold, because the deck stands this up
on hotspots shared with strangers:

**The request never names a file.** It names a position in a list the deck
handed the server. There is no path in the request to traverse out of, and
this file proves it by trying.

**The token gates everything.** No token, wrong token, or no path at all: the
same 404, with nothing in it that says which.

**It closes itself.** A server left running on a strange network is the thing
this feature must not become.

Driven over real HTTP against a server bound to loopback, because the whole
point is what an HTTP client can reach — a test that called the handler
directly would be testing the parts that are not the risk.
"""
import os
import sys
import tempfile
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import export

CONTENTS = {
    "qso.adi": "<CALL:6>K2ABC<EOR>\n",
    "qso.log": "2026-10-22 K2ABC 20m FT8\n",
    "wspr.log": "2026-10-22 KD3CCO FM19 14.097\n",
    "transcript.txt": "KD3CCO DE K2ABC K\n",
    "cyberdeck.conf": "CALLSIGN=KD3CCO\n",
}


def files(tmp, names=None):
    out = []
    for name in (names or CONTENTS):
        path = os.path.join(tmp, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(CONTENTS[name])
        out.append((name, path))
    return out


def get(url, timeout=5):
    """`(status, body)`. A 404 is an answer here, not a failure."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


print("the token is short, typeable, and never the same twice")
seen = {export.token() for _ in range(200)}
check("200 tokens are nearly all distinct", len(seen) > 190, len(seen))
for t in list(seen)[:20]:
    equals(f"{t} is {export.TOKEN_LEN} characters", len(t), export.TOKEN_LEN)
check("from an alphabet with no l, 1, o or 0",
      not (set("l1o0") & set(export.TOKEN_CHARS)), export.TOKEN_CHARS)
check("and that alphabet is what tokens are built from",
      all(set(t) <= set(export.TOKEN_CHARS) for t in seen))

tmp = tempfile.mkdtemp()
srv = export.Server(files(tmp), address="127.0.0.1",
                    port=export.free_port("127.0.0.1", 18080))
check("it binds and serves", srv.start(), srv.error)
base, by_name = srv.urls()
check("the address URL carries the token", srv.token in base, base)
check("and the hostname one is offered as well",
      export.HOSTNAME in by_name, by_name)

print("\nthe index lists what the deck actually has")
status, body = get(base)
equals("the token's own path answers", status, 200)
text = body.decode("utf-8")
for name in CONTENTS:
    check(f"{name} is listed", name in text, name)
check("with a size beside it", "bytes" in text or "kB" in text, text[:200])
check("nothing is fetched from off the network",
      "http://" not in text.replace(base, "") and "//cdn" not in text,
      [ln for ln in text.splitlines() if "http" in ln])

print("\na file comes back by position, and only by position")
for i, name in enumerate(CONTENTS):
    status, body = get(f"{base}/{i}")
    equals(f"{i} is {name}", status, 200)
    equals(f"and its contents are {name}'s",
           body.decode("utf-8"), CONTENTS[name])

print("\nnaming a file instead of a position is a 404")
for attempt in ("qso.adi", "cyberdeck.conf", "0.adi", "%2E%2E%2Fqso.adi"):
    status, _b = get(f"{base}/{attempt}")
    equals(f"{attempt}", status, 404)

print("\nand so is reaching above the export")
# The deck's secrets are the thing on the card that must never leave it, so
# the attempt is made against that name specifically as well as generically.
with open(os.path.join(tmp, "cyberdeck.secrets"), "w") as fh:
    fh.write("QRZ_PASSWORD=hunter2\n")
for attempt in ("../cyberdeck.secrets", "..%2Fcyberdeck.secrets",
                "%2e%2e/cyberdeck.secrets", "/etc/passwd",
                "cyberdeck.secrets", "0/../cyberdeck.secrets"):
    status, body = get(f"{base}/{attempt}")
    check(f"{attempt} is refused", status == 404, status)
    check(f"{attempt} leaks nothing", b"hunter2" not in body, body[:80])

print("\nHEAD answers with headers and no body")
# With `protocol_version = "HTTP/1.1"` the connection is kept alive, so a
# body sent for a HEAD the client is not reading would be parsed as the start
# of the next response.
import http.client


def head(path, port):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("HEAD", path)
        r = conn.getresponse()
        return r.status, r.getheader("Content-Length"), r.read()
    finally:
        conn.close()


token_path = "/" + srv.token
status, length, body = head(token_path, srv.port)
equals("the index answers", status, 200)
check("with a length", length and int(length) > 0, length)
equals("and no body", body, b"")

status, length, body = head(f"{token_path}/0", srv.port)
equals("a file answers", status, 200)
check("with its length", length and int(length) > 0, length)
equals("and no body", body, b"")

status, length, body = head("/nope", srv.port)
equals("a refusal answers 404", status, 404)
equals("and sends no body either", body, b"")

print("\nthe panel and the page agree on what is on offer")
# Two numberings would be a bug nobody would see until a tap fetched the
# wrong file: the page's numbers ARE how a file is requested.
status, page = get(base)
listed = [label for label, _size in srv.rows()]
for i, label in enumerate(listed):
    check(f"the page links {label} at {i}",
          f"/{srv.token}/{i}\" download>{label}".encode() in page, label)

print("\nthe token gates all of it")
other = "".join("z" if c != "z" else "y" for c in srv.token)
for path in ("", "/", f"/{other}", f"/{other}/0", "/0", "/index.html"):
    status, _b = get(f"http://127.0.0.1:{srv.port}{path}")
    equals(f"{path or '(root)'} is 404 without the token", status, 404)
check("a wrong token says no more than a right path with a bad index",
      get(f"http://127.0.0.1:{srv.port}/{other}")[1]
      == get(f"{base}/99")[1])

print("\na file removed after the page loaded is not a broken link")
os.unlink(os.path.join(tmp, "wspr.log"))
status, body = get(base)
check("it drops off the list", b"wspr.log" not in body, body[:400])
equals("and the remaining ones renumber", len(srv.rows()), 4)
status, _b = get(f"{base}/4")
equals("so the old last position is gone", status, 404)

srv.stop()
check("stopped", not srv.running())
try:
    get(base, timeout=2)
    check("and the address stops answering", False, "it still answered")
except Exception:
    check("and the address stops answering", True)

print("\nit closes itself when nothing asks for anything")
clock = [1000.0]
srv = export.Server(files(tempfile.mkdtemp()), address="127.0.0.1",
                    port=export.free_port("127.0.0.1", 18100),
                    idle_s=60.0, clock=lambda: clock[0])
check("started", srv.start(), srv.error)
base, _h = srv.urls()
clock[0] += 59.0
check("still up just before the timeout", srv.tick())
check("and it says how long is left", 0 < srv.remaining() <= 1.0,
      srv.remaining())
clock[0] += 2.0
check("down just after it", not srv.tick())
check("and it is really closed", not srv.running())

print("\na download puts the timer back")
clock = [2000.0]
srv = export.Server(files(tempfile.mkdtemp()), address="127.0.0.1",
                    port=export.free_port("127.0.0.1", 18120),
                    idle_s=60.0, clock=lambda: clock[0])
srv.start()
base, _h = srv.urls()
clock[0] += 55.0
get(f"{base}/0")
equals("the download was counted", srv.downloads, 1)
clock[0] += 10.0
check("65 seconds in, it is still up because 10 of them were idle",
      srv.tick(), srv.idle_for())
srv.stop()

print("\nwith no WiFi address there is nothing to serve to, and it says so")
srv = export.Server(files(tempfile.mkdtemp()), address="")
check("it refuses to start", not srv.start())
check("rather than binding everywhere", not srv.running())
check("and names the reason", "WiFi" in srv.error, srv.error)

print("\nan occupied port is stepped over, not reported as a failure")
hold = export.Server(files(tempfile.mkdtemp()), address="127.0.0.1",
                     port=export.free_port("127.0.0.1", 18140))
hold.start()
equals("the next free port is not the held one",
       export.free_port("127.0.0.1", hold.port) == hold.port, False)
hold.stop()

print("\nan empty export says so rather than showing a bare page")
srv = export.Server([], address="127.0.0.1",
                    port=export.free_port("127.0.0.1", 18160))
srv.start()
base, _h = srv.urls()
status, body = get(base)
equals("the page still answers", status, 200)
check("and says there is nothing yet", b"nothing to export" in body,
      body[:400])
srv.stop()

# -- the deck side -----------------------------------------------------------
#
# What the panel offers and what it refuses to offer. The list of five files
# is the whole security surface of this feature, so the test that the secrets
# are not on it is not a formality.

print("\nthe deck offers five files and never the secrets")
import cyberdeck
import session as session_mod
import config as configmod


def exporting(tmp, log_lines=1):
    d = cyberdeck.Deck.__new__(cyberdeck.Deck)
    log = os.path.join(tmp, "qso.adi_src.log")
    with open(log, "w", encoding="utf-8") as fh:
        for i in range(log_lines):
            fh.write("{\"call\": \"K2ABC\", \"band\": \"20m\", "
                     "\"mode\": \"FT8\", \"qso_date\": \"20261022\", "
                     "\"time_on\": \"120000\"}\n")
    wspr = os.path.join(tmp, "wspr.log")
    with open(wspr, "w", encoding="utf-8") as fh:
        fh.write("2026-10-22 KD3CCO FM19 14.097034 -21\n")
    secrets = os.path.join(tmp, "cyberdeck.secrets")
    with open(secrets, "w", encoding="utf-8") as fh:
        fh.write("QRZ_PASSWORD=hunter2\n")

    d.cfg = {"EXPORT_DIR": os.path.join(tmp, "export"),
             "EXPORT_PORT": 18200, "EXPORT_IDLE_MIN": 5,
             "WSPR_LOG_PATH": wspr, "CALLSIGN": "KD3CCO",
             "ACTIVITY": "", "ACTIVITY_START": ""}
    d.session = session_mod.Session(callsign="KD3CCO")
    d.session.receive("KD3CCO DE K2ABC K\n")
    d._log_path = lambda: log
    d._log_note = lambda text: None
    d._export_adif = lambda *a, **k: None
    d.export_server = None
    d.export_message = ""
    d.screen = cyberdeck.SET
    d._close_menu = lambda: None
    return d, secrets


tmp = tempfile.mkdtemp()
d, secrets = exporting(tmp)
offered = d._export_files()
names = [label for label, _p in offered]
paths = [path for _l, path in offered]
check("the contact log is offered", any("log" in n for n in names), names)
check("the WSPR spots are offered", "wspr.log" in names, names)
check("the transcript is offered", "transcript.txt" in names, names)
check("the secrets are NOT offered", secrets not in paths, paths)
check("not under any name, either",
      not any("secret" in n for n in names), names)

print("\nthe transcript is written, since it lives only in memory")
transcript = dict((label, path) for label, path in offered)["transcript.txt"]
with open(transcript, encoding="utf-8") as fh:
    body = fh.read()
check("it holds what was on the air", "K2ABC" in body, body)
check("attributed to the station that sent it", "RX" in body, body)

print("\nEsc takes the server down, not just the screen")
# Bound to loopback, not to whatever network the machine running the tests
# happens to be on. A test suite that puts a file server on the LAN for a
# few milliseconds is doing something it was not asked to do.
import wifi
_real_address = wifi.address
wifi.address = lambda device="": "127.0.0.1"
try:
    d, _s = exporting(tempfile.mkdtemp())
    d.cfg["EXPORT_PORT"] = export.free_port("127.0.0.1", 18400)
    d._open_export()
    srv = d.export_server
    check("it is up", srv is not None and srv.running(), d.export_message)
    check("on loopback, because that is the address it was given",
          srv is not None and srv.address == "127.0.0.1")
    status, body = get(srv.urls()[0])
    equals("and the page it advertises answers", status, 200)
    check("with the deck's files on it", b"transcript.txt" in body,
          body[:400])
    check("and the callsign in the title", b"KD3CCO" in body, body[:400])
    d._handle_export(27)
    check("Esc stopped it", not srv.running())
    check("and let go of it", d.export_server is None)
    equals("and went back to deck & rig", d.screen, cyberdeck.SET)

    print("\nSpace gives out a new address, so the old one stops working")
    d, _s = exporting(tempfile.mkdtemp())
    d.cfg["EXPORT_PORT"] = export.free_port("127.0.0.1", 18420)
    d._open_export()
    first = d.export_server.urls()[0]
    equals("the first address works", get(first)[0], 200)
    d._handle_export(32)
    second = d.export_server.urls()[0]
    check("the address changed", second != first, (first, second))
    equals("the new one works", get(second)[0], 200)
    # Asked about the TOKEN, on whichever port is now listening. The first
    # version of this check fetched the old URL whole and expected a 404; the
    # server had moved to the next port, because the one it released was in
    # TIME_WAIT and `free_port` steps over such a port rather than refusing,
    # so the old URL raised ConnectionRefused instead. That passed when the
    # file was run alone and failed in the suite -- the port was free the
    # first time and not the second.
    old_token = first.rsplit("/", 1)[1]
    host = second.rsplit("/", 1)[0]
    equals("and the old token is dead", get(f"{host}/{old_token}")[0], 404)
    d._handle_export(27)
finally:
    wifi.address = _real_address

print("\nthe idle timer runs from the main loop, not from the screen")
d, _s = exporting(tempfile.mkdtemp())
d.export_server = export.Server([], address="127.0.0.1",
                                port=export.free_port("127.0.0.1", 18300),
                                idle_s=1.0, clock=lambda: 0.0)
d.export_server.start()
d.export_server._clock = lambda: 99.0
d.screen = cyberdeck.CHAT          # somewhere else entirely
d._poll_export()
check("it closed while the operator was on another screen",
      d.export_server is None)
check("and the transcript says so",
      "closed itself" in d.session.last_note, d.session.last_note)

print("\nit is reached from the deck & rig menu")
import menus
item = [i for i in menus.DECK["items"] if "phone" in i[1].lower()]
check("the menu lists it", bool(item), menus.DECK["items"])

print("\nthe screen fits every panel, address and all")
import render
urls = ("http://192.168.1.47:8080/a7f3",
        f"http://{export.HOSTNAME}:8080/a7f3")
rows = [("qso.adi", "2.1 kB"), ("qso.log", "18.4 kB"),
        ("wspr.log", "412 bytes"), ("transcript.txt", "1.2 kB"),
        ("cyberdeck.conf", "3.0 kB")]
for w, h in ((66, 20), (50, 15), (80, 24), (40, 12)):
    lines = render.export_screen(urls, rows, w, h, remaining=252, downloads=2)
    equals(f"{w}x{h}: exactly {h} rows", len(lines), h)
    equals(f"{w}x{h}: each exactly {w} wide",
           {sum(len(t) for t, _k in ln) for ln in lines}, {w})

body = "\n".join("".join(t for t, _k in ln)
                 for ln in render.export_screen(urls, rows, 66, 20,
                                                remaining=252, downloads=2))
check("the address is on it whole", urls[0] in body, body)
check("the hostname is offered too", urls[1] in body, body)
check("and it says when it closes", "4:12" in body, body)
check("the address is the bright thing on the screen",
      any(k == "bright" and urls[0] in t
          for ln in render.export_screen(urls, rows, 66, 20) for t, k in ln))

print("\nwith no server there is no address pretending to work")
body = "\n".join("".join(t for t, _k in ln)
                 for ln in render.export_screen(("", ""), [], 66, 20,
                                                message="no WiFi address"))
check("it says what is wrong", "no WiFi address" in body, body)
check("and offers nothing", "nothing to export" in body, body)

sys.exit(report())
