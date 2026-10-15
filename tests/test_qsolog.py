"""The contact log's pure core: parsing, bands, modes, records and ADIF.

Everything here runs without curses, fldigi, rigctld or a clock, which is the
whole reason qsolog.py has none of them. What cannot be tested this way is
listed in §10 of docs/qso_log_design.md and needs the deck.

Two of these are pinned here because they are easy to get backwards later and
neither is visible from reading the code:

  * a single report in the input is the RECEIVED one, not the sent one. The
    sent report is what the operator already said out loud; the received one is
    the thing being written down. Backwards, this puts the wrong number in
    every casual QSO and nothing complains.
  * an absent ADIF field has to be omitted, not written empty. <BAND:0> is a
    band the reader could not parse; no BAND at all is a band that is unknown,
    and LoTW treats them differently.
"""
import datetime
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import qsolog
import activities


WHEN = datetime.datetime(2026, 10, 10, 16, 12, 3)


print("bands")
equals("40m", qsolog.band_for(7_074_000), "40m")
equals("20m", qsolog.band_for(14_070_000), "20m")
equals("80m lower edge", qsolog.band_for(3_500_000), "80m")
equals("80m upper edge", qsolog.band_for(4_000_000), "80m")
equals("WARC 30m is a band like any other", qsolog.band_for(10_120_000), "30m")
equals("2m", qsolog.band_for(144_390_000), "2m")
equals("between 40 and 30 is nothing", qsolog.band_for(8_000_000), "")
equals("no frequency", qsolog.band_for(None), "")
equals("zero", qsolog.band_for(0), "")
equals("not a number", qsolog.band_for("wobble"), "")

print("\nmodes")
equals("rig USB is SSB", qsolog.adif_mode("USB"), "SSB")
equals("rig LSB is SSB", qsolog.adif_mode("LSB"), "SSB")
equals("rig FM", qsolog.adif_mode("FM"), "FM")
equals("BPSK31 is PSK", qsolog.adif_mode("BPSK31"), "PSK")
equals("PSK125R is PSK", qsolog.adif_mode("PSK125R"), "PSK")
equals("QPSK63 is PSK", qsolog.adif_mode("QPSK63"), "PSK")
equals("RTTY", qsolog.adif_mode("RTTY-45"), "RTTY")
equals("Olivia", qsolog.adif_mode("Olivia 8/500"), "OLIVIA")
equals("MFSK16", qsolog.adif_mode("MFSK16"), "MFSK")
equals("CW", qsolog.adif_mode("CW"), "CW")
equals("Feld Hell", qsolog.adif_mode("FELDHELL"), "HELL")
equals("unknown modem survives", qsolog.adif_mode("Wobbulator-7"), "WOBBULATOR7")
equals("empty", qsolog.adif_mode(""), "")

print("\ndefault reports")
equals("SSB is two digits", qsolog.default_report("USB"), "59")
equals("FM is two digits", qsolog.default_report("FM"), "59")
equals("digital is three", qsolog.default_report("BPSK31"), "599")
equals("CW is three", qsolog.default_report("CW"), "599")

print("\ncallsigns")
check("plain", qsolog.is_callsign("W3ABC"))
check("two-letter prefix", qsolog.is_callsign("KD3CCO"))
check("portable", qsolog.is_callsign("W3ABC/P"))
check("stroke digit", qsolog.is_callsign("KD3CCO/3"))
check("lowercase accepted", qsolog.is_callsign("w3abc"))
check("no digit is not a call", not qsolog.is_callsign("HELLO"))
check("empty is not a call", not qsolog.is_callsign(""))

print("\nparsing")
equals("bare call", qsolog.parse_entry("W3ABC", "USB"),
       {"call": "W3ABC", "rst_s": "59", "rst_r": "59", "name": "", "qth": "",
        "park": "", "serial_rx": "", "exchange_rx": "", "comment": ""})
equals("lowercase is folded", qsolog.parse_entry("w3abc", "USB")["call"], "W3ABC")
equals("surrounding space", qsolog.parse_entry("  W3ABC  ", "USB")["call"], "W3ABC")

one = qsolog.parse_entry("W3ABC 57", "USB")
equals("one report is the RECEIVED one", one["rst_r"], "57")
equals("sent falls back to the default", one["rst_s"], "59")

both = qsolog.parse_entry("W3ABC 59 57", "USB")
equals("sent", both["rst_s"], "59")
equals("received", both["rst_r"], "57")

