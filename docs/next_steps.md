# Next steps — design notes

Seven features, specified on 2026-10-22 and built the same day. Each section
states what the feature is, where it lives, how it is driven, and what it was
built on; each ends with a **Built** note recording what was made, where the
implementation departed from the specification, and why.

The departures are the part worth reading. Three of them:

| Feature | Specified | Built | Why |
|---|---|---|---|
| 1. Ring order | Two screens, `FIELDS` then `ORDER` | One screen, same key bindings | Five areas fit one panel with room to spare |
| 4. Log from the transcript | The most recent **transmit** line; arrows reach earlier ones | The most recent **receive** line; `^G` again steps back | A transmitted line proves a call, not a contact. `↑` `↓` are history recall on that screen |
| 7. Export | A page on the deck, and rclone to Drive | The page only | The page needs no credentials, so it was the whole job; Drive is still open |

The frequency allocation tables are shared between features 2 and 3, and the
two maps (5 and 6) are one feature pointed at two datasets -- `src/wsprmap.py`
and `Deck._build_map` serve both.

---

## 1. Reorder the function ring

The ring that `^O` and `^P` walk is fixed at
`RING = (AREA_SETTINGS, AREA_LOG, AREA_DIGI, AREA_WSPR)` in `cyberdeck.py`,
with the log dropping out when logging is off. The operator chooses which
areas are on the ring and in what order.

**Deck & rig is excluded** and always present. It is the area that holds the
station settings and the system menu, including the way out of a deck that has
been configured into a corner, so it cannot be removed from the ring by the
ring editor.

### Where it lives

A screen in the deck & rig area, reached from its `F1` menu. That menu
currently holds two items, `1 Display` and `2 System` (`menus.DECK`), so the
ring editor is a third.

### The interaction already exists

The log schema editor solves exactly this problem — choose from a list, then
order what was chosen — and the ring editor reuses it rather than inventing a
second idiom:

| | Selecting (`FIELDS` screen) | Ordering (`ORDER` screen) |
|---|---|---|
| Move | `↑` `↓`, and `←` `→` / `PgUp` `PgDn` by a page | `↑` `↓` |
| Act | `Space` toggles the row in or out | `1`–`9` moves the selected row to that position |
| Leave | `Enter` advances, `Esc` backs out | `Enter` accepts, `Esc` back |

Two behaviors in `_handle_order` are worth carrying over verbatim, because
both were added in response to the screen reading as broken:

- **The selection follows the row that moved**, so a second number keeps
  operating on the same item rather than on whatever slid into its place.
- **A key that cannot do anything says why.** Typing `0` on the schema editor
  prints "the callsign is always first" rather than doing nothing. The ring
  editor needs the same for deck & rig.

### Built 2026-10-22

`RINGED` in `cyberdeck.py`, `render.ring_screen`, `tests/test_ring_editor.py`
(57 checks). Reached from the deck & rig `F1` menu as item 4.

**One screen, not two.** The key bindings are the schema editor's -- `Space`
toggles a row in or out, `1`-`9` moves the selected row to that position, the
selection follows the row that moved, `Enter` saves and `Esc` discards -- but
selecting and ordering happen on the same screen rather than on a `FIELDS`
screen followed by an `ORDER` screen. The schema editor splits them because
nineteen fields do not fit one panel and choosing nineteen things is a
genuinely separate step from ordering them; five areas fit with eleven rows
to spare, and an `Enter` between picking five and ordering three buys
nothing. The idiom being reused is the key bindings, which is the part an
operator has learned.

The areas on the ring are numbered 1..N and the ones left off are unnumbered
and dim. Numbering only what is on the ring is the point: the numbers **are**
the walk order, so a number beside an area that is not on it would be a
position in a sequence it is not part of.

### Answers to the open questions

- **An area can be deselected entirely.** `Space` takes it off, and the saved
  `RING_ORDER` simply omits it. That is not a second way to remove the log:
  switching logging off takes the log off the ring *for as long as it is off*
  and it rejoins when logging comes back, which is a different fact from the
  operator having taken it off. The editor reads the configured order rather
  than the live ring (`Deck._ring_order`, not `_ring_areas`) so an order
  edited while logging is off does not come back with logging dropped from
  it.
- **Deck & rig cannot be deselected**, and says so on the row before the key
  is pressed as well as when it is. It can be *moved*: `_ring_areas` inserts
  it only when the order omits it entirely.
- **Edited while WSPR holds the ring locked**: the editor is reachable, since
  it is a sub-screen of deck & rig rather than a ring stop of its own, and
  the new order is read live -- it applies the moment the lock lifts.
- **Persisted in `RING_ORDER`**, comma-separated, and listed in
  `cyberdeck._REMEMBERED` so it survives a power cycle rather than reverting
  to the conf file.

---

## 2. Frequency allocation tables

A reference screen on the function ring. No radio control, no state — it
displays the band plan and nothing else.

A toggle switches between **General** and **Extra** class allocations. The
tables are the ones in §3, and the two features share one source of truth: a
single module holding the segment list, consumed by both the reference screen
and the auto tuner. Two copies of a band plan will diverge.

### Built 2026-10-22

`src/bandplan.py` (shared with the auto tuner, as specified -- one segment
list, two consumers), `ALLOC` in `cyberdeck.py`, `render.allocation_screen`,
`tests/test_bandplan.py` (70 checks) and `tests/test_bandscreens.py` (65).

**The ranges come from 47 CFR §97.301, not from the tables below.** Those
tables were given as an example of how the segments should be DISPLAYED --
CW/data, phone, or all modes -- and the regulation is the source of truth for
where the edges are. `bandplans.tsv` carries a `verified_date` per row so a
row's provenance is readable rather than assumed.

Three things that are easy to conflate and are kept apart: **privilege
edges** (what the license class allows), **mode labels** (what the segment is
for), and **activity sub-segments** (where SSB is customary on 10 m, which is
convention rather than regulation). `MODE_BY_BAND` carries only the first
kind -- 30 m is CW/data by regulation, not by custom.

The table shows **band, segment and frequency range**, and nothing else. An
earlier version carried a memory count, which belongs to the tuner.

### Answers to the open questions

- **Its own ring area.** The point of a reference is being one key away while
  operating; three keystrokes into a menu is a thing looked up on a phone
  instead. It is the fifth area, and the ring editor (feature 1) means an
  operator who disagrees can take it off.
