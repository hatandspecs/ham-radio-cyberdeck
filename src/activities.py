"""Activity types: what a contact exchanges, and therefore what gets typed.

An activity is a named set of fields. POTA exchanges a park reference; a state
QSO party exchanges a serial number and a county; Field Day exchanges a class
and a section; an ordinary contact exchanges a name and a QTH. Each of those is
the same record with different optional fields filled in, so an activity is
data, not code.

**The field list is the entry grammar.** This is the point of the design. Given

    [PAQP]
    entry = serial_rx, exchange_rx

then `W3ABC 123 MONT` means serial 123, exchange MONT, and the reports default.
Given the general activity's `rst_s, rst_r, name, qth`, the same shape of line
means something else entirely. Without that, a positional parser cannot work:
`599` is a valid report *and* a valid serial number, and no amount of cleverness
tells them apart from the token alone. The activity says which one the operator
is typing, because the operator already knows — they chose the activity.

Two kinds of field, and the distinction matters:

  * **Typed per contact** — what the other station sends. Reports, their serial,
    their exchange, their park, name, QTH. These are the `entry` grammar.
  * **Fixed for the event** — what this station sends. Own park, own exchange
    (a class, a county, a section: the same on every contact of the event), and
    own serial, which is not typed at all because it increments.

Typing one's own exchange eighty times is eighty chances to mistype it, which
is the same reason `my_park` is a setting rather than part of the log line.

Activities are read from `activities.conf` so one can be added without touching
code — the whole point of "set up an activity type with custom fields". The
built-ins below are the defaults and are overridden by any section of the same
name in that file.
"""

import configparser
import os
import re

# Where a field comes from and how it parses. A text field takes one token,
# except in the last position where it absorbs the rest of the line — which is
# how "1B EPA" is one Field Day exchange and how a two-word QTH works in
# general logging, while `name qth` still splits on the first space.
TEXT, NUMBER, REPORT, REF = "text", "number", "report", "ref"

ENTRY_FIELDS = {
    "rst_s":       (REPORT, "Sent"),
    "rst_r":       (REPORT, "Rcvd"),
    "serial_rx":   (NUMBER, "Nr"),
    "exchange_rx": (TEXT,   "Exch"),
    "park":        (REF,    "Ref"),
    "name":        (TEXT,   "Name"),
    "qth":         (TEXT,   "QTH"),
}

# Settings an activity can draw on, each the same for every contact of an event.
STATION_FIELDS = ("my_park", "exchange_tx")


# What each field is, in the operator's words rather than the parser's. Shown
# on the selection screen, where the question is "do I want this one" and
# `exchange_rx` does not answer it.
FIELD_HELP = {
    "rst_s": "report you sent",
    "rst_r": "report they sent",
    "serial_rx": "their serial number",
    "exchange_rx": "their exchange — class, county, section",
    "park": "their park or summit reference",
    "name": "their name",
    "qth": "where they are",
}


def field_choices():
    """Every field an `entry` list may name, with its label and kind.

    This is the menu of possible fields. Returned in a fixed, sensible order
    rather than a dict's order so the chooser on the panel and the listing in
    the documentation agree.
    """
    order = ("rst_s", "rst_r", "serial_rx", "exchange_rx", "park",
             "name", "qth")
    return [(f, ENTRY_FIELDS[f][1], ENTRY_FIELDS[f][0]) for f in order]

DEFAULT_PATH = "~/.config/cyberdeck/activities.conf"


class ActivityError(Exception):
    """A malformed activity definition. Refused at load, not at log time."""


class Activity:
    """One activity type. Immutable once built."""

    def __init__(self, name, label="", entry=(), sig="", contest_id="",
                 serial=False, serial_start=1, labels=None):
        self.name = str(name).upper()
        self.label = label or self.name
        self.entry = tuple(entry)
        self.sig = sig
        self.contest_id = contest_id
        self.serial = bool(serial)
        self.serial_start = int(serial_start)
        self._labels = dict(labels or {})

    def label_for(self, field):
        """The column heading for a field, which an activity may rename.

        A state QSO party's `exchange_rx` is a county; Field Day's is a class
        and section. The field is the same; what to call it on the screen is
        not, and an operator reading a column during an exchange should see the
        word they are listening for.
        """
        if field in self._labels:
            return self._labels[field]
        return ENTRY_FIELDS.get(field, (None, field))[1]

    def wants(self, field):
        return field in self.entry

    def __repr__(self):
        return f"<Activity {self.name} entry={list(self.entry)}>"


# The general activity: what the logger is when no activity is chosen. Its
# grammar is the one the log has always had, so choosing nothing changes
# nothing.
GENERAL = Activity("GENERAL", label="General logging",
                   entry=("rst_s", "rst_r", "name", "qth"))

