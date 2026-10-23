"""Serve the deck's files to a phone on the same network, for a few minutes.

The operator presses one key, the panel shows an address, the phone's browser
opens it and the files download. No account, no app, no credentials anywhere,
and it works on a field hotspot with no uplink -- the deck and the phone see
each other whether or not anything else does.

**Read-only, and five files wide.** The request never names a path. It names
a position in a list this module was handed, and anything else is a 404. There
is no upload, no delete and no directory listing, which is most of why this is
safe to stand up on a hotspot shared with strangers.

**It is not always on.** The server starts when the export key is pressed and
closes itself after `IDLE_S` with nothing asked of it. A permanent file server
on a deck that joins strange networks is a different thing entirely, and not
this thing.

**The path carries a random token.** `http://192.168.1.47:8080/a7f3` for the
life of one export. That is the difference between the logs being on the
network and the logs being at an address nobody can guess for as long as the
server is up -- bought for one line, with no password to thumb into a
five-inch screen.

The token is deliberately short, because it is typed by hand. Four characters
from a 32-character alphabet is about a million combinations, which is ample
for something that exists for five minutes.
"""
import html
import http.server
import os
import secrets
import socket
import threading
import time


PORT = 8080

# No `l`, `1`, `o` or `0`. The token is read off a 5" panel and typed into a
# phone, where those four characters are the ones that get mistaken for each
# other.
TOKEN_CHARS = "abcdefghijkmnpqrstuvwxyz23456789"
TOKEN_LEN = 4

# How long with nothing asked of it before it closes itself. Long enough to
# find the deck's address, type it in and tap five files; short enough that an
# operator who walks away is not leaving a file server running.
IDLE_S = 300.0

# The hostname avahi advertises. Printed under the address as the shorter
# thing to type, never relied on: Android resolves `.local` inconsistently,
# and Android is the phone this is for.
HOSTNAME = "cyberdeck.local"


def token(length=TOKEN_LEN):
    """A fresh path token. `secrets`, not `random`."""
    return "".join(secrets.choice(TOKEN_CHARS) for _ in range(length))


def _page(title, rows, token_):
    """The whole interface: a list of links, and nothing else.

    No stylesheet, no script, no fonts, nothing fetched from anywhere. The
    page has to render on a phone that may have no route off this network,
    which rules out everything external whether or not it would be nicer.
    """
    out = ["<!doctype html>", "<html lang=\"en\">", "<head>",
           "<meta charset=\"utf-8\">",
           "<meta name=\"viewport\" content=\"width=device-width,"
           "initial-scale=1\">",
           f"<title>{html.escape(title)}</title>",
           "<style>",
           "body{font:16px/1.5 system-ui,sans-serif;margin:0;padding:1.5rem;"
           "background:#111;color:#eee}",
           "h1{font-size:1.25rem;margin:0 0 1rem}",
           "ul{list-style:none;margin:0;padding:0}",
           "li{border-bottom:1px solid #333}",
           "a{display:block;padding:0.9rem 0;color:#8cf;"
           "text-decoration:none}",
           "span{color:#888;font-size:0.85rem}",
           "p{color:#888;font-size:0.85rem;margin-top:1.5rem}",
           "</style>", "</head>", "<body>",
           f"<h1>{html.escape(title)}</h1>", "<ul>"]
    if not rows:
        out.append("<li><a>nothing to export yet</a></li>")
    for i, (label, size) in enumerate(rows):
        out.append(f"<li><a href=\"/{token_}/{i}\" download>"
                   f"{html.escape(label)}<br><span>{size}</span></a></li>")
    out += ["</ul>",
            "<p>This page closes itself a few minutes after the last "
            "download.</p>",
            "</body>", "</html>"]
    return "\n".join(out).encode("utf-8")


def _rows(files):
    """`(label, size)` for each file, skipping any that has gone.

    One implementation, used by both the panel and the page. Two would be two
    numberings, and the page's numbers ARE how a file is requested.
    """
    out = []
    for label, path in files:
        try:
            out.append((label, _human(os.path.getsize(path))))
        except OSError:
            continue
    return out


def _human(n):
    if n < 1024:
        return f"{n} bytes"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} kB"
    return f"{n / (1024 * 1024):.1f} MB"


