"""Band segments, the frequencies a tuner sweep visits, and what is locked off.

Pure data and arithmetic. Nothing here touches the radio, the config file or
the screen, which is what makes all of it testable without hardware.

**The ranges come from 47 CFR 97.301**, carried in `bandplans.tsv` beside this
file with a `verified_date` on every row. That file is copied from the
`ftx1-tuner-sweep` project, where it was built against the regulation itself
rather than a summary site, and the deck must not acquire a second band plan
of its own. If the two ever disagree, that one is right.

Three ideas that look similar and are not:

**A privilege edge** is where the law changes. `frequencies_for` pads 1 kHz
inside one so a sweep never keys exactly on a boundary.

**A mode label** -- CW/Data, Phone, All Modes -- is how a segment is
displayed, and on 17 m, 12 m, 10 m and 6 m it describes operating practice
rather than regulation. It drives the select-all-phone and select-all-CW
hotkeys and nothing else.

**An activity sub-segment** is a band-plan convention, such as 10 m SSB living
at 28.300-28.600 inside a CFR block that runs to 29.700. These make the wide
bands usable: 10 m swept whole is 171 memories, and its SSB portion is 31.
They deliberately do not tile the band, because a sweep should cover what gets
operated rather than every kilohertz that is permitted.
"""
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BANDPLANS = os.path.join(HERE, "bandplans.tsv")

# One kilohertz inside each edge of a privilege range. Tuning exactly on a
# boundary puts the carrier at the edge of what is permitted; 1 kHz inside
# keeps the whole cycle legal. Same constant, same reason, as
# `ftx1_cat.EDGE_PAD_HZ`.
EDGE_PAD_HZ = 1000

# The tuner steps in 10 kHz. Memories land on clean multiples between the
# padded ends.
STEP_HZ = 10_000

BAND_ORDER = ("160m", "80m", "40m", "30m", "20m", "17m", "15m", "12m",
              "10m", "6m")

# Free text in the TSV maps to a label the operator reads. **30 m is CW/data
# only for every class**, and the `us_extra` row in the source file says only
# "Full band" where the `us_general` row spells it out -- so the band is
# special-cased against the regulation rather than against a string somebody
# typed. See `MODE_BY_BAND`.
_NOTE_LABELS = {
    "CW/data segment": "CW/Data",
    "Phone/image segment": "Phone",
    "Full band, all modes": "All Modes",
    "Full band, no class restriction": "All Modes",
    "Full band, CW/data only (no phone permitted, any class)": "CW/Data only",
    "Full band": "All Modes",
}

# Bands whose mode is fixed by regulation regardless of what a row says.
MODE_BY_BAND = {"30m": "CW/Data only"}

CW, PHONE, ALL = "CW/Data", "Phone", "All Modes"
CW_ONLY = "CW/Data only"

# Labels that the select-all-phone hotkey should take. Phone is permitted on
# an All Modes segment, so skipping those would omit 17 m -- which is wanted
# -- while still making the operator find it by hand.
PHONE_LABELS = (PHONE, ALL)
CW_LABELS = (CW, CW_ONLY, ALL)

# Activity sub-segments for the wide bands, as customary US band-plan
# practice rather than regulation. Each must lie inside a privilege range for
# the license in use, which `segments()` enforces.
SUBSEGMENTS = {
    "10m": (
        ("CW/Data", 28_000_000, 28_300_000),
        ("SSB", 28_300_000, 28_600_000),
        ("AM / misc", 28_600_000, 29_000_000),
        ("FM / repeaters", 29_500_000, 29_700_000),
    ),
    "6m": (
        ("CW / beacons", 50_000_000, 50_100_000),
        ("SSB", 50_100_000, 50_300_000),
        ("FM simplex", 52_000_000, 52_100_000),
    ),
}

# Sub-segment labels that count as phone for the bulk hotkeys.
_PHONE_SUBLABELS = ("SSB", "AM / misc", "FM / repeaters", "FM simplex")


class Segment:
    """One selectable row: a band, a label, and a frequency range."""

    __slots__ = ("band", "label", "start_hz", "end_hz", "source")

    def __init__(self, band, label, start_hz, end_hz, source=""):
        self.band = band
        self.label = label
        self.start_hz = int(start_hz)
        self.end_hz = int(end_hz)
        self.source = source

    @property
    def key(self):
        """A stable identifier, for config files and lock lists."""
        return f"{self.band}:{self.label}"

    @property
    def name(self):
        """What the panel shows in its first column."""
        return f"{self.band} ({self.label})"

    @property
    def is_phone(self):
        return self.label in PHONE_LABELS or self.label in _PHONE_SUBLABELS

    @property
    def is_cw(self):
        return self.label in CW_LABELS or self.label.startswith("CW")

    def frequencies(self, step_hz=STEP_HZ):
        return frequencies_for(self.start_hz, self.end_hz, step_hz)

    def memory_count(self, step_hz=STEP_HZ):
        return len(self.frequencies(step_hz))

    def __repr__(self):
        return f"<Segment {self.key} {self.start_hz}-{self.end_hz}>"

    def __eq__(self, other):
        return (isinstance(other, Segment) and self.key == other.key
                and self.start_hz == other.start_hz
                and self.end_hz == other.end_hz)

    def __hash__(self):
        return hash((self.key, self.start_hz, self.end_hz))


