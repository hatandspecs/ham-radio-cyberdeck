"""The WSPR spot log: what was heard, what was sent, and in which session.

Pure. No clock, no radio, no subprocess — the caller supplies the time and
the readings, which is what makes a night of beaconing testable in
milliseconds.

**The logger's concepts, with one deliberate subtraction.** A session is
`(name, start)` with the start pinned when it begins; the file is one
`key=value` line per record carrying only the fields that have a value; and
session attributes are DERIVED from the records rather than stored beside
them, because a file that records what happened cannot drift from what
happened and a power cut cannot lose it. See `docs/qso_log_design.md` §7f
for where that shape came from.

The subtraction is **schemas**. The contact log has them because `599` is
both a report and a serial and only the operator knows which; a WSPR spot
has no such ambiguity, because `wsprd` decides what the fields are. So there
is one fixed field set, no picker and no `activity_type`.

**Two record kinds in one file**, told apart by `kind`:

  * `kind=rx` — a station heard. Carries its call, grid and claimed power
    and the measurements.
  * `kind=tx` — a beacon sent. Carries what this station announced.

The format carries no schema, which is what lets two shapes share a file.

**A spot is not a QSO and never enters the contact log.** Nothing about a
beacon reception is a two-way contact, and putting them in the file that
feeds an ADIF export would be wrong in the one direction that matters.
"""

import os

import qsolog

RX = "rx"
TX = "tx"

#: The order a line is written in: what identifies the record, then the
#: session, then the radio, then this station, then the other station. Chosen
#: so a line scanned by eye over SSH reads left to right from "what is this"
#: to "what was heard".
FIELD_ORDER = (
    "kind", "when",
    "activity", "activity_start",
    "band", "freq", "mode",
    "my_call", "my_grid", "my_rig", "my_antenna", "my_dbm", "tx_power",
    "call", "grid", "dbm", "snr", "dt", "drift",
)

#: Every record carries these or it is not a record.
_REQUIRED = ("kind", "when")

DEFAULT_NAME = "wspr.log"


def log_path(configured=""):
    """Where the spot log lives. Beside the contact log, not inside it."""
    if configured:
        return os.path.expanduser(str(configured))
    return os.path.join(os.path.dirname(qsolog.log_path("")) or ".",
                        DEFAULT_NAME)


def _station(my_call="", my_grid="", my_rig="", my_antenna=""):
    return {"my_call": str(my_call or "").upper(),
            "my_grid": str(my_grid or ""),
            "my_rig": str(my_rig or ""),
            "my_antenna": str(my_antenna or "")}


def rx_record(spot, when, band="", dial_hz=0, activity="", activity_start="",
              my_call="", my_grid="", my_rig="", my_antenna=""):
    """A station heard, as a record. `spot` is `wspr.parse_decode` output.

    `freq` is where the OTHER station was found, in hertz, following the
    contact log's `HERTZ_FIELDS` convention — one unit for frequency
    everywhere on the deck. The dial is not stored: it is implied by the
    band, and storing both invites them to disagree.

    `band` is passed in rather than derived from the frequency, because §8 of
    the design records the capture's band at capture time: a decode cannot be
    assumed to know what band its audio came from, and band hopping makes
    that a real distinction rather than a pedantic one.
    """
    rec = {"kind": RX, "when": str(when), "mode": "WSPR2", "band": str(band)}
    rec.update(_station(my_call, my_grid, my_rig, my_antenna))
    if activity:
        rec["activity"] = str(activity)
        if activity_start:
            rec["activity_start"] = str(activity_start)
    rec["call"] = str(spot.get("call", "")).upper()
    if spot.get("grid"):
        rec["grid"] = str(spot["grid"])
    for src, key in (("dbm", "dbm"), ("snr", "snr"), ("drift", "drift")):
        if spot.get(src) is not None:
            rec[key] = str(spot[src])
    if spot.get("dt") is not None:
        rec["dt"] = f"{float(spot['dt']):.1f}"
    if spot.get("freq"):
        rec["freq"] = str(int(spot["freq"]))
    return {k: v for k, v in rec.items() if v != ""}


def tx_record(when, band="", dial_hz=0, my_dbm=None, tx_power=None,
              activity="", activity_start="", my_call="", my_grid="",
              my_rig="", my_antenna=""):
    """A beacon sent, as a record.

    **`my_dbm` and `tx_power` are both kept and are not the same number.**
    One is what the beacon announced, snapped to a value WSPR can carry; the
    other is what the radio was actually making. 3 W announces 33 dBm, which
    is 2 W. Keeping both is what makes that discrepancy visible afterwards
    instead of being quietly rounded away.

    `freq` here is the DIAL, because that is where the transmission was:
    this station's own signal sits a known 1500 Hz above it and recording
    the sum would be recording an inference.
    """
    rec = {"kind": TX, "when": str(when), "mode": "WSPR2", "band": str(band)}
    rec.update(_station(my_call, my_grid, my_rig, my_antenna))
    if activity:
        rec["activity"] = str(activity)
        if activity_start:
            rec["activity_start"] = str(activity_start)
    if dial_hz:
        rec["freq"] = str(int(dial_hz))
    if my_dbm is not None:
        rec["my_dbm"] = str(my_dbm)
    if tx_power not in (None, ""):
        rec["tx_power"] = str(tx_power)
    return {k: v for k, v in rec.items() if v != ""}


