"""Full-screen menus, selected by a single key (docs/digimodes_design.md §5.8).

No pointer, no cursor to move, no nesting deeper than two: a menu is a list of
labeled keys and pressing one does the thing. That is the fastest interface
on a keyboard and the only sane one on a console with no mouse.

The structure is data and the rendering is a pure function, so both can be
tested at 50, 66, 80 and 100 columns without a terminal. What each item *does*
is wired up in cyberdeck.py, because only that knows about fldigi.
"""

# The curated first tier of conversational modems (§6). fldigi offers 169, of
# which 64 are keyboard modes; putting all of them on one screen makes the
# screen the problem. Everything else is reachable under "more".
MODE_TIER1 = [
    ("1", "BPSK31"),
    ("2", "BPSK63"),
    ("3", "QPSK31"),
    ("4", "RTTY"),
    ("5", "OLIVIA-8/250"),
    ("6", "OLIVIA-8/500"),
    ("7", "MFSK16"),
    ("8", "THOR22"),
    ("9", "CONTESTIA"),
    ("0", "DOMEX8"),
    ("h", "FELDHELL"),
    ("c", "CW"),
]

# Which modems count as conversational, for the "more" list.
# "CW" is in this list because CW is keyboard-to-keyboard operating — it is the
# original form of it — and fldigi offers it as a modem like any other. Leaving
# it out made it unreachable from the deck at all, not merely absent from the
# first tier, while the full list claimed to be complete.
_KEYBOARD_FAMILIES = ("CW", "BPSK", "QPSK", "PSK", "RTTY", "OLIVIA", "MFSK",
                      "CONTESTIA", "THOR", "DOMEX", "FELDHELL", "HELL")

PAGE_KEYS = "abcdefghijklmnopqrstuvwxyz"


def keyboard_modes(all_names):
    """The conversational subset of fldigi's modem list, in family order."""
    out = []
    for family in _KEYBOARD_FAMILIES:
        for name in all_names:
            if name.upper().startswith(family) and name not in out:
                out.append(name)
    return out


# One menu per AREA, not one menu for the deck.
#
# There used to be a single ROOT holding Mode, Tune Settings, Band, Display,
# Memories, Station, System and Logging -- three different concerns in one
# list, and an entire area (logging) behind one of its lines. Reaching the
# deck's own settings meant going through the digimode screen's menu, which is
# what made the digimode screen the deck's home whether or not that was
# intended.
#
# Now F1 opens the menu for wherever the operator is, and the three areas are
# reached from each other with ^B and ^F. A line that belongs to one area is
# not on another area's menu.
#
# The rule for adding a line: it goes in together with its handler in
# cyberdeck.py. An entry whose Enter does nothing is worse than no entry,
# because being discoverable is the line's only job and it then lies.
DIGI = {
    "title": "DIGIMODES",
    "items": [
        ("1", "Mode"),
        ("2", "Tune Settings"),
        # Band is digimode-specific and was briefly moved to the deck menu on
        # the reasoning that a band is a property of the radio. That reasoning
        # was wrong about what this entry DOES: it tunes to the digimode
        # calling frequency for the band, which is a digital-modes decision
        # and is useless to anything else on the deck.
        ("3", "Band"),
        ("4", "Memories"),
    ],
    "footer": "Esc back   \u2191\u2193 move   Enter select   ^O ^P screen",
}


def digi_menu(log_hotkey=""):
    """The digimode menu, with what `^G` currently does spelled out.

    A static entry reading "Log hotkey" would say which key to press and not
    what pressing it does, and the three behaviours differ in whether the
    screen changes under the operator -- which is exactly the part that has to
    be known before the key is pressed rather than after.
    """
    import decall
    label = decall.MODE_LABELS.get(log_hotkey, "")
    items = list(DIGI["items"])
    items.append(("5", f"^G logs the last station heard: {label}"
                  if label else "^G logs the last station heard"))
    return {**DIGI, "items": items}

