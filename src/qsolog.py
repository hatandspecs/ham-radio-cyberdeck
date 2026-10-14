"""The contact log: parsing, records, bands, and ADIF.

Deliberately free of curses, fldigi, rigctld and the clock, for the same
reason session.py is: the behavior that matters can then be tested without a
terminal, a modem or a radio. Everything here takes values in and returns
values out. The interface in cyberdeck.py supplies the frequency, the mode and
the instant; this module decides what they mean and how they are written down.

See docs/qso_log_design.md. The governing requirement is that a deck with
logging switched off is indistinguishable from one that never had it, which is
why nothing in this module opens a file, reads a setting or has state of its
own. A caller that never calls it leaves no trace.
"""

import os
import re

# ADIF band edges, in Hz. Upper bounds are inclusive. The gaps between entries
# are real: a frequency that falls in one is not on a band and `band_for`
# returns "" rather than guessing at the nearest.
#
# WARC bands are present because this is a general log, not a contest log —
# 30, 17 and 12 m are perfectly good places to have a QSO and the only reason
# to flag them is a contest rule. See §9 of the design doc.
BANDS = (
    ("2190m",    135_700,     137_800),
    ("630m",     472_000,     479_000),
    ("160m",   1_800_000,   2_000_000),
    ("80m",    3_500_000,   4_000_000),
    ("60m",    5_060_000,   5_450_000),
    ("40m",    7_000_000,   7_300_000),
    ("30m",   10_100_000,  10_150_000),
    ("20m",   14_000_000,  14_350_000),
    ("17m",   18_068_000,  18_168_000),
    ("15m",   21_000_000,  21_450_000),
    ("12m",   24_890_000,  24_990_000),
    ("10m",   28_000_000,  29_700_000),
    ("6m",    50_000_000,  54_000_000),
    ("4m",    70_000_000,  71_000_000),
    ("2m",   144_000_000, 148_000_000),
    ("1.25m",222_000_000, 225_000_000),
    ("70cm", 420_000_000, 450_000_000),
)

# fldigi's modem names are not ADIF mode names, and the mapping is many-to-one:
# every PSK variant is ADIF `PSK`, with the particular one belonging in
# SUBMODE. Matching is on a prefix of the upper-cased name so BPSK31, BPSK63
# and PSK125R all land on PSK without enumerating fldigi's whole modem list.
_MODE_PREFIXES = (
    ("OLIVIA", "OLIVIA"),
    ("CONTESTIA", "CONTESTIA"),
    ("RTTY", "RTTY"),
    ("THOR", "THOR"),
    ("THROB", "THRB"),
    ("MFSK", "MFSK"),
    ("DOMINOEX", "DOMINO"),
    ("DOMINO", "DOMINO"),
    ("BPSK", "PSK"),
    ("QPSK", "PSK"),
    ("8PSK", "PSK"),
    ("PSK", "PSK"),
    ("FSQ", "FSQCALL"),
    ("IFKP", "IFKP"),
    ("FELDHELL", "HELL"),
    ("HELL", "HELL"),
    ("CW", "CW"),
    ("MT63", "MT63"),
    ("NAVTEX", "RTTY"),
)

# What the rig itself reports, for voice. These are modes in their own right
# rather than carriers for something else.
_RIG_MODES = {
    "USB": "SSB",
    "LSB": "SSB",
    "SSB": "SSB",
    "AM": "AM",
    "FM": "FM",
    "FMN": "FM",
    "WFM": "FM",
    "CW": "CW",
    "CWR": "CW",
}

# A report is three digits for CW and digital, two for voice, optionally with a
# trailing letter some operators add. Anything else in that position is not a
# report and is treated as the start of the name — which is how `W3ABC Bob`
# works without a separate syntax.
_REPORT = re.compile(r"^\d{2,3}[A-Za-z]?$")

# A POTA park reference, following ADIF 3.1.4's POTARef type exactly:
# `xxxx-nnnnn[@yyyyyy]` — a 1-4 character national program, a hyphen, a 4-5
# digit number, and an optional ISO 3166-2 subdivision after an `@` for a park
# that spans more than one. `US-1234`, `K-0001` (the legacy form, still heard)
# and `US-4578@US-MD` are all valid.
#
# The earlier version of this allowed three-digit numbers and only three
# program characters, which contradicted both its own comment and the spec.
# Tightening the digits to 4-5 also makes it *less* likely to swallow
# something that is not a park.
_PARK = re.compile(r"^[A-Z0-9]{1,4}-\d{4,5}(@[A-Z0-9]{2}-[A-Z0-9]{1,3})?$")

# Deliberately permissive. A callsign validator strict enough to be correct
# rejects real calls, and the cost of accepting a typo is a line that can be
# edited over SSH, while the cost of rejecting a real call is a lost contact
# while the other station is still there. One digit, some letters, optionally a
# stroke suffix.
_CALL = re.compile(r"^[A-Z0-9]{1,3}[0-9][A-Z0-9]*(/[A-Z0-9]+)*$")