full = qsolog.parse_entry("W3ABC 59 57 Bob Pittsburgh PA", "USB")
equals("name", full["name"], "Bob")
# General logging has no `qth` field, so there is no position for one and the
# words after the name have nowhere to go. The field list IS the grammar: an
# operator who wants a QTH typed adds the field from the selector, and then
# this line means something different, which is the whole design.
equals("and nothing follows it under general logging", full["qth"], "")

named = qsolog.parse_entry("W3ABC Bob", "USB")
equals("a name where a report would be", named["name"], "Bob")
equals("and the reports default", named["rst_r"], "59")

digital = qsolog.parse_entry("W3ABC", "BPSK31")
equals("digital defaults to 599", digital["rst_s"], "599")

print("\nPOTA park references")
check("modern form", qsolog.is_park("US-1234"))
check("legacy K form", qsolog.is_park("K-0001"))
check("five digits", qsolog.is_park("CA-12345"))
check("lowercase accepted", qsolog.is_park("us-1234"))
check("a report is not a park", not qsolog.is_park("599"))
check("a call is not a park", not qsolog.is_park("W3ABC"))

hunt = qsolog.parse_entry("W3ABC 59 57 US-1234", "USB")
equals("park after the reports", hunt["park"], "US-1234")
equals("and nothing lands in name", hunt["name"], "")

named_park = qsolog.parse_entry("W3ABC 59 57 Bob US-1234", "USB")
equals("park found after a name", named_park["park"], "US-1234")
equals("name still parsed", named_park["name"], "Bob")

bare_park = qsolog.parse_entry("W3ABC us-1234", "USB")
equals("park with no reports", bare_park["park"], "US-1234")
equals("reports default", bare_park["rst_r"], "59")

equals("no park is empty, not missing",
       qsolog.parse_entry("W3ABC", "USB")["park"], "")

print("\nmalformed input")
for bad, why in (("", "empty"), ("   ", "whitespace only"), ("HELLO 59", "no callsign")):
    try:
        qsolog.parse_entry(bad, "USB")
        check(f"{why} raises", False, "no ParseError")
    except qsolog.ParseError as e:
        check(f"{why} raises", True)
        check(f"{why} says something useful", bool(str(e)), repr(str(e)))

print("\nrecords")
# The comment carries the multi-word value here. General logging has no `qth`
# field, so there is no position to type one into -- the field list IS the
# grammar -- and everything after a semicolon is the comment.
rec = qsolog.make_record(
    qsolog.parse_entry("W3ABC 59 57 Bob ; Pittsburgh", "USB"),
    WHEN, freq_hz=7_074_000, mode="USB",
    my_call="KD3CCO", my_grid="FN10CS")
equals("time is UTC and ISO", rec["when"], "2026-10-10T16:12:03Z")
equals("band derived", rec["band"], "40m")
equals("mode normalized", rec["mode"], "SSB")
equals("own call recorded", rec["my_call"], "KD3CCO")
check("empty fields are dropped",
      "name" in rec and rec.get("comment") and "qth" not in rec)

nofreq = qsolog.make_record(qsolog.parse_entry("W3ABC", "USB"), WHEN,
                            freq_hz=None, mode="USB", my_call="KD3CCO")
check("no frequency means no freq field", "freq" not in nofreq)
check("and no band", "band" not in nofreq)
equals("but the contact is still a record", nofreq["call"], "W3ABC")

print("\nround trip")
line = qsolog.format_record(rec)
check("one line", "\n" not in line, repr(line))
back = qsolog.parse_record(line)
equals("call survives", back["call"], "W3ABC")
equals("the comment survives", back["comment"], "Pittsburgh")
equals("time survives", back["when"], rec["when"])

spacey = qsolog.make_record(
    qsolog.parse_entry("W3ABC 59 57 Bob ; Mount Joy PA", "USB"),
    WHEN, freq_hz=14_070_000, mode="USB", my_call="KD3CCO")
rt = qsolog.parse_record(qsolog.format_record(spacey))
equals("a multi-word value round trips", rt["comment"], "Mount Joy PA")
equals("and the field after it is intact", rt["my_call"], "KD3CCO")

print("\nADIF")
adif = qsolog.adif_record(rec)
check("date", "<QSO_DATE:8>20261010" in adif, adif)
check("time", "<TIME_ON:6>161203" in adif, adif)
check("call with its length", "<CALL:5>W3ABC" in adif, adif)
check("band", "<BAND:3>40m" in adif, adif)
check("mode", "<MODE:3>SSB" in adif, adif)
check("frequency in MHz", "<FREQ:5>7.074" in adif, adif)
check("own call as STATION_CALLSIGN", "<STATION_CALLSIGN:6>KD3CCO" in adif, adif)
check("ends with EOR", adif.endswith("<EOR>"), adif)