# The deck and the radio: what this station is, what it is attached to, and
# what the panel itself does. Nothing here is about digital modes, and nothing
# here is about one contact.
DECK = {
    "title": "DECK & RIG",
    "items": [
        # No Station line. The deck-and-rig SCREEN is the station editor now --
        # every field, with its substitution token beside it, edited in place.
        # A menu that opened a second list of the same eight settings was the
        # same information twice, and the screen is the one you are already
        # looking at.
        ("1", "Display"),
        ("2", "System"),
        # The auto tuner. A sub-screen rather than a ring area: it keys the
        # transmitter for minutes at a time, and a screen that does that
        # should not be one `^O` away from everything else.
        ("3", "Auto tuner"),
        # The ring editor. Here rather than an area of its own because it is
        # set once and lived with -- and here rather than anywhere else
        # because deck & rig is the area that cannot leave the ring, so it is
        # the one place reachable from a deck configured into a corner.
        ("4", "Function ring order"),
        # Getting the files off the deck. Under deck & rig rather than under
        # logging or WSPR, because it offers all of their files at once --
        # and beside WiFi in spirit, since the phone it serves is on the
        # network the system menu joins.
        ("5", "Send files to a phone"),
    ],
    "footer": "Esc back   \u2191\u2193 move   Enter select   ^O ^P screen",
}

# Kept under its old name as well, because `ROOT` is what several tests and
# `tools/` reach for and because a menu that vanished would fail at the point
# of use rather than here. It is the digimode menu: that is the screen F1 used
# to open it from.
ROOT = DIGI

# Which menu Esc goes up to. A menu absent from this map is a top-level one and
# Esc closes it, returning to the screen underneath -- which is the screen of
# the area it belongs to, so backing out never crosses an area boundary.
MENU_PARENT = {
    "mode": "digi",
    "modes_all": "mode",
    "tuning": "digi",
    "memories": "digi",
    # The band picker tunes to digimode calling frequencies, so it backs out
    # to the digimode menu and not to the deck's.
    "radio": "digi",
    "display": "deck",
    "system": "deck",
    # Esc out of the danger zone goes back to the logging menu, not out to the
    # screen: arriving there is deliberate and leaving should be too.
    "danger": "logging",
    # The band picker has NO parent, so Esc closes it to the WSPR screen --
    # the same rule the log's schema picker follows (§7i). An operator who
    # pressed F3 from the screen expects Esc to return there, and sending
    # them up to a menu they did not open is the inconsistency that was
    # fixed once already on the log screen.
    #
    # The danger zone DOES go back to the WSPR menu: arriving there is
    # deliberate and leaving should be, which is why `danger` does the same.
    "wspr_danger": "wspr",
    "wspr_audio": "wspr",
}

DISPLAY = {
    "title": "DISPLAY",
    "items": [
        ("1", "Color: Hal      red"),
        ("2", "Color: Deckard  amber"),
        ("3", "Color: Matrix   green"),
        ("4", "Color: Tron     cyan"),
        ("5", "Color: Ripley   white"),
        ("t", "Timestamps on/off"),
    ],
    "footer": "Esc back   ↑↓ move   Enter select",
}

def _most(ms):
    """The upper bound as the menu shows it. 0 is not 'no wait' but 'do not
    wait at all' — the quality gate is off and the fixed window applies — and
    printing it as '0 ms' reads as the opposite."""
    return f"{ms} ms" if ms else "off"


def tuning_menu(afc, squelch, level, rsid, txid, reverse=False, rx_hold=0,
                rx_hold_max=0):
    """Tuning options with their current state shown.

    The static version of this menu gave no feedback: pressing `s` toggled
    the squelch and the screen did not change, which reads as a dead key.
    """
    def onoff(v):
        return "ON " if v else "off"

    return {
        "title": "TUNE SETTINGS",
        "items": [
            ("a", f"AFC         {onoff(afc)}"),
            ("s", f"Squelch     {onoff(squelch)}"),
            ("+", f"Squelch level up       ({level:.0f})"),
            ("-", f"Squelch level down     ({level:.0f})"),
            ("r", f"RSID        {onoff(rsid)}   follow others' identifiers"),
            ("t", f"TXID        {onoff(txid)}   send one before our overs"),
            ("v", f"Reverse     {onoff(reverse)}   mark/space sense, for RTTY"),
            ("c", "Park carrier at the configured offset"),
            ("[", f"RX hold least  down   ({rx_hold} ms)"),
            ("]", f"RX hold least  up     ({rx_hold} ms)"),
            ("{", f"RX hold most   down   ({_most(rx_hold_max)})"),
            ("}", f"RX hold most   up     ({_most(rx_hold_max)})"),
            (" ", "On the conversation screen, without coming here:"),
            (" ", "Ctrl-A / Ctrl-D carrier ±10 Hz  Ctrl-W / Ctrl-S search"),
        ],
        "footer": "Esc back   ↑↓ move   Enter select   F2 live tuning",
    }