# Hamlib mode strings that can only mean data. A rig in one of these is being
# driven by fldigi and nothing else, so the emission is whatever modem fldigi
# has up. Plain USB and LSB are NOT here: on this station the rig sits in USB
# for both voice and digital, which is the whole reason `resolve_mode` needs a
# second input.
# The rig modes digital work can use. Public, because the transmit interlock
# in cyberdeck.py asks the same question this module asks when deciding where
# a logged mode came from, and two lists would drift.
RIG_DATA_MODES = frozenset((
    "PKTUSB", "PKTLSB", "PKTFM", "PKT", "DATA", "DATA-U", "DATA-L",
    "DIGU", "DIGL", "RTTY", "RTTYR", "FSK", "USB-D", "LSB-D",
))

# How the operator is working, which decides where the mode comes from.
OPERATING_AUTO = "auto"        # infer, per resolve_mode
OPERATING_DIGITAL = "digital"  # the deck is the terminal; fldigi says the mode
OPERATING_VOICE = "voice"      # the deck is a logbook beside a microphone

OPERATING = (OPERATING_AUTO, OPERATING_DIGITAL, OPERATING_VOICE)


def resolve_mode(operating=OPERATING_AUTO, rig_mode="", fldigi_modem="",
                 fldigi_active=False):
    """Which ADIF mode to log, and where it came from. -> (mode, source)

    The rule the station wants: **on digital, fill the mode in from the deck;
    on SSB, do not.** fldigi always has a modem loaded whether or not it is
    being used, so "what modem is up" is not the same question as "what are we
    working", and taking fldigi's answer during a voice contact logs a 40-meter
    ragchew as BPSK31.

    Three inputs decide it:

      * `rig_mode`   hamlib's string from `rigctld_client.mode()`. A data mode
                     here is conclusive; `USB` is not, because this rig reports
                     `USB` for both.
      * `fldigi_modem` fldigi's current modem name. Present almost always.
      * `fldigi_active` whether the deck has actually passed traffic recently.
                     This is the discriminator `rig_mode` cannot provide, and
                     it is the deck's own knowledge — it knows when it last
                     sent or received a character.

    `source` is returned so the interface can say where a mode came from
    rather than presenting a guess as a reading: "fldigi", "rig", or
    "default".
    """
    operating = (operating or OPERATING_AUTO).lower()
    rig = (rig_mode or "").strip().upper()
    rig_adif = adif_mode(rig) if rig else ""

    def from_fldigi():
        if fldigi_modem:
            return adif_mode(fldigi_modem), "fldigi"
        return (rig_adif, "rig") if rig_adif else ("", "")

    # A rig data mode says "something digital is happening" and nothing about
    # which emission. `PKTUSB` is a hamlib string, not an ADIF mode, and
    # writing it into MODE produces a record LoTW will not take. So a data
    # mode is never used as the answer — only as evidence that fldigi's is.
    if rig in RIG_DATA_MODES:
        rig_adif = ""

    if operating == OPERATING_VOICE:
        # Never fldigi, whatever it has loaded. A voice mode from the rig is
        # believed; anything else falls back to SSB rather than logging a
        # digital mode for a contact made with a microphone.
        if rig_adif in ("SSB", "AM", "FM"):
            return rig_adif, "rig"
        return "SSB", "default"

    if operating == OPERATING_DIGITAL:
        mode, source = from_fldigi()
        return (mode, source) if mode else ("SSB", "default")

    # auto
    if rig in RIG_DATA_MODES or fldigi_active:
        mode, source = from_fldigi()
        if mode:
            return mode, source
    if rig_adif in ("SSB", "AM", "FM"):
        return rig_adif, "rig"
    if rig_adif:                       # CW from the rig is conclusive too
        return rig_adif, "rig"
    mode, source = from_fldigi()
    return (mode, source) if mode else ("SSB", "default")


DEFAULT_REPORTS = {
    "SSB": "59",
    "AM": "59",
    "FM": "59",
}
DEFAULT_REPORT_DIGITAL = "599"


def band_for(freq_hz):
    """The ADIF band name containing a frequency, or "" if it is not on one.

    An unknown frequency is "" rather than an exception: rigctld being
    unreachable is an ordinary condition and the record still commits.
    """
    if not freq_hz:
        return ""
    try:
        hz = int(freq_hz)
    except (TypeError, ValueError):
        return ""
    for name, low, high in BANDS:
        if low <= hz <= high:
            return name
    return ""


def adif_mode(name):
    """An ADIF mode from whatever fldigi or the rig called it.

    Unknown names come back upper-cased and stripped rather than empty. ADIF
    readers tolerate a mode they do not know; they do not tolerate a missing
    one, and an unrecognized modem is still a QSO that happened.
    """
    if not name:
        return ""
    up = str(name).strip().upper()
    if up in _RIG_MODES:
        return _RIG_MODES[up]
    for prefix, mode in _MODE_PREFIXES:
        if up.startswith(prefix):
            return mode
    return re.sub(r"[^A-Z0-9]", "", up)


