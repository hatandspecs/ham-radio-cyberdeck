"""Uploading WSPR spots to wsprnet. Never blocks; never sends unless armed.

The three rules `callbook.py` works to apply here unchanged, and one more
that is specific to this:

  * **It must never block.** cyberdeck.py is a single-threaded curses loop,
    and a slot's worth of spots is several HTTP requests. They go to a worker
    thread and the outcome is collected later, or never.
  * **It must never gate anything.** A spot is written to the deck's own log
    whether or not it ever reaches wsprnet. The upload is a report about a
    record, not the record.
  * **It must work offline.** No network is an ordinary condition. Spots that
    cannot be sent are dropped rather than queued forever -- see `Uploader`.
  * **It must not send unless all three conditions hold**: WSPR running, the
    toggle on, and a network present. Those are the operator's, and this
    module does not decide any of them -- it is handed `armed`.

The network is injectable (`post=`), so every test here runs with no network
and no mocking library.

## The protocol

Taken from **WSJT-X's own `Network/wsprnet.cpp`**, which is the thing every
other WSPR station is running, rather than from a description of it:

    POST http://wsprnet.org/post/
    Content-Type: application/x-www-form-urlencoded

A spot carries `function=wspr` and then the receiver's side -- `rcall`,
`rgrid`, `rqrg` -- the slot's `date` and `time`, the measurements `sig`, `dt`
and `drift`, and the transmitter's side as decoded: `tqrg`, `tcall`, `tgrid`,
`dbm`. Plus `version` and `mode`.

**A station that decoded nothing still reports itself**, with
`function=wsprstat` and no transmitter fields. That is how wsprnet knows a
receiver was listening on a band and heard nothing, which is information --
an absent report and a report of silence mean different things to anybody
reading the database afterwards. `tpct` carries the transmit percentage.

`mode` is `2` for WSPR-2 and `15` for WSPR-15. The FST4W modes use 3, 5, 16
and 30; the deck sends WSPR-2 and nothing else.

**Spots are sent one at a time**, which is what WSJT-X does -- it queues them
and dequeues on a 200 ms timer. There is no documented bulk endpoint, and
inventing one is not a thing a client gets to do.
"""

import threading
import time
import urllib.parse
import urllib.request

URL = "http://wsprnet.org/post/"

# WSJT-X spaces its uploads 200 ms apart. Matched rather than improved on: a
# client that hammers a shared service faster than the reference client is a
# client that gets blocked, and the deck has 120 seconds to send a handful of
# spots.
SPACING_S = 0.2

# Short, because nothing waits on this. A spot that cannot be sent in five
# seconds is dropped and the next slot will bring more.
TIMEOUT_S = 5.0

MODE_WSPR2 = "2"

# What the deck calls itself to wsprnet. Its own name and version, not a
# WSJT-X version string: claiming to be software this is not would make every
# bug reported against it somebody else's.
VERSION = "cyberdeck"


def _http_post(url, body, timeout=TIMEOUT_S):
    """One form POST. Returns the response text, or raises."""
    req = urllib.request.Request(
        url, data=body.encode("utf-8"), method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": VERSION})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def spot_params(spot, my_call, my_grid, dial_hz, date, time_hhmm,
                mode=MODE_WSPR2, version=VERSION):
    """The form fields for one decoded spot. Pure.

    `spot` is what `wspr.parse_decode` returned. `dial_hz` is what the radio
    was tuned to, which is the receiver's frequency and is NOT the spot's
    frequency -- `rqrg` is where this station was listening and `tqrg` is
    where the other station was found. Reporting one as the other is a wrong
    report rather than a missing one.

    Megahertz on the wire, because that is what the field carries. The deck
    keeps hertz everywhere internally (`HERTZ_FIELDS`) and converts here.

    A spot with no grid -- a type 2 compound-call message -- sends no `tgrid`
    at all rather than an empty one.
    """
    out = {
        "function": "wspr",
        "rcall": str(my_call or "").upper(),
        "rgrid": str(my_grid or ""),
        "rqrg": f"{int(dial_hz) / 1_000_000:.6f}",
        "date": str(date or ""),
        "time": str(time_hhmm or ""),
        "sig": str(spot.get("snr", "")),
        "dt": f"{float(spot.get('dt', 0.0)):.1f}",
        "drift": str(spot.get("drift", 0)),
        "tqrg": f"{int(spot.get('freq', 0)) / 1_000_000:.6f}",
        "tcall": str(spot.get("call", "")).upper(),
        "dbm": str(spot.get("dbm", "")),
        "version": str(version),
        "mode": str(mode),
    }
    if spot.get("grid"):
        out["tgrid"] = str(spot["grid"])
    return out


