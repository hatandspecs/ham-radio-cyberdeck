"""Station settings, read from cyberdeck.conf.

The same `KEY = value` form as the iGate project's configuration, so the two
read alike: blank lines and `#` comments ignored, values trimmed, unknown keys
refused rather than silently absorbed. An unknown key is almost always a typo,
and a typo that is ignored becomes a setting that mysteriously does nothing.
"""

import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

# Two layouts have to work. On the deck the modules are installed flat into
# /opt/cyberdeck alongside cyberdeck.conf, so the file sits next to this one.
# In the repository the modules are in src/ and the configuration is at the
# project root, one level up. Checking both keeps a single code path for the
# running deck and for anything driven from a checkout.
_CANDIDATES = (
    os.path.join(HERE, "cyberdeck.conf"),
    os.path.join(os.path.dirname(HERE), "cyberdeck.conf"),
)
DEFAULT_PATH = next((c for c in _CANDIDATES if os.path.exists(c)), _CANDIDATES[0])

# The environment wins, so a test can hand the deck a configuration of its own
# without editing the one in the checkout — the same reason
# CYBERDECK_STATE_PATH exists. Nothing on the deck sets it.
DEFAULT_PATH = os.environ.get("CYBERDECK_CONF") or DEFAULT_PATH

# Secrets live beside the configuration and never in it, for the reason the
# iGate project keeps igate.secrets separate: cyberdeck.conf describes a
# station and gets copied, pasted into a message, and read over somebody's
# shoulder at a club meeting. A key does not belong in a file that travels.
#
# Not deck.secrets, which is a different thing — that is consumed by
# build_deck_image.sh on a laptop and baked into the card, so changing a value
# in it means building a new card. This one is read at every start by the
# running deck, which is what a key that can be regenerated needs.
_SECRET_CANDIDATES = (
    os.path.join(HERE, "cyberdeck.secrets"),
    os.path.join(os.path.dirname(HERE), "cyberdeck.secrets"),
)
SECRETS_PATH = next((c for c in _SECRET_CANDIDATES if os.path.exists(c)),
                    _SECRET_CANDIDATES[0])
SECRETS_PATH = os.environ.get("CYBERDECK_SECRETS") or SECRETS_PATH

# Which settings may appear in the secrets file. Anything else there is an
# error for the same reason an unknown key in cyberdeck.conf is: a typo that
# is silently ignored becomes a credential that mysteriously does nothing.
SECRET_KEYS = ("QRZ_API_KEY", "QRZ_USER", "QRZ_PASSWORD",
               "HAMQTH_USER", "HAMQTH_PASSWORD")

# Non-fatal problems found by the last load(), in the order found. The deck
# prints these to stderr at startup so the journal carries them.
#
# A secrets file that cannot be READ lands here rather than raising. It once
# raised, and the result was a deck that crash-looped at 3-second intervals
# with a bare console on tty1: `sudo cp` into /opt/cyberdeck made the file
# root-owned, `chmod 600` locked the service user out of it, and load() died
# before curses started. Credentials are optional on every deck; the panel is
# the device. An unreadable credentials file costs callbook lookups, and that
# is all it may cost.
NOTES = []