def default_report(mode):
    """The report to assume when the operator did not type one."""
    return DEFAULT_REPORTS.get(adif_mode(mode), DEFAULT_REPORT_DIGITAL)


def is_callsign(text):
    return bool(_CALL.match(str(text).strip().upper()))


def is_park(text):
    """A POTA reference, e.g. US-1234, K-0001 or US-4578@US-MD.

    ADIF 3.1.4's POTARef grammar. Shape alone identifies it in a log line,
    which is why the entry syntax needs no separate field.
    """
    return bool(_PARK.match(str(text).strip().upper()))


class ParseError(ValueError):
    """Malformed input. The message is shown to the operator as a `--` line,
    so it is written for a person mid-QSO, not for a log file."""


def parse_entry(text, mode="", activity=None):
    """Parse a typed log line into the fields the operator supplied.

    Positional and forgiving, because this is typed while somebody waits. The
    **activity decides the positions** (`activities.py`): its `entry` list is
    the grammar after the callsign. With the default general activity:

        W3ABC                       call only
        W3ABC 57                    received report
        W3ABC 59 57                 sent and received
        W3ABC 59 57 Bob Pittsburgh  and a name, and the rest as QTH
        W3ABC 59 57 ; 5W to a wire  anything after ; is a free comment

    With a QSO party activity whose grammar is `serial_rx, exchange_rx`:

        W3ABC 123 MONT              serial 123, exchange MONT, reports default

    The same line shape means different things, which is the whole reason the
    grammar is per-activity: `599` is a valid report *and* a valid serial, and
    nothing about the token says which. The operator already chose an activity,
    so the ambiguity is resolved before it arises.

    Returns a dict with call, rst_s, rst_r, name, qth, park, serial_rx,
    exchange_rx and comment. Reports absent from the input are filled from the
    mode. Raises ParseError with a message fit to show, never a silent drop.
    """
    import activities as _act
    act = activity if activity is not None else _act.GENERAL
    # Everything after a semicolon is a free-text comment and is not parsed.
    # A general log needs somewhere to put "running 5 W to a wire" or "first
    # one from this county", and no positional scheme can tell that from a
    # QTH. One unambiguous separator is cheaper than a second field to tab
    # into, and nothing else in a log line contains a semicolon.
    body, _, comment = str(text).partition(";")

    words = body.strip().split()
    if not words:
        raise ParseError("nothing to log")

    call = words[0].upper()
    if not is_callsign(call):
        raise ParseError(f"{call} does not look like a callsign")

    rest = words[1:]

    # A park reference is pulled out by SHAPE, before anything positional, and
    # in every activity. `W3ABC 59 57 US-1234` and `W3ABC 59 57 Bob US-1234`
    # are both natural depending on whether the name was caught, and the shape
    # is unmistakable, so position does not have to carry it. It also means
    # working one park in an afternoon needs no activity change.
    park = ""
    for i, word in enumerate(rest):
        if is_park(word):
            park = rest.pop(i).upper()
            break

    grammar = [f for f in act.entry if f != "park"]
    out = {"name": "", "qth": "", "serial_rx": "", "exchange_rx": ""}

    # Reports come off the front as a block rather than one slot at a time, so
    # that the "one report is the received one" rule still works. An activity
    # that does not list them — a QSO party, where they are 59 every time —
    # gets the mode's default and leaves the numeric slot free for the serial.
    fallback = default_report(mode)
    want_reports = [f for f in grammar if f in ("rst_s", "rst_r")]
    reports = []
    while rest and len(reports) < len(want_reports) and _REPORT.match(rest[0]):
        reports.append(rest.pop(0))

    if not want_reports:
        rst_s = rst_r = fallback
    elif len(reports) == 0:
        rst_s = rst_r = fallback
    elif len(reports) == 1:
        # One report is the one that was *received*. The sent report is what
        # the operator already said out loud and is not news; the received one
        # is what has to be written down.
        if want_reports == ["rst_s"]:
            rst_s, rst_r = reports[0], fallback
        else:
            rst_s, rst_r = fallback, reports[0]
    else:
        rst_s, rst_r = reports[0], reports[1]

    # Everything else in the order the activity declared. A text field takes
    # one token, except in the last position where it absorbs the rest — which
    # is how "1B EPA" is one Field Day exchange while `name qth` still splits.
    tail = [f for f in grammar if f not in ("rst_s", "rst_r")]
    for pos, field in enumerate(tail):
        if not rest:
            break
        kind = _act.ENTRY_FIELDS.get(field, (_act.TEXT, field))[0]
        last = pos == len(tail) - 1
        if kind == _act.NUMBER:
            # Only consume it if it is actually a number. A missed serial must
            # not silently eat the exchange and shift every field after it.
            if rest[0].lstrip("0").isdigit() or rest[0].isdigit():
                out[field] = str(int(rest.pop(0)))
        elif last:
            out[field] = " ".join(rest)
            rest = []
        else:
            out[field] = rest.pop(0)

    return {
        "call": call,
        "rst_s": rst_s.upper(),
        "rst_r": rst_r.upper(),
        "name": out["name"],
        "qth": out["qth"],
        "park": park,
        "serial_rx": out["serial_rx"],
        "exchange_rx": out["exchange_rx"],
        "comment": comment.strip(),
    }