- **Technician is included**, since the data already carried it. `Space`
  cycles the class the table shows and `LICENSE_CLASS` remembers it.

---

## 3. FTX-1 auto tuner

Sets antenna tuner memories across chosen band segments without working the
VFO and the tune button by hand. The use case is a field-deployed antenna that
needs a tuner sweep before operating.

### Where it lives

A sub-screen of the deck & rig `F1` menu.

### The interaction

- Two license settings, **General** and **Extra**, which choose the segment
  table.
- A list of band segments, each selectable.
- Hotkeys: select all, deselect all, invert selection, select/deselect phone
  segments, select/deselect CW and data segments.

**Select-all-phone is the primary gesture, and the workflow is subtractive.**
The hotkeys are not six equals. The real sequence is one bulk selection
followed by a few deselections on the rows that do not apply to the antenna
in the air:

```
  1.  select all phone          9 segments, 684 memories, 57 min
  2.  Space on 10m, 6m, 12m, 160m
      -> 5 segments, 80 memories, 7 min at 5 s, 2 min at 1.5 s

      80m (Phone)   40m (Phone)   20m (Phone)   17m (All Modes)   15m (Phone)
```

Four keystrokes from nothing to a two-minute sweep of exactly the right
bands. That is the interaction to design for.

Two consequences:

- **Select-all-phone must include the All-Modes segments.** Phone is
  permitted on 17 m, 12 m, 10 m, 6 m and 160 m, so a "phone" selection that
  skipped them would omit 17 m — which is wanted — while still requiring the
  operator to find and add it by hand. Include them and let the deselect
  handle 12 m, 10 m, 6 m and 160 m, which is what the sequence above does.
- **Deselecting a single row has to be as cheap as the bulk select.** `Space`
  on the highlighted row, the same gesture the WSPR band picker already uses
  for its hop rotation.

### Locking segments off

A **lock** is persistent exclusion, and it is a different thing from a
deselection. Deselecting says "not this time". Locking says "never offer
this", and it survives restarts.

**A lock overrides every bulk operation.** Select-all, deselect-all,
select-all-phone, select-all-CW and invert all skip locked segments entirely —
a locked row never becomes selected, and invert does not flip it. Nothing
except unlocking it can put a locked segment into a sweep.

That is the whole point. Locking 10 m, 6 m, 160 m and 12 m means
select-all-phone lands directly on the working set with no deselecting at
all, which turns the four-keystroke sequence above into **one.**

Two further properties:

- A locked segment stays **visible on the list, marked as locked**, not
  hidden. A segment that silently vanished would read as a missing band, and
  the lock has to be as easy to undo as it is to set.
- The locks persist in `cyberdeck.conf` as a list of segment identifiers.

Locking is also how an operator records what the antenna cannot do. A wire
with no 160 m and no 6 m resonance does not want either band offered, ever,
and that is a property of the station rather than of today's session.

Marks on the row, with `[*]` selected and `[ ]` not:

```
  [*] 80m (Phone)             3.800 - 4.000
  [ ] 40m (CW/Data)           7.025 - 7.125
  [x] 160m (All Modes)        1.800 - 2.000      locked
  [x] 6m (SSB)               50.100 - 50.300     locked
```

One key toggles the lock on the highlighted row, distinct from the `Space`
that toggles selection.

### Subdividing the wide bands by activity

The CFR gives 10 m as one block, 28.000-29.700, which is **171 memories and
14 minutes** — and most of it is FM, satellite and repeater space that no
SSB operator would ever tune. The same block structure makes 6 m 401
memories.

Splitting those by customary activity makes them usable rather than something
to avoid:

| Segment | Range | Memories | At 5 s |
|---|---|---|---|
| 10m (CW/Data) | 28.000 – 28.300 | 31 | 2.6 min |
| 10m (SSB) | 28.300 – 28.600 | 31 | 2.6 min |
| 10m (AM / misc) | 28.600 – 29.000 | 41 | 3.4 min |
| 10m (FM / repeaters) | 29.500 – 29.700 | 21 | 1.8 min |
| 6m (CW / beacons) | 50.000 – 50.100 | 11 | 0.9 min |
| 6m (SSB) | 50.100 – 50.300 | 21 | 1.8 min |
| 6m (FM simplex) | 52.000 – 52.100 | 11 | 0.9 min |

**10 m SSB becomes a 2.6-minute sweep instead of a 14-minute one**, which is
the difference between a band worth including and a band to lock off.

Two cautions, because this is the same distinction as §"Ranges from the CFR":

- **These are band-plan conventions, not privilege edges.** The regulation
  grants 28.000-29.700 continuously. 28.300-28.600 is where SSB actually
  lives, not where it becomes legal. The sub-segment boundaries carry the
  1 kHz padding like any other, which is harmless here — padding an interior
  boundary costs two memories, not legality.
- **Gaps are intentional.** The ranges above do not tile the band; 29.000 to
  29.500 is omitted because nothing worth tuning for lives there. A sweep
  covers what gets operated, not every kilohertz that is permitted.

CW and data segments are rarely swept at all. For data this station tunes
manually at the calling frequency, which is one frequency rather than a band,
and the tuner's front panel is faster than a sweep for that. The
select-all-CW hotkey exists for symmetry and for an antenna where it matters,
not because it is the common path.
- **`^X` aborts a run in progress.** The operator is watching, and the point
  of the abort is to stop tuning on top of somebody already using the
  frequency. It has to take effect before the next tune cycle, not at the end
  of the current segment.

`^X` is the deck-wide clear key. On this screen it aborts, which is the same
sense — stop what is in progress — but the collision is worth a note in the
footer so the key reads as deliberate.

### What it does to the radio — already solved and field-tested

**This does not need to be worked out from scratch.** The
[`ftx1-tuner-sweep`](../../ftx1-tuner-sweep) project is a browser app that
already does exactly this sweep, field-tested against a real FTX-1 Optima and
a mAT-30 on 15 m and 12 m. Its `ftx1_cat.py` and `bandplans.tsv` are the
reference, and porting them is most of the work.

The commands, from the FTX-1 CAT manual (2508-C) and verified on the radio:

| Command | Meaning |
|---|---|
| `FA<9 digits>;` | Set or read the MAIN VFO frequency |
| `AC103;` | Antenna tuner: external, **start tuning** |
| `AC101;` | Tuner in circuit, not tuning |
| `AC100;` | Tuner off / bypassed |
| `RI;` | Radio information; P6 is the tuner-tuning bit |
| `PC;` `MD0;` | Configured TX power, operating mode |

`AC103` is the front-panel TUNER button held for two seconds, which is the
line the mAT-30 is wired to.

Three findings from that project carry straight over, and each cost
something to learn:

- **The radio cannot tell when an external tuner has finished.** The `RI`
  status bit never clears for a third-party tuner, because the trigger line is
  one way. There is no completion to poll for. Each frequency is held for a
  **fixed dwell** and the sweep moves on. Five seconds is the default; it is
  an operator setting, not a constant — see below.
- **Every step is a real transmission**, and the deck cannot hear the band.
  No code path keys the radio without a pre-flight acknowledgement, and the
  abort stays reachable throughout. That is a requirement, not a disclaimer —
  and it is the reason `^X` exists on this screen.
- **Leave the tuner in circuit however a sweep ends** — completed, aborted, or
  the cable pulled. An early version of that project left it bypassed, which
  is worse than never having run.

On the deck the equivalent calls are `set_frequency()` on `rigctld_client`,
with `send_cat()` for the `AC` commands hamlib does not model.

### Memory placement

Each segment is divided into 10 kHz steps, preferring even multiples of
10 kHz — 7.180, 7.190, 7.200 — with the first and last memories placed
**1 kHz inside the segment edges**. The frequencies at either end of a segment
need not be a full 10 kHz from their neighbor.

The 1 kHz inset is not cosmetic. Tuning exactly on a segment edge puts the
carrier at the boundary; 1 kHz inside keeps the whole cycle legal.

```
80m CW/Data, 3.525-3.600:
  3.526, 3.530, 3.540, 3.550, 3.560, 3.570, 3.580, 3.590, 3.599

40m Phone, 7.175-7.300:
  7.176, 7.180, 7.190, ... 7.280, 7.290, 7.299
```

### Runtime, and why segment selection is the point

**Selecting individual segments is the feature, not a convenience on top of
it.** Sweeping the entire General allocation is about an hour, and that
number is misleading in both directions: it is not how this gets used, and
nearly all of it comes from two bands this station does not operate. A real
sweep is the segments the antenna in the air actually covers.

The per-segment cost at the default 5-second dwell, General class:

| Segment | Memories | Time |
|---|---|---|
| 30m (CW/Data only) | 6 | 0.5 min |
| 80m (CW/Data) | 9 | 0.8 min |
| 12m (All Modes) | 11 | 0.9 min |
| 40m (CW/Data) | 12 | 1.0 min |
| 17m (All Modes) | 12 | 1.0 min |
| 40m (Phone) | 14 | 1.2 min |
| 20m (CW/Data) | 14 | 1.2 min |
| 20m (Phone) | 14 | 1.2 min |
| 15m (CW/Data) | 19 | 1.6 min |
| 15m (Phone) | 19 | 1.6 min |
| 160m (All Modes) | 21 | 1.8 min |
| 80m (Phone) | 21 | 1.8 min |
| **10m (All Modes)** | **171** | **14.2 min** |
| **6m (All Modes)** | **401** | **33.4 min** |

**Every segment except 10 m and 6 m is under two minutes.** Those two are
572 of the 744 General memories — **77% of the full sweep time for two
bands** — because the CFR grants 1.7 MHz on 10 m and 4 MHz on 6 m where
everything below is tens or hundreds of kilohertz.

The twelve other segments together are 172 memories, about 14 minutes. The
actual working selection for this station — 80, 40, 20, 17 and 15 m phone,
reached by selecting all phone and deselecting the rest — is **80 memories,
about seven minutes at the default dwell and two at 1.5 seconds.**

#### In practice 10 m and 6 m are not swept at all

This station almost never operates either, and when it does it is data on one
frequency, where running the tuner by hand on that frequency is simpler than
sweeping a band.

That collapses the headline number. The realistic ceiling is **every HF
segment that actually gets used**:

| Selection | Memories | 5 s | 1.5 s |
|---|---|---|---|
| Every HF segment including 160 m | 172 | 14 min | 4.3 min |
| 80 m through 12 m, no 160 m | 151 | 13 min | 3.8 min |
| 10 m + 6 m, for comparison | 572 | 48 min | 14 min |

**So a full sweep of everything this antenna covers is about a quarter of an
hour, and under four minutes on a re-sweep.** The hour-long figure describes
two bands that will not be selected. That is worth stating plainly, because a
feature that looks like it costs an hour gets used differently from one that
costs four minutes.

That shapes the screen:

- **The selection is remembered, and that matters more than the default.**
  The same antenna gets swept again at the next site. Whatever the deck ships
  with, after one use the right answer is whatever was ticked last time.
- **Nothing selected on first run.** The operator chooses what the antenna
  covers, because no default is right for every antenna — and a default of
  everything would put 10 m and 6 m in the sweep, which is exactly wrong here.
- **10 m and 6 m are worth a mark on the row**, not a warning. They are the
  only two segments that change a run from minutes to most of an hour, and
  with memory counts off the display nothing else says so. A mark is enough;
  an operator who wants them should not have to argue with a dialog.
- The running total — `selected: 6 segments   173 memories   about 15 min` —
  is what makes all of this legible before starting.

### The dwell is a setting

**Five seconds is a default, not a constant.** How long a tuner takes depends
on the tuner, the antenna, and — most of all — how far it has to move. A
tuner starting from a memory close to the target can settle in **as little as
1.5 seconds**, where the same tuner on a cold start somewhere new needs
several.

That is a large multiplier over a sweep, and it compounds with segment
selection:

| Selection | 1.5 s | 2 s | 3 s | 5 s |
|---|---|---|---|---|
| Field selection — 80/40/20/15 m phone | 2 min | 2 min | 3 min | 6 min |
| Everything except 10 m and 6 m | 4 min | 6 min | 9 min | 14 min |
| 6 m alone | 10 min | 13 min | 20 min | 33 min |
| Full General | 19 min | 25 min | 37 min | 62 min |

A re-sweep of a known antenna at 1.5 seconds is a third of the time of the
first pass, which is the difference between a thing done before operating and
a thing put off.