thin = qsolog.adif_record(nofreq)
check("no BAND when there is no frequency", "<BAND" not in thin, thin)
check("no FREQ either", "<FREQ" not in thin, thin)
check("and no empty NAME", "<NAME" not in thin, thin)

print("\nPOTA in ADIF")
p2p = qsolog.make_record(qsolog.parse_entry("W3ABC 59 57 US-1234", "USB"),
                         WHEN, freq_hz=14_250_000, mode="USB",
                         my_call="KD3CCO", my_grid="FN10CS", my_park="US-5678")
pa = qsolog.adif_record(p2p)
check("their park is SIG_INFO", "<SIG_INFO:7>US-1234" in pa, pa)
check("with SIG saying POTA", "<SIG:4>POTA" in pa, pa)
check("my park is MY_SIG_INFO", "<MY_SIG_INFO:7>US-5678" in pa, pa)
check("with MY_SIG saying POTA", "<MY_SIG:4>POTA" in pa, pa)

hunter = qsolog.make_record(qsolog.parse_entry("W3ABC 59 57 US-1234", "USB"),
                            WHEN, freq_hz=14_250_000, mode="USB", my_call="KD3CCO")
ha = qsolog.adif_record(hunter)
check("hunting records their park", "<SIG_INFO:7>US-1234" in ha, ha)
check("and not a park of its own", "<MY_SIG" not in ha, ha)

# "<SIG:" and not "SIG": STATION_CALLSIGN contains the letters SIG, which is
# how this check passed for the wrong reason the first time it was written.
plain_qso = qsolog.adif_record(rec)
check("no POTA fields on an ordinary contact",
      "<SIG:" not in plain_qso and "<MY_SIG" not in plain_qso, plain_qso)

print("\ngrid from a callbook lookup")
withgrid = dict(rec); withgrid["grid"] = "EN90ak"
check("exports as GRIDSQUARE",
      "<GRIDSQUARE:6>EN90ak" in qsolog.adif_record(withgrid))

whole = qsolog.adif_export([rec, nofreq])
check("header", "<EOH>" in whole, whole[:120])
equals("one record per line", whole.strip().count("<EOR>"), 2)
check("program id", "<PROGRAMID:9>cyberdeck" in whole, whole[:200])
equals("empty log still has a header", "<EOR>" in qsolog.adif_export([]), False)

print("\nthe file")
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "a", "deep", "qso.log")
    check("nothing exists before anything is logged", not os.path.exists(path))
    equals("and reading it is an empty log, not an error", qsolog.read(path), [])
    equals("count of nothing", qsolog.count(path), 0)

    qsolog.append(path, rec)
    check("the file and its directory appear on first use", os.path.exists(path))
    equals("one record", qsolog.count(path), 1)

    qsolog.append(path, p2p)
    back = qsolog.read(path)
    equals("two, oldest first", [r["call"] for r in back], ["W3ABC", "W3ABC"])
    equals("the second kept its park", back[1]["park"], "US-1234")
    equals("and its own park", back[1]["my_park"], "US-5678")

    with open(path, encoding="utf-8") as fh:
        lines = [ln for ln in fh.read().split("\n") if ln]
    equals("one line per contact", len(lines), 2)
    check("append-only: the first line is untouched",
          lines[0] == qsolog.format_record(rec), lines[0])

    # The file is documented as hand-editable over SSH, which is the recovery
    # path for anything the interface gets wrong. A half-finished edit must
    # not stop the log from opening.
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("this line is not a record\n")
        fh.write("# a comment somebody added\n")
        fh.write("\n")
        fh.write(qsolog.format_record(qsolog.make_record(
            qsolog.parse_entry("K2XYZ", "USB"), WHEN, mode="USB")) + "\n")
    survived = qsolog.read(path)
    equals("junk is skipped, not fatal", [r["call"] for r in survived],
           ["W3ABC", "W3ABC", "K2XYZ"])

    equals("exports what survived", qsolog.adif_export(survived).count("<EOR>"), 3)

with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "qso.log")
    for call in ("W3ABC", "K2XYZ", "N3QQQ"):
        qsolog.append(path, qsolog.make_record(
            qsolog.parse_entry(call, "USB"), WHEN, mode="USB", my_call="KD3CCO"))
    equals("order is the order they were logged",
           [r["call"] for r in qsolog.read(path)], ["W3ABC", "K2XYZ", "N3QQQ"])

print("\nwhere the file lives")
check("expands a tilde", qsolog.log_path().startswith(os.path.expanduser("~")))
equals("and takes an override", qsolog.log_path("/tmp/x.log"), "/tmp/x.log")

