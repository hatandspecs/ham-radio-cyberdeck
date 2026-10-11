"""The runtime secrets file: cyberdeck.secrets.

Separate from cyberdeck.conf on purpose. The configuration describes a station
and gets copied, pasted into a message and read over a shoulder at a club
meeting; a key does not belong in a file that travels. Separate from
deck.secrets too, which is consumed on a laptop by build_deck_image.sh and
baked into the card — changing a value there means building a new card, which
is the wrong shape for a credential that can be regenerated in a browser.

The property worth testing is the refusal. A key put in the wrong file, or
misspelled, has to be reported: a credential that is silently ignored looks
exactly like a credential that is wrong, and the symptom is a feature that
does nothing for a reason nothing explains.
"""
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import config


def write(dirname, name, text):
    path = os.path.join(dirname, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


print("no secrets file")
with tempfile.TemporaryDirectory() as tmp:
    values = {"QRZ_API_KEY": ""}
    config._load_secrets(values, os.path.join(tmp, "nothing-here"))
    equals("a missing file is the normal case", values["QRZ_API_KEY"], "")

print("\nreading a key")
with tempfile.TemporaryDirectory() as tmp:
    path = write(tmp, "cyberdeck.secrets",
                 "# a comment\n\nQRZ_API_KEY = 0000-1111-2222-3333\n")
    values = {"QRZ_API_KEY": ""}
    config._load_secrets(values, path)
    equals("read", values["QRZ_API_KEY"], "0000-1111-2222-3333")

    path = write(tmp, "s2", "qrz_api_key=0000-1111-2222-3333  # trailing\n")
    values = {"QRZ_API_KEY": ""}
    config._load_secrets(values, path)
    equals("case and spacing do not matter", values["QRZ_API_KEY"],
           "0000-1111-2222-3333")

    path = write(tmp, "s3", "QRZ_API_KEY =\n")
    values = {"QRZ_API_KEY": "stale"}
    config._load_secrets(values, path)
    equals("an empty value clears it", values["QRZ_API_KEY"], "")

print("\nwhat does not belong")
with tempfile.TemporaryDirectory() as tmp:
    path = write(tmp, "s", "CALLSIGN = KD3CCO\n")
    try:
        config._load_secrets({"QRZ_API_KEY": ""}, path)
        check("a setting in the secrets file is refused", False, "no error")
    except config.ConfigError as e:
        check("a setting in the secrets file is refused", True)
        check("and the message names it", "CALLSIGN" in str(e), str(e))
        check("and says what was expected", "QRZ_API_KEY" in str(e), str(e))

    path = write(tmp, "s2", "QRZ_API_KY = oops\n")
    try:
        config._load_secrets({"QRZ_API_KEY": ""}, path)
        check("a misspelled key is refused, not ignored", False, "no error")
    except config.ConfigError:
        check("a misspelled key is refused, not ignored", True)

    path = write(tmp, "s3", "QRZ_API_KEY\n")
    try:
        config._load_secrets({"QRZ_API_KEY": ""}, path)
        check("a line with no = is refused", False, "no error")
    except config.ConfigError:
        check("a line with no = is refused", True)

print("\nthe schema knows about it")
check("QRZ_API_KEY is a setting", "QRZ_API_KEY" in config.SCHEMA)
equals("and defaults to nothing", config.SCHEMA["QRZ_API_KEY"][0], "")
check("and is listed as a secret", "QRZ_API_KEY" in config.SECRET_KEYS)

print("\na credential in cyberdeck.conf is refused, not quietly honored")
# This behavior CHANGED on 2026-10-11, and the earlier version is worth
# recording because it was the weaker design. A secret in cyberdeck.conf used
# to work and merely be overridden by the secrets file. But cyberdeck.conf is
# the file meant to be safe to hand over — pasted into a message, read over a
# shoulder at a club meeting — and a credential that works from it is a
# credential that travels. Silently honoring it is the worst of both: it works,
# so nobody moves it, and it leaks.
with tempfile.TemporaryDirectory() as tmp:
    for key in ("QRZ_API_KEY", "HAMQTH_PASSWORD", "HAMQTH_USER"):
        conf = write(tmp, "cyberdeck.conf", f"{key} = whatever\n")
        # Hermetic on purpose. Without an explicit path this reads the
        # operator's real cyberdeck.secrets, which is how the first version of
        # this test failed — it asserted the conf value and got the real key
        # instead. A test that depends on whether the machine running it has
        # credentials is not a test.
        try:
            config.load(conf, secrets_path=os.path.join(tmp, "absent"))
        except config.ConfigError as exc:
            check(f"{key} is refused there", "does not belong in this file"
                  in str(exc), str(exc))
            check(f"and {key}'s message names where it does belong",
                  "cyberdeck.secrets" in str(exc), str(exc))
        else:
            check(f"{key} should have been refused", False, "it was accepted")

    # A non-secret setting in the same file is untouched by all of that.
    conf = write(tmp, "cyberdeck.conf", "CALLSIGN = KD3CCO\nACTIVITY = POTA\n")
    loaded = config.load(conf, secrets_path=os.path.join(tmp, "absent"))
    equals("ordinary settings still load", loaded["CALLSIGN"], "KD3CCO")
    equals("including the new ones", loaded["ACTIVITY"], "POTA")

    # And the secrets file remains the one place they work.
    secrets = write(tmp, "cyberdeck.secrets",
                    "QRZ_API_KEY = from-the-secrets\n"
                    "HAMQTH_USER = KD3CCO\n"
                    "HAMQTH_PASSWORD = pw\n")
    loaded = config.load(conf, secrets_path=secrets)
    equals("the secrets file supplies the key", loaded["QRZ_API_KEY"],
           "from-the-secrets")
    equals("and the HamQTH user", loaded["HAMQTH_USER"], "KD3CCO")
    equals("and the HamQTH password", loaded["HAMQTH_PASSWORD"], "pw")

print("\nHamQTH credentials are secrets, like the QRZ key")
for key in ("HAMQTH_USER", "HAMQTH_PASSWORD"):
    check(f"{key} is in the schema", key in config.SCHEMA, key)
    check(f"{key} is listed as a secret", key in config.SECRET_KEYS,
          str(config.SECRET_KEYS))
    equals(f"{key} defaults to nothing", config.SCHEMA[key][0], "")

def conf(body):
    """config.load on a throwaway cyberdeck.conf, with no secrets file.

    The secrets path is pinned at /nonexistent so this never reads the real
    cyberdeck.secrets on the machine running the test — a test that depends on
    whether the machine has credentials is not a test.
    """
    with tempfile.TemporaryDirectory() as tmp:
        return config.load(write(tmp, "cyberdeck.conf", body),
                           secrets_path=os.path.join(tmp, "nonexistent"))


def refuses(body, phrase):
    try:
        conf(body)
    except config.ConfigError as exc:
        check(f"refused, saying {phrase!r}", phrase in str(exc), str(exc))
    else:
        check(f"should have refused {body.strip()!r}", False, "it did not")


print("\nthe new logging settings")
# There is deliberately no POTA setting: POTA is an activity. A toggle and an
# activity that both mean "show the park fields" are two controls for one
# thing, and they drift apart.
check("POTA is not a setting", "POTA" not in config.SCHEMA,
      "it was merged into ACTIVITY")
equals("ACTIVITY defaults to general logging", conf("")["ACTIVITY"], "")
equals("and names an activity", conf("ACTIVITY = POTA\n")["ACTIVITY"], "POTA")

equals("RIG is a station setting", conf("RIG = FTX-1\n")["RIG"], "FTX-1")
equals("so is ANTENNA", conf("ANTENNA = EFHW\n")["ANTENNA"], "EFHW")
equals("TX_POWER defaults to nothing known", conf("")["TX_POWER"], 0)
equals("and is a wattage", conf("TX_POWER = 20\n")["TX_POWER"], 20)
refuses("TX_POWER = 9000\n", "not a plausible wattage")

equals("OPERATING defaults to auto", conf("")["OPERATING"], "auto")
for value in ("auto", "digital", "voice"):
    equals(f"{value} is accepted", conf(f"OPERATING = {value}\n")["OPERATING"],
           value)
equals("and case is folded", conf("OPERATING = VOICE\n")["OPERATING"], "voice")
refuses("OPERATING = ssb\n", "auto, digital or voice")

equals("LOTW_LOCATION defaults to blank", conf("")["LOTW_LOCATION"], "")
equals("and is free text — tqsl names its own locations",
       conf("LOTW_LOCATION = Field Day\n")["LOTW_LOCATION"], "Field Day")
# No certificate and no passphrase in the schema, deliberately. Signing
# happens off the deck; see docs/qso_log_design.md §11.
check("no LoTW passphrase is a setting",
      not any("LOTW" in k and "PASS" in k for k in config.SCHEMA), "")
check("and no certificate path either",
      not any("LOTW" in k and "CERT" in k for k in config.SCHEMA), "")

sys.exit(report())
