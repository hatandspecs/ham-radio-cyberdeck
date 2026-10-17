"""The WSPR spot log — docs/wspr_design.md §5.

Pure: no clock, no radio, no subprocess. The caller supplies the time and the
readings, which is what makes a night of beaconing testable in milliseconds.

The property this file exists to hold is that **two record shapes share one
file**. A station heard and a beacon sent carry different fields, and the
`key=value` format carries no schema — so a reader has to be able to tell
them apart and a writer must not have to pad one into the other's shape.
"""
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import wspr
import wsprlog

STATION = dict(my_call="KD3CCO", my_grid="FN10cs", my_rig="FTX-1",
               my_antenna="EFHW")
BEGAN = "2026-10-17T01:00:00Z"
SES = dict(activity="Saturday night", activity_start=BEGAN)
SPOT = wspr.parse_decode("0208 -25  0.7   7.040053  0  WW0WWV DN70 30")


print("a station heard becomes a record")
rx = wsprlog.rx_record(SPOT, "2026-10-17T02:08:00Z", band="40 m", **SES,
                       **STATION)
equals("it is an rx record", rx["kind"], "rx")
equals("the station heard", rx["call"], "WW0WWV")
equals("its grid", rx["grid"], "DN70")
equals("its claimed power", rx["dbm"], "30")
equals("the measurements", (rx["snr"], rx["dt"], rx["drift"]),
       ("-25", "0.7", "0"))
# Hertz, following the contact log's HERTZ_FIELDS convention: one unit for
# frequency everywhere on the deck.
equals("the frequency is where the OTHER station was found, in hertz",
       rx["freq"], "7040053")
equals("the mode", rx["mode"], "WSPR2")
equals("the band, as passed in", rx["band"], "40 m")
for k, v in STATION.items():
    equals(f"this station's {k}", rx[k], v if k != "my_call" else "KD3CCO")

print("\na beacon sent becomes a different shape in the same file")
tx = wsprlog.tx_record("2026-10-17T02:10:00Z", band="40 m",
                       dial_hz=7_038_600, my_dbm=27, tx_power="0.5",
                       **SES, **STATION)
equals("it is a tx record", tx["kind"], "tx")
# The dial, not the dial plus 1500: this station's own signal sits a known
# offset above it, and recording the sum would be recording an inference.
equals("the frequency is the DIAL", tx["freq"], "7038600")
check("and there is no other station on it",
      not any(k in tx for k in ("call", "grid", "snr", "dt", "drift")),
      str(sorted(tx)))
# Both numbers, and they are not the same one.
equals("what the beacon announced", tx["my_dbm"], "27")
equals("what the radio was making", tx["tx_power"], "0.5")

print("\nthe two shapes round-trip through one file")
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "wspr.log")
    wsprlog.append(path, rx)
    wsprlog.append(path, tx)
    back = wsprlog.read(path)
    equals("both came back", len(back), 2)
    equals("in order", [r["kind"] for r in back], ["rx", "tx"])
    equals("the rx record survived whole", back[0]["call"], "WW0WWV")
    equals("and the tx record", back[1]["my_dbm"], "27")
    # A session name with a space in it has to be quoted on the way out and
    # unquoted on the way back, or it parses as a name plus two stray words.
    equals("a session name with spaces survives",
           back[0]["activity"], "Saturday night")
    text = open(path).read()
    check("which means it was quoted in the file",
          'activity="Saturday night"' in text, text[:120])

print("\nreading keeps beacons, which a contact log's reader would discard")
# `qsolog.read` requires a callsign. A transmission has no other station's
# call in it, so that predicate would throw away every beacon this deck
# ever sent -- which is why `wsprlog.read` has its own.
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "wspr.log")
    wsprlog.append(path, tx)
    import qsolog
    equals("the contact log's reader sees nothing", len(qsolog.read(path)), 0)
    equals("the spot log's reader sees the beacon", len(wsprlog.read(path)), 1)