print("\ncomments: the catch-all a general log needs")
# Everything after a semicolon is free text. A general log's most-used field
# after the call is the one that holds "QRP 5W" or "first one from this
# county", and no positional scheme can tell that from a QTH.
c = qsolog.parse_entry("W3ABC 59 57 Bob ; running 5W to a wire", "USB")
equals("the comment is taken whole", c["comment"], "running 5W to a wire")
equals("and the name before it is still the name", c["name"], "Bob")
equals("the name still parses", c["name"], "Bob")

c = qsolog.parse_entry("W3ABC ; first one from this county", "USB")
equals("a comment with nothing else", c["comment"], "first one from this county")
equals("and no name invented from it", c["name"], "")
equals("reports still default", (c["rst_s"], c["rst_r"]), ("59", "59"))

c = qsolog.parse_entry("W3ABC 59 57 US-1234 Bob ; park to park", "USB")
equals("a park and a comment coexist", (c["park"], c["comment"]),
       ("US-1234", "park to park"))

equals("no semicolon, no comment",
       qsolog.parse_entry("W3ABC 59 57 Bob", "USB")["comment"], "")
equals("a semicolon with nothing after it is not a comment",
       qsolog.parse_entry("W3ABC 59 57 Bob ;", "USB")["comment"], "")
equals("a second semicolon stays in the comment",
       qsolog.parse_entry("W3ABC ; a; b", "USB")["comment"], "a; b")

# The storage format quotes on spaces, so a comment has to survive a round
# trip or it is worse than not having the field at all.
r = qsolog.make_record(
    qsolog.parse_entry("W3ABC 59 57 Bob ; running 5W to a wire", "USB"),
    WHEN, freq_hz=7_040_000, mode="USB", my_call="KD3CCO")
line = qsolog.format_record(r)
check("a comment with spaces is quoted", 'comment="running 5W to a wire"' in line, line)
equals("and reads back", qsolog.parse_record(line)["comment"],
       "running 5W to a wire")
check("and exports as ADIF COMMENT",
      "<COMMENT:20>running 5W to a wire" in qsolog.adif_record(r),
      qsolog.adif_record(r))
equals("no comment, no ADIF field",
       "<COMMENT" in qsolog.adif_record(qsolog.make_record(
           qsolog.parse_entry("W3ABC", "USB"), WHEN, freq_hz=7_040_000,
           mode="USB", my_call="KD3CCO")), False)

print("\nwhere the mode comes from")
# The station's rule: on digital, fill the mode in from the deck; on SSB, do
# not. fldigi always has a modem loaded whether or not it is in use, so
# "what modem is up" is a different question from "what are we working", and
# answering the first one logs a voice contact as BPSK31.
rm = qsolog.resolve_mode

print("  voice never asks fldigi")
equals("a rig in USB is SSB", rm("voice", "USB", "BPSK31", True), ("SSB", "rig"))
equals("even mid-transmission on a loaded modem",
       rm("voice", "LSB", "Olivia-8-500", True), ("SSB", "rig"))
equals("FM is believed", rm("voice", "FM", "RTTY"), ("FM", "rig"))
# A data mode from the rig contradicts the operator's own setting. The setting
# wins and the fallback is SSB, because logging PSK for a contact the operator
# says was voice is the error that matters.
equals("a data mode from the rig does not override the setting",
       rm("voice", "PKTUSB", "BPSK31", True), ("SSB", "default"))

print("  digital takes fldigi's modem")
equals("psk", rm("digital", "USB", "BPSK31"), ("PSK", "fldigi"))
equals("olivia", rm("digital", "USB", "Olivia-8-500"), ("OLIVIA", "fldigi"))
equals("no modem falls back to the rig",
       rm("digital", "USB", ""), ("SSB", "rig"))
equals("and to SSB with nothing at all",
       rm("digital", "", ""), ("SSB", "default"))

print("  auto")
# The ambiguity this exists for: this rig reports USB for voice AND for
# digital, so the rig's mode alone cannot tell them apart.
equals("USB with fldigi idle is voice",
       rm("auto", "USB", "BPSK31", False), ("SSB", "rig"))
equals("USB with fldigi actually passing traffic is digital",
       rm("auto", "USB", "BPSK31", True), ("PSK", "fldigi"))
equals("a data mode from the rig is conclusive on its own",
       rm("auto", "PKTUSB", "BPSK31", False), ("PSK", "fldigi"))
equals("so is RTTY", rm("auto", "RTTY", "RTTY", False), ("RTTY", "fldigi"))
equals("CW from the rig is believed", rm("auto", "CW", "BPSK31"), ("CW", "rig"))
# The sharp edge, pinned deliberately: with no rig at all, auto trusts the
# modem, because the deck is a digital terminal first. An SSB session with no
# CAT control wants OPERATING = voice. docs/qso_log_design.md §6 says so.
equals("no rig information at all leans digital",
       rm("auto", "", "BPSK31"), ("PSK", "fldigi"))