# Low to high. The HF entries are the long-standing PSK31 watering holes; the
# VHF and UHF ones are the PSK31 calling frequencies — 6 m 50.290, 2 m 144.144
# (activity runs 144.144-144.150), 70 cm 432.200.
#
# Eleven bands need eleven single keys, so the digits run 1-9 then 0 and the
# last is `a`. Ordering is by frequency rather than by key, because the list is
# read as a band plan: the alternative keeps 20 m on `4` forever at the cost of
# 17 m and 12 m appearing at the bottom, away from the bands either side of
# them.
BANDS = (
    ("1", "80 m", "3.580", 3_580_000),
    ("2", "40 m", "7.070", 7_070_000),
    ("3", "30 m", "10.142", 10_142_000),
    ("4", "20 m", "14.070", 14_070_000),
    ("5", "17 m", "18.100", 18_100_000),
    ("6", "15 m", "21.070", 21_070_000),
    ("7", "12 m", "24.920", 24_920_000),
    ("8", "10 m", "28.120", 28_120_000),
    ("9", "6 m", "50.290", 50_290_000),
    ("0", "2 m", "144.144", 144_144_000),
    ("a", "70 cm", "432.200", 432_200_000),
)

BAND_FREQUENCIES = {key: hz for key, _label, _display, hz in BANDS}


def band_menu(supported=None):
    """The band list, marking what this radio cannot reach.

    `supported` is a set of band labels, or None meaning every band listed.
    A band the radio does not cover is shown rather than hidden: knowing the
    deck knows about 70 cm, and that this radio will not do it, is more useful
    than a list that quietly varies with the hardware.
    """
    items = []
    for key, label, display, _hz in BANDS:
        if supported is not None and label not in supported:
            items.append((key, f"{display:<8} {label:<6} (not supported)"))
        else:
            items.append((key, f"{display:<8} {label}"))
    return {"title": "BAND", "items": items,
            "footer": "Esc back   \u2191\u2193 move   Enter select"}

def activity_type_menu(names, current="", labels=None):
    """Pick a saved activity TYPE. The list comes from activities.load().

    A picker rather than a toggle because the whole point is that an operator
    defines their own: a list of named templates, chosen by name, is what
    "save an activity type and select it later" means at the panel.

    A *type* is the template of fields. An *activity* is a session that uses
    one and has a name and a log file of its own -- that is the ACTIVITIES
    screen, not this.
    """
    labels = labels or {}
    items = [("g", "General logging" +
              ("   *" if not current or current == "GENERAL" else ""))]
    for i, name in enumerate(n for n in names if n != "GENERAL"):
        mark = "   *" if name == current else ""
        label = labels.get(name, name)
        items.append((str(i + 1)[-1], f"{name:<12} {label[:28]}{mark}"))
    return {
        "title": "LOG SCHEMA",
        "items": items,
        # Five things can start here: select a schema, edit one in place,
        # copy one into a new schema, begin one with nothing in it, or delete
        # one. Creating belongs here rather than on the logging menu, where it
        # asked the operator to decide to create one before seeing what
        # already exists.
        #
        # `e`, `c` and `d` each take a number after them. Two keystrokes and,
        # for the delete, a confirmation as well -- a schema an operator spent
        # a contest getting right should not go on one.
        #
        # **"Esc keep", not "Esc back".** Naming a new activity opens this
        # picker by itself, so Esc is the route for "the schema I am already
        # using is the right one" -- which is a choice, not a retreat, and it
        # closes to the log screen exactly as selecting one does. 62 of 66.
        "footer": ("Esc keep  Enter select  e+n edit  c+n copy  "
                   "n new  d+n delete"),
    }