def stat_params(my_call, my_grid, dial_hz, tx_percent=0, dbm=0,
                mode=MODE_WSPR2, version=VERSION):
    """The form fields for "listening, nothing heard". Pure.

    Sent for a slot that decoded nothing, because an absent report and a
    report of silence are different facts: the first says nothing about
    whether anybody was listening on that band.
    """
    return {
        "function": "wsprstat",
        "rcall": str(my_call or "").upper(),
        "rgrid": str(my_grid or ""),
        "rqrg": f"{int(dial_hz) / 1_000_000:.6f}",
        "tpct": str(int(tx_percent or 0)),
        "tqrg": f"{int(dial_hz) / 1_000_000:.6f}",
        "dbm": str(dbm or 0),
        "version": str(version),
        "mode": str(mode),
    }


def encode(params):
    """Form fields as an `application/x-www-form-urlencoded` body."""
    return urllib.parse.urlencode(
        {k: v for k, v in params.items() if v != ""})


class Uploader:
    """Sends spots on a worker thread, and only while armed.

    Dropped rather than queued forever when there is no network. A queue that
    survived an afternoon off-grid would upload a thousand spots the moment
    WiFi came back, timestamped hours earlier, which is worse for the
    database than not reporting them -- and the deck's own log has them all
    regardless.

    `post=` is the seam. Nothing in the tests touches a network.
    """

    #: Beyond this many waiting, the oldest are dropped. One slot of a busy
    #: band is a few dozen spots; a backlog larger than this means the
    #: network is gone and the queue is not catching up.
    MAX_PENDING = 200

    def __init__(self, post=None, spacing=SPACING_S):
        self._post = post or _http_post
        self._spacing = spacing
        self._lock = threading.Lock()
        self._pending = []
        self._worker = None
        self.sent = 0
        self.failed = 0
        self.dropped = 0
        self.last_error = ""

    @property
    def pending(self):
        with self._lock:
            return len(self._pending)

    def submit(self, params, armed=True):
        """Queue one report. Returns whether it was taken.

        `armed` is all three of the operator's conditions ANDed by the
        caller: WSPR running, the toggle on, network present. Unarmed is not
        an error and not a drop -- there is simply nothing to do, and the
        spot is in the deck's log either way.
        """
        if not armed:
            return False
        with self._lock:
            self._pending.append(dict(params))
            while len(self._pending) > self.MAX_PENDING:
                self._pending.pop(0)
                self.dropped += 1
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._drain,
                                                daemon=True)
                self._worker.start()
        return True

    def _drain(self):
        """Send what is queued, one at a time, spaced like WSJT-X's."""
        while True:
            with self._lock:
                if not self._pending:
                    self._worker = None
                    return
                params = self._pending.pop(0)
            try:
                self._post(URL, encode(params))
                with self._lock:
                    self.sent += 1
            except Exception as exc:
                # Never raised out of the thread: a failed upload is an
                # ordinary condition and must not be able to disturb a
                # session. Recorded so the screen can say so.
                with self._lock:
                    self.failed += 1
                    self.last_error = f"{type(exc).__name__}: {exc}"
            if self._spacing:
                time.sleep(self._spacing)

    def wait(self, seconds=5.0):
        """Block until the queue empties. For tests and for shutdown only."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.pending == 0 and (self._worker is None
                                      or not self._worker.is_alive()):
                return True
            time.sleep(0.01)
        return False


def upload_state(toggle_on, online, running):
    """The three-state word the screen shows: on, off, or no wifi.

    The same three the callbook reports, for the same reason: "switched off"
    and "cannot right now" are different conditions and an operator needs to
    tell them apart at a glance.
    """
    if not toggle_on:
        return "off"
    if not online:
        return "no wifi"
    return "on" if running else "off"