# How a contact counts as already worked. Five rules, because which one is
# right is a property of the event and not of the logger: a QSO party scores
# once per band, Field Day once per band and mode, a POTA activation not at
# all, and a casual operator may just want to know they have met before.
DUPE_OFF = "off"
DUPE_CALL = "call"
DUPE_BAND = "band"
DUPE_MODE = "mode"
DUPE_BAND_MODE = "band+mode"

DUPE_RULES = (DUPE_OFF, DUPE_CALL, DUPE_BAND, DUPE_MODE, DUPE_BAND_MODE)

DUPE_LABELS = {
    DUPE_OFF: "off — never say",
    DUPE_CALL: "any band, any mode",
    DUPE_BAND: "same band",
    DUPE_MODE: "same mode",
    DUPE_BAND_MODE: "same band and mode",
}


def find_dupes(records, call, band="", mode="", rule=DUPE_BAND_MODE,
               activity=""):
    """Earlier contacts with this station that count as duplicates.

    Returns them oldest first, so the caller can say when the first one was
    and how many there have been. Empty when the rule is `off`, when the call
    is blank, or when nothing matches.

    **A missing band or mode never matches.** Logging with the radio
    unreachable leaves them empty, and treating empty-equals-empty as a match
    would make every such contact a duplicate of every other. The rule asks
    about a band; a record with no band cannot answer it.

    Scoped to an activity when one is given, because working the same station
    in last weekend's QSO party is not a duplicate in this one.
    """
    call = str(call or "").strip().upper()
    if not call or rule == DUPE_OFF or rule not in DUPE_RULES:
        return []

    want_band = str(band or "").strip().lower()
    want_mode = str(mode or "").strip().upper()
    want_activity = str(activity or "").strip().upper()

    out = []
    for rec in records:
        if str(rec.get("call", "")).strip().upper() != call:
            continue
        if want_activity and \
                str(rec.get("activity", "")).strip().upper() != want_activity:
            continue
        if rule in (DUPE_BAND, DUPE_BAND_MODE):
            theirs = str(rec.get("band", "")).strip().lower()
            if not theirs or not want_band or theirs != want_band:
                continue
        if rule in (DUPE_MODE, DUPE_BAND_MODE):
            theirs = str(rec.get("mode", "")).strip().upper()
            if not theirs or not want_mode or theirs != want_mode:
                continue
        out.append(rec)
    return out


def dupe_note(matches):
    """A one-line way to say it, or "" for no duplicates.

    Says when the last one was and on what, because "worked before" is not
    actionable and "worked 20m SSB at 18:31" is — it is enough to decide
    whether to log it anyway.
    """
    if not matches:
        return ""
    last = matches[-1]
    when = str(last.get("when", ""))[11:16]
    where = " ".join(p for p in (last.get("band", ""), last.get("mode", ""))
                     if p)
    times = f" ({len(matches)}x)" if len(matches) > 1 else ""
    tail = f" {where}" if where else ""
    return f"{last.get('call', '')} worked{tail} at {when}{times}".strip()


def activity_slug(name):
    """A filename stem for an activity name, or "" if nothing is left.

    The operator types what the event is called -- "Bald Eagle SP", "PAQP
    2026" -- and that has to become a filename without surprising them. Case
    is kept, because a log named BaldEagle-SP.log is recognizable in a
    directory listing and baldeagle-sp.log is less so; everything that is not
    a letter, a digit, a dot, a dash or an underscore becomes a dash, and runs
    of dashes collapse.
    """
    out = []
    for ch in str(name or "").strip():
        out.append(ch if (ch.isalnum() or ch in "._-") else "-")
    slug = "".join(out).strip("-.")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug


# An activity's file is <slug>_<YYYY-MM-DD>.log. The date is stamped ONCE,
# when the activity is created, from the deck's clock -- which is backed by a
# DS3231 and is right with no network, so this works at a picnic table.
#
# It is deliberately not re-derived afterwards. A contest weekend is one
# activity across two UTC days, Field Day crosses UTC midnight, and an evening
# POTA activation in EDT starts after 00:00Z. Recomputing "name + today" each
# time the activity was opened would put Sunday's contacts in a second file
# and fork the very thing the date is meant to keep distinct. The path is
# stored with the activity instead; see cyberdeck._set_activity_session.
#
# The same name on a LATER day is a different activation and gets its own
# file. The same name on the SAME day is the same activation resumed after a
# break, and appends.
_ACTIVITY_DATE = re.compile(r"^(?P<slug>.+)_(?P<date>\d{4}-\d{2}-\d{2})$")


