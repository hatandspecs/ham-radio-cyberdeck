"""Upload contacts to a QRZ.com logbook, when there is a network and not before.

The arrangement is the one the rest of the deck uses for anything off the
board: the local file is the record, and QRZ is a destination that may or may
not be reachable. Nothing here can lose a contact, delay one, or make the
operator wait.

    commit  ->  qso.log            always, immediately, fsynced
            ->  outbox             a line of callsigns waiting to go
            ->  (eventually) QRZ   when there is a network and the key works

The outbox is why this works in a park. The deck spends most of its life with
the WiFi off; contacts queue up, and the next time it associates they drain.
An activation uploads itself on the drive home.

API, from https://www.qrz.com/docs/logbook/QRZLogbookAPI.html:

    POST https://logbook.qrz.com/api
    KEY=<logbook key>&ACTION=INSERT&ADIF=<one record>

    RESULT=OK       inserted; LOGID is the record id
    RESULT=REPLACE  a duplicate was overwritten (only with REPLACE=1)
    RESULT=FAIL     REASON says why
    RESULT=AUTH     the key is wrong

One QSO per INSERT — the API takes no batches — so an eighty-contact
activation is eighty requests. That is fine at a second apiece on the way home
and is the reason the outbox drains in the background rather than on commit.

**The key is a secret.** It belongs in `deck.secrets`, which is gitignored and
baked into the card by `build_deck_image.sh`, not in `cyberdeck.conf`, which
describes the station and gets copied around.

INSERT requires a QRZ subscription. Without one the API answers and refuses,
which this treats as an ordinary permanent failure — see `classify`.
"""

import json
import os
import threading
import time
import urllib.parse
import urllib.request

ENDPOINT = "https://logbook.qrz.com/api"
TIMEOUT_S = 10.0

# Outcomes, in the only three categories the caller can act on differently.
OK = "ok"            # it is in the logbook; stop trying
RETRY = "retry"      # the network or QRZ was not there; try again later
PERMANENT = "fail"   # the key, the subscription or the record is wrong