class Server:
    """An HTTP server over a fixed list of files, for one export.

    `files` is `[(label, path), ...]`. The label is what the page shows and
    the download is named; the path is never derived from a request.
    """

    def __init__(self, files, address="", port=PORT, token_=None,
                 idle_s=IDLE_S, clock=time.monotonic, title="Cyberdeck files"):
        self.files = [(str(label), str(path)) for label, path in files]
        self.address = address
        self.port = port
        self.token = token_ or token()
        self.idle_s = idle_s
        self.title = title
        self._clock = clock
        self._httpd = None
        self._thread = None
        self._last = clock()
        self.hits = 0
        self.downloads = 0
        self.error = ""

    # -- what is on offer -------------------------------------------------

    def rows(self):
        """The files that exist right now, as `(label, size)`.

        Asked at request time rather than at start, because the ADIF is
        written on the way in and a log can grow while the page is open.
        """
        return _rows(self._present())

    def _present(self):
        return [(label, path) for label, path in self.files
                if os.path.isfile(path)]

    # -- running ----------------------------------------------------------

    def urls(self):
        """`(by address, by hostname)`. The address first: it always works."""
        host = self.address or "0.0.0.0"
        return (f"http://{host}:{self.port}/{self.token}",
                f"http://{HOSTNAME}:{self.port}/{self.token}")

    def running(self):
        return self._httpd is not None

    def start(self):
        """Bind and serve. False with `error` set when it cannot."""
        if self._httpd is not None:
            return True
        if not self.address:
            # Not `0.0.0.0`. The deck has other interfaces, and a server that
            # exists only on the network the operator is looking at is the
            # one that can be reasoned about. No address means no WiFi, which
            # means there is nothing to serve to.
            self.error = "no WiFi address — join a network first"
            return False
        try:
            self._httpd = http.server.ThreadingHTTPServer(
                (self.address, self.port), self._handler())
        except OSError as exc:
            self._httpd = None
            self.error = str(exc)
            return False
        self._httpd.daemon_threads = True
        self._last = self._clock()
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        kwargs={"poll_interval": 0.2},
                                        daemon=True)
        self._thread.start()
        self.error = ""
        return True

    def stop(self):
        httpd, self._httpd = self._httpd, None
        if httpd is None:
            return
        httpd.shutdown()
        httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None

    def idle_for(self):
        return self._clock() - self._last

    def tick(self):
        """Called from the draw loop. False once it has closed itself."""
        if self._httpd is None:
            return False
        if self.idle_s and self.idle_for() >= self.idle_s:
            self.stop()
            return False
        return True

    def remaining(self):
        """Seconds left on the idle timer, for the panel to count down."""
        if self._httpd is None or not self.idle_s:
            return 0
        return max(0.0, self.idle_s - self.idle_for())

    # -- the one request this answers -------------------------------------

    def _handler(self):
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            # Not `SimpleHTTPRequestHandler`. That one maps a request path
            # onto the filesystem, which is the single thing this must not do.
            protocol_version = "HTTP/1.1"
            server_version = "cyberdeck"
            sys_version = ""

            def log_message(self, fmt, *args):
                """Nothing to stderr.

                On the deck stderr is tty1 -- the same console curses is
                drawing the panel on. `http.server`'s default logging would
                scribble a request line across the screen for every tap.
                """

            def _deny(self):
                # The same answer for a bad token, a bad index and a path
                # above the export: nothing here says which of the three it
                # was.
                body = b"not found\n"
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                # A HEAD gets the headers and no body. With
                # `protocol_version = "HTTP/1.1"` the connection is kept
                # alive, so a body the client is not reading would be parsed
                # as the start of the next response.
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _parts(self):
                path = self.path.split("?")[0].split("#")[0]
                return [p for p in path.split("/") if p]

            def do_GET(self):                     # noqa: N802
                server._last = server._clock()
                server.hits += 1
                parts = self._parts()
                if not parts or not secrets.compare_digest(parts[0],
                                                           server.token):
                    # Constant-time, so a wrong token cannot be found one
                    # character at a time off the response timing.
                    return self._deny()
                files = server._present()
                if len(parts) == 1:
                    return self._index(files)
                if len(parts) != 2:
                    return self._deny()
                try:
                    i = int(parts[1])
                except ValueError:
                    return self._deny()
                # A POSITION in the list, never a name from the request. There
                # is no path here to traverse out of.
                if not 0 <= i < len(files):
                    return self._deny()
                return self._send(*files[i])

            def do_HEAD(self):                    # noqa: N802
                self.do_GET()

            def _index(self, files):
                body = _page(server.title, _rows(files), server.token)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _send(self, label, path):
                try:
                    with open(path, "rb") as fh:
                        body = fh.read()
                except OSError:
                    return self._deny()
                server.downloads += 1
                self.send_response(200)
                self.send_header("Content-Type",
                                 "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Content-Disposition",
                                 f"attachment; filename=\"{label}\"")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

        return Handler


def free_port(address, first=PORT, tries=8):
    """A port that binds, starting at `first`.

    An export interrupted and restarted can meet its own socket still in
    TIME_WAIT, and a deck that refuses to export because of that would be
    refusing for a reason the operator cannot see or fix.
    """
    for port in range(first, first + tries):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind((address, port))
            return port
        except OSError:
            continue
        finally:
            s.close()
    return first