def danger_menu(activity="", contacts=0, session=0, sessions=0):
    """The three ways to throw contacts away, in one place and named.

    Separated from the logging menu for one reason: the logging menu is used
    constantly and these are used while testing and demonstrating. A line that
    empties the log does not belong next to the one that changes how many rows
    a contact takes.

    Each line says the COUNT it would destroy, because "clear the log" and
    "delete 412 contacts" are different sentences and only the second one is
    true. Each is confirmed as well; the count is what makes the confirmation
    worth reading.
    """
    return {
        "title": "DANGER ZONE",
        "items": [
            # First because it is the one that destroys nothing: the contacts
            # keep their labels and only the deck's list forgets them.
            ("a", f"Forget all activities        "
                  f"{sessions} in the list, contacts kept"),
            ("s", f"Delete this activity's QSOs  "
                  f"{session} from {activity or '(no activity)'}"),
            ("m", f"Delete EVERY QSO             "
                  f"{contacts} in the whole log"),
        ],
        "footer": "Esc back   \u2191\u2193 move   Enter select   each one asks",
    }


def log_menu(on, count=0, park="", lookup=False, has_qrz_key=False,
             qrz_pending=0, operating="auto", has_tqsl=False,
             activity="", dupe="band+mode", log_name="",
             activity_type="", callbook_state="", log_lines=1,
             master_log=True):
    # `master_log` is accepted and ignored. It fed the removed Master log
    # item; the parameter stays so a caller passing it is not a TypeError.
    # has_qrz_key and qrz_pending are accepted and ignored. They fed the
    # removed QRZ upload item; the parameters stay so that a caller passing
    # them is not a TypeError, and so that reinstating an upload item is a
    # deliberate edit here rather than a side effect somewhere else.
    """The logging menu. One line in the root menu leads here.

    When logging is off this is a single item, because that is the whole of
    what the feature is when it is off (docs/qso_log_design.md §1). The rest
    appears only once there is something for it to act on.

    The items are ordered general first: the log, its export, the mode source
    and the lookup apply to every contact. POTA mode comes after them, and
    this station's park reference appears only once POTA mode is on — off, it
    is not a field waiting to be filled, it is a question that does not apply.

    **Nothing here uploads a contact anywhere.** `Export ADIF` writes a file
    beside the log and `Sign and upload to LoTW` writes that file and prints
    the tqsl command for it -- the command is never run, because signing needs
    a callsign certificate that does not belong on a card that travels. The
    only code in this project that transmits a log to a third party is
    `tools/qso.py lotw --upload`, which is a flag, on a subcommand, typed by
    hand on the laptop. There is deliberately no panel key that does it and
    nothing on any timer that does it: a deck full of test contacts must not
    be one keystroke from someone's permanent record.

    There was a `Upload to QRZ  n waiting` item here. It was removed: no
    handler was ever bound to it, so the line did nothing, and "n waiting"
    described a queue that drains, which is exactly the impression this
    feature must not give.
    """
    if not on:
        return {
            "title": "LOGGING",
            "items": [("l", "Logging                      off")],
            "footer": "Esc back   Enter select",
        }

    # Grouped, most-used first, and nothing shown that does not apply.
    #
    #   state      -- is it on, and how much is in it
    #   session    -- what is being logged right now
    #   entry      -- how what gets typed is read
    #   the file   -- where it is and how it leaves
    #
    # The session group is second because it is what changes during an
    # operating session; the file group is last because it is set once. The
    # earlier order put the activity and its schema below the dupe rule and
    # the mode source, which are the two things nobody touches twice.
    items = [
        ("l", f"Logging                      on — {count} "
              f"QSO{'' if count == 1 else 's'}"),

        # -- what is being logged ------------------------------------------
        # Two lines, because these are two things. The ACTIVITY is the session
        # -- this park, this contest weekend -- and carries the operator's own
        # name for it. The SCHEMA is the template of fields it uses, edited
        # once and reused by every activity that wants it.
        #
        # They were one setting called "Activity". That let an operator choose
        # POTA but not say which activation it was, and made two weekends of
        # one QSO party share a serial sequence.
        ("e", f"Activity                     "
              f"{activity or 'master log'}"),
        # Creating a schema is not a line here. It belongs on the picker that
        # lists them, where the operator can already see what exists and what
        # is worth copying -- a menu item asked them to decide to create one
        # before seeing the alternatives.
        ("v", f"Log schema                   "
              f"{activity_type or 'general logging'}"),
        # The map of where the contacts are. Named with its key, because the
        # log screen's footer is already 61 of 66 columns and has no room to
        # say so -- the same reason `F3 type` is left off it.
        ("g", "Map of the contacts          F5 on the log screen"),
    ]
    if needs_reference(activity_type):
        # Only when the schema has a reference field. Otherwise this station's
        # own park is not an unset setting, it is a question that does not
        # apply to the operating being done.
        items.append(("p", f"My reference                 "
                           f"{park or 'not set'}"))

    items += [
        # -- how what gets typed is read -----------------------------------
        ("d", f"Duplicates                   {_DUPE_LABEL(dupe)}"),
        # Three words from two settings: "off" is a decision, "no wifi" is a
        # condition the operator can fix, "on" is working. Showing "off" for a
        # station with no association made a missing network look like a
        # switched-off feature.
        ("c", f"Callbook lookup              "
              f"{callbook_state or ('on' if lookup else 'off')}"),
        ("m", f"Mode from                    "
              f"{_OPERATING_LABEL.get(operating, operating)}"),
        # How tall a contact is in the LIST, which is about reading the log
        # rather than writing it. What the extra rows show is deliberately not
        # described: it is the schema's own field order, so any description
        # here would be wrong for most schemas.
        ("n", f"Lines per contact            "
              f"{log_lines} of 3"),

        # -- the file, and getting out of it -------------------------------
        # One log. An activity is a label on its records, so which file is in
        # use is not a question any more -- this is the file.
        ("f", f"Log file                     {log_name or 'qso.log'}"),
        ("a", f"Export the whole log         "
              f"{(log_name or 'qso.log').rsplit('.', 1)[0]}.adi"),
    ]
    # Only with an activity running. Without one it would export the same
    # records as the line above it under a different name, which is two menu
    # items for one action and the reader left wondering what the difference
    # is.
    if activity:
        items.append(("x", f"Export {activity[:21]}"))
    if has_tqsl:
        # Signing needs a callsign certificate and tqsl blocks rather than
        # failing without one, so this is an export-and-a-command, not a
        # one-key upload. The label says so: nothing is sent from here.
        items.append(("t", "Export + print the LoTW command"))
    # Last, and named so that nobody arrives in it by accident. Everything on
    # it destroys something; see `danger_menu`.
    items.append(("z", "Danger zone — clear logs"))
    return {
        "title": "LOGGING",
        "items": items,
        "footer": "Esc back   ↑↓ move   Enter select   ^O ^P areas",
    }