def activity_dir(base=""):
    """The directory an activity's own logs live in, beside the default log."""
    return os.path.join(os.path.dirname(log_path(base)), "activities")


def activity_log_path(activity, base="", date=""):
    """The log file for one activity, dated. `base` is the default log path.

    Each activity gets its own file, so a park activation and a contest
    weekend are separate files that can be exported, mailed and uploaded one
    at a time with nothing filtered out of them first.

    No activity means the default log: casual contacts are not an event and
    do not deserve a file named after one.

    `date` is the stamp to use, YYYY-MM-DD; today in UTC when not given. Pass
    it explicitly to reproduce a path that was created earlier.
    """
    base = log_path(base)
    slug = activity_slug(activity)
    if not slug:
        return base
    stamp = str(date or "").strip() or _utc_today()
    return os.path.join(activity_dir(base), f"{slug}_{stamp}.log")


def _utc_today():
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")


def split_activity_stem(stem):
    """(name, date) from an activity log's filename stem, date possibly "".

    The name comes back with dashes turned to spaces, so an activity typed as
    "Bald Eagle SP" and stored as Bald-Eagle-SP_2026-10-11 is offered for
    resuming as "Bald Eagle SP" rather than as its filename.
    """
    m = _ACTIVITY_DATE.match(str(stem or "").strip())
    if not m:
        return str(stem or "").replace("-", " ").strip(), ""
    return m.group("slug").replace("-", " ").strip(), m.group("date")


def activity_logs(base=""):
    """Every activity log on disk, newest first.

    Each entry is {name, date, path, contacts}. Listed from the directory
    rather than from a register kept beside it, for the reason serials are
    read from the log: a list of what happened cannot drift from what
    happened, and nothing has to be written to keep it true.
    """
    directory = activity_dir(base)
    out = []
    try:
        names = os.listdir(directory)
    except OSError:
        return out
    for entry in names:
        if not entry.endswith(".log"):
            continue
        path = os.path.join(directory, entry)
        name, date = split_activity_stem(entry[:-len(".log")])
        if not name:
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                contacts = sum(1 for line in fh if line.strip())
        except OSError:
            contacts = 0
        out.append({"name": name, "date": date, "path": path,
                    "contacts": contacts})
    # By date then name, newest first. An activity with no date in its
    # filename sorts last, which is where a file nobody recognizes belongs.
    return sorted(out, key=lambda e: (e["date"], e["name"]), reverse=True)


def resolve_activity_log(activity, base=""):
    """The file an activity should be appended to right now.

    The newest existing file for that name if there is one, and today's
    otherwise. For callers with nowhere to store the path they were given --
    `tools/qso.py` runs once and exits, so it cannot remember anything.

    Resuming the newest rather than stamping today is what keeps a multi-day
    activity in one file: a contest that began on Saturday is still the same
    contest when a contact is logged on Sunday. The deck stores the path
    instead, which is stronger, and uses this only as a fallback for an
    activity named in cyberdeck.conf that it has never opened.
    """
    slug = activity_slug(activity)
    if not slug:
        return log_path(base)
    want = slug.strip().upper()
    existing = [e for e in activity_logs(base)
                if activity_slug(e["name"]).strip().upper() == want]
    if existing:
        return existing[0]["path"]
    return activity_log_path(activity, base)


def export_path(log_file):
    """The ADIF file for a log file: same directory, same stem, .adi.

    The log is append-only `key=value` text and the export is ADIF; naming
    the log `.adi` would make the file that is not ADIF look like the one
    that is.
    """
    return os.path.splitext(str(log_file))[0] + ".adi"


def parse_freq(text):
    """Hertz from whatever an operator or a screen put in a frequency field.

    The log screen shows the radio's full resolution -- 7.185.000, the same
    grouping `render.frequency` uses and the same thing the radio's own
    display reads -- because rounding to three decimals throws away the part
    that matters inside a 31 Hz-wide signal.

    That means the field holds a string `float()` cannot read, so all the
    spellings an operator might reasonably type are accepted:

        "7.185.000"  -> 7185000   megahertz.kilohertz.hertz
        "7.185"      -> 7185000   megahertz, as typed on the air
        "7.1853"     -> 7185300   megahertz, more precisely
        "7185000"    -> 7185000   hertz, because nobody means 7 MHz by it
        "7"          -> 7000000   megahertz

    Returns 0 for anything unreadable, which is what an absent frequency is.
    """
    raw = str(text or "").strip().replace(" ", "")
    if not raw:
        return 0
    try:
        if raw.count(".") >= 2:
            mhz, khz, hz = (raw.split(".") + ["0", "0"])[:3]
            return (int(mhz or 0) * 1_000_000 + int((khz or "0").ljust(3, "0"))
                    * 1_000 + int((hz or "0").ljust(3, "0")))
        value = float(raw)
    except (TypeError, ValueError):
        return 0
    # No dot and big enough that megahertz would be absurd: it is hertz.
    if "." not in raw and value >= 1000:
        return int(round(value))
    return int(round(value * 1_000_000))


