"""The log entry form: fields, a cursor, Tab between them.

Replaces typing a whole contact on one line. The activity (`activities.py`)
decides which fields exist and in what order; this holds their values, which
one has focus, and what survives a commit.

**It dissolves the ambiguity the one-line grammar was built around.** `599` is
a valid signal report and a valid serial number, and on a single line nothing
but the activity could say which was meant. In a field of its own the question
cannot arise. The activity's `entry` list stops being a parse order and becomes
a tab order, which is what it always wanted to be.

Three kinds of field, and the difference is what happens when a contact is
logged:

  * **per contact** — the callsign, the reports, what they sent. Cleared on
    commit, because the next station is a different station.
  * **sticky** — this station's own park, this station's exchange, and a
    comment the operator typed. Kept on commit. These are the same on every
    contact of an event and retyping them eighty times is eighty chances to
    mistype one. Clearing a sticky field is how you turn it off.
  * **from the radio** — frequency and mode. Prefilled and refreshed while
    untouched, and **frozen the moment the operator edits one**, because a
    field that re-filled itself after being corrected could never be
    corrected.

Pure: no curses, no sockets, no clock. The deck feeds it keys and radio
readings; `render.log_screen` draws it; `qsolog.make_record` consumes what
`commit()` returns.
"""

import activities

# Fields that are not part of any activity's `entry` list but are always on
# the form. The callsign leads because it is always the first thing typed and
# often the only thing known; the comment trails because it is free text of
# unbounded length.
CALL = ("call", "Call", False)
COMMENT = ("comment", "Comment", True)

# Sticky wherever it appears, including when an activity lists it among its own
# fields and so decides its position. The comment is the one per-contact field
# that is usually the same all session -- "5W to a wire", "mobile" -- and it is
# carried across a type change for the same reason. Without this, moving it
# into an activity's field list silently turned it into a field that cleared
# itself on every commit.
STICKY_ANYWHERE = ("comment",)

# Fields held in upper case however they are typed. A callsign is upper case
# everywhere it is ever written -- on the air, in ADIF, in every log -- so
# Caps Lock and the Shift key should not be able to produce a lower-case one,
# and the operator should not have to look at the field to find out which they
# got. A reference is the same: `activities._PARK` only matches upper case and
# `qsolog.make_record` upper-cases it on the way to the record, so showing it
# any other way would show something different from what gets logged.
#
# `grid` is deliberately NOT here: a Maidenhead locator is conventionally
# mixed case (FN10cs), and upper-casing it would be wrong rather than tidy.
UPPER = ("call", "park", "my_park")

# This station's own side of the contact. Shown and editable, but placed after
# the per-contact fields so the common path — call, reports, Enter — does not
# tab through them. Sticky, every one.
STATION = (
    ("my_park", "My ref", True),
    ("exchange_tx", "My exch", True),
)

# Prefilled from the radio and refreshed until touched. `tx_power` is here
# only when an activity asks for it: the wattage is recorded on every contact
# regardless, read from CAT at commit, and putting it ON THE FORM is a
# different thing -- it lets the operator see what is about to be logged and
# correct it when the radio cannot be read.
RADIO = ("freq", "mode", "tx_power")

# From the Station menu rather than from the radio, and otherwise the same:
# written in until the operator edits one, and then left alone. Together with
# RADIO these are the fields nobody types. `Field.from_radio` is what marks a
# field as one of them -- the name is older than the station settings.
#
# Not `STATION`: that is taken, by the sticky own-side fields above. These two
# are per-contact fields an activity can ask for, which happen to be filled
# from the configuration rather than typed.
FROM_CONFIG = ("my_rig", "my_antenna")
PREFILLED = RADIO + FROM_CONFIG

# Filled from a callbook answer about the station being worked. They belong to
# that callsign and to no other, so changing the callsign drops them -- see
# `forget_lookup`. `grid` is here even though no built-in activity shows it,
# because an activity may.
LOOKUP = ("name", "qth", "grid")


class Field:
    """One field: a label, a value, and what happens to it on commit."""

    def __init__(self, name, label, sticky=False, value="", from_radio=False):
        self.name = name
        self.label = label
        self.upper = name in UPPER
        self.sticky = sticky
        self.value = value
        self.from_radio = from_radio
        # What this field was last *given* — by the radio, by the log's next
        # serial, by the sticky value carried through a commit. Ctrl-Z puts
        # it back after it has been typed over, which is the whole reason it
        # is kept separately from `value`.
        self.prefill = value
        # What Ctrl-Z displaced, so a second Ctrl-Z undoes the undo. An
        # accidental restore should not be the one keystroke that cannot be
        # taken back.
        self.displaced = None
        # Set once the operator types into a radio-sourced field. A correction
        # that got overwritten on the next poll would be worse than no
        # prefill at all.
        self.touched = False

    def __repr__(self):
        return f"<Field {self.name}={self.value!r}{' *' if self.sticky else ''}>"