equals("and with neither, SSB", rm("auto", "", ""), ("SSB", "default"))

print("  a rig data mode is evidence, never the answer")
# Measured on the deck 2026-10-11: the FTX-1 reports `PKTUSB` while fldigi
# drives it. That is a hamlib string, not an ADIF mode — writing it into MODE
# produces a record LoTW will not take. It says "something digital is
# happening" and nothing about which emission, so it selects fldigi's answer
# rather than becoming one.
equals("PKTUSB selects fldigi's modem",
       rm("auto", "PKTUSB", "BPSK31"), ("PSK", "fldigi"))
equals("and with no fldigi it does NOT leak into the log",
       rm("auto", "PKTUSB", ""), ("SSB", "default"))
equals("same for RTTY as a rig mode with nothing driving it",
       rm("auto", "RTTY", ""), ("SSB", "default"))
check("no data mode ever reaches ADIF as itself",
      all(rm(op, data, "")[0] not in qsolog.RIG_DATA_MODES
          for op in qsolog.OPERATING
          for data in ("PKTUSB", "PKTLSB", "DATA-U", "RTTY")),
      "a hamlib mode string reached the MODE field")

print("  robustness")
equals("an empty operating is auto", rm("", "USB", "BPSK31"), ("SSB", "rig"))
equals("None is auto", rm(None, "USB", "BPSK31"), ("SSB", "rig"))
equals("case does not matter", rm("VOICE", "usb", "bpsk31"), ("SSB", "rig"))
equals("whitespace does not either", rm("auto", "  USB  ", "BPSK31"), ("SSB", "rig"))
check("every documented value is accepted",
      all(rm(v, "USB", "BPSK31")[0] for v in qsolog.OPERATING), qsolog.OPERATING)

print("\nduplicates, under five rules")
# Which earlier contact counts as already worked is a property of the EVENT,
# not of the logger: a QSO party scores once per band, Field Day once per
# band and mode, a park activation not at all.
WORKED = [
    {"when": "2026-10-11T18:31:00Z", "call": "W3ABC", "band": "20m",
     "mode": "SSB", "activity": "CONTEST"},
    {"when": "2026-10-11T18:45:00Z", "call": "W3ABC", "band": "40m",
     "mode": "SSB", "activity": "CONTEST"},
    {"when": "2026-10-11T19:02:00Z", "call": "W3ABC", "band": "20m",
     "mode": "CW", "activity": "CONTEST"},
    {"when": "2026-10-11T19:10:00Z", "call": "K2XYZ", "band": "20m",
     "mode": "SSB", "activity": "CONTEST"},
]
def dupes(rule, call="W3ABC", band="20m", mode="SSB", **kw):
    return qsolog.find_dupes(WORKED, call, band, mode, rule, **kw)

equals("off never matches", dupes("off"), [])
equals("call matches every band and mode", len(dupes("call")), 3)
equals("band matches only 20m", len(dupes("band")), 2)
equals("mode matches only SSB", len(dupes("mode")), 2)
equals("band+mode matches one", len(dupes("band+mode")), 1)
equals("a new band is not a duplicate under band",
       dupes("band", band="15m"), [])
equals("a new mode is not one under mode", dupes("mode", mode="RTTY"), [])
equals("but is under call", len(dupes("call", band="15m", mode="RTTY")), 3)
equals("a station never worked is never a duplicate",
       dupes("call", call="N0ONE"), [])
equals("case does not matter", len(dupes("call", call="w3abc")), 3)
equals("a blank call matches nothing", dupes("call", call=""), [])
equals("an unknown rule matches nothing", dupes("sometimes"), [])

# Logging with the radio unreachable leaves band and mode empty. Treating
# empty-equals-empty as a match would make every such contact a duplicate of
# every other one.
equals("no band known cannot answer a band rule",
       dupes("band", band=""), [])
equals("nor a band+mode rule", dupes("band+mode", band=""), [])
equals("and a record with no band is not matched by one that has one",
       qsolog.find_dupes([{"call": "W3ABC", "mode": "SSB"}],
                         "W3ABC", "20m", "SSB", "band"), [])
equals("while the call rule still works without either",
       len(qsolog.find_dupes([{"call": "W3ABC"}], "W3ABC", "", "", "call")), 1)

# Working the same station in last weekend's QSO party is not a duplicate in
# this one.
equals("another activity's contacts do not count",
       dupes("call", activity="FD"), [])