**The setting belongs on the tuner screen**, next to the selection, because
it is part of the same decision and its effect shows in the running total as
it changes. A `TUNER_DWELL_S` config key holds it across restarts, following
`WSPR_TIMEOUT_MIN` and the other cycled values.

#### Too short is a silent failure

This is the risk and it needs saying on the screen, not only here. **The radio
cannot report that an external tuner has finished** — the `RI` bit never
clears, which is why the dwell is fixed rather than polled. So a dwell shorter
than the tuner actually needs produces no error. The sweep steps on, a memory
is written from an unconverged match, and nothing anywhere says so.

The failure surfaces later as a band that will not tune, by which time the
sweep is long over.

So the guidance the screen should carry:

- **A new antenna gets a conservative first pass.** Five seconds, or longer if
  the tuner is slow.
- **A re-sweep of a known antenna can be short**, because the tuner starts
  from a memory near the target. This is the case the 1.5-second figure comes
  from.
- The floor should not be arbitrarily low. A dwell under about a second is
  shorter than any tuner's own cycle and guarantees bad memories.

### Ranges from the CFR, labels from the display convention

**The authoritative ranges are `ftx1-tuner-sweep/bandplans.tsv`**, sourced
from 47 CFR §97.301 with the regulation checked into that project's `refs/`
and a `verified_date` on every row. Nothing in the deck should carry a second
copy of a band plan.

What the tables in the original specification contribute is the **display
convention**: segments labelled by what may be operated there — CW/Data,
Phone, or All Modes — rather than as bare frequency pairs. That is the right
presentation and it is preserved below.

The two are different things and the distinction matters when sweeping:

- **A privilege edge is a legal boundary.** The sweep must not transmit
  outside it, which is what the 1 kHz padding protects.
- **A mode split is a convention.** On 17 m, 12 m, 10 m and 6 m the CFR grants
  one contiguous range with no class restriction; the CW/phone division inside
  it is operating practice, not regulation.

**Splitting a band for display must not split it for sweeping.** A display
split that reached the sweep would insert two spurious padded points at an
internal boundary that is not an edge — and skip the 1 kHz either side of a
frequency that is perfectly legal. On 10 m, sweeping 28.000-29.700 as one
range gives 171 memories; sweeping it as 28.000-28.300 plus 28.300-29.700
gives 172, and the extra one is an artifact of a boundary that does not exist.

So: the segment list drives the sweep, the mode labels drive the display and
the select-phone / select-CW hotkeys.

### General class

| Band | Modes | Range (MHz) | Bandwidth | Memories |
|---|---|---|---|---|
| 160m | All Modes | 1.800 – 2.000 | 200 kHz | 21 |
| 80m | CW/Data | 3.525 – 3.600 | 75 kHz | 9 |
| 80m | Phone | 3.800 – 4.000 | 200 kHz | 21 |
| 40m | CW/Data | 7.025 – 7.125 | 100 kHz | 12 |
| 40m | Phone | 7.175 – 7.300 | 125 kHz | 14 |
| 30m | CW/Data only | 10.100 – 10.150 | 50 kHz | 6 |
| 20m | CW/Data | 14.025 – 14.150 | 125 kHz | 14 |
| 20m | Phone | 14.225 – 14.350 | 125 kHz | 14 |
| 17m | All Modes | 18.068 – 18.168 | 100 kHz | 12 |
| 15m | CW/Data | 21.025 – 21.200 | 175 kHz | 19 |
| 15m | Phone | 21.275 – 21.450 | 175 kHz | 19 |
| 12m | All Modes | 24.890 – 24.990 | 100 kHz | 11 |
| 10m | All Modes | 28.000 – 29.700 | 1,700 kHz | 171 |
| 6m | All Modes | 50.000 – 54.000 | 4,000 kHz | 401 |
| **Total** | | | **7,250 kHz** | **744** |

### Extra class

The CFR grants Extra contiguous privileges on most bands, so the stored plan
holds whole bands rather than CW and phone halves. The mode labels are the
display overlay described above.

| Band | Modes | Range (MHz) | Bandwidth | Memories |
|---|---|---|---|---|
| 160m | All Modes | 1.800 – 2.000 | 200 kHz | 21 |
| 80m | All Modes | 3.500 – 4.000 | 500 kHz | 51 |
| 40m | All Modes | 7.000 – 7.300 | 300 kHz | 31 |
| 30m | CW/Data only | 10.100 – 10.150 | 50 kHz | 6 |
| 20m | All Modes | 14.000 – 14.350 | 350 kHz | 36 |
| 17m | All Modes | 18.068 – 18.168 | 100 kHz | 12 |
| 15m | All Modes | 21.000 – 21.450 | 450 kHz | 46 |
| 12m | All Modes | 24.890 – 24.990 | 100 kHz | 11 |
| 10m | All Modes | 28.000 – 29.700 | 1,700 kHz | 171 |
| 6m | All Modes | 50.000 – 54.000 | 4,000 kHz | 401 |
| **Total** | | | **7,750 kHz** | **786** |

**160 m is in the CFR data and was absent from the original tables.** It is
included here. If the antenna does not work there, deselect it — that is what
the selection list is for.

Memory counts are what `ftx1_cat.frequencies_for()` produces at a 10 kHz step
with `EDGE_PAD_HZ = 1000`: the first point 1 kHz above the lower edge, clean
multiples of 10 kHz between, the last 1 kHz below the upper edge.

**The deck shows two columns: band and segment, then the range in MHz.** The
tables above carry bandwidth and memory counts because this is reference
material for building the feature, not a mock of the screen. Neither belongs
on the panel — they are noise next to the decision the operator is making,
which is whether to sweep that segment.

```
  [*] 160m (All Modes)        1.800 - 2.000
  [*] 80m (CW/Data)           3.525 - 3.600
  [ ] 80m (Phone)             3.800 - 4.000
  [*] 40m (CW/Data)           7.025 - 7.125
  [*] 40m (Phone)             7.175 - 7.300
  [ ] 30m (CW/Data only)     10.100 - 10.150
```

Band and mode read as one label, `40m (Phone)`, rather than as separate
columns. At 66 characters wide that leaves room for the selection mark and
the range with space to spare.

What the screen does need is the **total for the current selection and what it
will cost in time**, because that is the number that decides whether to start.
One line, updating as segments are toggled:

```
  selected: 6 segments   173 memories   about 15 min
```

The same two columns apply to the reference screen in §2, which displays the
band plan and never sweeps anything.

