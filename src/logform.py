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

# This station's own side of the contact. Shown and editable, but placed after
# the per-contact fields so the common path — call, reports, Enter — does not
# tab through them. Sticky, every one.
STATION = (
    ("my_park", "My ref", True),
    ("exchange_tx", "My exch", True),
)

# Prefilled from the radio and refreshed until touched.
RADIO = ("freq", "mode")


class Field:
    """One field: a label, a value, and what happens to it on commit."""

    def __init__(self, name, label, sticky=False, value="", from_radio=False):
        self.name = name
        self.label = label
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

    def __init__(self, activity=None, show_radio=True):
        self.activity = activity or activities.GENERAL
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
        act = self.activity
        order = [Field(*CALL)]

        # 1. Typed for this contact, in the activity's own order.
        for name in act.entry:
            order.append(Field(name, act.label_for(name)))
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
        f.value = str(value)
        if prefill:
            f.prefill = f.value
            f.displaced = None
        if touch:
            f.touched = True
        return True

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

    def from_radio(self, freq="", mode=""):
        """Refresh the radio-sourced fields, skipping any the operator edited.

        Called on whatever poll the interface was already doing. Silently does
        nothing to a touched field, which is the whole point.

        The signal reports are prefilled from the mode at the same time. They
        have to be: the line this form replaced defaulted them, so a form that
        left them blank would make the commonest contact — call, 59, 59 — more
        typing than before rather than less.
        """
        for name, value in (("freq", freq), ("mode", mode)):
            f = self.field(name)
            if f is not None and not f.touched and value:
                f.value = str(value)
                f.prefill = f.value

        if mode:
            import qsolog
            default = qsolog.default_report(mode)
            for name in ("rst_s", "rst_r"):
                f = self.field(name)
                if f is not None and not f.touched:
                    f.value = default
                    f.prefill = default

    # -- committing -------------------------------------------------------

    def ready(self):
        """Whether there is enough to log. A callsign, and nothing else."""
        return bool(self.value("call").strip())

    def collect(self):
        """Every field's value, as a plain dict. Does not reset anything."""
        return {f.name: f.value.strip() for f in self.fields}

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

    def advance_serial(self, records, start=1):
        """Put this station's next serial on the form, if it sends one.

        Derived from the log rather than counted in memory, so it survives a
        restart and cannot drift from what was actually sent. Called after
        each commit, and once when the screen opens.

        A serial the operator has edited is still replaced: the next number
        comes from the log, and the log now contains the contact they just
        made. Editing it is for fixing the *current* contact, not for setting
        a counter.
        """
        if not self.activity.serial:
            return 0
        import qsolog
        nxt = qsolog.next_serial(records, self.activity.name, start)
        self.set("serial_tx", str(nxt))
        return nxt