equals("while the same activity's do",
       len(dupes("call", activity="CONTEST")), 3)

print("  and the way it is said")
equals("nothing to say", qsolog.dupe_note([]), "")
note = qsolog.dupe_note(dupes("band+mode"))
check("names the station", "W3ABC" in note, note)
check("says when", "18:31" in note, note)
check("and on what, because 'worked before' is not actionable",
      "20m" in note and "SSB" in note, note)
check("more than once is counted", "3x" in qsolog.dupe_note(dupes("call")),
      qsolog.dupe_note(dupes("call")))
check("once is not", "1x" not in note, note)

equals("every rule has a label for the panel",
       sorted(qsolog.DUPE_LABELS), sorted(qsolog.DUPE_RULES))

print("\nQRP power survives as a fraction")
# Measured on the radio 2026-10-11: the FTX-1 field head's minimum is 0.5 W,
# and it answers `PC10.5;` there -- a decimal, though the CAT manual documents
# three digits. int() would have logged every sub-watt contact as 0 and
# dropped the field, which is the one case a QRP operator cares most about.
for watts, want in ((0.5, "0.5"), (0.05, "0.05"), (6, "6"), (10, "10"),
                    (100, "100"), (6.0, "6")):
    rec = qsolog.make_record(
        qsolog.parse_entry("W3ABC 59 57", "USB"), WHEN, freq_hz=7_070_000,
        mode="USB", my_call="KD3CCO", tx_power=watts)
    equals(f"{watts} W is stored as {want!r}", rec.get("tx_power"), want)
check("a whole number keeps no pointless decimal",
      "." not in qsolog.make_record(
          qsolog.parse_entry("W3ABC", "USB"), WHEN, freq_hz=7_070_000,
          mode="USB", my_call="KD3CCO", tx_power=6.0)["tx_power"])
half = qsolog.make_record(
    qsolog.parse_entry("W3ABC", "USB"), WHEN, freq_hz=7_070_000, mode="USB",
    my_call="KD3CCO", tx_power=0.5)
check("and a fraction reaches ADIF intact",
      "<TX_PWR:3>0.5" in qsolog.adif_record(half), qsolog.adif_record(half))
check("and survives the storage round trip",
      qsolog.parse_record(qsolog.format_record(half)) == half)
for junk in (0, "", None, "banana", -5):
    rec = qsolog.make_record(
        qsolog.parse_entry("W3ABC", "USB"), WHEN, freq_hz=7_070_000,
        mode="USB", my_call="KD3CCO", tx_power=junk)
    check(f"{junk!r} records no power rather than a wrong one",
          "tx_power" not in rec, str(rec.get("tx_power")))

print("\nthe park grammar is ADIF 3.1.4's POTARef, not an approximation")
check("the common form", qsolog.is_park("US-1234"))
check("legacy single-letter program", qsolog.is_park("K-0001"))
check("five digits", qsolog.is_park("CA-12345"))
check("a four-character program", qsolog.is_park("3B8-1234"))
check("an ISO 3166-2 suffix for a park spanning two subdivisions",
      qsolog.is_park("US-4578@US-MD"))
# Three digits used to pass, which contradicted both the spec and this
# module's own comment. Tightening it also makes a false positive less likely.
check("three digits is not a reference", not qsolog.is_park("US-123"))
check("nor six", not qsolog.is_park("US-123456"))
check("nor one with no hyphen", not qsolog.is_park("US1234"))
check("a report is still not a park", not qsolog.is_park("599"))
check("a callsign is still not a park", not qsolog.is_park("W3ABC"))
check("a stroke callsign either", not qsolog.is_park("KD3CCO/3"))

print("\nboth POTA spellings are written")
# ADIF 3.1.4 added dedicated POTA_REF/MY_POTA_REF. The generic SIG pair is
# what pota.app has always matched on and what older loggers read; the
# dedicated pair is what current ones (QLog among them) look for. Writing one
# and not the other loses the park at one end or the other.
p2p = qsolog.adif_record(qsolog.make_record(
    qsolog.parse_entry("N3QQQ 59 55 US-1234 Jim", "USB"), WHEN,
    freq_hz=14_250_000, mode="USB", my_call="KD3CCO", my_park="US-5678"))
for field, value in (("SIG", "POTA"), ("SIG_INFO", "US-1234"),
                     ("POTA_REF", "US-1234"), ("MY_SIG", "POTA"),
                     ("MY_SIG_INFO", "US-5678"), ("MY_POTA_REF", "US-5678")):
    check(f"<{field}> is {value}",
          f"<{field}:{len(value)}>{value}" in p2p, p2p)