# key -> (default, converter, description)
SCHEMA = {
    "CALLSIGN":        ("", str, "this station's callsign"),
    "NAME":            ("", str, "operator name, for macros"),
    "QTH":             ("", str, "location, for macros"),
    "LOCATOR":         ("", str, "Maidenhead grid square"),
    "RIG":             ("", str, "radio, for memories: {rig}, and logged as "
                                 "MY_RIG on every contact"),
    "ANTENNA":         ("", str, "antenna, for memories: {ant}, and logged as "
                                 "MY_ANTENNA on every contact"),
    # The ceiling of whatever configuration is in use. hamlib reports the
    # power control as a position between 0 and 1, not a wattage, so this is
    # what turns the position into watts — and it is the one number that
    # changes when the station changes. On this station: 6 on the internal
    # battery, 10 on external power, 100 with the amplifier.
    #
    # Generic on purpose. Reading watts straight out of the radio needs a
    # command only that radio has; one setting works on any rig hamlib can
    # drive. See docs/qso_log_design.md §6c.
    "TX_POWER_MAX":    (0, int, "maximum transmit power in watts for the "
                                "current configuration; scales the CAT power "
                                "reading. 0 means do not scale"),
    # Watts. The fallback for when the radio cannot be asked at all: `{power}`
    # and the log prefer a CAT reading and fall back to this.
    "TX_POWER":        (0, int, "transmit power in watts when the radio "
                                "cannot be read, for memories: {power}, and "
                                "logged as TX_PWR"),
    "RIG_BANDS":       ("", str, "bands this radio covers, comma separated, "
                                 "e.g. '80 m, 40 m, 20 m'. Empty means all of "
                                 "them — the FTX-1 covers every band listed"),

    # Logging. Off, and absent when off: no key bound, no status field, no
    # file created, nothing in the main loop. See docs/qso_log_design.md §1.
    # This is the value at boot; the menu toggle overrides it in the state
    # file, the same arrangement REMEMBER_STATE uses for mode and carrier.
    "LOGGING":         ("no", str, "yes | no — the contact log, off by default"),
    "LOG_PATH":        ("", str, "contact log file; blank means "
                                 "~/.local/share/cyberdeck/qso.log"),
    # How tall one contact is in the list. One line is the contact; two adds
    # where they are; three adds this station's side and the notes. A contact
    # always takes exactly this many rows, blank ones included, because the
    # arrows select whole contacts.
    "LOG_LINES":       ("1", str, "1 | 2 | 3 — lines per contact in the log "
                                  "list; more shows more fields, fewer shows "
                                  "more contacts"),
    # The session in progress, as an ISO timestamp. Written onto every
    # contact of the session so that a session is (ACTIVITY, ACTIVITY_START)
    # -- which is what lets one park be activated twice and an activation
    # cross UTC midnight. Normally set on the panel and remembered in the
    # state file; in the conf it pins a session for an unattended start.
    "ACTIVITY_START":  ("", str, "the session's start, ISO 8601; blank means "
                                 "the master log. Set on the panel"),
    # There is deliberately no POTA setting. POTA is an activity — ACTIVITY =
    # POTA — because a toggle and an activity that both mean "show the park
    # fields" are two controls for one thing, and they drift.
    "MY_PARK":         ("", str, "this station's POTA or SOTA reference while "
                                 "activating, e.g. US-5678; blank otherwise"),
    "OPERATING":       ("auto", str, "auto | digital | voice — where the "
                                     "logged mode comes from. auto fills it "
                                     "in from fldigi on digital and leaves "
                                     "voice alone; see qso_log_design.md §6"),
    # An ACTIVITY is one operating session the operator names: a park
    # activation, a weekend of a QSO party. An ACTIVITY_TYPE is the template
    # it uses -- GENERAL, POTA, CONTEST, or one built on the panel. These were
    # a single setting holding the type name; a conf that still spells it that
    # way is read as both, and says so in config.NOTES.
    "ACTIVITY":        ("", str, "name of the current logging session, e.g. "
                                 "'Bald Eagle SP'; blank is casual logging. "
                                 "Each activity gets its own log file"),
    "ACTIVITY_TYPE":   ("", str, "which activity type the current activity "
                                 "uses: GENERAL, POTA, CONTEST or one of your "
                                 "own. See activities.conf and "
                                 "qso_log_design.md §6b"),
    "EXCHANGE_TX":     ("", str, "this station's exchange for the current "
                                 "activity — a class, county or section; the "
                                 "same on every contact of an event"),
    # Which earlier contact counts as already worked. The right answer is a
    # property of the event, not of the logger: a QSO party scores once per
    # band, Field Day once per band and mode, a park activation not at all.
    "DUPE_CHECK":      ("band+mode", str, "off | call | band | mode | "
                                          "band+mode — when to say a station "
                                          "has been worked before"),
    # On by default (2026-10-14, the operator's decision). It sends every
    # call worked to a third party, which is why it remains a setting of its
    # own rather than following LOGGING -- but a name and a grid filled in
    # automatically is most of what a log is for, and a station with no
    # network simply shows "no wifi" instead of pretending to be off.
    "CALLBOOK":        ("yes", str, "yes | no — look up callsigns over the "
                                    "network. Sends every call worked to a "
                                    "third party. On, it reads 'no wifi' when "
                                    "there is no default route"),

    # Secrets. These are NOT read from cyberdeck.conf — see SECRETS_PATH below
    # and the note on `load`. They are listed here so the rest of the program
    # can read settings["QRZ_API_KEY"] without knowing where it came from.
    "QRZ_API_KEY":     ("", str, "QRZ logbook API key; read from "
                                 "cyberdeck.secrets, never from cyberdeck.conf"),
    # QRZ's XML callsign lookup, which is a DIFFERENT service from the logbook
    # upload above with a different credential and a different subscription.
    # An account name and password, not a key.
    "QRZ_USER":        ("", str, "QRZ account name for XML callsign lookup; "
                                 "read from cyberdeck.secrets"),
    "QRZ_PASSWORD":    ("", str, "QRZ account password; read from "
                                 "cyberdeck.secrets"),
    # HamQTH covers the world where callook.info covers only the US. It needs
    # an account, so the credentials are secrets, not configuration.
    "HAMQTH_USER":     ("", str, "HamQTH account callsign; read from "
                                 "cyberdeck.secrets"),
    "HAMQTH_PASSWORD": ("", str, "HamQTH password; read from "
                                 "cyberdeck.secrets"),

    # LoTW. Signing happens off the deck — see qso_log_design.md §11 — so
    # there is no certificate and no passphrase here, only the station
    # location name tqsl was configured with, which the export note quotes
    # back so the command can be copied and pasted.
    "LOTW_LOCATION":   ("", str, "tqsl Station Location name for this "
                                 "station, e.g. 'Home'; blank if unused"),

    "WIFI_ON_START":   ("yes", str, "switch the WiFi radio back on at every start"),
    "DEFAULT_MODE":    ("BPSK31", str, "modem selected at startup"),
    "DEFAULT_CARRIER": (1500, int, "audio carrier parked here, in Hz"),
    "COLOR":          ("matrix", str, "matrix | deckard | hal | tron | ripley"),
    "FONT":            ("12x24", str, "console font; sets the character grid"),

    "FLDIGI_URL":      ("http://127.0.0.1:7362/", str, "fldigi's XML-RPC address"),
    # Where rigctld is. Configurable rather than hard-coded so a second
    # instance can be addressed -- which is what `tools/deck_local.py` needs
    # when a real fldigi or rigctld already holds the usual port.
    "RIGCTLD_HOST":    ("127.0.0.1", str, "rigctld's address"),
    "RIGCTLD_PORT":    (4532, int, "rigctld's port"),
    "POLL_MS":         (200, int, "how often to ask fldigi for new text"),
    "SCROLLBACK":      (2000, int, "transcript lines kept in memory"),
    "TX_TIMEOUT":      (180, int, "seconds before an over is aborted; 0 disables"),
    "RX_HOLD_MS":      (1000, int, "always ignore decodes for this long after "
                                   "an over ends; the receiver recovering from "
                                   "transmit decodes as garbage. 0 disables"),
    "RX_HOLD_MAX_MS":  (4000, int, "keep ignoring them, up to this long, until "
                                   "the modem reports a real signal. 0 uses the "
                                   "fixed RX_HOLD_MS window instead"),
    "TIMESTAMPS":      ("yes", str, "yes | no"),
    "TOUCH":           ("yes", str, "yes | no — drag the transcript to scroll"),
    "PAIR_ON_NO_KEYBOARD": ("yes", str, "yes | no — open the pairing screen at "
                                        "startup when no keyboard exists to "
                                        "open it with"),
    "TOUCH_DEVICE":    ("", str, "/dev/input/eventN; empty finds the "
                                 "touchscreen by capability"),
    "TOUCH_ROW_PIXELS": (24, int, "the console cell height, so a drag of one "
                                  "row moves the transcript by one line"),
    "INHIBIT_ON_START": ("yes", str, "yes | no — start with transmit inhibited"),
    # NOT written to the radio. The deck reports the rig's mode and never
    # changes it -- see cyberdeck._report_rig_mode. Kept in the schema so an
    # existing cyberdeck.conf still loads, and because the value records what
    # this station's data mode is for anyone reading the file.
    "RIG_MODE":        ("PKTUSB", str, "this station's data mode, for "
                                       "reference only. The deck reports the "
                                       "radio's mode and never sets it; "
                                       "transmit is inhibited while the radio "
                                       "is not in a data mode"),
    "RSID_ON_START":   ("yes", str, "yes | no — follow other stations' mode "
                                    "identifiers automatically"),
    "REMEMBER_STATE":  ("yes", str, "yes | no — restore mode, carrier, color "
                                    "and timestamps across restarts"),
    "STATE_PATH":      ("~/.local/state/cyberdeck.json", str,
                        "where that is kept; delete it to start clean"),

    # Message memories, inserted at the cursor by F5-F12. {call}, {name},
    # {qth}, {grid}, {rig} and {ant} are replaced from the station settings
    # above, and {power} from the radio itself when it answers, so
    # a memory does not have to be rewritten when the callsign changes.
    # Memories edited on the deck are written to STATE_PATH and override these.
    "MEMORY_5":  ("CQ CQ CQ DE {call} {call} {call} PSE K", str, "F5"),
    "MEMORY_6":  ("DE {call} {call} K", str, "F6"),
    "MEMORY_7":  ("NAME HR IS {name} {name}, QTH {qth} {qth}. HW? BTU", str, "F7"),
    "MEMORY_8":  ("RIG IS {rig} RUNNING {power} TO {ant}. ", str, "F8"),
    "MEMORY_9":  ("TNX FB QSO. 73 ES GD DX. DE {call} SK", str, "F9"),
    "MEMORY_10": ("", str, "F10"),
    "MEMORY_11": ("", str, "F11"),
    "MEMORY_12": ("", str, "F12"),
}