class LogForm:
    """The fields for one activity, and which of them has focus."""

    def __init__(self, activity_type=None, show_radio=True):
        self.activity_type = activity_type or activities.GENERAL
        self.fields = []
        self._build(show_radio)
        self.index = 0
        self.cursor = 0

    def _build(self, show_radio):
        """Tab order: what is typed every contact, then what is not.

        The ordering is the whole ergonomics of this screen. Everything the
        operator types for *this* station comes first, so the common path is
        call, reports, Enter without passing through anything. The prefilled
        fields — own park, own exchange, frequency, mode — are reachable by
        tabbing on, and are the ones that are usually already right.

        Putting the radio fields second, which is where they first went,
        meant tabbing off the callsign landed on the frequency and the
        exchange was typed into it.
        """
        act = self.activity_type
        order = [Field(*CALL)]

        # 1. Typed for this contact, in the activity's own order. One of them
        # is not typed at all: tx_power comes from the radio, and is marked so
        # it prefills and stops tracking the moment it is corrected.
        for name in act.entry:
            order.append(Field(name, act.label_for(name),
                               from_radio=(name in PREFILLED),
                               sticky=(name in STICKY_ANYWHERE)))
        # Every form has a comment field, whether or not the activity asked
        # for one: a note about a contact is never not worth having.
        #
        # Unless the activity DID ask for one, in which case it has already
        # been placed above, in the position the operator chose. Appending it
        # again put two Comment fields on one form -- which became possible
        # the moment `comment` was made selectable, and is the sort of thing a
        # field list must not be able to say twice.
        if "comment" not in act.entry:
            order.append(Field(*COMMENT))

        # 2. This station's side, starting with the serial being sent. It is
        # on the form rather than computed at commit so the operator can SEE
        # the number before saying it on the air — which is the whole point of
        # a serial — and can correct it when a contact was not logged.
        if act.serial:
            order.append(Field("serial_tx", "My nr", sticky=True))
        # Only the fields this activity can use: an activity with no reference
        # field has no business asking for one.
        for name, label, sticky in STATION:
            if name == "my_park" and not act.wants("park"):
                continue
            if name == "exchange_tx" and not act.wants("exchange_rx"):
                continue
            order.append(Field(name, label, sticky=sticky))

        # 3. The radio, last. Editable rather than display-only, because the
        # radio can be unreachable and a frequency that cannot be corrected
        # makes a contact unloggable rather than merely imprecise.
        if show_radio:
            order.append(Field("freq", "Freq", from_radio=True))
            order.append(Field("mode", "Mode", from_radio=True))

        self.fields = order

    # -- access -----------------------------------------------------------

    def field(self, name):
        for f in self.fields:
            if f.name == name:
                return f
        return None

    def value(self, name):
        f = self.field(name)
        return f.value if f else ""

    def set(self, name, value, touch=False, prefill=True):
        """Put a value in programmatically. Counts as a prefill by default.

        `prefill=False` is for restoring a draft — reopening the screen on a
        half-typed contact — where the text is the operator's, not ours, and
        Ctrl-Z should not offer to replace it.
        """
        f = self.field(name)
        if f is None:
            return False
        f.value = str(value).upper() if f.upper else str(value)
        if prefill:
            f.prefill = f.value
            f.displaced = None
        if touch:
            f.touched = True
        self._wrote(f)
        return True

    def _wrote(self, f):
        """Put the cursor after a value written into the focused field.

        A lookup answer arrives while the operator is sitting in the field it
        fills. Without this the cursor stays where it was -- at 0, on an empty
        field that is no longer empty -- and Backspace returns early on
        `cursor <= 0`, so the name that appeared cannot be deleted. Found on
        the deck 2026-10-11 against a name pulled from HamQTH.
        """
        if f is self.current:
            self.cursor = len(f.value)

    def restore(self):
        """Ctrl-Z: put the prefill back into the focused field.

        Pressed again it puts back what it displaced, and keeps toggling
        between the two — because an accidental restore should not be the one
        keystroke that cannot be taken back, and a key whose effect depends on
        how many times it has been pressed is worse than one that flips.
        The deck binds this as `(26, curses.KEY_SUSPEND)`: TERM=linux defines
        `kspd=^Z`, so ncurses eats byte 26 and returns KEY_SUSPEND instead,
        and matching only 26 ships dead on the panel. That has happened here
        once already — see design_doc.md on the memory-insert undo.

        Returns False when there is nothing to put back, so the caller can say
        so rather than leaving a key looking broken.
        """
        f = self.current
        if f is None:
            return False
        # Nothing was ever prefilled here, so there is nothing to put back.
        # Without this, Ctrl-Z on a freshly typed callsign wipes it — which
        # is not undoing a mistake, it is making one. The transcript screen
        # says "nothing to undo" in the same situation.
        if not f.prefill and f.displaced is None:
            return False
        if f.value != f.prefill:
            f.displaced = f.value
            f.value = f.prefill
            # A radio field tracks again: restoring the prefill is a statement
            # that the operator did not mean to override it.
            f.touched = False
        elif f.displaced is not None:
            f.value, f.displaced = f.displaced, None
            if f.from_radio:
                f.touched = True
        else:
            return False
        self.cursor = len(f.value)
        return True

    @property
    def current(self):
        return self.fields[self.index] if self.fields else None

    def labels(self):
        return [(f.label, f.value) for f in self.fields]

    # -- movement ---------------------------------------------------------

    def tab(self, back=False):
        """Move focus. Wraps, because a form that stops at the end makes the
        operator look down to find out why the key did nothing."""
        if not self.fields:
            return
        self.index = (self.index + (-1 if back else 1)) % len(self.fields)
        self.cursor = len(self.current.value)

    def focus(self, name):
        for i, f in enumerate(self.fields):
            if f.name == name:
                self.index, self.cursor = i, len(f.value)
                return True
        return False

    # -- editing ----------------------------------------------------------

    def type(self, text):
        """Insert at the cursor. Marks the field as touched by hand."""
        f = self.current
        if f is None:
            return
        f.touched = True
        for ch in str(text):
            if f.upper:
                ch = ch.upper()
            f.value = f.value[:self.cursor] + ch + f.value[self.cursor:]
            self.cursor += 1
        if f.from_radio:
            f.touched = True

    def backspace(self):
        f = self.current
        if f is None or self.cursor <= 0:
            return
        f.value = f.value[:self.cursor - 1] + f.value[self.cursor:]
        self.cursor -= 1
        if f.from_radio:
            f.touched = True

    def delete(self):
        f = self.current
        if f is None or self.cursor >= len(f.value):
            return
        f.value = f.value[:self.cursor] + f.value[self.cursor + 1:]
        if f.from_radio:
            f.touched = True

    def kill(self):
        """Clear the focused field. **This is how a sticky field is turned
        off** — there is no separate gesture, because "delete it to stop it
        coming back" is what the operator would try first."""
        f = self.current
        if f is None:
            return
        f.value = ""
        self.cursor = 0
        if f.from_radio:
            f.touched = True

    def left(self):
        self.cursor = max(0, self.cursor - 1)

    def right(self):
        self.cursor = min(len(self.current.value) if self.current else 0,
                          self.cursor + 1)

    def home(self):
        self.cursor = 0

    def end(self):
        self.cursor = len(self.current.value) if self.current else 0

    # -- the radio --------------------------------------------------------

    def from_station(self, rig="", antenna=""):
        """Refresh the fields that come from the Station menu.

        Separate from `from_radio` because the source is different and so is
        the failure: a radio that cannot be read leaves the power blank, an
        unset Station menu leaves these blank, and those are fixed in two
        different places. Skipping a touched field is the same rule -- a
        corrected antenna has to survive the next poll.
        """
        for name, value in (("my_rig", rig), ("my_antenna", antenna)):
            f = self.field(name)
            if f is not None and not f.touched and value:
                f.value = str(value)
                f.prefill = f.value
                self._wrote(f)

    def from_radio(self, freq="", mode="", power=""):
        """Refresh the radio-sourced fields, skipping any the operator edited.

        Called on whatever poll the interface was already doing. Silently does
        nothing to a touched field, which is the whole point.

        The signal reports are prefilled from the mode at the same time. They
        have to be: the line this form replaced defaulted them, so a form that
        left them blank would make the commonest contact — call, 59, 59 — more
        typing than before rather than less.
        """
        for name, value in (("freq", freq), ("mode", mode),
                            ("tx_power", power)):
            f = self.field(name)
            if f is not None and not f.touched and value:
                f.value = str(value)
                f.prefill = f.value
                self._wrote(f)

        if mode:
            import qsolog
            default = qsolog.default_report(mode)
            for name in ("rst_s", "rst_r"):
                f = self.field(name)
                if f is not None and not f.touched:
                    f.value = default
                    f.prefill = default
                    self._wrote(f)

    # -- committing -------------------------------------------------------

    def ready(self):
        """Whether there is enough to log. A callsign, and nothing else."""
        return bool(self.value("call").strip())

    def collect(self):
        """Every field's value, as a plain dict. Does not reset anything."""
        return {f.name: f.value.strip() for f in self.fields}

    def typed(self):
        """Field names the OPERATOR put something in, in form order.

        What a schema change would throw away, and therefore what the deck
        refuses to change schema over -- see `qso_log_design.md` §7i. A
        schema change rebuilds the form and carries only the sticky fields
        across, so a typed callsign and reports used to vanish without a
        word.

        Four kinds of value are deliberately NOT counted, because none of
        them is the operator's work and all of them survive or are recomputed:

        * **sticky fields** -- the comment, this station's own reference and
          exchange -- which `_set_activity_type` carries across by hand,
        * **radio fields the operator has not touched**, which the next poll
          refills,
        * **anything still equal to what the deck prefilled it with**: a
          `599` nobody edited, a serial the log handed out, a rig name off
          the Station settings,
        * **empty fields**, obviously.

        So this is empty on a form the operator has not typed into, whatever
        the deck has filled in around them -- which is the common case, and
        the one where a schema change has to just work.
        """
        out = []
        for f in self.fields:
            if not f.value:
                continue
            if f.sticky or f.name in STICKY_ANYWHERE:
                continue
            if f.from_radio and not f.touched:
                continue
            if not f.touched and f.value == f.prefill:
                continue
            out.append(f.name)
        return out

    def commit(self):
        """Return the contact and clear the form for the next one.

        Sticky fields keep their values; everything else empties. The radio
        fields keep theirs too — the frequency does not change between
        contacts — but their `touched` flag is left alone, so a correction
        stays corrected until the operator clears it.
        """
        out = self.collect()
        for f in self.fields:
            if not f.sticky and not f.from_radio:
                f.value = ""
                f.touched = False
            # Whatever a field holds going into the next contact IS its
            # prefill, so Ctrl-Z offers to put that back rather than something
            # from two contacts ago.
            f.prefill = f.value
            f.displaced = None
        self.focus("call")
        return out

    def forget_lookup(self):
        """Drop the callbook details, keeping anything the operator typed.

        Called when the callsign changes, because the name and QTH on the
        form describe the station that callsign used to be. Two separate
        faults on the deck, 2026-10-11, were both this: the first station's
        name stayed on the form for the second, and a second lookup could not
        displace it because the merge only filled fields that were empty.

        `touched` is the whole distinction. A name the operator typed is a
        correction and outranks any callbook; a name the callbook supplied is
        provisional and goes when its callsign does.
        """
        dropped = False
        for name in LOOKUP:
            f = self.field(name)
            if f is None or f.touched or not f.value:
                continue
            f.value = ""
            f.prefill = ""
            f.displaced = None
            self._wrote(f)
            dropped = True
        return dropped

    def clear(self):
        """Throw away the staged contact. Sticky and radio fields are kept.

        For the wrong callsign typed, the station that turned out to be
        someone else, the half-entered contact that never completed. What is
        discarded is this *contact*; the park, the exchange, the comment and
        the frequency describe the operating session and survive it -- the
        same division `commit` makes, because "clear" and "logged" should
        leave the form in the same shape.

        A sticky field is still cleared one at a time with Ctrl-U, which is
        how sticky is turned off.

        Returns whether anything was actually discarded, so a key pressed on
        an already-empty form can say so rather than look broken.
        """
        staged = [(f, f.value) for f in self.fields
                  if not f.sticky and not f.from_radio]
        for f, _was in staged:
            f.value = ""
            f.touched = False
            f.prefill = ""
            f.displaced = None
        # The reports are prefilled from the MODE and not from the station
        # worked, so a cleared form gets them back. Without this, clearing
        # costs the operator the 59 that was there before they typed.
        self.from_radio(mode=self.value("mode"))
        self.focus("call")
        # Compared against the cleared form rather than against emptiness: a
        # report sitting at the mode's default is not something the operator
        # staged, so clearing a form that holds only defaults has done
        # nothing and should say so.
        return any(was != f.value for f, was in staged)

    def advance_serial(self, records, start=1, activity=""):
        """Put this station's next serial on the form, if it sends one.

        Derived from the log rather than counted in memory, so it survives a
        restart and cannot drift from what was actually sent. Called after
        each commit, and once when the screen opens.

        A serial the operator has edited is still replaced: the next number
        comes from the log, and the log now contains the contact they just
        made. Editing it is for fixing the *current* contact, not for setting
        a counter.
        """
        if not self.activity_type.serial:
            return 0
        import qsolog
        # Scoped to the ACTIVITY, not to the type: two weekends of the same
        # QSO party are two activities and each counts from one. Passed in by
        # the caller because the form knows its type and not which session
        # it is being used for.
        nxt = qsolog.next_serial(records, activity, start)
        self.set("serial_tx", str(nxt))
        return nxt