hunting = qsolog.adif_record(qsolog.make_record(
    qsolog.parse_entry("N3QQQ 59 55 US-1234", "USB"), WHEN,
    freq_hz=14_250_000, mode="USB", my_call="KD3CCO"))
check("hunting writes POTA_REF and no MY_POTA_REF",
      "<POTA_REF:" in hunting and "<MY_POTA_REF" not in hunting, hunting)

ordinary = qsolog.adif_record(qsolog.make_record(
    qsolog.parse_entry("W3ABC 59 57 Bob", "USB"), WHEN, freq_hz=14_250_000,
    mode="USB", my_call="KD3CCO"))
check("and an ordinary contact has neither spelling",
      "POTA" not in ordinary, ordinary)
# The header claims 3.1.4 and 3.1.4 is the version that defines POTA_REF, so
# the claim and the content have to agree.
check("the header version is the one that defines these fields",
      "<ADIF_VER:5>3.1.4" in qsolog.adif_header(),
      qsolog.adif_header())

print("\nfrequencies, at the radio's own resolution")
# The log screen shows 7.185.000 rather than 7.185: rounding to three decimals
# throws away the tens of hertz, which is the part that matters inside a 31 Hz
# signal and the part that lets the reading be checked against the radio. That
# means the field holds a string float() cannot read.
for text, hz in (("7.185.000", 7_185_000),
                 ("14.070.589", 14_070_589),
                 ("7.185", 7_185_000),
                 ("7.1853", 7_185_300),
                 ("7", 7_000_000),
                 ("7185000", 7_185_000),
                 ("", 0),
                 ("junk", 0),
                 ("0", 0)):
    equals(f"{text!r} is {hz} Hz", qsolog.parse_freq(text), hz)
equals("and the band comes out of it",
       qsolog.band_for(qsolog.parse_freq("14.070.589")), "20m")
# Round trip against the renderer, which is what writes the field.
import render as _render
equals("what render.frequency writes, parse_freq reads",
       qsolog.parse_freq(_render.frequency(7_185_000)), 7_185_000)

print("\nactivities listed out of the log")
RECS = [{"activity": "Bald Eagle SP", "activity_type": "POTA",
         "when": "2026-10-11T14:00:00Z"},
        {"activity": "Bald Eagle SP", "activity_type": "POTA",
         "when": "2026-10-11T14:05:00Z"},
        {"activity": "PAQP 2026", "activity_type": "CONTEST",
         "when": "2026-10-10T18:00:00Z"},
        {"call": "W1AW", "when": "2026-10-12T00:00:00Z"}]
found = qsolog.activities_in(RECS)
equals("one entry per activity, not per contact", len(found), 2)
equals("newest first by last contact", found[0]["name"], "Bald Eagle SP")
equals("with its type", found[0]["type"], "POTA")
equals("and how many contacts it holds", found[0]["count"], 2)
check("a contact belonging to no activity is not one",
      all(e["name"] for e in found), str(found))

equals("filtering to an activity takes only its contacts",
       len(qsolog.for_activity(RECS, "Bald Eagle SP")), 2)
equals("an empty name means the ones belonging to no activity",
       len(qsolog.for_activity(RECS, "")), 1)

print("\nserials are scoped to the activity, not to the type")
# Two weekends of the same QSO party are two activities, and each counts from
# one. Scoping to the type would have the second continue the first.
SER = [{"activity": "PAQP 2026", "activity_type": "CONTEST", "serial_tx": "4"},
       {"activity": "PAQP 2025", "activity_type": "CONTEST", "serial_tx": "88"}]
equals("this year's next serial", qsolog.next_serial(SER, "PAQP 2026"), 5)
equals("last year's is a different sequence",
       qsolog.next_serial(SER, "PAQP 2025"), 89)
equals("and a new activity starts at one",
       qsolog.next_serial(SER, "PAQP 2027"), 1)

print("\nthe rig modes digital transmit can use are public")
check("PKTUSB is one", "PKTUSB" in qsolog.RIG_DATA_MODES)
check("and USB is not — it is plain sideband",
      "USB" not in qsolog.RIG_DATA_MODES)
check("nor is LSB", "LSB" not in qsolog.RIG_DATA_MODES)
check("nor FM", "FM" not in qsolog.RIG_DATA_MODES)

print("\ncorrecting a contact already logged")
# The file was append-only by design and the design doc said so. The reason
# was good -- an append cannot damage what is already there, and this deck's
# whole power story is that the plug gets pulled. The reason it changed is
# also good: a callsign taken down wrong is wrong in the exported ADIF and in
# every upload made from it, and "edit the file over SSH" is no recovery path
# from a park bench.
#
# So the file is never written in place. It is replaced WHOLE and atomically,
# which is what these assert: the neighbours, the order and the count survive
# every edit, and a failed match changes nothing at all.
import tempfile as _tf