def format_record(rec):
    """One line of the spot log."""
    return qsolog.format_line(rec, FIELD_ORDER)


def read(path):
    """Every record in the spot log, oldest first.

    Kept when it has a `kind` and a `when` — not a callsign, because a
    transmission has no other station's call in it and `qsolog.read`'s
    predicate would discard every beacon this deck ever sent.
    """
    return qsolog.read_lines(
        path, keep=lambda r: all(r.get(k) for k in _REQUIRED))


def append(path, rec):
    """Add one record. Returns it.

    Append rather than rewrite: a slot's spots arrive while the next capture
    is already running, and the whole-file replace that corrections use
    (`qsolog._rewrite`) is the wrong shape for something that happens every
    two minutes.
    """
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(format_record(rec) + "\n")
    return rec


def append_spots(path, spots, **common):
    """Every spot of one window, as records. Returns them.

    Deduplicated first, because a window can decode the same transmission
    twice and `wspr.dedupe` is where that is decided — logging both would
    put a station in the log twice for one two-minute slot.
    """
    import wspr
    out = []
    for spot in wspr.dedupe(spots):
        out.append(append(path, rx_record(spot, **common)))
    return out


def session_of(rec):
    """`(activity, activity_start)` — the session a record belongs to."""
    return (str(rec.get("activity", "") or ""),
            str(rec.get("activity_start", "") or ""))


def for_session(records, activity, start=""):
    """The records of one session, in the order given.

    An empty `start` with a name means every record of that name whatever its
    start, which is what a hand-written line needs and what an operator means
    by "show me this session".
    """
    want, want_start = str(activity or ""), str(start or "")
    out = []
    for rec in records:
        name, began = session_of(rec)
        if name != want:
            continue
        if want_start and began != want_start:
            continue
        out.append(rec)
    return out


def sessions_in(records, forgotten=()):
    """Every session in the log, newest first by its last record.

    `[{"name", "start", "rig", "antenna", "grid", "bands", "heard", "sent",
    "last"}, ...]`. Derived, not stored.

    **The station attributes are the NEWEST record's**, as §7i resolves a
    contact log session's schema: an antenna changed halfway through a night
    is a fact in the file, and the question "what is this session using" is
    answered by the most recent evidence. The grid is here and not only a
    station setting because it is the attribute that changes when the station
    moves, and every distance computed from these spots depends on it.
    """
    skip = {(str(n), str(s)) for n, s in (forgotten or ())}
    seen = {}
    for rec in records:
        name, start = session_of(rec)
        if not name or (name, start) in skip:
            continue
        key = (name, start)
        entry = seen.setdefault(key, {
            "name": name, "start": start, "rig": "", "antenna": "",
            "grid": "", "bands": [], "heard": 0, "sent": 0, "last": ""})
        if rec.get("kind") == TX:
            entry["sent"] += 1
        else:
            entry["heard"] += 1
        band = str(rec.get("band", "") or "")
        if band and band not in entry["bands"]:
            entry["bands"].append(band)
        when = str(rec.get("when", "") or "")
        if when >= entry["last"]:
            entry["last"] = when
            for field, key_name in (("my_rig", "rig"),
                                    ("my_antenna", "antenna"),
                                    ("my_grid", "grid")):
                if rec.get(field):
                    entry[key_name] = str(rec[field])
    return sorted(seen.values(), key=lambda e: e["last"], reverse=True)


def counts(records, activity="", start=""):
    """`(heard, sent)` for a session, or for the whole log when unnamed.

    What the danger zone's confirmations say, because "473 records" hides
    which — an operator about to lose a night of received data cares about a
    different number than one clearing their own transmission history.
    """
    chosen = for_session(records, activity, start) if activity else records
    sent = sum(1 for r in chosen if r.get("kind") == TX)
    return len(chosen) - sent, sent


def remove_session(path, activity, start=""):
    """Delete one session's records. Returns how many went."""
    records = read(path)
    doomed = for_session(records, activity, start)
    keep = [r for r in records if r not in doomed]
    gone = len(records) - len(keep)
    if gone:
        qsolog._rewrite(path, keep)
    return gone


def clear(path):
    """Delete every record. Returns how many went.

    The file is left in place and empty rather than removed, so whatever
    created it — a directory, a permission, a symlink an operator put there
    on purpose — survives being emptied.
    """
    gone = len(read(path))
    qsolog._rewrite(path, [])
    return gone
