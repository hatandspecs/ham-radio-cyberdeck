"""Uploading to a QRZ logbook, with the network injected so none of it leaves.

The parsing is the easy half. The properties worth testing are the ones that
decide whether a contact can be lost:

  * an unrecognized reply is RETRY, not PERMANENT. A captive portal, an HTML
    error page or a half-second of nothing are all "try later". Classifying
    them as permanent drops the QSO from the outbox and nothing ever says so.
  * a duplicate is OK. The contact is in the logbook, which is the only thing
    the outbox cares about; retrying it forever is the alternative.
  * a drain stops at the FIRST retryable failure. One unreachable server means
    the network is gone, and seventy-nine more timeouts prove it seventy-nine
    more times while the operator waits.
  * the outbox is keyed by the contact, not by its position in the file.
    Hand-editing qso.log over SSH is the documented recovery path, and a
    position key would silently re-upload everything after the edit.
"""
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import qrzlog


def rec(call, when="2026-10-10T16:12:03Z", band="20m", mode="SSB"):
    return {"when": when, "call": call, "band": band, "mode": mode}


def adif_of(r):
    return f"<CALL:{len(r['call'])}>{r['call']} <EOR>"


print("parsing replies")
equals("ok with a logid", qrzlog.parse_reply("RESULT=OK&LOGID=123456&COUNT=1"),
       {"RESULT": "OK", "LOGID": "123456", "COUNT": "1"})
equals("url-encoded reason",
       qrzlog.parse_reply("RESULT=FAIL&REASON=invalid+key")["REASON"],
       "invalid key")
equals("an HTML error page", qrzlog.parse_reply("<html>502</html>"), {})
equals("empty", qrzlog.parse_reply(""), {})
equals("None", qrzlog.parse_reply(None), {})

print("\nclassifying")
equals("OK", qrzlog.classify({"RESULT": "OK"}), qrzlog.OK)
equals("REPLACE is also in the logbook",
       qrzlog.classify({"RESULT": "REPLACE"}), qrzlog.OK)
equals("a duplicate is already there",
       qrzlog.classify({"RESULT": "FAIL", "REASON": "duplicate QSO"}), qrzlog.OK)
equals("AUTH is permanent", qrzlog.classify({"RESULT": "AUTH"}), qrzlog.PERMANENT)
equals("a bad key is permanent",
       qrzlog.classify({"RESULT": "FAIL", "REASON": "invalid key"}), qrzlog.PERMANENT)
equals("no subscription is permanent",
       qrzlog.classify({"RESULT": "FAIL", "REASON": "subscription required"}),
       qrzlog.PERMANENT)
equals("an unexplained failure is worth retrying",
       qrzlog.classify({"RESULT": "FAIL", "REASON": "server busy"}), qrzlog.RETRY)
equals("and so is a reply that made no sense", qrzlog.classify({}), qrzlog.RETRY)

print("\nuploading")
seen = []
def ok_post(url, data, timeout=None):
    seen.append(data)
    return "RESULT=OK&LOGID=987&COUNT=1"

outcome, logid, detail = qrzlog.upload("<CALL:5>W3ABC <EOR>", "ABCD-1234", post=ok_post)
equals("outcome", outcome, qrzlog.OK)
equals("logid captured", logid, "987")
equals("nothing to tell the operator", detail, "")
equals("the key went with it", seen[0]["KEY"], "ABCD-1234")
equals("as an INSERT", seen[0]["ACTION"], "INSERT")
check("and no REPLACE unless asked", "OPTION" not in seen[0], seen[0])

qrzlog.upload("<CALL:5>W3ABC <EOR>", "K", post=ok_post, replace=True)
equals("REPLACE when asked", seen[1]["OPTION"], "REPLACE")

def dead_post(url, data, timeout=None):
    raise OSError("Network is unreachable")

outcome, _, detail = qrzlog.upload("<EOR>", "K", post=dead_post)
equals("no network is retryable", outcome, qrzlog.RETRY)
check("and says so in a line fit to show", "unreachable" in detail, detail)

equals("no key at all", qrzlog.upload("<EOR>", "", post=ok_post)[0], qrzlog.PERMANENT)
equals("nothing to send", qrzlog.upload("", "K", post=ok_post)[0], qrzlog.PERMANENT)

print("\noutbox")
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "sub", "qrz-outbox.json")
    ob = qrzlog.Outbox(path)
    a, b = rec("W3ABC"), rec("K2XYZ", when="2026-10-10T16:20:00Z")

    check("nothing sent yet", not ob.is_sent(a))
    ob.mark_sent(a, "987")
    check("sent", ob.is_sent(a))
    equals("logid remembered", ob.logid(a), "987")
    check("and the other one is not", not ob.is_sent(b))

    again = qrzlog.Outbox(path)
    check("survives a restart", again.is_sent(a))

    equals("pending skips what has gone", [r["call"] for r in again.pending([a, b])],
           ["K2XYZ"])

    again.mark_failed(b, "QRZ: invalid key")
    equals("a permanent failure is not retried forever", again.pending([a, b]), [])
    equals("but it is remembered", again.failure(b), "QRZ: invalid key")
    equals("counts", again.counts([a, b]), {"sent": 1, "failed": 1, "pending": 0})

    # The identity key, not the position: an edit that reorders or inserts
    # lines must not re-upload everything after it.
    same_contact_moved = dict(a)
    check("identity travels with the record", again.is_sent(same_contact_moved))
    equals("a different band is a different contact",
           again.is_sent(rec("W3ABC", band="40m")), False)
    equals("a different mode too", again.is_sent(rec("W3ABC", mode="CW")), False)