# The built-in type names, for reading a record written before an activity
# and an activity type were different things.
_LEGACY_TYPES = frozenset(("GENERAL", "POTA", "CONTEST"))


def for_activity(records, activity):
    """The contacts of one named activity. Oldest first, as given.

    Each activity gets its own log file, so this is rarely what separates
    them -- the file does. It stays because a file can hold more than one:
    the log in use before activities were named, and any log an operator
    points two activities at on purpose.

    An empty `activity` means the contacts belonging to no named activity,
    not every contact.
    """
    want = (activity or "").strip().upper()
    out = []
    for rec in records:
        name, _kind = activity_of(rec)
        if name.strip().upper() == want:
            out.append(rec)
    return out


def activities_in(records):
    """Every activity named in a log, newest first by last contact.

    Derived from the log rather than kept in a list beside it, for the reason
    serials are: a file that records what happened cannot drift from what
    happened, and a power cut cannot lose it.
    """
    seen = {}
    for rec in records:
        name, kind = activity_of(rec)
        if not name:
            continue
        entry = seen.setdefault(name, {"name": name, "type": kind,
                                       "count": 0, "last": ""})
        entry["count"] += 1
        when = str(rec.get("when", "") or "")
        if when > entry["last"]:
            entry["last"] = when
        if kind and not entry["type"]:
            entry["type"] = kind
    return sorted(seen.values(), key=lambda e: e["last"], reverse=True)


def next_serial(records, activity="", start=1):
    """The serial to send on the next contact of an event.

    Derived from the log rather than kept in a state file, deliberately. The
    log is the append-only record that survives a power pull; a counter in a
    separate file is a second source of truth that can disagree with it, and
    the failure mode — sending a serial already sent, or skipping twenty — is
    one nobody notices until the log is checked.

    Scoped to the activity, so a QSO party on Saturday and another on Sunday
    each count from their own start.
    """
    want = str(activity or "").strip().upper()
    highest = 0
    for rec in records:
        if want and activity_of(rec)[0].strip().upper() != want:
            continue
        try:
            highest = max(highest, int(rec.get("serial_tx") or 0))
        except (TypeError, ValueError):
            continue
    return max(int(start), highest + 1)


def make_record(parsed, when, freq_hz=None, mode="", my_call="", my_grid="",
                my_park="", activity_type=None, activity="", serial_tx="",
                exchange_tx="", my_rig="", my_antenna="", tx_power=0,
                tx_backend=""):
    """Assemble a complete record from a parsed entry and the deck's context.

    `when` is a datetime, which the caller supplies so this module needs no
    clock and the tests need no patching. Everything the file needs to export
    on its own is written into the record, including this station's own call:
    a log that depends on a configuration file to be meaningful is a log that
    stops being meaningful when the configuration changes.
    """
    rec = dict(parsed)
    rec["when"] = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    rec["mode"] = adif_mode(mode)
    if freq_hz:
        rec["freq"] = str(int(freq_hz))
        rec["band"] = band_for(freq_hz)
    rec["my_call"] = str(my_call).upper()
    if my_grid:
        rec["my_grid"] = str(my_grid).upper()
    # Set while activating, blank otherwise. It goes on every QSO of the
    # activation, which is why it is a station setting and not something typed
    # per contact.
    if my_park:
        rec["my_park"] = str(my_park).upper()

    # What this station sent. Not typed per contact: an exchange is the same on
    # every QSO of an event, and a serial increments on its own. Both are
    # written into the record anyway, because an exported log has to say what
    # was sent without the configuration that was in force at the time.
    if serial_tx not in ("", None):
        rec["serial_tx"] = str(serial_tx)
    if exchange_tx:
        rec["exchange_tx"] = str(exchange_tx).upper()

    # The station itself, on every contact of every activity. Rig and antenna
    # come from the station settings; power prefers an actual CAT reading and
    # falls back to the configured wattage, because what was logged should be
    # what the radio was doing rather than what the configuration hoped.
    if my_rig:
        rec["my_rig"] = str(my_rig)
    if my_antenna:
        rec["my_antenna"] = str(my_antenna)
    if tx_power:
        # NOT int(). This radio goes to 0.5 W, and int() would log every
        # sub-watt QRP contact as 0 and drop the field entirely. ADIF's
        # TX_PWR is a Number, so a fraction is valid; the integer form is
        # kept where there is no fraction, because "6.0" in a log is noise.
        try:
            watts = round(float(tx_power), 2)
        except (TypeError, ValueError):
            watts = 0
        if watts > 0:
            rec["tx_power"] = (str(int(watts)) if watts == int(watts)
                               else str(watts))
    # Which back end produced that power, when the radio says. The wattage
    # alone does not distinguish 5 W from the field head from 5 W through the
    # amplifier, and it cannot be reconstructed afterwards. Kept in the local
    # log only: MY_RIG stays exactly what the Station menu says, because that
    # is where the operator asked for it to come from.
    if tx_backend:
        rec["tx_backend"] = str(tx_backend)

    # An ACTIVITY is the operating session -- a park activation, one weekend
    # of a QSO party -- and is named by the operator. An ACTIVITY TYPE is the
    # template it uses. Both are recorded: the name is what a log is filtered
    # back to, and the type is what says how to read the fields in it.
    #
    # These were one field holding the type name. A record written then has
    # `activity=CONTEST` and no `activity_type`; `activity_of` reads it as a
    # session called CONTEST that used the CONTEST type, which is both true
    # and the only reading that loses nothing.
    if activity:
        rec["activity"] = str(activity)
    type_name = getattr(activity_type, "name", "") or ""
    if type_name and type_name != "GENERAL":
        rec["activity_type"] = type_name
        if activity_type.contest_id:
            rec["contest_id"] = activity_type.contest_id
    return {k: v for k, v in rec.items() if v != ""}


