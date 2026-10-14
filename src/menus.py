"""Full-screen menus, selected by a single key (docs/design_doc.md §5.8).

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


ROOT = {
    "title": "MENU",
    "items": [
        ("1", "Mode"),
        ("2", "Tune Settings"),
        ("3", "Band"),
        ("4", "Display"),
        ("5", "Memories"),
        ("6", "Station"),
        ("7", "System"),
        # Added together with its handler in cyberdeck.py, which is the rule:
        # a root entry whose Enter does nothing is worse than no entry, since
        # being discoverable is the line's only job and it then lies.
        ("8", "Logging"),
    ],
    "footer": "Esc back to the conversation   ↑↓ move   Enter select",
}

DISPLAY = {
    "title": "DISPLAY",
    "items": [
        ("1", "Color: Matrix   green"),
        ("2", "Color: Deckard  amber"),
        ("3", "Color: Hal      red"),
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
        "title": "ACTIVITY TYPE",
        "items": items,
        # `d` then a number deletes one, and then asks: two keystrokes and
        # a confirmation, because a type an operator spent a contest getting
        # right should not go on one.
        "footer": "Esc back   Enter select   d+number deletes   * in use",
    }


def log_menu(on, count=0, park="", lookup=False, has_qrz_key=False,
             qrz_pending=0, operating="auto", has_tqsl=False,
             activity="", dupe="band+mode", log_name="",
             activity_type=""):
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

    items = [
        ("l", f"Logging                      on — {count} "
              f"QSO{'' if count == 1 else 's'}"),
        # The DEFAULT log, which is also the directory the per-activity logs
        # sit beside. It is not the file in use unless logging is casual --
        # an activity has its own, named after it. Which file is actually
        # open is on the log screen's header, where it is read while typing
        # into it rather than two keystrokes away.
        ("f", f"Default log                  {log_name or 'qso.log'}"),
        ("a", "Export ADIF"),
        ("m", f"Mode from                    {_OPERATING_LABEL.get(operating, operating)}"),
        ("d", f"Duplicates                   {_DUPE_LABEL(dupe)}"),
        ("c", f"Callbook lookup              {'on' if lookup else 'off'}"),
        # Two lines, because these are two things. The ACTIVITY is the
        # session being logged -- this park, this contest weekend -- and it
        # carries the operator's name for it and a log file of its own. The
        # ACTIVITY TYPE is the template of fields it uses, edited once and
        # reused by every activity that wants it.
        #
        # They were one setting called "Activity". That let the operator
        # choose POTA but not say which activation it was, and made two
        # weekends of the same QSO party share one serial sequence.
        ("e", f"Activity                     "
              f"{activity or 'casual logging'}"),
        ("v", f"  Activity type              "
              f"{activity_type or 'general logging'}"),
        # Copy, change, name, save. Copying rather than starting blank
        # because every type an operator wants is a small change to one
        # that already exists.
        ("n", "    New type, copied from this one"),
    ]
    if needs_reference(activity_type):
        # Only when the selected activity has a reference field. Otherwise
        # this station's own park is not an unset field, it is a question that
        # does not apply to the operating being done.
        items.append(("p", f"    My reference             {park or 'not set'}"))
    extra = []
    if has_tqsl:
        # Signing needs a callsign certificate and tqsl blocks rather than
        # failing without one, so this is an export-and-a-command, not a
        # one-key upload. The label says so: nothing is sent from here.
        extra.append(("t", "Export + print the LoTW command"))
    items[2:2] = extra
    return {
        "title": "LOGGING",
        "items": items,
        "footer": "Esc back   ↑↓ move   Enter select   ^N the log screen",
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
        ("i", "Transmit inhibit on/off      Ctrl-I  (also Tab)"),
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