#### One correction needed in the source data

`bandplans.tsv` annotates `us_general` 30 m as *"Full band, CW/data only (no
phone permitted, any class)"* and `us_extra` 30 m as only *"Full band"*. A
label derived from that free-text field would render **`30m (All Modes)`** for
an Extra licensee and invite a phone sweep on a band where **phone is
prohibited for every class**.

Two consequences:

- The Extra row in `ftx1-tuner-sweep/bandplans.tsv` wants the same annotation
  the General row has.
- **The deck should not derive the mode label from free text at all.** The
  label belongs in a structured field, or 30 m is special-cased against the
  regulation rather than against a string someone typed.

### Built 2026-10-22

`src/tuner.py`, `TUNER` in `cyberdeck.py`, `render.tuner_screen`,
`tests/test_tuner.py` (57 checks, no radio in any of them). Reached from the
deck & rig `F1` menu as item 3 -- a sub-screen rather than a ring area,
because it keys the transmitter for an hour and a screen that does that
should not be one `^O` away from everything else.

**The radio cannot report that an external tuner has finished.** The `RI`
status bit never clears, which is why a run uses a fixed dwell rather than
waiting for completion, and why **too short fails silently**: the sweep moves
on from a frequency the tuner never matched. `TUNER_DWELL_S` is the setting,
floor 1 s, default 5 s, and the floor is there because a dwell of zero would
look like a working sweep that stored nothing.

**Neither phase of a step sleeps.** A sweep that slept through its dwell
could not read `^X` during the only part of the run where aborting matters --
which is when it is transmitting on top of somebody already using the
frequency.

**`finish` always puts the tuner back in circuit**, however the run ended:
completed, aborted, or dead on a CAT error. A run that ended with the tuner
bypassed would leave the antenna worse than before it started.

Locks respect nothing above them: `select_all`, `invert`, `select_phone` and
`select_cw` all skip a locked segment, which is what "the lock would negate
select all" asked for. Mutation testing found two of those four tests
passing vacuously and both were rewritten.

### Answers to the open questions

- **All three US classes**, since the data carried them. The Canadian plan is
  a row in `bandplans.tsv` away and nothing in the code is US-specific.
- **The mode is not set per segment.** A tuner cares about frequency, the
  radio has not been observed refusing to tune in any mode, and setting the
  mode would make a sweep change something the operator did not ask it to
  change. If a refusal turns up on the air, this is where it goes.
- **The operator's frequency is read at `start` and restored by `finish`**,
  after the tuner goes back in circuit -- the order that matters is the one
  that cannot leave the antenna unmatched. A radio that cannot be read
  reports 0 and nothing is restored, which beats setting a frequency that was
  never in use. The MODE is not touched, per the point above.
- **A run holds the ring**, as WSPR does. Every key on the tuner screen is
  already swallowed while a sweep runs, including `Esc`; `^O` and `^P` are
  read before the per-screen handlers, so they were the one way to walk away
  from a transmitting deck. The refusal names `^X`, which is the key that
  clears it.

---

## 4. Log a digimode contact from the conversation screen

A hotkey on the digimodes screen that turns a transcript line into a log
entry, without retyping a callsign that is already on the screen.

### What it takes from the transcript

**The most recent received line, not a transmitted one.** Corrected
2026-10-22: the original specification said transmit, and received is what
was meant and what is built.

The difference is not cosmetic. A received line is evidence the far end was
there and answering; a transmitted one only proves somebody was called, which
is not a contact. It also inverts the parsing -- on receive the line reads
`KD3CCO DE K2ABC`, so the correspondent is the token **after** `DE` and this
station is before it.

Checking the call before `DE` against this station is what keeps other
people's overs out of the log: two stations working each other land in the
same transcript, and `W9XYZ DE K2ABC` is nobody's contact here. A CQ is
refused for the same reason -- `CQ CQ DE K2ABC` is somebody calling into the
air, and logging it would invent a QSO that has not happened.

The arrows select any earlier received line that names a correspondent.

The entry is filled from what the deck already knows: the callsign from the
line, plus the mode, frequency, band, time and configured power — the same
fields the logger fills today from the radio and the configuration.

### Three behaviors, chosen in the digimodes `F1` menu

A toggleable menu item cycles:

1. **Log it** — write the entry against the current activity and stay on the
   conversation screen.
2. **Prefill and switch** — fill the entry form and move to the log screen.
3. **Prefill and stay** — fill the entry form, remain on the conversation.

The menu item follows the pattern of the existing cycling items, such as the
WSPR transmit percent and the deck's `Mode from` setting, which cycle through
a fixed list rather than opening a picker.

### Built 2026-10-22

`src/decall.py`, `Deck._log_from_transcript` and `_prefill_log`,
`menus.digi_menu`, `tests/test_decall.py` (50 checks) and
`tests/test_logfromchat.py` (45 checks).

**"Log it" goes through `_log_commit`**, the same path the log screen's
`Enter` takes. Not `LogForm.commit` directly: that readies the form for the
next contact and does not write the file, so a hotkey calling it would clear
the entry and throw the contact away.

**The callsign goes in as a prefill, not as typing.** `LogForm.set` with its
default `prefill=True`, so `Ctrl-Z` offers to replace it exactly as it does
for a callbook lookup -- which is what makes a misdecoded callsign cheap to
get rid of. It is also therefore absent from `LogForm.typed()`, so a schema
change does not treat a deck-supplied callsign as work in progress.

### Answers to the open questions

- **`^G`**, byte 7, which was unbound on every screen. Named in the digimodes
  `F1` menu as item 5 rather than on the footer: that line is already 61 of
  66 columns at deck width, and the two widest tiers are the only place the
  ring is taught, which is worth more than a hint for a key the menu can
  carry.
- **A line with no `DE`, a CQ, or a line between two other stations is
  refused with a reason** in the transcript -- "no received line names a
  station -- nothing like 'MYCALL DE THEIRS'". The transcript is the only
  text surface the conversation screen has, so that is where the refusal
  goes.
- **No duplicate check, deliberately.** `DUPE_CHECK` belongs to the log
  screen, which can show the operator the earlier contact and let them
  decide. The honest failure here is a second entry, which is visible in the
  log and removable; a hotkey that silently declined would look like a dead
  key at exactly the moment the operator was counting on it. `prefill`, the
  default behavior, puts the contact in front of the log screen's own check
  before anything is written.