BUILTIN = {
    "GENERAL": GENERAL,
    # Hunting is typed; this station's own reference is a setting. Reports
    # first, because a park contact is still a signal report.
    "POTA": Activity("POTA", label="Parks on the Air",
                     entry=("rst_s", "rst_r", "park", "name"),
                     sig="POTA", labels={"park": "Park"}),
    # A serial-and-exchange event, both directions. Reports are deliberately
    # NOT in the grammar: in a contest they are 59 every time and typing them
    # is wasted motion, and leaving them out is what frees the numeric slot
    # for the serial. This station's own serial increments; its own exchange
    # is EXCHANGE_TX, because it is the same on every contact.
    "CONTEST": Activity("CONTEST", label="Contest or QSO party",
                        entry=("serial_rx", "exchange_rx"),
                        serial=True, labels={"exchange_rx": "Exchange"}),
}

# Three defaults, and only three. SOTA, WWFF, Field Day, Sweepstakes and the
# state QSO parties are not built in — they are examples in
# activities.conf.example, to be copied and changed. A built-in nobody uses is
# a line in a picker that has to be scrolled past forever; a worked example is
# a starting point. `like = CONTEST` is how one is made.

class FieldPicker:
    """Which fields an activity uses, and in what order. Pure.

    Two operations, because the panel asks two separate questions: *which*
    fields on one screen, and *what order* on another. Splitting them is what
    makes each answerable with one keystroke — a toggle, then a number.

    **Renumbering is remove-and-insert, then renumber 1..N.** Typing 1 on the
    fourth item makes it first and pushes the rest down; typing 4 on the
    second makes it fourth and pulls the rest up. One rule covers both
    directions, and the list always comes back as a clean 1..N with no gaps
    and no duplicates — which is what makes it safe to keep typing numbers at
    it until the order looks right.
    """

    def __init__(self, selected=()):
        self.available = [f for f, _l, _k in field_choices()]
        self.selected = [f for f in selected if f in self.available]

    # -- which ------------------------------------------------------------

    def is_on(self, name):
        return name in self.selected

    def toggle(self, name):
        """Turn a field on or off. Returns its new state.

        A field turned on joins the end of the order rather than its position
        in the catalogue: it was just chosen, so the operator is thinking
        about it, and the ordering screen is one key away.
        """
        if name not in self.available:
            return False
        if name in self.selected:
            self.selected.remove(name)
            return False
        self.selected.append(name)
        return True

    def rows(self):
        """Every available field with its state, for the selection screen."""
        labels = {f: l for f, l, _k in field_choices()}
        return [(f, labels[f], f in self.selected) for f in self.available]

    # -- what order -------------------------------------------------------

    def order(self):
        """The selected fields, numbered from one, for the ordering screen."""
        labels = {f: l for f, l, _k in field_choices()}
        return [(i + 1, f, labels[f]) for i, f in enumerate(self.selected)]

    def move(self, name, position):
        """Put `name` at `position` (1-based) and renumber everything.

        Out-of-range numbers are clamped rather than refused: on a panel the
        operator is typing a single digit at a list of four things, and "7"
        plainly means last.
        """
        if name not in self.selected:
            return False
        try:
            position = int(position)
        except (TypeError, ValueError):
            return False
        self.selected.remove(name)
        at = max(0, min(position - 1, len(self.selected)))
        self.selected.insert(at, name)
        return True

    def entry(self):
        """The `entry` list an activity definition would carry."""
        return tuple(self.selected)


def format_activity(name, entry, label="", like="", sig="", contest_id="",
                    serial=False, serial_start=1, labels=None):
    """One activity as the INI text that defines it.

    Written rather than pickled so the file an operator edits by hand and the
    file the deck writes are the same file — a definition made on the panel
    can be read, copied and corrected over SSH, and one made over SSH shows
    up in the picker.
    """
    out = [f"[{str(name).strip().upper()}]"]
    if label:
        out.append(f"label = {label}")
    if like:
        out.append(f"like = {str(like).strip().upper()}")
    out.append("entry = " + ", ".join(entry))
    if sig:
        out.append(f"sig = {sig}")
    if contest_id:
        out.append(f"contest_id = {contest_id}")
    if serial:
        out.append("serial = yes")
        if int(serial_start) != 1:
            out.append(f"serial_start = {int(serial_start)}")
    for field, text in sorted((labels or {}).items()):
        out.append(f"label_{field} = {text}")
    return "\n".join(out) + "\n"


def save(path, name, text):
    """Write one activity into `path`, replacing any section of that name.

    Replacing rather than appending, because saving twice under one name is
    what an operator does while getting a definition right, and two sections
    with the same name would mean the second silently wins with no sign of
    the first.

    The rest of the file is preserved byte for byte: it may hold definitions
    this program has never seen and comments explaining them.
    """
    import os
    name = str(name).strip().upper()
    path = os.path.expanduser(path)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines(keepends=True)
    except OSError:
        lines = []

    out, skipping = [], False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            skipping = stripped[1:-1].strip().upper() == name
        if not skipping:
            out.append(line)

    body = "".join(out).rstrip()
    whole = (body + "\n\n" if body else "") + text

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(whole)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return path


def _split_list(text):
    return [p.strip() for p in re.split(r"[,\s]+", (text or "").strip()) if p.strip()]