def activity_of(rec):
    """(activity name, activity type name) for one record.

    Either may be empty: a contact made outside any named activity has no
    name, and one using general logging has no type worth storing.

    A record from before the split carries the TYPE in `activity` and no
    `activity_type`. It is read as a session of that name using that type,
    so an old log still groups and still exports with its contest id.
    """
    name = str(rec.get("activity", "") or "").strip()
    kind = str(rec.get("activity_type", "") or "").strip()
    if name and not kind and name.upper() in _LEGACY_TYPES:
        return name, name.upper()
    return name, kind


# Field order in the stored line. Fixed rather than dict order so a file is
# diffable between versions and a human scanning it finds the same thing in
# the same place on every line.
_FIELD_ORDER = ("when", "call", "freq", "band", "mode",
                "rst_s", "rst_r", "serial_rx", "exchange_rx",
                "park", "name", "qth", "grid",
                "my_call", "my_grid", "my_park",
                "serial_tx", "exchange_tx", "activity", "activity_type",
                "contest_id",
                "my_rig", "my_antenna", "tx_power", "tx_backend", "comment")

_NEEDS_QUOTES = re.compile(r'[\s"]')


def format_record(rec):
    """One line of the log file: space-separated key=value, values quoted only
    when they need it. Quoting everything would be simpler to write and harder
    to read, and this file is meant to be read."""
    out = []
    for key in _FIELD_ORDER:
        if key in rec:
            out.append(f"{key}={_quote(rec[key])}")
    for key in sorted(k for k in rec if k not in _FIELD_ORDER):
        out.append(f"{key}={_quote(rec[key])}")
    return " ".join(out)


def _quote(value):
    s = str(value)
    if not s:
        return '""'
    if _NEEDS_QUOTES.search(s):
        return '"' + s.replace('"', '\\"') + '"'
    return s


def parse_record(line):
    """Read a line back. The inverse of format_record, so the file is the
    record and anything that can read it can regenerate every export."""
    rec = {}
    for key, raw in re.findall(r'([A-Za-z_]+)=("(?:[^"\\]|\\.)*"|\S*)', line):
        if raw.startswith('"'):
            raw = raw[1:-1].replace('\\"', '"')
        rec[key] = raw
    return rec


# -- ADIF ------------------------------------------------------------------
#
# ADIF is length-prefixed: <CALL:5>W3ABC. The length is in characters and is
# not optional, which is why this is generated rather than templated.

_ADIF_FIELDS = (
    ("call", "CALL"),
    ("band", "BAND"),
    ("mode", "MODE"),
    ("rst_s", "RST_SENT"),
    ("rst_r", "RST_RCVD"),
    # Contest and QSO-party exchanges. ADIF splits each into a number and a
    # string: STX/SRX are PositiveInteger for a serial, STX_STRING/SRX_STRING
    # are free text for a class, a county, a section — whatever the event
    # exchanges instead of or alongside a number. Writing the serial into the
    # integer field is what lets a scoring program add them up.
    ("serial_tx", "STX"),
    ("serial_rx", "SRX"),
    ("exchange_tx", "STX_STRING"),
    ("exchange_rx", "SRX_STRING"),
    # CONTEST_ID is an ADIF *enumeration*, so a value not in their table is
    # non-conforming even though it will be written. The activity supplies it
    # and the operator owns getting it right; `qso.py` warns on one that is
    # not a recognizable shape rather than silently emitting it.
    ("contest_id", "CONTEST_ID"),
    ("name", "NAME"),
    ("qth", "QTH"),
    ("grid", "GRIDSQUARE"),
    # The rest of what an activity may ask about the station worked. Each is
    # a standard ADIF field; `activities.ENTRY_FIELDS` is the list an operator
    # picks from, and a field there with no entry here would be typed, shown,
    # logged, and then lost at export.
    ("state", "STATE"),
    # ADIF calls a county a secondary administrative subdivision and expects
    # it spelled the way the ADIF enumeration spells it. It is written as
    # typed: the operator copies what the other station said, and a county
    # silently rewritten is worse in a QSO party than one spelled oddly.
    ("county", "CNTY"),
    ("cq_zone", "CQZ"),
    ("power_rx", "RX_PWR"),
    ("check", "CHECK"),
    ("precedence", "PRECEDENCE"),
    ("comment", "COMMENT"),
    ("my_call", "STATION_CALLSIGN"),
    ("my_grid", "MY_GRIDSQUARE"),
    # This station's own equipment. MY_ANTENNA_INTL is deliberately not used:
    # it is for ADX files only, per the ADIF spec.
    ("my_rig", "MY_RIG"),
    ("my_antenna", "MY_ANTENNA"),
    ("tx_power", "TX_PWR"),
)