def frequencies_for(start_hz, end_hz, step_hz=STEP_HZ, pad_hz=EDGE_PAD_HZ):
    """The frequencies a sweep visits in one range, ascending.

    The first point sits `pad_hz` above the lower edge and the last `pad_hz`
    below the upper edge, so the sweep never keys exactly on a boundary.
    Everything between lands on a clean multiple of `step_hz`, which is why
    the ends need not be a full step from their neighbors.

    This is `ftx1_cat.frequencies_for` for a single range, and it has to keep
    producing the same list: that project's output is what was field-tested
    against a real FTX-1 and a mAT-30.
    """
    first = start_hz + pad_hz
    last = end_hz - pad_hz
    if last <= first:
        # Too narrow for padding plus an interior grid. Use the edges rather
        # than returning nothing, which would silently drop the segment.
        return sorted({start_hz, end_hz})
    points = [first]
    grid = (first // step_hz + 1) * step_hz
    while grid < last:
        points.append(grid)
        grid += step_hz
    points.append(last)
    return points


def _label_for(band, notes):
    if band in MODE_BY_BAND:
        return MODE_BY_BAND[band]
    return _NOTE_LABELS.get(notes, ALL)


def licenses(path=BANDPLANS):
    """Every license id in the plan file, with its display name."""
    out = {}
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            out.setdefault(row["license_id"], row["license_name"])
    return out


def segments(license_id="us_general", path=BANDPLANS, subdivide=True):
    """Selectable segments for a license, in band order.

    With `subdivide`, a band in `SUBSEGMENTS` is replaced by its activity
    ranges rather than offered as one block -- 10 m whole is 171 memories and
    its SSB portion is 31. A sub-segment outside the license's privilege range
    is dropped, so a plan that does not grant the frequencies cannot offer
    them.
    """
    rows = []
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            if row["license_id"] == license_id:
                rows.append(row)
    rows.sort(key=lambda r: (BAND_ORDER.index(r["band"])
                             if r["band"] in BAND_ORDER else len(BAND_ORDER),
                             int(r["start_hz"])))

    out = []
    for row in rows:
        band = row["band"]
        lo, hi = int(row["start_hz"]), int(row["end_hz"])
        subs = SUBSEGMENTS.get(band) if subdivide else None
        if not subs:
            out.append(Segment(band, _label_for(band, row["notes"]), lo, hi,
                               row["source"]))
            continue
        for label, s_lo, s_hi in subs:
            # Clip to what this license actually grants, and drop anything
            # that falls outside it entirely.
            lo2, hi2 = max(lo, s_lo), min(hi, s_hi)
            if hi2 - lo2 > 0:
                out.append(Segment(band, label, lo2, hi2, row["source"]))
    return out


class Selection:
    """What is selected, and what a sweep of it would cost.

    One segment at a time, through `toggle`. The bulk operations --
    `select_all`, `clear`, `invert`, `select_phone`, `select_cw` -- and the
    per-segment lock that existed to override them were removed
    2026-10-23, after the first sweep on the panel: scrolling a list of
    twenty-odd rows and pressing `Space` is fast enough, and with no bulk
    operation to protect against, a lock protected against nothing.
    """

    def __init__(self, segs, chosen=()):
        self._segs = list(segs)
        self._chosen = set(chosen)

    # -- the rows -----------------------------------------------------------
    def rows(self):
        return list(self._segs)

    def is_selected(self, key):
        return key in self._chosen

    def selected(self):
        """Selected segments, in list order."""
        return [s for s in self._segs if s.key in self._chosen]

    # -- single rows --------------------------------------------------------
    def toggle(self, key):
        """Space on a row. Returns whether the row is now selected."""
        if key in self._chosen:
            self._chosen.discard(key)
            return False
        self._chosen.add(key)
        return True

    def memory_count(self, step_hz=STEP_HZ):
        return sum(s.memory_count(step_hz) for s in self.selected())

    def seconds(self, dwell_s, settle_s=0.3, step_hz=STEP_HZ):
        return self.memory_count(step_hz) * (dwell_s + settle_s)

    def summary(self, dwell_s, settle_s=0.3):
        """The one line the screen carries above the list."""
        n = len(self.selected())
        mem = self.memory_count()
        if not mem:
            return "selected: nothing"
        mins = self.seconds(dwell_s, settle_s) / 60.0
        when = f"{mins:.0f} min" if mins >= 1 else f"{mins * 60:.0f} s"
        return (f"selected: {n} segment{'' if n == 1 else 's'}   "
                f"{mem} memories   about {when}")

    def sweep_frequencies(self, step_hz=STEP_HZ):
        """Every frequency a run would visit, ascending across segments."""
        out = []
        for seg in sorted(self.selected(), key=lambda s: s.start_hz):
            out.extend(seg.frequencies(step_hz))
        return out