### Not built: selecting an earlier line with the arrows

The specification above says the arrows reach earlier received lines.
`decall.candidates` returns them all, newest first, so the data is there --
but on the conversation screen `↑` and `↓` are over history recall, and
taking them would cost a key that is used far more often than this one.

`^G` pressed again in either prefill mode steps back to the next older
candidate instead, and the transcript names the line it took. Same
capability, on the key that is already in the operator's hand.

---

## 5. WSPR map

A toggleable display on the WSPR screen: a line-drawn world map with spot
locations lit.

### Appearance

- Continent and country outlines drawn in the **dim** variant of the active
  color scheme; spots lit in the **bright** variant. `colors.py` already
  defines both for all five schemes.
- Country boundaries plus US states and Canadian provinces. No great-circle
  paths.
- The world is cut at the **Tibet meridian**, the same split used by the
  cyberdeck WSPR article's interactive map, which puts the station in the
  middle and leaves no path crossing the seam. Enough of Antarctica to show
  the Antarctic stations, which do appear — `DP0GVN` at Neumayer III was
  decoded on 30m during the October run.
- Band toggles on hotkeys, listed across the bottom.
- Scope configurable: the current WSPR activity, or a user-defined window
  backward from now.

### A working prototype already exists

`wspr_7510_analysis/terminal_map_prototype/terminal_map.py` renders this,
and the output reads exactly as intended — phosphor-green line work on black
at the panel's native 800x480. It settles most of what would otherwise be
guesswork:

- **The Tibet split is done properly.** It clips geometry into two boxes at
  90 E and shifts the eastern part by -360, so country outlines are cut and
  rejoined rather than smeared across the seam. The map spans -270 to +90 and
  puts the Americas and the station in the middle.
- **Mercator with the poles clipped** to -78 and +80 degrees, which keeps
  enough of Antarctica for the Antarctic stations — `DP0GVN` at Neumayer III
  was decoded on 30 m during the October run — without the infinite stretch.
- **The dim/bright treatment is already the deck's.** Coastlines at `#004100`,
  spots at `#00FF00`: the Matrix scheme's dim and bright values from
  `colors.py`, arrived at independently.
- Grid-to-lat/lon, band classification, a distinct home-station marker, and a
  band list across the bottom.

### What the prototype does not yet do

- **US states and Canadian provinces are missing.** It loads
  `ne_110m_admin_0_countries` only. The spec calls for internal boundaries,
  which is `ne_110m_admin_1_states_provinces` as a second layer.
- **Band toggles are not interactive.** The bottom line lists the bands heard;
  it does not switch them.
- **It colors for Matrix only.** The hex values are literals and need to come
  from the active scheme.

### Two problems to solve before it runs on the deck

**It fetches Natural Earth over the network at render time**, from an AWS
bucket. A field deck has no network by assumption. The boundary data has to be
vendored onto the card.

**The dependency stack is heavy for a Pi 3A+** — geopandas, shapely,
matplotlib and pyproj on a 512 MB board, to draw a picture that does not
change.

That second point suggests the shape of the fix. **The basemap is static and
only the spots move.** Nothing about the coastlines depends on the data, the
band selection or the time window. So the expensive half can be done once, off
the deck:

- Pre-render the boundary layer — as a PNG per color scheme, or better, as a
  compact list of projected polylines — and ship that on the card.
- On the deck, draw the spots over it. That needs grid math and line drawing,
  both of which `src/grid.py` already has, and none of geopandas.

This removes the network dependency and the dependency stack in one step, and
leaves the deck doing work proportional to the number of spots rather than to
the complexity of the world's coastlines.

### Then the display question

With a pre-rendered or lightly-drawn basemap there are two ways to get it on
screen, and they have different risks.

**A framebuffer image viewer** — `fim` or `fbi` — shows a PNG at native
resolution, which is what the prototype already produces. The risk is that
**the deck owns `tty1` and draws through curses, and an image viewer writes to
the same device.** Handing the framebuffer over and taking it back cleanly,
without a corrupted curses screen and without losing the keyboard while the
viewer holds it, has not been tried. The WSPR audio handover is the precedent
for how badly this class of problem goes: fldigi opening the codec once and
never retrying cost a stuck transmitter.

**Drawing in curses with block and line characters** avoids the handover
entirely, inherits the color scheme for free, and keeps the keyboard. It is
lower fidelity, and whether it still looks like an 80s computer display at
66x20 is the open question — though the panel can run a smaller font for this
screen alone, which buys back resolution without leaving curses.

The second is the safer default. The first is worth prototyping on the deck
before committing to either, and that prototype is a half-hour test rather
than a feature.

### What exists on the deck already

`src/wsprlog.py` reads the spot log; `src/grid.py` does grid-to-lat/lon math
validated against wsprnet rows to within half a kilometer on 6-character
grids. Neither needs anything added for this.

### Built 2026-10-22

`src/wsprmap.py` (projection, spots, band and direction filtering),
`src/fbdraw.py` (the framebuffer), `tools/make_basemap.py` (off-deck),
`WSPRMAP` in `cyberdeck.py`, `render.map_overlay`. `tests/test_wsprmap.py`
95 checks, `tests/test_fbdraw.py` 30, `tests/test_mapscreen.py` 59. `m` on
the WSPR screen.

**No geopandas, no network, no image library on the deck.** The basemap is a
zlib-compressed 1-bit mask, about 11 kB per view, generated off the deck and
shipped on the card -- `src/basemap_focus.bin`, `basemap_global.bin`,
`basemap_wide.bin`. Drawing it is pure arithmetic over `src/grid.py`'s math.
The dependency stack the prototype needed never reaches the Pi.

**Direct framebuffer writes, not `fim` or `fbi`.** The handover problem the
specification worried about is real and was not risked: the WSPR audio
handover is the precedent, where fldigi opening the codec once and never
retrying cost a stuck transmitter. `fbdraw` packs RGB565 and BGRX, builds the
canvas whole and writes it once, and `available()` returns False off the
deck, where the two text rows still work and the map area says so.

Because the framebuffer is the same memory the text console draws on, **the
picture is written on entry and on change, not every frame**. Curses owns the
two rows it needs; every other write would fight the redraw.