def _adif_field(name, value):
    value = str(value)
    return f"<{name}:{len(value)}>{value}"


def adif_record(rec):
    """One ADIF record, ending in <EOR>.

    A field with no value is omitted rather than written empty: an ADIF reader
    treats <BAND:0> as a band it could not understand, where an absent BAND is
    simply unknown. That distinction matters to LoTW.
    """
    parts = []
    when = rec.get("when", "")
    if when:
        date = when[:10].replace("-", "")
        time = when[11:19].replace(":", "")
        parts.append(_adif_field("QSO_DATE", date))
        parts.append(_adif_field("TIME_ON", time))
    if rec.get("freq"):
        # ADIF wants MHz with a decimal point, not Hz.
        mhz = int(rec["freq"]) / 1_000_000.0
        parts.append(_adif_field("FREQ", f"{mhz:.6f}".rstrip("0").rstrip(".")))
    for key, adif in _ADIF_FIELDS:
        if rec.get(key):
            parts.append(_adif_field(adif, rec[key]))
    # Both spellings, deliberately. ADIF 3.1.4 added dedicated POTA_REF and
    # MY_POTA_REF fields; the generic SIG/SIG_INFO pair is what POTA's own
    # upload has always matched on and what older loggers read. Writing only
    # the generic pair means a modern logger (QLog, for one, which has its own
    # POTA field) may not see the park at all; writing only the dedicated pair
    # breaks the pota.app upload. Both is what every current logger does, and
    # ADIF permits it.
    #
    # SIG/SIG_INFO and POTA_REF are the park the OTHER station is in — what a
    # hunter records. The MY_ forms are this station's park,
    # which is what an activator puts on every contact of the activation. Both
    # appear on a park-to-park, which is why they are separate fields and not
    # one with a direction flag.
    if rec.get("park"):
        parts.append(_adif_field("SIG", "POTA"))
        parts.append(_adif_field("SIG_INFO", rec["park"]))
        parts.append(_adif_field("POTA_REF", rec["park"]))
    if rec.get("my_park"):
        parts.append(_adif_field("MY_SIG", "POTA"))
        parts.append(_adif_field("MY_SIG_INFO", rec["my_park"]))
        parts.append(_adif_field("MY_POTA_REF", rec["my_park"]))
    parts.append("<EOR>")
    return " ".join(parts)


def adif_header(created_by="cyberdeck"):
    return (
        "ADIF export from cyberdeck\n"
        f"{_adif_field('ADIF_VER', '3.1.4')}\n"
        f"{_adif_field('PROGRAMID', created_by)}\n"
        "<EOH>\n"
    )


def adif_export(records, created_by="cyberdeck"):
    """A complete ADIF file as a string."""
    body = "\n".join(adif_record(r) for r in records)
    return adif_header(created_by) + body + ("\n" if body else "")


# -- the file ---------------------------------------------------------------
#
# Append-only, one record per line, flushed and fsynced on every commit. The
# deck is expected to lose power without warning; a log that loses the last
# contact is worse than no log, because it is a log you have stopped checking.

DEFAULT_PATH = "~/.local/share/cyberdeck/qso.log"


def log_path(configured=""):
    return os.path.expanduser(configured or DEFAULT_PATH)


def append(path, rec):
    """Add one record. Returns the line written.

    Creates the directory and the file on first use and not before, which is
    what makes "no file exists when logging is off" true rather than aspirational.

    fsync, not just flush. flush moves the bytes out of Python into the kernel;
    only fsync gets them onto the card. Between the two is exactly the window a
    pulled plug lands in, and the deck's whole power story is that the plug
    gets pulled.
    """
    line = format_record(rec)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return line


def read(path):
    """Every record in the file, oldest first.

    A line that cannot be parsed is skipped rather than fatal. The file is
    documented as hand-editable over SSH — that is the recovery path for
    anything the interface gets wrong — and a half-finished edit must not stop
    the log from opening.
    """
    out = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw or raw.startswith("#"):
                    continue
                rec = parse_record(raw)
                if rec.get("call"):
                    out.append(rec)
    except OSError:
        # No file is an empty log, not an error. It is the normal state of a
        # deck that has not logged anything.
        return []
    return out


def count(path):
    return len(read(path))