# Short enough to fit the 66-column panel beside its label. What each one
# actually does is in docs/qso_log_design.md §6; the panel only has room to
# say which of the three is selected.
def needs_reference(activity_type):
    """Whether an activity TYPE puts this station's reference on every contact.

    Asked of the type rather than hard-coded, so an operator who defines a
    WWFF or IOTA type with a `park` field gets the setting without anyone
    editing this file.
    """
    try:
        import activities as _acts
        act = _acts.get(activity_type, _acts.load())
        return act.wants("park")
    except Exception:
        return str(activity_type or "").upper() in ("POTA", "SOTA", "WWFF")


def _DUPE_LABEL(rule):
    """What the panel calls a duplicate rule. Short enough for 66 columns."""
    try:
        import qsolog
        return qsolog.DUPE_LABELS.get(rule, rule)
    except Exception:
        return rule


_OPERATING_LABEL = {
    "auto": "auto — fldigi on digital",
    "digital": "fldigi, always",
    "voice": "the rig, always",
}


SYSTEM = {
    "title": "SYSTEM",
    "items": [
        ("b", "Pair a Bluetooth keyboard"),
        ("w", "WiFi — join a network, or switch the radio off"),
        ("i", "Transmit inhibit on/off      Ctrl-B, any screen"),
        ("c", "Clear the transcript         Ctrl-X"),
        ("q", "Quit                         Ctrl-Q"),
    ],
    "footer": "Esc back   ↑↓ move   Enter select",
}