print("\na window's spots are deduplicated on the way in")
# A window can decode one transmission twice; logging both would put a
# station in the log twice for one two-minute slot.
dupes = wspr.parse_decodes("\n".join([
    "0208 -10  0.0   7.040053  0  WW0WWV DN70 30",
    "0208 -25  0.7   7.040053  0  WW0WWV DN70 30",
    "0208 -26  0.2   7.040115  0  KC0MVF EN13 30",
    "<DecodeFinished>"]))
equals("three decodes", len(dupes), 3)
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "wspr.log")
    written = wsprlog.append_spots(path, dupes, when="2026-10-17T02:08:00Z",
                                   band="40 m", **SES, **STATION)
    equals("two records written", len(written), 2)
    equals("and two in the file", len(wsprlog.read(path)), 2)
    equals("the stronger copy was kept",
           [r["snr"] for r in wsprlog.read(path)], ["-10", "-26"])

print("\nsessions are derived from the records, never stored")
records = [
    wsprlog.rx_record(SPOT, "2026-10-17T02:08:00Z", band="40 m", **SES,
                      **STATION),
    wsprlog.tx_record("2026-10-17T02:10:00Z", band="40 m", dial_hz=7038600,
                      my_dbm=27, **SES, **STATION),
    wsprlog.rx_record(SPOT, "2026-10-17T02:12:00Z", band="30 m", **SES,
                      **dict(STATION, my_antenna="dipole")),
    # A different session, same night.
    wsprlog.rx_record(SPOT, "2026-10-16T22:00:00Z", band="20 m",
                      activity="Earlier", activity_start="2026-10-16T21:00:00Z",
                      **STATION),
]
ses = {s["name"]: s for s in wsprlog.sessions_in(records)}
equals("two sessions", len(ses), 2)
night = ses["Saturday night"]
equals("two heard", night["heard"], 2)
equals("one sent", night["sent"], 1)
equals("both bands, in the order used", night["bands"], ["40 m", "30 m"])
equals("its start", night["start"], BEGAN)
# Newest wins, as §7i resolves a contact log session's schema: an antenna
# changed halfway through a night is a fact in the file.
equals("the antenna is the NEWEST record's", night["antenna"], "dipole")
equals("the rig, unchanged", night["rig"], "FTX-1")
equals("and the grid, which is what changes when the station moves",
       night["grid"], "FN10cs")
equals("newest session first",
       [s["name"] for s in wsprlog.sessions_in(records)],
       ["Saturday night", "Earlier"])

print("\nforgetting a session hides it and changes no record")
forgotten = wsprlog.sessions_in(records, forgotten=[("Earlier",
                                                     "2026-10-16T21:00:00Z")])
equals("one session listed", len(forgotten), 1)
equals("and it is the other one", forgotten[0]["name"], "Saturday night")

print("\ncounts are broken out by kind, which the danger zone needs")
# "473 records" hides which. An operator about to lose a night of received
# data cares about a different number than one clearing transmissions.
equals("for one session", wsprlog.counts(records, "Saturday night", BEGAN),
       (2, 1))
equals("for the whole log", wsprlog.counts(records), (3, 1))

print("\nand the danger zone's two deletions")
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "wspr.log")
    for r in records:
        wsprlog.append(path, r)
    equals("four records", len(wsprlog.read(path)), 4)
    equals("removing one session takes its three",
           wsprlog.remove_session(path, "Saturday night", BEGAN), 3)
    equals("one left", len(wsprlog.read(path)), 1)
    check("and it is the other session's",
          wsprlog.read(path)[0]["activity"] == "Earlier", "")
    equals("clearing takes the rest", wsprlog.clear(path), 1)
    equals("nothing left", len(wsprlog.read(path)), 0)
    check("but the file is still there", os.path.exists(path), path)

print("\nthe spot log is not the contact log")
with tempfile.TemporaryDirectory() as tmp:
    contact = os.path.join(tmp, "qso.log")
    spots = wsprlog.log_path(os.path.join(tmp, "wspr.log"))
    check("they are different files", spots != contact, f"{spots} {contact}")
    check("and the default is named for what it holds",
          wsprlog.DEFAULT_NAME == "wspr.log", wsprlog.DEFAULT_NAME)

report()