print("\ncorrupt outbox")
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "qrz-outbox.json")
    with open(path, "w") as fh:
        fh.write("{ truncated")
    ob = qrzlog.Outbox(path)
    equals("is an empty outbox, not an error", ob.counts([rec("W3ABC")]),
           {"sent": 0, "failed": 0, "pending": 1})

print("\ndraining")
with tempfile.TemporaryDirectory() as tmp:
    ob = qrzlog.Outbox(os.path.join(tmp, "ob.json"))
    records = [rec(c, when=f"2026-10-10T16:{i:02d}:00Z")
               for i, c in enumerate(("W3ABC", "K2XYZ", "N3QQQ"))]

    posts = []
    def all_ok(url, data, timeout=None):
        posts.append(data["ADIF"])
        return "RESULT=OK&LOGID=1&COUNT=1"

    s = qrzlog.drain(records, "K", ob, adif_of, post=all_ok)
    equals("all three", s["sent"], 3)
    equals("one request each", len(posts), 3)
    check("and nothing stopped it", not s["stopped"])

    s2 = qrzlog.drain(records, "K", ob, adif_of, post=all_ok)
    equals("a second drain sends nothing", s2["sent"], 0)
    equals("and makes no requests", len(posts), 3)

with tempfile.TemporaryDirectory() as tmp:
    ob = qrzlog.Outbox(os.path.join(tmp, "ob.json"))
    records = [rec(c, when=f"2026-10-10T17:{i:02d}:00Z")
               for i, c in enumerate(("W3ABC", "K2XYZ", "N3QQQ"))]

    tries = []
    def dies_on_second(url, data, timeout=None):
        tries.append(data["ADIF"])
        if len(tries) == 1:
            return "RESULT=OK&LOGID=1"
        raise OSError("Network went away")

    s = qrzlog.drain(records, "K", ob, adif_of, post=dies_on_second)
    equals("the first got through", s["sent"], 1)
    check("and it stopped", s["stopped"])
    equals("without grinding through the rest", len(tries), 2)
    equals("the two left are still pending", len(ob.pending(records)), 2)

with tempfile.TemporaryDirectory() as tmp:
    ob = qrzlog.Outbox(os.path.join(tmp, "ob.json"))
    records = [rec(c, when=f"2026-10-10T18:{i:02d}:00Z")
               for i, c in enumerate(("W3ABC", "K2XYZ"))]

    def no_sub(url, data, timeout=None):
        return "RESULT=FAIL&REASON=subscription+required"

    s = qrzlog.drain(records, "K", ob, adif_of, post=no_sub)
    equals("a permanent failure does not stop the drain", s["stopped"], False)
    equals("both were tried and both refused", s["failed"], 2)
    equals("and neither is retried", ob.pending(records), [])

with tempfile.TemporaryDirectory() as tmp:
    ob = qrzlog.Outbox(os.path.join(tmp, "ob.json"))
    records = [rec(c, when=f"2026-10-10T19:{i:02d}:00Z")
               for i, c in enumerate(("W3ABC", "K2XYZ", "N3QQQ"))]
    s = qrzlog.drain(records, "K", ob, adif_of, post=ok_post, limit=1)
    equals("limit is respected", s["sent"], 1)
    equals("the rest wait", len(ob.pending(records)), 2)

    s = qrzlog.drain(records, "K", ob, adif_of, post=ok_post,
                     stop=lambda: True)
    equals("a stop before the first record sends nothing", s["sent"], 0)
    check("and reports that it stopped", s["stopped"])

print("\nbackground drain")
import time as _t
with tempfile.TemporaryDirectory() as tmp:
    ob = qrzlog.Outbox(os.path.join(tmp, "ob.json"))
    records = [rec("W3ABC"), rec("K2XYZ", when="2026-10-10T20:00:00Z")]
    bg = qrzlog.Background()
    equals("nothing to take before it runs", bg.take(), None)
    check("started", bg.start(records=records, key="K", outbox=ob,
                              to_adif=adif_of, post=ok_post))
    got = None
    for _ in range(200):
        got = bg.take()
        if got is not None:
            break
        _t.sleep(0.01)
    equals("the summary arrives", (got or {}).get("sent"), 2)
    equals("and only once", bg.take(), None)

    def explodes(url, data, timeout=None):
        raise RuntimeError("something unexpected")

    bg2 = qrzlog.Background()
    bg2.start(records=[rec("N3QQQ")], key="K", outbox=ob, to_adif=adif_of,
              post=explodes)
    for _ in range(200):
        got = bg2.take()
        if got is not None:
            break
        _t.sleep(0.01)
    check("an unexpected error is caught, not raised at the deck",
          got is not None and got["stopped"], repr(got))

sys.exit(report())