def memories_menu(settings):
    """The eight message memories, and which F-key each sits on.

    Choosing one opens it for editing in place. An empty slot is marked so
    that a deleted memory is obviously deleted rather than looking like a
    rendering fault.
    """
    items = []
    for slot in range(5, 13):
        text = (settings.get(f"MEMORY_{slot}") or "").strip()
        items.append((str(slot - 4), f"F{slot}  {text if text else '(empty)'}"))
    return {"title": "MESSAGE MEMORIES", "items": items,
            "footer": "Esc back   \u2191\u2193 move   Enter edit"}


# The station fields, in menu order: key, label, and the token that stands
# for it inside a message memory.
STATION_FIELDS = (
    ("CALLSIGN", "Callsign", "{call}"),
    ("NAME", "Name", "{name}"),
    ("QTH", "QTH", "{qth}"),
    ("LOCATOR", "Locator", "{grid}"),
    ("RIG", "Rig", "{rig}"),
    ("ANTENNA", "Antenna", "{ant}"),
    ("TX_POWER_MAX", "Max power (W)", ""),
    ("TX_POWER", "Power (W)", "{power}"),
)


def station_menu(settings):
    """What this station calls itself, and the token for each field.

    The tokens are shown because this is where an operator looks when writing
    a memory: knowing that {qth} exists is most useful at the moment you are
    reading what QTH is set to.
    """
    items = []
    width = max(len(f"{l} {t}") for _k, l, t in STATION_FIELDS)
    for i, (key, label, token) in enumerate(STATION_FIELDS, start=1):
        value = settings.get(key) or "(not set)"
        items.append((str(i), f"{label} {token}".ljust(width) + f" : {value}"))
    return {"title": "STATION", "items": items,
            "footer": "Esc back   \u2191\u2193 move   Enter edit"}


def mode_menu(current, extra=None, auto=False):
    """The mode picker.

    AUTO sits at the top because it is what a newcomer wants and what an
    experienced operator leaves on. It is not a modem: it is RSID, which reads
    the identifier other stations send ahead of a transmission and switches to
    whatever they are using. Listing it beside the modems is honest about what
    it does for you, even though it is a different kind of thing.
    """
    items = [("a", f"AUTO (RSID)  {'ON' if auto else 'off'}")]
    items += list(MODE_TIER1)
    if extra:
        items = items + extra
    items = [(k, (f"{n}  <" if n == current else n)) for k, n in items]
    items.append(("m", "more modes ..."))
    return {"title": "MODE", "items": items,
            "footer": "Esc back   ↑↓ move   Enter select   < marks the mode in use"}