**Three views, cycled with `v`**, after the Mercator-vs-Miller question was
settled with rendered examples rather than argument: the latitude clip
matters more than the projection, because Mercator spends 44% of the panel on
Greenland and Antarctica. `focus` is the USA with a longitude clip, `global`
drops the poles, `wide` keeps a strip of Antarctica -- which is not
decoration: `DP0GVN` at Neumayer III is a station this antenna has heard.

**The world is cut at 90°E**, through Tibet, so no path crosses the seam.
Cutting at the date line put Australia on the map twice with paths running
to the wrong copy.

#### The wrong turn worth keeping

The near-vertical lines on the first map were read as polar great circles to
VK6 and written up as such. **They were corrupt decodes** -- grids at 88°N
and 86°S, impossible for the callsigns carrying them. The filter that
replaced the guess is network corroboration, not a latitude heuristic: a real
WSPR beacon is heard by dozens of receivers and a corrupt decode by exactly
one. In the October capture, 454 of 463 stations were heard by five or more
receivers and 9 by exactly one, with nothing in between.

A latitude filter was tried first and **dropped `DP0GVN`**, a real station in
Antarctica. That is why the heuristic is gone rather than tuned.

#### Two regex bugs made twice

`Q`, `0` and `1` are never the FIRST character of a callsign. `Q` anywhere
else is ordinary -- `SQ2WB`, `KQ4ADJ` -- and a pattern barring `Q` outright
rejects real stations. This was written wrong in the corrupt-decode filter and
then written wrong again in `src/decall.py`. Both bar it only in first
position now.

---

## 6. Logger map

The same map, pointed at the contact log instead of the spot log: same
layout, same controls, same color treatment, same band toggles.

It is one feature built twice only if it is written twice. The map should take
a list of `(latitude, longitude, band)` points and a scope, and the two
screens should differ only in what fills that list — `wsprlog` records for
WSPR, `qsolog` records for the logger.

Contacts carry a grid when the schema includes one or the callbook lookup
filled it, and not otherwise. A contact with no grid cannot be plotted, so the
logger map needs to say how many records it is leaving out rather than quietly
showing fewer points than the log contains.

### Built 2026-10-22

`LOGMAP` in `cyberdeck.py`, sharing `src/wsprmap.py` and
`Deck._build_map` / `_draw_map` / `_blit_map` / `_handle_map` with the WSPR
map. It was written once: the two screens differ in `_build_map`'s two
branches and in the direction legend, and in nothing else.

Reached with `F5` on the log screen, and from the logging `F1` menu as `g`.
A function key rather than a letter because every printable key on the log
screen types into the entry form -- the WSPR screen can afford `m` for the
same job and this one cannot. The footer has no room to say so, at 61 of 66
columns already, so the menu names the key.

**One direction legend, not two.** The WSPR map's `t` cycles heard /
heard-by, because on WSPR those are different questions and the gap between
them is the measurement. A worked contact answers both at once: a QSO that
only went one way is not a QSO. So the log map shows one legend reading
"worked", and `t` says "every contact is two-way -- nothing to filter"
rather than offering a filter whose other position would always be empty.

---

## 7. One-key export off the deck

Getting the transcript, the contact log, the WSPR spots and the settings off
the deck without a laptop, **into a Google Drive folder**, where they can be
picked up from a phone and uploaded onward.

The destination is a staging place, not a destination of record. See the
boundary at the end of this section.

### Built 2026-10-22 — the LAN page. The Drive path is not built.

`src/export.py`, `wifi.address`, `EXPORT` in `cyberdeck.py`,
`render.export_screen`, `tests/test_export.py` (122 checks, driven over real
HTTP against a server bound to loopback). Reached from the deck & rig `F1`
menu as item 5.

Config: `EXPORT_DIR`, `EXPORT_PORT` (8080), `EXPORT_IDLE_MIN` (5).

Everything decided below is as built, with three things worth recording
because they are not obvious from the specification:

- **The request names a position, never a file.** `/a7f3/2` is the third item
  on the list the deck handed the server. There is no path in the request to
  traverse out of, which is why `../cyberdeck.secrets` and its encodings are
  a 404 rather than something a filter has to catch -- and
  `tests/test_export.py` tries all of them, including against a real
  `cyberdeck.secrets` planted in the served directory.
  `BaseHTTPRequestHandler`, not `SimpleHTTPRequestHandler`: the latter maps
  request paths onto the filesystem, which is the single thing this must not
  do.
- **The handler logs nothing.** `http.server` writes a request line to
  stderr, and on the deck stderr is tty1 -- the console curses is drawing the
  panel on. Every tap on the phone would have scribbled across the screen.
- **The idle timer is polled from the main loop**, beside the WSPR and tuner
  polls, not from the export screen's own draw. A server that only expired
  while its screen was being looked at would stay up for as long as the
  operator was anywhere else on the deck, which is exactly the case the timer
  exists for. It also comes down in the `finally` that un-keys the
  transmitter, so a crash does not leave a socket bound across the systemd
  restart.

Two additions to what was specified: `Space` issues a new token and address,
for when the old one has been read out loud or the deck has changed networks,
and the port is stepped over if it is occupied -- an export interrupted and
restarted can meet its own socket in `TIME_WAIT`, and refusing for that
reason would be refusing for a reason the operator cannot see or fix.

The token alphabet leaves out `l`, `1`, `o` and `0`. It is read off a 5"
panel and typed into a phone, where those four are the characters that get
mistaken for each other.

### Decided: a web page on the deck, opened in the phone's browser

Go to a URL, see the files, tap the ones wanted, they download. Nothing
installed on the phone, no account, no app.

**Plain HTTP, not FTP.** FTP was considered and is the worse fit for this
specific job: **Chrome removed FTP support in 2021**, so `ftp://` does not
open in the phone browser at all and would need a separate file-manager app.
`http.server` is in the Python standard library; a usable FTP server
(`pyftpdlib`) is not installed on the deck and would be a new dependency on
the card. FTP's advantage is write access, which this feature does not need —
and SFTP already covers that case, see the note at the end of this section.

### Why serving from the deck beats a cloud round trip

**The deck and the phone are usually already on the same network.** The deck
joins a phone hotspot as a matter of course — `callbook.py` and `qrzlog.py`
both handle that case explicitly — and `cyberdeck.local` already resolves,
which is how the deploy and pull procedures in `scratch_notes.md` reach it.