COLORS = ("matrix", "deckard", "hal", "tron", "ripley")

# Duplicated from qsolog rather than imported: config.py is loaded before
# anything else and importing a feature module into it would make the
# configuration depend on the feature, which is backwards.
_PARK_RE = re.compile(r"^[A-Z]{1,3}-\d{3,5}$")


class ConfigError(Exception):
    pass


# Settings renamed since a config file may have been written. Accepting the
# old spelling costs one lookup; refusing it would stop the terminal from
# starting at all, since an unknown key is an error — and a deck that will not
# boot because a file says COLOUR is a poor trade for consistency.
ALIASES = {
    "COLOUR": "COLOR",
}


def load(path=None, secrets_path=None):
    """Return a dict of settings. A missing file is not an error: the
    defaults describe a usable station that simply has no callsign yet, and
    refusing to start over a missing file would be unhelpful on a first run."""
    path = path or DEFAULT_PATH
    del NOTES[:]
    values = {k: v[0] for k, v in SCHEMA.items()}
    if not os.path.exists(path):
        return values

    unknown = []
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if "=" not in line:
                raise ConfigError(f"{path}:{lineno}: expected KEY = value")
            key, _, value = line.partition("=")
            key, value = key.strip().upper(), value.strip()
            key = ALIASES.get(key, key)
            if key not in SCHEMA:
                unknown.append(f"{path}:{lineno}: unknown setting '{key}'")
                continue
            if key in SECRET_KEYS:
                # Refused, not quietly honored. The whole point of the split is
                # that cyberdeck.conf is safe to hand over — pasted into a
                # message, read over a shoulder at a club meeting. A credential
                # that works from here is a credential that travels, and it
                # would work silently, which is the worst of both.
                raise ConfigError(
                    f"{path}:{lineno}: {key} is a credential and does not "
                    f"belong in this file, which gets copied around. Put it in "
                    f"{SECRETS_PATH} instead (mode 600).")
            converter = SCHEMA[key][1]
            try:
                values[key] = converter(value)
            except ValueError:
                raise ConfigError(
                    f"{path}:{lineno}: {key} = '{value}' is not a "
                    f"{converter.__name__}") from None

    if unknown:
        raise ConfigError("\n".join(unknown))

    _load_secrets(values, secrets_path)
    _split_activity(values)
    validate(values)
    return values