def paged_menu(title, names, page, width, height):
    """A long list broken into single-key pages.

    Two columns where the width allows, because 64 modems in one column is
    four pages of scrolling and one of reading.
    """
    per_page = max(1, min(len(PAGE_KEYS), (height - 6) * (2 if width >= 60 else 1)))
    pages = max(1, (len(names) + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    chunk = names[page * per_page:(page + 1) * per_page]
    items = [(PAGE_KEYS[i], name) for i, name in enumerate(chunk)]
    return {
        "title": f"{title}  page {page + 1}/{pages}",
        "items": items,
        "footer": "Esc  back      PgUp/PgDn  more",
    }, page, pages, {PAGE_KEYS[i]: n for i, n in enumerate(chunk)}


def selectable(menu):
    """Indices of items that can actually be chosen.

    The station menu lists read-only fields keyed with a space; arrow-key
    navigation has to step over them rather than land on a row that does
    nothing when Enter is pressed.
    """
    return [i for i, (key, _) in enumerate(menu["items"]) if key.strip()]


def _mark(is_selected):
    """Marker and text style for a menu row.

    Reverse video was the obvious choice and it was unreadable on the panel:
    the selected row's text disappeared into its own highlight. A leading
    marker plus a step from dim to bright carries the same information without
    depending on how a particular console renders an attribute.
    """
    return ("\u25b8 ", "bright") if is_selected else ("  ", "dim")


def render(menu, width, height, selected=None):
    """A menu as rendered lines: list of (text, kind) segments.

    `selected` is an index into menu["items"]; that row is drawn in reverse
    video so the arrow keys have something to point at.
    """
    lines = [[(" " + menu["title"][:width - 2].ljust(width - 1), "reverse")],
             [("", "bright")]]

    items = menu["items"]
    two_col = width >= 60 and len(items) > (height - 6)
    if two_col:
        half = (len(items) + 1) // 2
        col_w = (width - 3) // 2
        for i in range(half):
            left = items[i]
            right = items[i + half] if i + half < len(items) else None
            lm, lk = _mark(selected == i)
            segs = [(lm, "bright"), (f"{left[0]} ", "bright"),
                    (left[1][:col_w - 4].ljust(col_w - 2), lk)]
            if right:
                rm, rk = _mark(selected == i + half)
                segs += [(rm, "bright"), (f"{right[0]} ", "bright"),
                         (right[1][:col_w - 4], rk)]
            lines.append(segs)
    else:
        for i, (key, label) in enumerate(items):
            mark, kind = _mark(selected == i)
            lines.append([(mark, "bright"), (f"{key}  ", "bright"),
                          (label[:width - 8], kind)])

    while len(lines) < height - 2:
        lines.append([("", "bright")])
    lines = lines[:height - 2]
    lines.append([("─" * width, "dim")])
    lines.append([(" " + menu["footer"][:width - 2], "dim")])
    return lines[:height]


def _duration(minutes):
    """A time-out as an operator reads it: `45 min`, `2 h`, `12 h`, `off`.

    Minutes all the way up read badly once they pass an hour -- a twelve
    hour time-out printed as `720 min` is arithmetic the reader has to do.
    """
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        return "off"
    if minutes <= 0:
        return "off"
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h" if not rest else f"{hours} h {rest} min"


def wspr_menu(state=None):
    """The WSPR menu. Grouped the way the logging menu is.

    State, then the session, then the schedule, then the file — with the
    current value on each line, because that is what makes the logging menu
    readable without opening anything.

    The four toggles are single keys and each shows its own state, so an
    operator who opens this menu to check what is on does not have to open
    anything else. See `docs/wspr_design.md` §6a and §10.
    """
    st = dict(state or {})

    def onoff(key, extra=""):
        return ("on" if st.get(key) else "off") + (f" — {extra}" if extra
                                                   else "")

    band = str(st.get("band") or "(none)")
    if st.get("hopping"):
        band += f"  hopping {st.get('hop_count', 0)} bands"
    tot = st.get("timeout_minutes")
    items = [
        # -- what it is doing ---------------------------------------------
        ("w", f"WSPR                         {onoff('wspr')}"),
        ("d", f"Decode                       {onoff('decode')}"),
        ("t", f"Transmit                     {onoff('transmit')}"),
        ("n", f"Transmit next slot           {onoff('tx_next')}"),

        # -- the session ---------------------------------------------------
        ("e", f"Session                      "
              f"{st.get('session') or '(none)'}"),
        ("b", f"Band                         {band}"),

        # -- the schedule --------------------------------------------------
        ("p", f"Transmit percent             {st.get('tx_percent', 0)}%"),
        # "Time-out" alone did not say time out of WHAT -- the slot, the
        # decode and the session all have clocks. It is the session's.
        ("o", f"Session ToT                  " + _duration(tot)),
        ("u", f"Upload spots                 {st.get('upload') or 'off'}"),

        # -- the file, and getting out ------------------------------------
        ("f", f"Spot log                     "
              f"{st.get('log_name') or 'wspr.log'}"),
        ("x", f"Export this session          "
              f"{st.get('heard', 0)} heard, {st.get('sent', 0)} sent"),
    ]
    # Only with a radio that can be tested into. Keyed and time-bounded, so
    # it sits behind a menu rather than under a key that can be brushed.
    # **One row, not three.** The transmit level, the capture gain and the
    # test tone that sets them are one concern -- §6b calls it calibrating
    # the audio -- and they were three rows that pushed this menu to 16.
    # `menus.render` goes two-column above `height - 6`, which on the panel
    # is 14, and the second column has no room for the values. A WSPR menu
    # without its current values on the lines is the one thing this menu is
    # for, so the item count is a design constraint and not an accident.
    items.append(("a", f"Audio levels                 "
                       f"TX {st.get('tx_level', 50)}%  "
                       f"RX {st.get('rx_gain', 70)}%"))
    # Last, and named so nobody arrives in it by accident.
    items.append(("z", "Danger zone — clear spots"))
    return {
        "title": "WSPR",
        "items": items,
        "footer": "Esc back   ↑↓ move   Enter select   "
                  "^O ^P locked while running",
    }


def wspr_audio_menu(state=None):
    """Transmit level, capture gain, and the tone that sets the first.

    Together because they are one job, and because the measured dBFS of the
    last capture belongs beside the gain it judges -- a gain control with no
    meter is a knob.

    The two are set by DIFFERENT mechanisms and the menu says so, because an
    operator who knows the deck shares a codec with fldigi will reasonably
    ask which of these touches it. See §6a1.
    """
    st = dict(state or {})
    dbfs = st.get("dbfs")
    heard = ("no reading yet" if dbfs is None
             else f"{float(dbfs):.0f} dBFS")
    # **The levels are reported here and changed in the calibration
    # screens.** Stepping them from this menu was a third way to do the same
    # thing, with no meter in sight -- and a level set without watching
    # something is a number changed, not a level set.
    return {
        "title": "WSPR AUDIO",
        "items": [
            (" ", f"   TX audio {st.get('tx_level', 50)}%"
                  f"     RX gain {st.get('rx_gain', 70)}%"
                  f"     {heard}"),
            (" ", ""),
            ("c", "Calibrate transmit        a tone, + and - to set"),
            ("m", "Calibrate receive         a meter, + and - to set"),
        ],
        "footer": "Esc back   ↑↓ move   Enter select   "
                  "the levels are set in those screens",
    }


def wspr_danger_menu(session="", heard=0, sent=0, total_heard=0,
                     total_sent=0, sessions=0):
    """The three ways to throw spots away. Counts broken out BY KIND.

    "473 records" hides which: an operator about to lose a night of received
    data cares about a different number than one clearing their own
    transmission history. See `docs/wspr_design.md` §5a.
    """
    return {
        "title": "WSPR DANGER ZONE",
        "items": [
            ("a", f"Forget all sessions          "
                  f"{sessions} in the list, spots kept"),
            # The session NAME is not on this line. With a name of any
            # length the line ran past 66 and was cut mid-word -- "from
            # Satu" -- which is the fault the log's columns were rebuilt to
            # avoid. The name goes in the footer, where there is room, and
            # the counts are what make the question worth reading.
            ("s", f"Delete this session's spots  "
                  f"{heard} heard + {sent} sent"),
            ("m", f"Delete EVERY WSPR record     "
                  f"{total_heard} heard + {total_sent} sent"),
        ],
        "footer": ("Esc back   ↑↓ move   Enter select   "
                   + (session[:24] if session else "general")),
    }


def wspr_band_menu(chosen=(), current=""):
    """Pick the band, or the set to hop through.

    The keys are `menus.BANDS`' own -- same eleven bands, same digits, `a`
    for 70 cm -- so a band key an operator already knows means the same band
    here. The FREQUENCIES differ: that table holds digimode calling
    frequencies and this one WSPR dial frequencies.

    A band already in the rotation is marked `*` and the one in use is marked
    `<`.

    **A number or Enter selects that band alone and tunes to it; Space
    toggles the highlighted band in and out of the hop rotation.** `[*]`
    marks a band in the rotation and `<` the one in use.

    Two idioms came before this one. Membership-toggling on a bare number
    meant pressing 20 m from a default of 40 m gave a two-band rotation
    rather than 20 m, when an operator pressing a band key means "go
    there". Replacing it with `+` then a number fixed that and introduced a
    worse problem: a two-key prefix with no visible state between the keys,
    reported as undiscoverable in exactly those terms. Space acts on the row
    the arrows are already on, and the `[*]` is the checkbox it implies.
    """
    import wsprbands
    picked = set(chosen or ())
    items = []
    for key, label, dial in wsprbands.BANDS:
        mark = "[*]" if label in picked else "[ ]"
        here = " <" if label == current else ""
        items.append((key, f"{mark} {label:<6} "
                           f"{dial / 1_000_000:>11.6f} MHz{here}"))
    title = "WSPR BAND"
    if len(picked) > 1:
        title += f" — hopping {len(picked)}"
    # **No mode check here.** Selecting a band now SETS it to a data mode
    # and gives the previous mode back on leaving -- the check this replaced
    # told the operator to go and do by hand what the deck can do itself.
    return {"title": title, "items": items,
            "footer": "Esc back  Enter use this one  "
                      "Space hop on/off  [*] in rotation"}