def validate_entry(fields, name="activity"):
    """Refuse a grammar that cannot be parsed, with a reason.

    Two rules, both because the alternative is a parser that reads a line
    wrong and says nothing: every field has to be one this module knows how to
    parse, and no field may be listed twice.

    A text field in a non-final position is fine — it takes a single token,
    which is exactly how `name qth` has always worked. Only the last text
    field is greedy.
    """
    unknown = [f for f in fields if f not in ENTRY_FIELDS]
    if unknown:
        raise ActivityError(
            f"{name}: unknown entry field{'s' if len(unknown) > 1 else ''} "
            f"{', '.join(unknown)} (known: {', '.join(sorted(ENTRY_FIELDS))})")

    dupes = [f for f in set(fields) if list(fields).count(f) > 1]
    if dupes:
        raise ActivityError(f"{name}: {', '.join(sorted(dupes))} listed twice")

    return tuple(fields)


def parse_file(text, name="", inherit_from=None):
    """Activities from an INI body. Returns {NAME: Activity}.

    `inherit_from` is the table a `like =` may refer to — the built-ins, when
    loading the user's file — so a saved activity can be used as a template
    without being restated.

    Never silently drops a section: a typo in an activity definition is
    refused with a message naming the section, because an activity that
    quietly does not exist looks exactly like one that does nothing.
    """
    inherit_from = inherit_from if inherit_from is not None else {}
    parser = configparser.ConfigParser()
    try:
        parser.read_string(text)
    except configparser.Error as exc:
        raise ActivityError(f"{name or 'activities'}: {exc}") from exc

    out = {}
    for section in parser.sections():
        sec = parser[section]
        key = section.strip().upper()
        unknown = [k for k in sec
                   if k.lower() not in ("label", "entry", "sig", "contest_id",
                                        "serial", "serial_start", "like")
                   and not k.lower().startswith("label_")]
        if unknown:
            raise ActivityError(
                f"[{section}]: unknown setting{'s' if len(unknown) > 1 else ''} "
                f"{', '.join(unknown)}")

        # `like` starts this activity from an existing one — the saved
        # template. A state QSO party is a QSOPARTY with a contest id and a
        # different word for the exchange, and saying so is better than
        # restating the field list and letting the two drift.
        parent = sec.get("like", "").strip().upper()
        if parent:
            base = out.get(parent) or inherit_from.get(parent)
            if base is None:
                known = sorted(set(list(out) + list(inherit_from)))
                raise ActivityError(
                    f"[{section}]: like = {parent} is not a known activity "
                    f"(known: {', '.join(known)})")
        else:
            # A section whose name matches an existing activity is customizing
            # that one, so it inherits implicitly. Otherwise `[POTA]\nlabel =
            # ...` — changing one word — would silently blank its field list
            # and the next park contact would log nothing but a callsign.
            base = inherit_from.get(key)

        if "entry" in {k.lower() for k in sec}:
            entry = validate_entry(_split_list(sec.get("entry", "")),
                                   name=f"[{section}]")
        elif base is not None:
            entry = base.entry
        else:
            entry = ()

        serial_raw = sec.get("serial", "").strip().lower()
        if serial_raw and serial_raw not in ("yes", "no"):
            raise ActivityError(f"[{section}]: serial must be yes or no")
        if serial_raw:
            serial = serial_raw == "yes"
        else:
            serial = base.serial if base is not None else False

        try:
            start = int(sec.get("serial_start",
                                base.serial_start if base is not None else 1))
        except ValueError:
            raise ActivityError(
                f"[{section}]: serial_start must be a number") from None

        labels = dict(base._labels) if base is not None else {}
        labels.update({k.lower()[6:]: v for k, v in sec.items()
                       if k.lower().startswith("label_")})

        out[key] = Activity(
            key,
            label=sec.get("label", base.label if base is not None else ""),
            entry=entry,
            sig=sec.get("sig", base.sig if base is not None else "").strip().upper(),
            contest_id=sec.get("contest_id",
                               base.contest_id if base is not None else "").strip(),
            serial=serial, serial_start=start, labels=labels)
    return out


def config_path(path=None):
    """Where activity definitions live, resolved the one way.

    `load` and `save` have to agree, and when they did not, an activity built
    on the panel was written to one file and looked for in another — it saved
    without error and then was not there.
    """
    return os.path.expanduser(path or os.environ.get("CYBERDECK_ACTIVITIES")
                              or DEFAULT_PATH)


def load(path=None):
    """Built-ins, overridden by `activities.conf` where it defines a name.

    A missing file is the normal case and is not an error — the built-ins are a
    working set on their own.
    """
    table = dict(BUILTIN)
    path = config_path(path)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            body = fh.read()
    except OSError:
        return table
    table.update(parse_file(body, name=os.path.basename(path),
                            inherit_from=table))
    return table


def get(name, table=None):
    """One activity by name, falling back to GENERAL.

    Falling back rather than raising: an activity named in the configuration
    that no longer exists must not stop the deck from logging. The contact is
    worth more than the activity.
    """
    table = table if table is not None else BUILTIN
    if not name:
        return table.get("GENERAL", GENERAL)
    return table.get(str(name).strip().upper(), table.get("GENERAL", GENERAL))