def _http_post(url, data, timeout=TIMEOUT_S):
    """The default transport. Replaced wholesale in tests."""
    body = urllib.parse.urlencode(data).encode("ascii")
    req = urllib.request.Request(
        url, data=body,
        headers={"User-Agent": "cyberdeck",
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_reply(text):
    """QRZ answers with `KEY=VALUE&KEY=VALUE`. Returns a dict, upper-cased keys.

    Never raises. A reply that is not in that shape — a captive portal's login
    page, an HTML error, an empty body — comes back as {} and is classified as
    retryable, because that is what a wifi hotspot that intercepted the request
    actually is.
    """
    out = {}
    if not text:
        return out
    for pair in str(text).strip().split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[k.strip().upper()] = urllib.parse.unquote_plus(v.strip())
    return out


def classify(reply):
    """Which of the three outcomes a parsed reply is.

    `REPLACE` counts as OK: the contact is in the logbook, which is the only
    thing the outbox cares about.

    An unrecognized reply is RETRY rather than PERMANENT. Getting this
    backwards loses contacts silently — a transient server error that is
    treated as permanent drops the QSO and nothing says so — and the cost of
    the other mistake is only that the deck tries again later.
    """
    result = (reply.get("RESULT") or "").upper()
    if result in ("OK", "REPLACE"):
        return OK
    if result == "AUTH":
        return PERMANENT
    if result == "FAIL":
        reason = (reply.get("REASON") or "").lower()
        # A duplicate is not a failure worth retrying: the contact is already
        # there, which is the outcome wanted. Anything about the key or the
        # subscription will not fix itself either.
        if "duplicate" in reason:
            return OK
        for phrase in ("invalid key", "not authorized", "subscription",
                       "unable to add", "invalid adif", "wrong station"):
            if phrase in reason:
                return PERMANENT
        return RETRY
    return RETRY


def upload(adif, key, post=_http_post, endpoint=ENDPOINT, replace=False):
    """Insert one record. Returns (outcome, logid, detail).

    `detail` is a short string fit to show the operator as a `--` line, and is
    empty on success.
    """
    if not key:
        return PERMANENT, "", "no QRZ API key"
    if not adif:
        return PERMANENT, "", "nothing to upload"

    data = {"KEY": key, "ACTION": "INSERT", "ADIF": adif}
    if replace:
        data["OPTION"] = "REPLACE"

    try:
        text = post(endpoint, data)
    except Exception as exc:
        # Deliberately broad, for the same reason as callbook: urllib raises
        # half a dozen unrelated types for "no network" and on the deck they
        # are one event.
        return RETRY, "", f"QRZ unreachable ({type(exc).__name__})"

    reply = parse_reply(text)
    outcome = classify(reply)
    logid = reply.get("LOGID", "")
    if outcome == OK:
        return OK, logid, ""
    detail = reply.get("REASON") or reply.get("RESULT") or "unrecognized reply"
    return outcome, logid, f"QRZ: {detail}"


class Outbox:
    """Which contacts have not reached QRZ yet, and which have.

    A sidecar file, deliberately NOT the log itself. `qso.log` is append-only
    and is the record; rewriting it to flip an "uploaded" flag would make it
    neither append-only nor trustworthy after a power cut mid-write. This file
    can be lost entirely and cost nothing but a round of duplicate-detection.

    Keyed by a contact's own identity — time, call, band, mode — rather than by
    line number, so hand-editing the log over SSH does not silently re-upload
    everything after the edited line.
    """

    def __init__(self, path, now=time.time):
        self.path = path
        self._now = now
        self._sent = {}        # key -> {"logid": str, "at": float}
        self._failed = {}      # key -> reason, for permanent failures
        self._load()

    @staticmethod
    def key_for(rec):
        return "|".join((rec.get("when", ""), rec.get("call", ""),
                         rec.get("band", ""), rec.get("mode", "")))

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                self._sent = data.get("sent") or {}
                self._failed = data.get("failed") or {}
        except (OSError, ValueError):
            self._sent, self._failed = {}, {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"sent": self._sent, "failed": self._failed}, fh)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except OSError:
            # Same rule as the callbook cache: this runs near the commit path
            # and must never raise. Losing it costs a duplicate check.
            pass

    def is_sent(self, rec):
        return self.key_for(rec) in self._sent

    def logid(self, rec):
        return (self._sent.get(self.key_for(rec)) or {}).get("logid", "")

    def mark_sent(self, rec, logid=""):
        self._sent[self.key_for(rec)] = {"logid": logid, "at": self._now()}
        self._failed.pop(self.key_for(rec), None)
        self._save()

    def mark_failed(self, rec, reason):
        self._failed[self.key_for(rec)] = reason
        self._save()

    def failure(self, rec):
        return self._failed.get(self.key_for(rec), "")

    def pending(self, records):
        """Those not yet in the logbook and not permanently refused.

        A permanent failure is skipped rather than retried forever. It stays
        in the local log, which is the record, and the operator is told once.
        """
        return [r for r in records
                if not self.is_sent(r) and not self.failure(r)]

    def counts(self, records):
        sent = sum(1 for r in records if self.is_sent(r))
        failed = sum(1 for r in records if self.failure(r))
        return {"sent": sent, "failed": failed,
                "pending": len(records) - sent - failed}


def drain(records, key, outbox, to_adif, post=_http_post, endpoint=ENDPOINT,
          limit=None, stop=None):
    """Upload everything outstanding. Returns a summary dict.

    Stops at the first retryable failure. One unreachable server means the
    network is gone, and grinding through seventy-nine more timeouts proves it
    seventy-nine more times while the operator waits.

    `stop` is a callable checked between records so a drain can be abandoned —
    the operator pressing Esc, or the deck shutting down. `to_adif` turns a
    record into an ADIF string, injected so this module needs no import of
    qsolog and can be tested on its own.
    """
    todo = outbox.pending(records)
    if limit:
        todo = todo[:limit]

    summary = {"sent": 0, "failed": 0, "stopped": False, "detail": ""}
    for rec in todo:
        if stop is not None and stop():
            summary["stopped"] = True
            break
        outcome, logid, detail = upload(to_adif(rec), key, post=post,
                                        endpoint=endpoint)
        if outcome == OK:
            outbox.mark_sent(rec, logid)
            summary["sent"] += 1
        elif outcome == PERMANENT:
            outbox.mark_failed(rec, detail)
            summary["failed"] += 1
            summary["detail"] = detail
        else:
            summary["stopped"] = True
            summary["detail"] = detail
            break
    return summary


class Background:
    """Run a drain off the interface thread.

    Same contract as callbook.Background: `start` returns immediately, `take`
    collects the summary once it exists. The deck polls it on a frame it was
    drawing anyway. A drain still running at shutdown is abandoned, and its
    contacts are still in the local log and still in the outbox.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._result = None
        self._running = False
        self._cancel = False

    def start(self, **kwargs):
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._cancel = False
        kwargs.setdefault("stop", lambda: self._cancel)

        def work():
            try:
                summary = drain(**kwargs)
            except Exception as exc:          # never take the deck down
                summary = {"sent": 0, "failed": 0, "stopped": True,
                           "detail": f"upload error ({type(exc).__name__})"}
            with self._lock:
                self._result = summary
                self._running = False

        threading.Thread(target=work, daemon=True).start()
        return True

    def cancel(self):
        self._cancel = True

    def running(self):
        with self._lock:
            return self._running

    def take(self):
        with self._lock:
            out, self._result = self._result, None
            return out