So the shortest path off the deck does not involve the internet at all. The
deck starts a small HTTP server on demand over a fixed directory and shows
the URL on the panel. The phone opens it, the files are listed, a tap
downloads. The upload to QRZ then happens from the phone.

What this buys over a cloud round trip:

- **No credentials anywhere.** No OAuth, no refresh token on the card, no
  account in the loop, nothing to expire.
- **It works with no internet.** On a field hotspot with no uplink the deck
  and the phone still see each other. A cloud destination needs egress; this
  does not.
- **About twenty lines**, on `http.server` from the standard library. No new
  binary to ship on the card and no ARM build to track.

**Put a random token in the path** — `http://cyberdeck.local:8080/a7f3k2/qso.adi`
— generated per export. On a shared hotspot that is the
difference between the logs being on the network and the logs being at an
unguessable address for as long as the server is up. It costs one line and
needs no password entry on a five-inch screen.

The server starts when the export key is pressed and stops on exit or after a
short idle timeout. An always-on file server on a deck that joins strange
networks is a different thing entirely.

#### The address the panel shows

The panel shows the address as text and the operator types it into the phone's
browser. No encoder to vendor and no screen given over to a graphic.

**The address, not the hostname.** The deck does advertise itself — Raspberry
Pi OS Lite ships `avahi-daemon`, which is why `cyberdeck.local` works in the
deploy and pull procedures — but **Android resolves `.local` inconsistently**,
and Android is the phone this is for. So the screen leads with
`http://192.168.1.47:8080/a7f3` and prints `cyberdeck.local` underneath as the
shorter thing to type when it happens to work.

**Keep the token short, because it is typed.** Four lowercase alphanumeric
characters is about 1.7 million combinations, which is ample for a server that
exists for ninety seconds, and it is four characters to thumb in rather than
six. The point is not to withstand an attack; it is that the logs are not
sitting at a guessable address on a hotspot shared with strangers.

A URL this short leaves room on the panel for the file list beside it.

#### Binding

Bind to the WiFi interface's own address rather than `0.0.0.0`. The deck has
other interfaces, and a server that only exists on the network the operator is
actually looking at is easier to reason about than one that exists everywhere.

#### What is served

A single page listing the files, each a direct download link:

- the freshly written ADIF
- `qso.log`, the raw contact log
- `wspr.log`, the spot log
- the session transcript
- the settings, with `cyberdeck.secrets` excluded

The ADIF is generated on demand today rather than kept current, so the export
writes it before serving rather than offering a stale copy.

The page is the whole interface. No upload, no delete, no directory browsing
above the export folder — a read-only list of five files is the entire
surface, which is also most of why this is safe to stand up on a hotspot.

#### SFTP already works, for the other half

**SSH is enabled on the deck by default** — `DECK_SSH` defaults to `yes` in
the image build, and the deploy and pull procedures in `scratch_notes.md`
depend on it. An Android file manager that speaks SFTP can connect to the deck
today with no new code at all, browse the whole filesystem, and copy files in
both directions.

That is the answer when the need is to *manage* files rather than fetch them.
It needs an app and credentials, which is why it is not the one-key path, but
it is already there and costs nothing to document.

### The two paths answer different questions

| Situation | Method |
|---|---|
| Phone in hand, same network | **A page on the deck.** Simpler, no secrets, works with no internet |
| Unattended, deck has internet | **rclone to Drive.** Files land without anyone present |

They compose rather than compete. The LAN server needs no secrets, so
building it first costs nothing against adding Drive later.

The rest of this section covers the Drive path.

### Drive: the hard part is consent, not transfer

Google's Drive API needs OAuth2, and the **device-code flow — the one meant
for TVs and keyboard-less devices — does not cover Drive scopes.** There is no
clean way to complete a Drive consent flow on a 5-inch panel with no browser.

### rclone, for the Drive path

`rclone` moves the consent off the deck and does it once. `rclone authorize
"drive"` runs on a laptop, produces a token blob, and that blob goes into the
deck's `rclone.conf`. The token refreshes itself from then on, and no laptop
is involved again — which is the actual requirement.

- **A single static ARM binary**, no Python dependency tree on a 512 MB
  Pi 3A+.
- **Not locked to Google.** The same command targets Dropbox, OneDrive, S3,
  WebDAV, Nextcloud or SFTP, so a self-hosted destination later needs no new
  code in the deck.
- **One subprocess call**, the pattern the deck already uses for `arecord`,
  `wsprd` and `systemctl`.

```bash
rclone copy ~/.local/share/cyberdeck/qso.adi  remote:cyberdeck/
rclone copy ~/.local/share/cyberdeck/wspr.log remote:cyberdeck/
```

`rclone.conf` holds a live refresh token and needs the handling
`cyberdeck.secrets` already gets — mode 600, gitignored, and never rendered on
a settings screen.

`remote:` is the Drive remote named during that one-time authorize step, and
the folder it writes into is an ordinary Drive folder that syncs to a phone.

### The one alternative worth keeping in mind

**A Google service account** reaches Drive with no consent flow at all: create
the account, share a Drive folder with its address, and it can write there
forever using a JSON key file. No laptop is needed even for setup.

It is worth knowing about because it removes the single awkward step in the
rclone route — the one-time `rclone authorize` on a laptop. The cost is JWT
signing and a few hundred lines of HTTP where rclone is a subprocess call, and
files land in a folder owned by the service account rather than by the
operator unless the sharing is set up the right way round.

**rclone is still the recommendation.** The setup step happens once, on a
machine that is already in the room when the deck is being built.

### The boundary this must not cross

**The QRZ upload is deliberately not bound to a key.** `src/qrzlog.py` is
written and carries 58 passing checks, and the `Upload to QRZ` line was
removed from the logging menu on purpose. The reasoning is recorded in
`menus.log_menu`: *a deck full of test contacts must not be one keystroke from
someone's permanent record.*

Exporting to a staging folder does not cross that line — it is reversible and
nothing downstream happens without a person. **Uploading to QRZ from a panel
key does**, and this feature is not a reason to revisit it. Off the deck
first; uploaded from somewhere else afterward.

There is also a plain practical reason the API path is closed. **QRZ's
logbook INSERT requires a paid subscription**, which this station does not
have — `qrzlog.py` already records that the API answers and refuses without
one. Manual ADIF upload through the QRZ website works on any account. So
file export is not a workaround for the safety decision; it is the only route
available, and the safety decision costs nothing.