def _split_activity(values):
    """Read an old ACTIVITY that named a type, not a session.

    Before an activity and an activity type were different things, ACTIVITY
    held the type: `ACTIVITY = POTA`. Such a line is read as both -- a session
    called POTA using the POTA type -- which is what the deck did then and
    loses nothing. Anything else in ACTIVITY is a session name and is left
    alone.
    """
    name = str(values.get("ACTIVITY", "") or "").strip()
    kind = str(values.get("ACTIVITY_TYPE", "") or "").strip()
    if not name or kind:
        return values
    if name.upper() in ("GENERAL", "POTA", "CONTEST"):
        values["ACTIVITY_TYPE"] = name.upper()
        NOTES.append(
            "cyberdeck.conf: ACTIVITY = {0} names an activity TYPE. It is "
            "being read as an activity called {0} using the {0} type. Set "
            "ACTIVITY_TYPE = {0} and give ACTIVITY the name of the session "
            "to silence this.".format(name.upper()))
    return values


def _load_secrets(values, path=None):
    """Overlay cyberdeck.secrets, if there is one.

    A missing file is the normal case and not an error — most decks have no
    credentials at all, and the features that want them are off by default.
    A key named here that is not in SECRET_KEYS is refused, so a value put in
    the wrong file is reported rather than ignored.

    An UNREADABLE file is a note, not an error. See NOTES.
    """
    # The environment is consulted here rather than only at import, so a test
    # can point this somewhere empty after the module is loaded. Without that
    # every test calling load() silently picks up the operator's real key.
    path = path or os.environ.get("CYBERDECK_SECRETS") or SECRETS_PATH
    if not os.path.exists(path):
        return values

    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        NOTES.append(
            f"{path}: cannot be read ({exc.strerror}), so callbook lookups "
            f"have no credentials. It is most likely owned by root rather "
            f"than by the user the deck runs as -- chown it to that user and "
            f"chmod it 600.")
        return values

    unknown = []
    for lineno, raw in enumerate(lines, 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if "=" not in line:
            raise ConfigError(f"{path}:{lineno}: expected KEY = value")
        key, _, value = line.partition("=")
        key, value = key.strip().upper(), value.strip()
        if key not in SECRET_KEYS:
            unknown.append(
                f"{path}:{lineno}: '{key}' does not belong in a secrets "
                f"file (expected one of: {', '.join(SECRET_KEYS)})")
            continue
        values[key] = value
    if unknown:
        raise ConfigError("\n".join(unknown))
    return values


def validate(values):
    if values["COLOR"].lower() not in COLORS:
        raise ConfigError(
            f"COLOR = '{values['COLOR']}' is not one of: {', '.join(COLORS)}")
    values["COLOR"] = values["COLOR"].lower()

    if not 100 <= values["DEFAULT_CARRIER"] <= 4000:
        raise ConfigError(
            f"DEFAULT_CARRIER = {values['DEFAULT_CARRIER']} is outside any SSB "
            "passband; use something like 1500")

    if not 50 <= values["POLL_MS"] <= 5000:
        raise ConfigError(f"POLL_MS = {values['POLL_MS']} is not sensible")

    if values["TX_TIMEOUT"] < 0 or values["TX_TIMEOUT"] > 3600:
        raise ConfigError("TX_TIMEOUT must be 0 (disabled) to 3600 seconds")

    if values["SCROLLBACK"] < 100:
        raise ConfigError("SCROLLBACK below 100 lines is not worth keeping")

    if values["TIMESTAMPS"].lower() not in ("yes", "no"):
        raise ConfigError("TIMESTAMPS must be yes or no")
    values["TIMESTAMPS"] = values["TIMESTAMPS"].lower()

    for key in ("LOGGING", "CALLBOOK"):
        if values[key].lower() not in ("yes", "no"):
            raise ConfigError(f"{key} must be yes or no")
        values[key] = values[key].lower()

    for key in ("TX_POWER", "TX_POWER_MAX"):
        if not 0 <= values[key] <= 2000:
            raise ConfigError(
                f"{key} = {values[key]} is not a plausible wattage; "
                "0 means 'leave it to the radio'")

    import qsolog as _qsolog
    if values["DUPE_CHECK"].lower() not in _qsolog.DUPE_RULES:
        raise ConfigError(
            f"DUPE_CHECK = '{values['DUPE_CHECK']}' must be one of: "
            f"{', '.join(_qsolog.DUPE_RULES)}")
    values["DUPE_CHECK"] = values["DUPE_CHECK"].lower()

    if values["OPERATING"].lower() not in ("auto", "digital", "voice"):
        raise ConfigError(
            f"OPERATING = '{values['OPERATING']}' must be auto, digital or "
            "voice")
    values["OPERATING"] = values["OPERATING"].lower()

    # A park reference typed into the configuration with the wrong shape is
    # worth refusing at start rather than discovering in an upload that POTA
    # rejects weeks later.
    park = values["MY_PARK"].strip().upper()
    if park and not _PARK_RE.match(park):
        raise ConfigError(
            f"MY_PARK = '{values['MY_PARK']}' is not a POTA reference "
            "(expected something like US-5678)")
    values["MY_PARK"] = park
    return values