def _logged():
    d = _tf.mkdtemp(prefix="qsolog-update-")
    path = os.path.join(d, "qso.log")
    for i, call in enumerate(("W1AW", "KD3CPP", "W3TM")):
        qsolog.append(path, {"when": f"2026-10-14T14:0{i}:00Z", "call": call,
                             "band": "40m", "mode": "SSB", "rst_s": "59",
                             "rst_r": "59", "my_call": "KD3CCO"})
    return d, path

d, path = _logged()
got = qsolog.update(path, "2026-10-14T14:01:00Z", "KD3CPP", {"call": "KD3CCP"})
equals("the callsign is corrected", got and got["call"], "KD3CCP")
equals("and that is what is in the file",
       [r["call"] for r in qsolog.read(path)], ["W1AW", "KD3CCP", "W3TM"])
equals("the count is unchanged", len(qsolog.read(path)), 3)
check("no temp file is left behind",
      [f for f in os.listdir(d) if f.startswith(".")] == [],
      str(os.listdir(d)))

# The timestamp is the key. It is not editable, because a contact whose time
# can be retyped is a contact whose duplicate check means nothing.
d, path = _logged()
qsolog.update(path, "2026-10-14T14:01:00Z", "KD3CPP",
              {"when": "1999-01-01T00:00:00Z", "name": "Ryan"})
mid = qsolog.read(path)[1]
equals("the timestamp cannot be retyped", mid["when"], "2026-10-14T14:01:00Z")
equals("but the edit alongside it took", mid.get("name"), "Ryan")

# An empty value clears the field, because a value typed by mistake has to be
# removable -- but not the callsign, which every record must have.
d, path = _logged()
qsolog.update(path, "2026-10-14T14:01:00Z", "KD3CPP", {"name": "Ryan"})
qsolog.update(path, "2026-10-14T14:01:00Z", "KD3CPP", {"name": ""})
check("a field can be cleared", "name" not in qsolog.read(path)[1],
      str(qsolog.read(path)[1]))
qsolog.update(path, "2026-10-14T14:01:00Z", "KD3CPP", {"call": ""})
equals("the callsign cannot be cleared", qsolog.read(path)[1]["call"],
       "KD3CPP")

# A guard that does not match is a refusal, not a guess: same instant,
# different station means the file changed underneath the screen.
d, path = _logged()
before = open(path).read()
equals("a wrong callsign guard refuses",
       qsolog.update(path, "2026-10-14T14:01:00Z", "N0ONE", {"name": "X"}),
       None)
equals("an unknown timestamp refuses",
       qsolog.update(path, "1999-01-01T00:00:00Z", "", {"name": "X"}), None)
equals("and neither touched the file", open(path).read(), before)

print("\none contact, field by field")
# What the detail screen is built from. In the STORED order, so a line read
# over SSH and this screen put the same field in the same place.
rec = {"when": "2026-10-14T14:05:00Z", "call": "KD3CCP", "band": "40m",
       "mode": "SSB", "rst_s": "59", "name": "Ryan", "my_call": "KD3CCO",
       "activity_type": "POTA", "handwritten": "added over ssh"}
rows = qsolog.detail_rows(rec, activities.get("POTA"))
names = [n for n, _l, _v, _e in rows]
equals("the timestamp leads, as it does in the file", names[0], "when")
check("the callsign follows it", names[1] == "call", str(names[:3]))
check("every field with a value is shown",
      all(k in names for k in rec), str(names))
# The second half of what makes this screen able to fix an OMISSION: POTA
# wants a reference, this contact has none, and the blank row is what lets it
# be filled in.
check("a field the activity wants is shown even when empty",
      "park" in names, str(names))
equals("and it is empty",
       [v for n, _l, v, _e in rows if n == "park"], [""])
check("a field only the file knows about is still shown",
      "handwritten" in names, str(names))
# Hiding `when` would leave an operator wondering where the time went.
# Showing it locked says it is there and is not theirs to change.
locked = [n for n, _l, _v, e in rows if not e]
equals("the timestamp is the only locked field", locked, ["when"])
check("every label is non-empty", all(l for _n, l, _v, _e in rows), str(rows))
equals("labels come from the selection screen where there is one",
       qsolog.field_label("tx_power"),
       activities.ENTRY_FIELDS["tx_power"][1])
equals("and from this module for what the deck fills in",
       qsolog.field_label("my_call"), "My call")

sys.exit(report())
