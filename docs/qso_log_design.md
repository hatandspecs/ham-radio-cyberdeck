# QSO Logging — Design

A general-purpose contact log for SSB and digital operating, built so that a
deck with logging switched off is indistinguishable from a deck that never had
the feature.

**General-purpose is a design constraint, not a description.** The log is a
plain list of contacts: time, call, frequency, band, mode, reports, name, QTH
and a free-text comment. Nothing above that layer knows what kind of operating
produced the contact. Special-interest programs — POTA, and anything else that
uses ADIF's generic activity fields — are an optional overlay of two fields
that are omitted from a record entirely when unused (§6a). A ragchew on 40 m,
a digital contact across the state and a park activation are the same record
type with different fields filled in.

Status: **design and prototype**. The cores — `src/qsolog.py`,
`src/callbook.py`, `src/qrzlog.py` and `src/lotw.py` — exist with 370 checks
in their own test files, none of which touch a network or need the rig, and
`tools/qso.py` drives them from a terminal today (§8a). Nothing is wired into `cyberdeck.py` yet: the log screen
renderer and the logging menu exist and are tested as pure functions, and the
root-menu entry and key handler that reach them do not.

**QRZ upload is paused** as of 2026-10-10: the code is complete and correct,
and the account has no QRZ subscription, which their API requires for every
action including a read-only status check. See §7.7a. Everything else — the
log itself, ADIF export, the activity fields and the callbook lookup — is
unaffected and needs nothing from QRZ.

---

## 1. The governing requirement

Logging is **off by default and absent when off**. That is not a preference
about defaults; it is the constraint the architecture is built around, and it
decides most of what follows.

Absent means, specifically:

* No key is bound. The log key falls through to the unhandled-key branch in
  `_chat_key`, exactly as an unused key does today, and prints its diagnostic
  to stderr.
* No field appears in the status line. The line is already at its width budget
  (§5.2 of the design doc records that the radio's own mode was removed because
  seven columns were the difference between fldigi's second status field
  fitting and not).
* No file is created anywhere. Not an empty log, not a state key.
* Nothing runs in the main loop. The logger polls nothing and has no timer.
* One menu entry exists, and only one, so the feature is discoverable without
  reading the source. That entry and its key handler are added together: an
  entry whose Enter does nothing is worse than no entry, because the line's
  entire purpose is to be discoverable and it then misleads. `test_menus.py`
  asserts it is absent from `ROOT` until `cyberdeck.py` can act on it, and
  `test_menu_arrows.py` catches the dead-item case, since Up-then-Enter from
  the first item lands on whatever is last.

The single visible trace when off is that root-menu line. The alternative —
enabling it only by editing `cyberdeck.conf` over SSH — is more invisible and
worse, because the deck is meant to be operable from the panel.

## 2. Scope

**In.** Logging any contact made in SSB or in the digital modes the deck
already runs — a casual contact, a net, a schedule, a park activation, all the
same way. Date, time, frequency, band, mode, both reports, name, QTH, grid and
a free-text comment. A dedicated log screen. Append-only storage that survives
a power pull. ADIF export. Callsign lookup when there is a network, and silence
when there is not. The mode filled in from the deck when the deck is what is
making the contact, and left alone when it is not (§6). Optional upload to a
QRZ logbook, queued so it works with the WiFi off, and ADIF-plus-`tqsl` for
LoTW (§11). An optional POTA mode, off by default, for operators who chase
that program (§6a).

**Out, deliberately.** Contest exchanges, serial numbers, multiplier tracking,
dupe checking, rate meters, spotting, Cabrillo, and any integration with
fldigi's own logbook. A contest logger is a different program
with a different interface, and §9 says what it would take.

## 3. Why ADIF and not Cabrillo

ADIF is the interchange format every other piece of amateur software reads —
LoTW, eQSL, QRZ, club logs, and every desktop logger. Cabrillo describes one
contest entry and is useless outside it.

The stored format is neither. It is a plain line-per-QSO text file with named
fields, from which ADIF is generated. That separation matters: the file is the
record, the export is a view of it, and a bug in the exporter costs nothing
because it can be run again.

## 4. Storage

```
~/.local/share/cyberdeck/qso.log
```

One record per line, `key=value` pairs separated by spaces, values containing
spaces quoted. Append-only. Flushed and `fsync`ed on every commit, because the
deck is expected to lose power without warning and a log that loses the last
contact is worse than no log.

```
when=2026-10-10T16:12:03Z call=W3ABC freq=7074000 band=40m mode=SSB rst_s=59 rst_r=57 name=Bob qth="Pittsburgh PA"
```

Readable and hand-editable over SSH, which is the recovery path for anything
the interface gets wrong. The field names are the ADIF names where ADIF has
one, so the export is a rename rather than a translation.

**Why not JSON or SQLite.** JSON requires rewriting the whole file to append,
and appending is what happens on every contact — a correction (§7e) rewrites,
but a correction is rare and a contact is not. SQLite survives
power loss well but is not readable or repairable with the tools on the deck,
and the failure mode of a corrupt database is worse than the failure mode of a
truncated text file — the latter loses one line.

## 5. What is captured, and from where

| Field | Source | Notes |
|---|---|---|
| `when` | system clock, UTC | RTC-backed; see §8 |
| `call` | typed | uppercased, validated |
| `freq` | rigctld | Hz; absent and marked if rigctld is unreachable |
| `band` | derived from `freq` | `40m` and so on; empty if frequency unknown |
| `mode` | fldigi on digital, the rig on voice | `OPERATING` picks the policy; see §6 |
| `rst_s`, `rst_r` | typed, defaulted | `59` for SSB, `599` for CW, `599` for digital |
| `name`, `qth` | typed, optional | |
| `grid` | callbook, or typed | §7.5; typed always wins |
| `comment` | typed after `;` | free text; the catch-all a general log needs |
| `park` | typed, recognized by shape | optional, any mode; §6a |
| `my_park` | station setting | POTA mode only; §6a |
| `my_call`, `my_grid` | station settings | written into every record so the file exports alone |

Absent hardware is an ordinary condition. If rigctld does not answer, the
record still commits, with `freq` and `band` empty and a `--` warning in the
transcript. A log entry with an unknown frequency is worth more than a lost
contact.

## 6. Mode determination

Two sources, in order:

1. **rigctld.** If the rig reports `USB`, `LSB`, `AM` or `FM`, the operator is
   on voice and the mode is `SSB`, `AM` or `FM`. The deck's digital modes
   cannot be in use, because fldigi is not driving a voice contact.
2. **fldigi.** Otherwise the mode is fldigi's current modem name, normalized to
   an ADIF mode: `BPSK31` → `PSK`, `RTTY` → `RTTY`, `Olivia` → `OLIVIA`,
   `MFSK16` → `MFSK`, `CW` → `CW`.

`rigctld_client.mode()` returns `(mode, passband_hz)` from rigctld's `m`
command, which answers with the mode on one line and the width on the next.

**The rule: on digital the mode is filled in from the deck; on voice it is
not.** fldigi always has a modem loaded whether or not it is being used, so
"which modem is up" is a different question from "what are we working", and
answering the first one logs a 40-meter ragchew as BPSK31.

Three inputs decide it, in `qsolog.resolve_mode`:

| Input | What it settles |
|---|---|
| `rig_mode` | A data mode (`PKTUSB`, `RTTY`, `DATA-U` …) is conclusive: only fldigi drives a rig in one. `USB` is **not** conclusive — this rig reports `USB` for voice and for digital alike, which is the whole reason the other two inputs exist. |
| `fldigi_modem` | What to log once it is established that digital is in use. |
| `fldigi_active` | Whether the deck has actually passed traffic recently. This is the discriminator the rig cannot provide, and it is the deck's own knowledge: it sees its own characters go by. |

`OPERATING` selects between three policies:

* **`voice`** — fldigi is never consulted, whatever it has loaded. A voice
  mode from the rig is believed; anything else falls back to `SSB`, because
  logging a digital mode for a contact made with a microphone is the error
  that matters.
* **`digital`** — fldigi's modem is the mode, falling back to the rig.
* **`auto`** (the default) — a data mode from the rig, or fldigi actually
  passing traffic, means digital. Otherwise a voice or CW mode from the rig is
  believed.

`resolve_mode` also returns where the mode came from — `fldigi`, `rig` or
`default` — so the interface can say that rather than present a guess as a
reading.

**One sharp edge, deliberately kept.** With no rig information at all and a
modem loaded, `auto` leans digital, because the deck is a digital terminal
first. An SSB session with no CAT control therefore wants `OPERATING = voice`;
that is what the setting is for, and the menu makes it two keystrokes.
`test_qsolog.py` pins this case so it cannot be changed by accident.

What still needs the rig is only the question of **which** hamlib string the
FTX-1 reports when fldigi is driving it. If it reports `PKTUSB` or similar,
`auto` needs no help at all; if it reports plain `USB`, `fldigi_active` is
load-bearing. §10 lists it as the first thing to test, and both answers are
already handled.

## 6a. Special-interest activities

Some operators chase programs — parks, summits, islands, lighthouses — where a
contact carries a reference in addition to the usual exchange. ADIF handles all
of them with one generic pair of fields, so the logger supports them the same
way: as two optional fields, not as a mode the log has to be put into.

**POTA is an activity, not a mode.** There was briefly both — a `POTA`
setting *and* `ACTIVITY = POTA` — which is two controls for one thing, and two
controls for one thing drift apart. The setting is gone (2026-10-11); POTA is
selected the same way every other activity is, and the same way an operator's
own definitions are.

Selecting it changes three things and nothing else:

| | General logging | `ACTIVITY = POTA` |
|---|---|---|
| Header | `LOG  20m  SSB  14.250` | `LOG  POTA  20m  SSB  14.250  US-5678` |
| Reference column | absent unless a contact has one | reserved once `MY_PARK` is set |
| This station's reference | not a question that applies | a menu line, and on every record |

The menu asks the *activity* whether it has a `park` field rather than
checking for the name "POTA", so an operator who defines a WWFF or IOTA
activity gets the reference setting without anyone editing the code.

The park column is the one place where drawing a blank field is right: during
an activation, the column being there is what makes the list scannable, and a
column that appears on the first park-to-park and shifts every row under it is
worse than an empty one. An unset park shows as `(no park set)` rather than
being omitted, so starting an activation without setting it is visible instead
of silently missing from all eighty records.

**Hunting needs no mode.** A park reference typed into an entry is recognized
by shape and honored whether or not POTA mode is on, because working one park
in an afternoon is not a reason to change modes. What the mode gates is *this
station's own* park — the activator side — which is the part that goes on every
contact and therefore the part worth being deliberate about. `--my-park`
without POTA mode is refused with a note rather than silently applied, so a
reference left in the configuration from last weekend cannot leak into an
ordinary log.

**Nothing here is on unless it is used.** A record with no park has no `park`
field in storage and no `SIG` fields in its ADIF (`test_qsolog.py` asserts
this). An ordinary contact is unaffected by the existence of this section.

POTA is the program implemented, because it is the one in use here. SOTA,
WWFF and IOTA use the same generic fields with a different `SIG` value and
would be a lookup-table entry, not a design change — §12 carries that as an
open item rather than speculation about demand.

**Hunting.** The park worked is recorded per contact, in `park`. It is typed
as part of the log line and recognized by shape — `US-1234` or the legacy
`K-0001` — so there is no separate field to tab into while somebody is reading
a reference at speed. It can appear anywhere after the reports, because
`W3ABC 59 57 US-1234` and `W3ABC 59 57 Bob US-1234` are both natural depending
on whether the name was caught.

**Activating.** This station's own park goes in `my_park`, a station setting
rather than something typed, because it is the same on every contact of the
activation and typing it eighty times is eighty chances to mistype it.

**Both at once** is a park-to-park, which is why these are two fields and not
one with a direction flag.

ADIF has two ways to say this and the export writes both.

ADIF 3.1.4 added dedicated `POTA_REF` and `MY_POTA_REF` fields. Before that,
POTA rode on the generic "special interest activity" pair, which is still what
pota.app's own upload matches on and what older loggers read. Current loggers —
QLog among them, which keeps its own POTA field — look for the dedicated ones.
Writing only one spelling loses the park at one end or the other, so the export
writes both, which is what every current logger does and what ADIF permits:

| | Hunting | Activating |
|---|---|---|
| `SIG` / `SIG_INFO` | `POTA` / `US-1234` | — |
| `POTA_REF` | `US-1234` | — |
| `MY_SIG` / `MY_SIG_INFO` | — | `POTA` / `US-5678` |
| `MY_POTA_REF` | — | `US-5678` |

So the ADIF export is also the activation upload, with no second format, and it
imports into a desktop logger without losing the park.

**The reference grammar is ADIF's `POTARef`, exactly:**
`xxxx-nnnnn[@yyyyyy]` — a 1-4 character national program, a hyphen, a 4-5
digit number, and an optional ISO 3166-2 subdivision for a park that spans
more than one. `US-1234`, `K-0001` and `US-4578@US-MD` are all valid. An
earlier version of the pattern allowed three-digit numbers and only three
program characters, which matched neither the spec nor its own comment;
tightening the digits also makes a false positive less likely.

## 6b. Activity types

An activity is a **named, ordered list of fields**. POTA exchanges a park
reference; a state QSO party exchanges a serial and a county; Field Day
exchanges a class and a section; an ordinary contact exchanges a name and a
QTH. Those are the same record with different optional fields filled in, so an
activity is data, not code — `src/activities.py` and `activities.conf`.

### 6b.0 Three defaults

| | Entry grammar | For |
|---|---|---|
| `GENERAL` | `rst_s, rst_r, name, qth` | everything else |
| `POTA` | `rst_s, rst_r, park, name` | park activations and hunting |
| `CONTEST` | `serial_rx, exchange_rx` | serial-and-exchange events, both directions |

**Three, and only three.** SOTA, WWFF, Field Day, Sweepstakes and the state
QSO parties are *examples* in `activities.conf.example`, to be copied and
changed — not built in. A built-in nobody uses is a line in a picker to scroll
past forever; a worked example is a starting point, and `like = CONTEST` is
how one becomes an activity.

All three record the same station context on every contact: frequency (and the
band derived from it), mode, UTC time, both reports, **and this station's rig,
antenna and transmit power** (§6c). Name and grid are filled from a callbook
when there is a network, or backfilled later when there is one (§7.5).

### 6b.1 The field list is the entry grammar

This is the whole design, and it exists to resolve an ambiguity that would
otherwise make a positional parser impossible. Given

```ini
[PAQP]
like = QSOPARTY
label = Pennsylvania QSO Party
contest_id = PA-QSO-PARTY
label_exchange_rx = County
```

then `W3ABC 123 MONT` is serial 123 and county MONT, and the reports default.
The same line shape in general logging means something else entirely.

**`599` is a valid signal report and a valid serial number**, and nothing about
the token says which one it is. No amount of cleverness in the parser can tell
them apart. The activity resolves it, because the operator chose the activity
before they started typing — the knowledge already exists and only has to be
written down once instead of inferred eighty times.

The fields an `entry` list may name:

| Field | Kind | Default label |
|---|---|---|
| `rst_s` | report | Sent |
| `rst_r` | report | Rcvd |
| `serial_rx` | number | Nr |
| `exchange_rx` | text | Exch |
| `park` | reference | Ref |
| `name` | text | Name |
| `qth` | text | QTH |

A text field takes one token, **except in the last position, where it absorbs
the rest of the line.** That is how `1B EPA` is one Field Day exchange while
`Bob Pittsburgh PA` still splits into a name and a QTH.

A number field is consumed **only if the token is actually a number.** This
matters more than it looks: if a missed serial let the exchange slide into the
numeric slot, every field after it would shift, and the log would be quietly
wrong rather than visibly wrong. `test_activities.py` pins it.

A park reference is pulled out **by shape, before anything positional, in every
activity.** Its shape is unmistakable (§6a), so position does not have to carry
it — and working one park in an afternoon needs no activity change.

### 6b.2 Sent versus received

Two kinds of field, and the distinction is the reason the grammar is short:

* **Typed per contact** — what the other station sends. The `entry` list.
* **Fixed for the event** — what this station sends. `EXCHANGE_TX` (a class, a
  county, a section: the same on every contact) and `MY_PARK`. Typing one's own
  exchange eighty times is eighty chances to mistype it.
* **Not typed at all** — this station's serial, which increments.

### 6b.3 Serials come from the log

`qsolog.next_serial` reads the highest `serial_tx` already recorded for that
activity and adds one. There is no counter file, deliberately: a counter is a
second source of truth that can disagree with the log, and its failure mode —
a serial sent twice, or twenty skipped — is not noticed until the log is
checked. The log is the thing that survives a power pull, so the log is what
the serial comes from. (It is no longer strictly append-only — §7e — but it is
still never written in place, so this holds.) Scoped per activity, so two events in one
weekend each count from their own start.

### 6b.4 Saving and reusing a definition

`[SECTION]` **is** the saved activity, by name. `like = QSOPARTY` starts a new
one from an existing one — the template — and anything restated overrides it.
A section whose name matches an existing activity customizes that one and
inherits implicitly, so `[POTA]` with one changed label does not blank POTA's
field list.

A definition that cannot work is refused **at load, with the section named**:
an unknown field, a field listed twice, a `like` that names nothing, a
non-numeric `serial_start`. An activity that silently does not exist looks
exactly like one that does nothing, and the operator finds out mid-contact.

An activity named in the configuration that no longer exists falls back to
general logging rather than raising. The contact is worth more than the
activity.

### 6b.5 ADIF

| Record field | ADIF | Type |
|---|---|---|
| `serial_tx` | `STX` | PositiveInteger |
| `serial_rx` | `SRX` | PositiveInteger |
| `exchange_tx` | `STX_STRING` | String |
| `exchange_rx` | `SRX_STRING` | String |
| activity's `contest_id` | `CONTEST_ID` | **Enumeration** |

The serial goes in the integer field because that is what lets a scoring
program add them up. `CONTEST_ID` is an ADIF *enumeration*, so a value outside
their table is non-conforming even though it is written — the activity supplies
it and the operator owns getting it right.

## 6c. The station on every contact

Three fields go on every record of every activity, because they describe this
end of the contact and an exported log should not need the configuration that
was in force at the time in order to be meaningful.

| Record | ADIF | From |
|---|---|---|
| `my_rig` | `MY_RIG` | `RIG` — the existing Station menu field, not a new one |
| `my_antenna` | `MY_ANTENNA` | `ANTENNA` — added to the same menu |
| `tx_power` | `TX_PWR` | **the radio**, falling back to `TX_POWER` |

Rig and antenna come from the Station menu because that is where the operator
already sets the rig, and a second place to say the same thing is a second
place for it to be wrong. `MY_ANTENNA_INTL` is deliberately unused: the ADIF
spec restricts it to ADX files.

### Power, and why the ceiling is a setting

hamlib reports the power control as a normalized 0.0-1.0 — a **position**, not
a wattage. Logging it directly records "0.4 watts" for a transmission at forty
percent of whatever the rig can do.

Turning a position into watts needs to know the ceiling, and **the ceiling is
not a property of the radio model.** This station is the case that proves it:
the FTX-1 runs at 6 W on its internal battery, 10 W on external power, and
100 W docked in the Optima with the SPA-1 amplifier. The same radio, the same
control position, three different wattages.

That rules out hamlib's `power2mW`, which converts using a **static** power
curve compiled into the backend. A curve built for 100 W logs a full-scale
control position as 100 W on a 6 W battery setup — a sixteen-fold error,
written silently into the log.

So `TX_POWER_MAX` is a setting: the ceiling of whatever configuration is in
use, scaled by the control position.

```
watts = round(level × TX_POWER_MAX)
```

One number, changed when the station changes, and **it works on any radio
hamlib can drive**. That portability is the point. Reading watts straight out
of the radio requires a command only that radio has, and a logger that works
with one radio is worth less than one that works with any.

`rigctld_client.power()` therefore tries, in order:

| | Source | Portable |
|---|---|---|
| 1 | `l RFPOWER` scaled by `TX_POWER_MAX` | any hamlib rig |
| 2 | `power_control()` — the radio asked directly | FTX-1 only |
| 3 | `power2mW` — hamlib's static curve | any rig, but wrong by the configuration's factor |

and the caller falls back to a fixed `TX_POWER` when none of them answers.

**The rig-specific step is isolated and deletable.** `power_control()` reads
the FTX-1's `PC` command, which answers in watts and names the back end (field
head, 005-010 W; SPA-1, 005-100 W — CAT reference p. 21). On any other radio
the command is not understood, it returns `(0, "")`, and the generic path
carries on. Deleting it costs the FTX-1 its automatic back-end detection and
costs every other radio nothing. It sits *behind* the generic path rather than
in front of it for that reason.

One thing `PC` does **not** resolve: it distinguishes the field head from the
SPA-1, but not the 6 W battery case from the 10 W external one — both are
`P1=1`, range 005-010. Whether the radio clamps its reported setting to 006 on
battery is unknown and needs a measurement (§10). `TX_POWER_MAX` covers it
either way, which is another argument for the setting being primary.

### Verified on the radio, 2026-10-11

Measured on the deck, FTX-1 field head on external power, hamlib 4.7.2:

| Front panel | `l RFPOWER` | `× 10` | `w PC;` | Agree |
|---|---|---|---|---|
| 0.5 W (minimum) | `0.05` | 0.5 W | `PC10.5;` | yes |
| 6 W | `0.6` | 6 W | `PC1006;` | yes |
| 10 W (maximum) | `1` | 10 W | `PC1010;` | yes |

Three points, all agreeing, and **linear from zero** — had hamlib normalized
against the rig's 5 W floor, 6 W would have read 0.2 rather than 0.6. So
`watts = level × TX_POWER_MAX` is exact rather than the approximation it was
written as, and the ceiling for this configuration is 10.

**The minimum is where the manual is wrong.** The CAT reference documents `PC`
as three digits (`005 - 010`); at 0.5 W the radio sends `PC10.5;`. A
three-digit pattern fails to match and reports "no answer" — so full power
reads correctly and QRP does not, which is the quiet kind of wrong. Transmit
power is therefore never rounded to a whole number either: `TX_PWR` is an ADIF
Number, `0.5` is valid, and a QRP station running half a watt is exactly who
cares about this field.

Four things the measurement changed:

* **`power2mW` answers `RPRT -1`** — not implemented in the FTX-1 backend. The
  hamlib-curve fallback is dead on this radio, so `TX_POWER_MAX` is not a
  convenience over it; it is the only generic path that works.
* **`w` returns replies with a trailing NUL** (`'PC1006;\x00'`), which
  `str.strip()` does not remove. The field parsers use `search` and would have
  survived it silently.
* **The rig reports `PKTUSB`**, a hamlib string and not an ADIF mode. See §6 —
  a rig data mode is now evidence that fldigi's answer is right, never the
  answer itself.

What `l RFPOWER` and `PC` still cannot distinguish is the 6 W internal-battery
case from the 10 W external one: on external power the panel set to 6 W reads
exactly the same as it would on battery at its maximum. `TX_POWER_MAX` is what
carries that, which is the argument for the setting being primary.

The same preference applies to the `{power}` message-memory token (§6d). A
brag line that says 20 W while the radio sits at 5 is worse than no brag line.

## 6d. Message memories

The memory tokens gain `{ant}` and `{power}` beside the existing `{call}`,
`{name}`, `{qth}`, `{grid}` and `{rig}`:

```
RIG IS {rig} RUNNING {power} TO {ant}.
```

`{rig}` and `{ant}` are station settings. **`{power}` is read from the radio**
at the moment the memory is inserted, falling back to `TX_POWER`, and expanding
to nothing at all when neither is available — a memory reading "RUNNING  TO A
WIRE" is odd, but one stating a wattage the radio is not using is wrong, and on
the air wrong is worse than odd.

The rigctld client is created lazily and only by `{power}`. The deck has never
held one — it drives the radio through fldigi — and a memory nobody has put
`{power}` into should not start a connection.

## 7. Interface

### 7.1 A screen of its own

**Superseded by §7f and the area ring: there is no key that jumps to the log.**
`^O` and `^P` reach it as they reach every application, and `Esc` backs out
within it rather than leaving it. The original reasoning follows.

**Ctrl-N** opens the log screen; **Esc** returns to the transcript. One key,
not two, because on SSB the transcript has nothing on it worth reading and the
whole display should be the log.

The deck already has this shape: `pair_screen`, `wifi_screen` and
`no_keyboard_screen` are full-screen renderers in `render.py` with their own
key handler and a `self.screen` constant. The log screen is `LOG`, built the
same way, which means it is testable as a pure function of its arguments like
the others.

F1-F4 are taken on every screen: F1 the menu for the area, F2 and F3 that
area's two sub-views, F4 the color cycle. Of the free control keys — 5, 7, 11,
15, 16, 22 — Ctrl-N for "new QSO" is the least unmemorable. Bound **only when
logging is on**; otherwise it falls through to the unhandled-key branch like
any unused key.

Ctrl-O and Ctrl-P are no longer free: they walk the area ring, which is the
other way into the log. Ctrl-Z is not free either, whatever a count of unused
bytes says — `linux` terminfo maps `kspd=^Z`, so ncurses returns KEY_SUSPEND
on the deck and the byte never arrives. Nor is Ctrl-M, which is byte 13 and
therefore Enter.

Layout at 66x20:

```
 LOG  20m SSB  14.250  US-5678              14 QSOs   16:12Z
 ------------------------------------------------------------
 16:04  W3ABC     59/57  US-1234  Bob      Pittsburgh, PA
 16:07  K2XYZ     59/59           Jim      Albany, NY
 16:09  N3QQQ     59/55  US-0042
 ...
 ------------------------------------------------------------
 > W3ABC 59 57 US-1234 Bob_
   Esc back   Enter log
```

The header carries band, mode, frequency and this station's park when
activating, because on SSB those are the things being read aloud and the
transcript is no longer showing them. The entry line is the only thing with
focus.

**It never touches the compose buffer.** The deck's first rule is that typed
text is not lost, and the log screen has its own buffer for exactly that
reason. An over in progress survives a visit to the log and back.

### 7.2 During an over

Refused, with `-- not while transmitting` in the transcript. The operator is
sending; the keystrokes belong to the radio. The alternative — opening anyway
and diverting keys — is the kind of surprise that costs a contact.

### 7.3 What is typed

Positional, forgiving, with defaults:

```
W3ABC                       → 59/59 (or 599 digital), nothing else
W3ABC 57                    → sent 59, received 57
W3ABC 59 57                 → both reports
W3ABC 59 57 Bob Pittsburgh  → reports, name, and the rest as QTH
W3ABC 59 57 ; 5W to a wire  → everything after ; is a free-text comment
W3ABC 59 57 US-1234         → a park reference, recognized by shape (§6a)
```

The comment is the field that makes this a general log rather than a
contest-exchange log. "QRP 5 W", "first one from this county", "will send a
card" — none of that fits a positional scheme, and no positional scheme can
tell it from a QTH. One unambiguous separator costs less than a second field
to tab into, and nothing else on a log line contains a semicolon. It is the
last column on the screen and the first thing truncated, because everything
to its left is a field someone may need to read back.

Enter commits, Esc cancels. Malformed input produces a `--` message and leaves
the line intact for correction, never a silent drop.

**Prefill from the transcript.** The session already knows who it is talking
to: entries carry `who`. If the most recent remote entry has a callsign, the
log line opens with it filled in and the cursor after it. This is the one place
where the deck being a *conversation* terminal rather than a logging terminal
earns something.

### 7.4 Status line

The log screen has its own header, so the transcript's status line needs
nothing — which is the point. When logging is on and the operator is on the
chat screen, one field is appended showing the session's contact count, placed
**first in the drop order** so a narrow screen loses it before anything that
was there before. The status line's existing contract is not disturbed.

### 7.5 Callsign lookup

Off by default, separately from logging, because it sends every callsign
worked to a third party and that should be a decision rather than a default.

When on and the deck has a network, typing a callsign and pausing starts a
**background** lookup against callook.info — free, no key, no registration, US
callsigns. Three rules, all of them from the deck rather than from the lookup:

* **It never blocks.** `cyberdeck.py` is a single-threaded curses loop; an
  HTTP request in it freezes the screen for as long as the network takes,
  which in the field means until the timeout. The lookup runs on a worker
  thread and the answer is collected on a frame the interface was drawing
  anyway, or never.
* **It never gates a commit.** A contact is logged whether or not anything is
  known. A lookup still running when Enter is pressed is simply not used.
  Absent network is an ordinary condition, exactly like absent rigctld.
* **What was typed always wins.** The lookup fills blanks only. The operator
  heard it on the air; callook is reading a license record that may be years
  old.

Every answer, including "not found", is cached to disk. A negative result is
cached precisely so that a call nothing knows about does not cost four seconds
of timeout every time it is worked. **The cache is the point, not an
optimization** — the deck spends most of its life with the WiFi off, and a
station worked once at home is known at the park.

#### Three providers, ordered by what each gives away free

| | callook.info | HamQTH | QRZ XML |
|---|---|---|---|
| Coverage | US only | worldwide | worldwide |
| Account | none | free | free |
| Session | none | one per hour | no stated lifetime |
| Gives the **grid** | yes, when the FCC record is geocoded | yes | **usually not** without a subscription |
| Tried | first | second | last |

The order is by the grid, not by reputation. callook needs no account at all
and its license data is the most authoritative for a US call. HamQTH is what
makes a non-US call work. QRZ is last because the one field it withholds from
a non-subscriber is the one most worth having — measured 2026-10-11, `<grid>`
came back for one call in three, the others carrying "A subscription is
required to access the complete record."

QRZ's XML service is **not** the QRZ logbook upload of §7.7: different
endpoint, different credential, different subscription. Having one says nothing
about having the other. `QRZ_USER`/`QRZ_PASSWORD` versus `QRZ_API_KEY`.

#### Partial answers are filled in, not accepted

This station's own callsign is the case that proves the rule. callook has the
name and the town but an **empty `gridsquare`** — the FCC record was never
geocoded — while HamQTH has `FN10`. An earlier version of the chain stopped at
the first non-empty answer and so returned a contact with no grid when a grid
was one request away.

So the chain fills gaps: earlier providers win **per field**, and it stops as
soon as name, QTH and grid are all present. A complete first answer therefore
still costs exactly one request. The extra round trip when an answer is partial
costs nothing visible, because lookups run off the interface thread.

One provider raising does not stop the next being asked, and none of them can
stop a contact being logged.

**HamQTH's username is the callsign, not the email address.** Verified against
the live API on 2026-10-11: the email is refused with "Wrong user name or
password". This is worth knowing because it is the failure that looks like a
wrong password.

**A password containing `&` must be URL-encoded.** This station's QRZ password
does. Pasted raw into a query string it terminates the query there and sends a
different, shorter password, which the server reports as an incorrect
password — another failure that looks like the wrong credential rather than a
client bug. Both providers build their queries with `urlencode`, and
`test_callbook.py` asserts the escaping.

**`nick`, not `name`.** HamQTH's `name` is a private field and is empty
whenever the operator has hidden it, which is common; `nick` is the on-air name
and is the one worth logging. Reading `name` first returns blanks from exactly
the stations most likely to care.

Credentials are `HAMQTH_USER` and `HAMQTH_PASSWORD` in `cyberdeck.secrets`,
never in `cyberdeck.conf` — which now **refuses** them outright rather than
honoring them quietly, because that file is the one meant to be safe to hand
over. A credential that works from a shareable file is a credential that
travels.

HamQTH's session is held for fifty minutes against a documented hour. QRZ
documents **no** guaranteed lifetime and invalidates a key when the client's IP
changes — which on a deck that moves between a home network and a phone
hotspot does happen — so there is no timer there at all: a lapsed key is
detected from the reply and the login repeated, which is the only thing that
can work.

A lookup is retried **only** on session expiry. "Callsign not found" is also an
`<error>`, in both services, and retrying on any error would double the traffic
for exactly the lookups that were already a dead end.

Names are cased for a log rather than title-cased blindly. callook returns
capitals, so `.title()` alone turns an operator whose nick is "JP" into "Jp".
A token with no vowels, or one of two characters, is initials and is left
alone.

POTA park names could be resolved the same way from `api.pota.app`. Not built;
the reference alone is what the log and the upload need.

### 7.6 Menu

Logging is an AREA, not a line on another area's menu: `Ctrl-O` and `Ctrl-P`
reach it from either side, and nothing else does. Its own menu is `F1` from the log
screen, and the toggle is the first line of that:

```
Logging          on — 14 QSOs
```

The rest of that menu:

```
Logging                      on — 14 QSOs
Export ADIF
Upload to QRZ                3 waiting
Sign and upload to LoTW
Mode from                    auto — fldigi on digital
Callbook lookup              on
POTA mode                    on
  My park                    US-5678
```

General items first: the log, its exports, where the mode comes from, and the
lookup all apply to every contact. POTA mode is last because it is the one
that does not, and `My park` is indented under it because it only exists while
that mode is on.

Three items are absent rather than disabled:

* `Upload to QRZ` without a configured key
* `Sign and upload to LoTW` without `tqsl` on PATH
* `My park` with POTA mode off — not an unset field, a question that does not
  apply

An item whose only possible answer is "this is not set up" occupies a line,
invites a keystroke and teaches nothing.

At its fullest the menu is eight items, which matters: more than `height - 6`
makes the renderer split into two columns that truncate every label at 27
characters. `test_menus.py` asserts it stays inside one column at 66x20 and
that nothing overflows at any width.

### 7.7 Uploading to QRZ — built, and PAUSED

**Paused 2026-10-10.** The module and its tests exist and are correct; the
account cannot use them. Nothing is wired into `cyberdeck.py`, so the paused
state costs nothing and needs no switch. If a subscription is bought later,
§7.7a says what to re-check.

Off by default, like everything else here, and gated on a key the operator
supplies.

**The arrangement.** The local file is the record. QRZ is a destination that
may or may not be reachable, and nothing about it can lose a contact, delay
one, or make the operator wait:

```
commit  ->  qso.log      always, immediately, fsynced
        ->  outbox       a note that this one has not gone yet
        ->  QRZ          when there is a network
```

That queue is why this works in a park. The deck spends most of its life with
the WiFi off, and contacts accumulate until they are sent.

**The drain is started by the operator, not by the deck.** `Upload to QRZ` in
the log menu, and nothing else — not on associating with WiFi, not on a timer,
not on commit.

The reason is the recovery path. Hand-editing `qso.log` over SSH is how a
mistyped callsign gets fixed, and that only works while the contact is still
local. Once it is in QRZ, correcting it means a delete and a re-insert, or
`OPTION=REPLACE` with the risk that carries. An automatic drain uploads the
typo somewhere between hearing it wrong and noticing, which is exactly the
window in which it is cheap to fix.

It also keeps the feature honest about the first requirement: a deck that
reaches out to a third party on its own, because it happened to find a
network, is not behaving like something that is switched off.

The cost is having to remember. The menu line carries the pending count for
that reason — `Upload to QRZ    14 waiting` — so the number is in front of the
operator whenever the menu is open, rather than being something to keep track
of.

**The API.** `POST https://logbook.qrz.com/api` with
`KEY=<logbook key>&ACTION=INSERT&ADIF=<one record>`. Replies are
`RESULT=OK` with a `LOGID`, `RESULT=REPLACE`, `RESULT=FAIL` with a `REASON`,
or `RESULT=AUTH`. **One QSO per request** — the API takes no batches — so an
eighty-contact activation is eighty requests, which is why the drain happens
in the background and not on commit.

**INSERT requires a QRZ subscription.** Without one the API answers and
refuses. That is treated as an ordinary permanent failure: the operator is
told once and the deck stops trying, because no amount of retrying will buy a
subscription.

**Where the key lives.** `cyberdeck.secrets`, beside `cyberdeck.conf`,
gitignored, mode 600, read by `config.load` at every start.

Not `cyberdeck.conf`: that describes a station and gets copied, pasted into a
message and read over a shoulder at a club meeting, and a key does not belong
in a file that travels.

Not `deck.secrets` either, which is what an earlier draft of this document
said and was wrong about. That file is consumed on a laptop by
`build_deck_image.sh` and baked into the card, so changing a value in it means
building a new card — the wrong shape entirely for a credential that can be
regenerated in a browser in ten seconds. `cyberdeck.secrets` is read by the
running deck, which is what this needs.

A key named in the secrets file that is not a known secret is **refused**, not
ignored, for the same reason an unknown setting in `cyberdeck.conf` is: a
credential that is silently dropped looks exactly like a credential that is
wrong, and the symptom is a feature doing nothing for a reason nothing
explains.

Mode 600 protects against a shoulder and a shared screenshot. It does not
protect against somebody holding the card — Raspberry Pi OS has no disk
encryption and the card pulls out with a fingernail, which is the same caveat
`deck.secrets.example` already carries.

#### Three outcomes, and why the default matters

| Reply | Outcome | Why |
|---|---|---|
| `OK`, `REPLACE`, `FAIL: duplicate` | done | the contact is in the logbook, which is all the outbox wants |
| `AUTH`, bad key, no subscription | permanent | retrying will not fix it; say so once |
| anything else, including nonsense | **retry** | a captive portal, an HTML error, half a second of nothing |

An unrecognized reply is retryable rather than permanent, deliberately.
Getting that backwards drops a contact from the queue and nothing ever says
so; the other mistake only costs another attempt later.

**A drain stops at the first retryable failure.** One unreachable server means
the network has gone, and grinding through seventy-nine more timeouts proves
it seventy-nine more times while the operator watches. A *permanent* failure
does not stop it — a single malformed record should not block the eighty
behind it.

**The outbox is a sidecar, not a flag in the log.** Upload state is not the
log's business: it belongs to a particular upload to a particular service, and
a contact can be sent to two of them. The log says what was worked. §7e added
the ability to correct a contact, so "the log is never rewritten" is no longer
the reason — the reason is that a flag per service per contact would make the
log a record of this program's housekeeping rather than of the air. Entries are
keyed by the contact's own identity — time, call, band, mode — rather than by
line number, so hand-editing the log over SSH, which is the documented recovery
path, does not silently re-upload everything after the edit. The sidecar can
be deleted entirely and costs nothing but one round of duplicate detection,
which QRZ handles.

**Not built, and deliberately.** LoTW needs TQSL and a signing certificate,
which is not something to run on a deck in a field. POTA takes ADIF through
its website; the export is already in the right shape with `MY_SIG_INFO` set,
so that stays a copy-and-upload.

### 7.7a Verified against the real API, 2026-10-10

A read-only `ACTION=STATUS` was sent with a real key, which is the cheapest
way to find out whether any of this can work before building on it.

```
STATUS=AUTH
RESULT=AUTH
REASON=user does not have a valid QRZ subscription to use this function,
       if you have purchased a new subscription please wait 300 seconds
EXTENDED=
```

**What this establishes.**

* The key is well formed and QRZ recognizes it. The failure is the account,
  not the credential, and not the code.
* `STATUS`, `INSERT`, `DELETE` and `FETCH` are all behind a subscription. A
  free QRZ account with a logbook and an API key still cannot upload.
* The transport, `parse_reply` and `classify` are correct against a genuine
  response rather than a fixture. The real reply carries **both** `STATUS=` and
  `RESULT=`, plus an empty `EXTENDED=`, none of which the parser had seen
  before; it handled them, and `classify` returned **permanent** without being
  told to. Retrying an `AUTH` forever was the failure mode that would have
  mattered, and the code avoided it unprompted.
* After buying a subscription, **wait 300 seconds**. QRZ says so in the
  refusal. A first attempt five minutes early looks exactly like a broken
  setup, and that is the kind of thing that costs an evening.

**To un-pause**, if a subscription is ever bought: re-run the same STATUS call
and look for `RESULT=OK`. Nothing else about the design changes — the outbox,
the drain, the three outcomes and the operator-initiated trigger were all
built around an API that behaves exactly as documented here.

## 7e. Reading back and correcting a contact

The list has one row per contact and a contact has up to forty fields, so most
of what is recorded cannot be seen on the panel at all. `LOG_LINES` gives a
contact one, two or three rows — the contact, then where the other station is,
then what this station ran — and a contact always occupies exactly that many
rows, blank ones included, because the arrows select whole contacts and a row
height that varied with how much happened to be filled in could not be walked
predictably.

The arrows pick a contact; Tab and Shift-Tab move between form fields, which
is what they already did. The arrows were previously a second, redundant way
to do the same thing, which is why reading the log back had no keys at all.
Enter on a picked contact opens it field by field; Enter on a field edits it;
Esc steps back out one level at a time. Three rules keep the fast path intact:
Esc deselects before it leaves the screen, typing always goes to the form and
drops the selection, and the footer says `Enter open` rather than `Enter log`
exactly when Enter has changed meaning.

`when` is the only field that cannot be changed. It is the key the contact is
found by, and the one field the operator did not type. The callsign *is*
editable, and is the reason this exists.

### The log is no longer append-only, and is still never written in place

§4 chose append-only, and the reason was sound: an append cannot damage what is
already in the file, and this deck's whole power story is that the plug gets
pulled. What that reasoning missed is that a wrong record is also damage, and
one the operator can see and could not fix.

`qsolog.update` replaces the file WHOLE: a temp file beside it, `fsync`,
`os.replace`, then an `fsync` of the directory because the rename is metadata
and is not durable until that happens. `os.replace` is atomic within a
filesystem, so a power cut leaves either the old log or the new one and never
part of one. The property that mattered — no torn write survives a pulled plug
— is kept; the one that was given up is that the file only ever grows.

The contact is found by its timestamp and guarded by its callsign, never by a
line number. An index is a promise about a file this program does not own: the
log is documented as hand-editable over SSH, and an index that had shifted by
one would rewrite a different contact. A guard that does not match is a
refusal, not a guess.

## 7f. One log, and sessions inside it

Decided 2026-10-16. This supersedes the per-activity files described above and
the `MASTER_LOG` setting, both of which are removed.

### There is one log file

Every contact goes to the file `LOG_PATH` names and nowhere else. An activity
is not a file; it is a **label on records**, and the activity screen is a
**filter** over the one log.

This is what the code was already half doing. Every record has carried
`activity` and `activity_type` since activities existed, `qsolog.for_activity`
has existed as long, and the log screen already called it in three places to
decide what to show. The per-activity files were a second mechanism underneath
a view that was already a filter.

What the change removes, rather than adds:

- **The duplicated write.** Two `append`s and two `fsync`s per contact, and
  `update` and `remove` each having to find the same contact in two files — a
  divergence waiting for the first write that half succeeded.
- **`MASTER_LOG`.** Nothing to switch off: the log is the log.
- **`activity_log_path`, `split_activity_stem`, `resolve_activity_log`,
  `activity_logs`, and `activity_path` in the state file.** With no path to
  stamp, the whole "stamp the date once or a contest weekend forks across UTC
  midnight" problem stops existing.
- **The asymmetry between deleting an activity and deleting a contact.**

What it costs: `read()` parses the whole log on open and after every edit. At
ten thousand contacts that is a couple of megabytes and a few hundred
milliseconds on a Pi 3A+ — acceptable, because it is per-open and per-edit and
never per-keystroke. The per-activity files kept each read small and that is
given up deliberately. If it ever bites, the answer is an index beside the
log, not a return to many files.

### A session is `(activity, activity_start)`

Records gain one field: **`activity_start`**, an ISO timestamp pinned when the
session begins and identical on every contact in it. A session is the set of
records sharing a name and a start.

Derived session identity was considered and rejected. "Same name, same UTC
day" cannot survive midnight: an activation from 23:50 to 00:30 would split in
two, and a contest weekend likewise. That is the exact failure the dated
filename was stamped once to avoid, so the stamp moves from the filename into
the record where it belongs.

A full date-time, not a date, because a date cannot tell a morning activation
from an evening one and brings the midnight problem back. The activities
screen *displays* only the date.

| Case | Result |
|---|---|
| Activation 23:50 → 00:30 | One session; every record shares one `activity_start` |
| Same park next weekend | A different `activity_start`; cleanly separate |
| Resuming after a break | The operator's choice: resume keeps the start, starting fresh makes a new one |
| Restart mid-activation | The state file holds `activity_start` instead of `activity_path` |

`activity_start` is **not exported**. ADIF describes a contact, not a session,
and there is no field for it.

### Deleting an activity forgets it; the records keep the label

Deleting an activity removes it from the deck's list and **changes no
records**. The contacts keep their `activity` and `activity_start`, so the
session remains identifiable and exportable afterwards.

That needs state, because a list derived from the records would show the
session again the moment it was rebuilt. The state file carries a
**forgotten-sessions list** of `(activity, activity_start)` pairs, and the
activities screen shows derived sessions minus that set.

Three consequences, all wanted:

- The requirement that started this — "delete an activity and still get the
  contacts back" — stops being a feature with a mechanism and becomes a fact
  about where the contacts are.
- It is reversible, so an undelete is possible.
- A session dismissed and then logged into again comes back, because logging
  under a name is a clearer statement of intent than having dismissed it.

**The confirmation wording changes with it.** "Permanently deleted" was true
of a file and is false of a label. Deleting an activity is no longer
destructive at all; the only way to destroy a contact is to delete that
contact.

### Export

One function with an optional filter: the whole log, or one session. A POTA
upload wants the latter and gets a cleaner file than before, because a
filtered export cannot contain a stray contact that landed in the wrong file.

## 8. Time

UTC from the system clock, which is RTC-backed on the deck. The RTC is the
reason this is trustworthy after a power pull in the field with no network, and
it is why the clock work was worth doing before this feature existed.

The record stores an ISO 8601 instant with a `Z`. ADIF's split
`QSO_DATE`/`TIME_ON` is generated at export.

## 8a. Using it today, before the screen exists

Nothing is wired into `cyberdeck.py`, so there is no log screen and no Ctrl-N.
What does work on the deck is `tools/qso.py`, the logging core with a terminal
in front of it. It writes the same file in the same format the screen will
read, so nothing logged this way has to be migrated later — and it is usable
on its own: SSH in from a phone at a park and log the activation.

### Getting it onto the deck

On the laptop, the same live-update path as any other module change (see
`docs/deploy_cyberdeck_instructions.md`), plus the tool and its tests:

```bash
rsync -av src/*.py deck@cyberdeck.local:/tmp/deckupd/
rsync -av tools/qso.py tests/ deck@cyberdeck.local:/tmp/deckupd/
```

On the deck:

```bash
sudo cp /tmp/deckupd/*.py /opt/cyberdeck/
sudo chmod 755 /opt/cyberdeck/qso.py
```

**No restart is needed.** None of this is loaded by `cyberdeck-ui` yet, which
is the clearest statement that logging is absent when it is off: the running
deck does not know these files exist.

### Checking it works on the hardware

```bash
cd /tmp/deckupd && python3 test_qsolog.py && python3 test_callbook.py && python3 test_secrets.py
```

Each ends in `ALL PASS`. These are the three that need neither fldigi nor a
network. `test_qrzlog.py` passes too but exercises a feature that is paused
(§7.7a).

### Logging

```bash
/opt/cyberdeck/qso.py log W3ABC 59 57 Bob Pittsburgh
/opt/cyberdeck/qso.py log K2XYZ 55
/opt/cyberdeck/qso.py list
/opt/cyberdeck/qso.py count
```

Frequency comes from rigctld when it answers and is left out when it does not.
The mode comes from `resolve_mode` (§6), so the tool and the deck decide it the
same way, and every entry says where it came from:

```
-- mode PSK from fldigi (BPSK31)
-- mode SSB from the rig (USB)
-- mode defaulted to SSB; use --mode to change it
```

`--freq` and `--mode` override either. `--operating voice|digital|auto`
overrides the policy for one entry, which is the quick way to log an SSB
contact on a deck that is configured for digital:

```bash
/opt/cyberdeck/qso.py log --operating voice W1AW 59 59
```

**A comment** is anything after `;` on the deck's own screen. On a command
line `;` has to be quoted past the shell, and argparse will not take
positional words after an option, so it is a flag here:

```bash
/opt/cyberdeck/qso.py log --comment "running 5W to a wire" K2XYZ 59 57
```

**POTA mode** is off by default and the log is general. Hunting needs nothing
turned on — a park reference typed into an entry is recognized by shape:

```bash
/opt/cyberdeck/qso.py log N3QQQ 59 55 US-1234
```

Activating does, because this station's own park goes on every contact:

```bash
/opt/cyberdeck/qso.py log --pota --my-park US-5678 N3QQQ 59 55 US-1234
```

Set `POTA = yes` and `MY_PARK = US-5678` in `cyberdeck.conf` for the duration
of an activation rather than passing both every time. `--my-park` without POTA
mode is refused with a note, so a reference left over from last weekend cannot
leak into an ordinary log.

### Getting the ADIF off the deck

The file itself is at `~/.local/share/cyberdeck/qso.log` and is plain text —
readable, greppable and hand-editable, which is the recovery path for anything
typed wrong. The ADIF is generated from it on demand, so exporting twice costs
nothing and a fixed typo re-exports correctly.

**On the deck**, write the export somewhere easy to fetch:

```bash
/opt/cyberdeck/qso.py adif /tmp/kd3cco.adi
```

**On the laptop**, pull it back:

```bash
scp deck@cyberdeck.local:/tmp/kd3cco.adi ~/Downloads/
```

Or in one step without leaving a copy on the card, which is the better habit:

```bash
ssh deck@cyberdeck.local /opt/cyberdeck/qso.py adif > ~/Downloads/kd3cco.adi
```

That writes the ADIF to standard output on the deck and redirects it into a
file on the laptop. It also works when the deck's filesystem is read-only or
nearly full, and it leaves nothing behind to go stale.

Worth taking the raw log as well as the export, since the log is the record
and the ADIF is a view of it:

```bash
scp deck@cyberdeck.local:.local/share/cyberdeck/qso.log ~/Downloads/
```

### What to do with the file

* **LoTW** — `qso.py lotw` writes the ADIF and prints the exact `tqsl`
  command; run it on the laptop, where the certificate lives. Deliberately not
  signed on the deck: a signing key does not belong on a card that pulls out
  with a fingernail, and tqsl hangs rather than failing when it has no
  certificate. §11 has the measurements.
* **POTA** — upload the same ADIF at `pota.app` under your activation.
  `MY_SIG_INFO` is set if POTA mode was on with a park, which is what POTA
  matches on.
* **QRZ** — import the ADIF through the website. The API route is built and
  paused (§7.7a).

## 9. What a contest mode would add

Recorded so the boundary is deliberate rather than accidental. A contest
logger needs: a persisted serial counter with "next to send" semantics, a
`{NR}` token in the F5-F12 memories, an exchange field in place of name and
QTH, dupe checking on call + band + mode, WARC-band warnings, Cabrillo export
with a header block, and a way to view and set the next serial for recovery.

None of it belongs in the general logger. The two interfaces want different
things from the same keystroke, and a logger that tries to be both will be
worse at the one that matters on the day.

## 10. Testing

The core is pure — no curses, no fldigi, no rigctld, no clock — so most of it
is testable without hardware, in the existing suite's style
(`tests/harness.py`, `check` and `equals`, ending in `ALL PASS`).

**Covered by `tests/test_qsolog.py`:**

* Entry parsing: bare call; call with one report; call with both; call with
  name and QTH; lowercase input; leading and trailing whitespace.
* Malformed input: empty, no callsign, a report that is not a report.
* Callsign validation, including portable and stroke forms (`W3ABC/P`,
  `KD3CCO/3`).
* Band derivation across every HF and VHF band the rig covers, the gaps
  between them, and an unknown frequency.
* Default reports by mode.
* Record round trip: format a record, parse it back, get the same fields.
* Quoting: a QTH containing spaces survives the round trip.
* ADIF export: header, field lengths, `<EOR>`, and a record with optional
  fields absent.
* ADIF mode normalization for every modem name the deck can report.
* A record with no frequency exports without `BAND` or `FREQ` rather than with
  empty ones.
* Park references: modern and legacy forms, found after the reports and after
  a name, and not confused with a report or a callsign.
* POTA in ADIF: `SIG`/`SIG_INFO` when hunting, `MY_SIG`/`MY_SIG_INFO` when
  activating, both on a park-to-park, and neither on an ordinary contact.
* Comments: taken whole after `;`, not mistaken for a QTH, coexisting with a
  park, surviving the storage round trip with spaces in them, exported as
  `COMMENT`, and absent from the ADIF when empty.
* `resolve_mode` in all three policies: that `voice` never consults fldigi
  even mid-transmission on a loaded modem; that a rig data mode is conclusive
  on its own; that `USB` plus an idle fldigi is voice while `USB` plus a
  working fldigi is digital; and the sharp edge where no rig information at
  all leans digital.

**Covered by `tests/test_callbook.py`**, all of it with the network injected so
nothing reaches out:

* A good reply, a call that does not exist, a reply that is not JSON, an empty
  reply, and no network at all — none of which raise.
* What was typed is never overwritten; blanks are filled.
* The cache survives a restart, is case-insensitive, expires, and treats a
  corrupt file as an empty one rather than an error.
* A negative answer is cached, so a non-US call costs one timeout and not one
  per contact.
* A background lookup returns its answer once, and a failing one still
  completes.

**Covered by `tests/test_qrzlog.py`**, with the transport injected:

* Reply parsing, including URL-encoded reasons and an HTML error page.
* Classification of every documented reply, and that an unrecognized one is
  retryable rather than permanent.
* A duplicate counts as delivered.
* The outbox survives a restart, treats a corrupt file as an empty one, and is
  keyed by the contact rather than by its position in the file.
* A drain stops at the first retryable failure and does **not** stop at a
  permanent one.
* A second drain sends nothing and makes no requests.
* `limit` and `stop` are honored.
* A background drain returns its summary once, and an unexpected exception in
  the worker is caught rather than taken out on the deck.

**Covered by `tests/test_lotw.py`**, with the subprocess injected so nothing
is signed:

* A timeout kill is `PERMANENT` and the detail blames the certificate, not the
  network.
* `tqsl -v` exits 255 and that is still a success — gating on zero reports
  tqsl as missing on a machine that has it, which is how this was found.
* Status 9 (duplicates skipped) is success; an unknown status is retryable.
* The banner line is stripped from the detail and the useful last line is not.
* `--upload` wins over `--output`, so asking for both does not leave a stray
  signed file.
* A path with a space is quoted for the shell in the printed command.
* The three outcome words match `qrzlog`'s exactly.

**Covered by `tests/test_log_screen.py` and `tests/test_menus.py`:**

* General mode draws no park column, no park header slot and no `POTA` label;
  POTA mode reserves all three, and an unset park reads `(no park set)` rather
  than being omitted.
* General mode is what you get by default.
* Every row is exactly `width` characters in both modes, at every width.
* The park menu item is absent with POTA mode off, and `My park` reads
  `not set` with it on — a mode that is on with nothing set, not a switch.
* `Sign and upload to LoTW` is absent without `tqsl` on PATH.
* The fullest menu — eight items — stays inside one column at 66x20 and
  overflows at no width.

**Covered by `tests/test_secrets.py`:**

* A missing secrets file is the normal case, not an error.
* Case and spacing do not matter; an empty value clears the key.
* A setting that does not belong in a secrets file is refused, and the message
  names both what was found and what was expected.
* A misspelled key is refused rather than ignored.
* **A credential in `cyberdeck.conf` is refused**, with a message naming
  `cyberdeck.secrets`. This changed on 2026-10-11: it used to work there and
  merely be overridden. `cyberdeck.conf` is the file meant to be safe to hand
  over, so a credential that works from it is a credential that travels — and
  silently honoring it is the worst case, because it works, so nobody moves it.
* Ordinary settings in that same file are untouched by the refusal.
* `POTA` defaults to off and refuses anything but yes/no; `OPERATING` defaults
  to `auto` and refuses anything but the three policies.
* There is no `LOTW_PASSPHRASE` and no `LOTW_CERT` in the schema, asserted
  directly, because §11.2 says signing happens off the deck.

That last pair is written with an explicit path. The first version was not,
and failed — it read the operator's real key instead of the fixture. A test
that depends on whether the machine running it has credentials is not a
test.

**Needs the deck, and is listed rather than written:**

* With logging off the log is not a stop on the ring: `^O` and `^P` walk two
  applications instead of three.
* No file is created when logging has never been switched on.
* The log line refuses to open during an over.
* Prefill from the transcript.
* Which hamlib mode string the FTX-1 reports while fldigi drives it (§6) —
  the policy handles either answer, so this decides only whether
  `fldigi_active` is load-bearing or a backstop.
* `rigctld_client.mode()` against the real radio. Written and unexercised:
  rigctld's `m` is documented to answer with the mode and then the passband
  width, and that parse has never seen a real reply.
* A signed LoTW upload end to end, which needs a callsign certificate.
* **`l RFPOWER` and the power chain.** Does rigctld answer it for this rig,
  and is the position linear enough for a log? Then: on the internal battery
  at maximum, does `PC;` report `PC1006;` or `PC1010;`? That one answer says
  whether the radio knows about the 6 W cap or only the operator does.
* **`read_cat()` against a Yaesu reply.** hamlib's `w` is used for set
  commands today and has never been asked to return a `;`-terminated answer
  here.
* A power pull mid-session loses nothing already committed.

## 11. Logbook of The World

LoTW is the other destination worth having, and it works nothing like QRZ.

**It is free.** A callsign certificate costs nothing; the ARRL issues one after
validating the operator's identity. That is unrelated to the QRZ logbook's paid
subscription (§7.7a). Having one says nothing about having the other, and the
pause on QRZ does not apply here.

**There is no API.** Every record has to be cryptographically signed with that
certificate, and the only thing that can sign it is `tqsl`, the ARRL's own
program. So `src/lotw.py` is not a client; it is the ADIF export plus a careful
wrapper around a subprocess.

### 11.1 What tqsl actually does

Measured on tqsl 2.8.6, 2026-10-10:

| Invocation | Result |
|---|---|
| `tqsl --batch --nodate --quiet <log>` with an empty keystore | **hangs indefinitely.** No error, no exit. Unsetting `DISPLAY` and `WAYLAND_DISPLAY` makes no difference. |
| the same with a display present | opens a GUI window despite `--batch` |
| `tqsl -v` | prints the version and exits **255**, not 0 |
| a command-line syntax error | exits promptly, status 10 |

Three consequences, and they shape the design:

* **Every invocation gets a hard timeout**, and a timeout kill is classified
  `PERMANENT` with a detail that names the certificate. A logger that can hang
  the deck waiting for a dialog nobody can see is worse than one that cannot
  upload, and "timed out" on its own sends the operator to look at their WiFi.
* **Liveness is tested by output, not by exit status.** Gating on zero reports
  tqsl as missing on a machine that has it — which is how the 255 was found.
* **Unknown statuses are retryable.** Only 0 and 10 are confirmed here; the
  rest are from tqsl's documentation, so the default has to be the safe one.

### 11.2 Signing belongs off the deck

The default path is: **export ADIF on the deck, sign and upload on the
laptop.** `qso.py lotw` writes the file and prints the exact `tqsl` command to
run, from the same function that would have executed it, so the printed command
and the real one cannot drift apart.

Two reasons, and the hang is the lesser one. A callsign certificate is a
private key, and the deck's SD card travels in a backpack. Nothing in this
project needs that key to be in the field, so it is not put there — and there
is deliberately no `LOTW_CERT` or `LOTW_PASSPHRASE` setting to make it easy.
`test_secrets.py` asserts their absence.

`lotw.upload()` exists for a station that has deliberately installed a
certificate on the deck. It is not the default and the menu item says *sign*,
not *upload*, because signing is the step that can fail in a way the operator
has to understand.

### 11.3 Whole file, not per contact

tqsl signs a log, and LoTW's own duplicate handling makes re-uploading an
overlapping file harmless. So there is no outbox here — the opposite of
`qrzlog.drain`, which must go one QSO at a time because the QRZ API takes no
batches. The same three outcome words (`ok`, `retry`, `fail`) are used by both
so the interface can treat an upload the same way whichever destination it
went to.

`LOTW_LOCATION` is the one setting: tqsl's name for a Station Location, which
it needs to know which callsign and grid signed the log. Without it tqsl asks,
and in batch mode it cannot, so an unset value is called out at export time.

## 12. Decisions still open

* **Which hamlib mode string the FTX-1 reports under fldigi.** The policy in
  §6 is settled and handles either answer; this only decides whether
  `fldigi_active` is load-bearing in `auto` or merely a backstop. Needs the
  rig.
* **Whether `auto` should lean voice instead of digital when the rig is
  unreachable.** It currently leans digital, because the deck is a digital
  terminal first. An operator doing SSB from a park with no CAT cable gets
  the wrong mode on every contact until they set `OPERATING = voice`. The
  alternative is wrong for the deck's commonest use. Pinned by test either
  way, so it is a one-line change if the field says otherwise.
* **Ctrl-N or another key.** Free, but unmemorable.
* **Whether the log screen should show the last N contacts or a running
  summary.** The list is reassuring during an activation; a summary — count,
  rate, bands worked — is what gets read at the end of it.
* **Whether a lookup should start on a pause in typing or only on commit.**
  Starting early means the answer is there when Enter is pressed; it also
  sends partial callsigns to a third party as they are typed.
* **Which other programs to recognize.** SOTA, WWFF and IOTA use the same
  generic ADIF activity fields as POTA with a different `SIG` value, so each is
  a reference pattern and a `SIG` string rather than a design change. None is
  built, because none is in use here; the question is whether a second one
  needs a way to say *which* program a typed reference belongs to, since
  `GW-0001` is a valid-looking reference under more than one of them.
* ~~**Non-US callsigns.**~~ **Done.** HamQTH is wired in behind the same
  `fetch` seam, tried only when callook has nothing. See §7.5.
* **Whether to send `OPTION=REPLACE`.** It makes a corrected record overwrite
  the original instead of duplicating it, and it can overwrite a *confirmed*
  QSO with unconfirmed data. Currently off, and moot while §7.7 is paused.
* **Whether a QRZ subscription is worth buying at all.** The log, the ADIF
  export, the POTA upload and LoTW all work without one — LoTW's certificate
  is free (§11). QRZ would only save the step of uploading a file.
* **Whether to put a callsign certificate on the deck.** It would make
  `lotw.upload()` usable in the field. It also puts a private key on an SD
  card that travels, to save a step that can be done at home the same evening.
  Currently no, and there is deliberately no setting for it.
* ~~Whether the comment field wants to be editable after commit.~~ **Decided
  2026-10-14: every field of a logged contact is editable on the panel.** See
  §7e. The question was framed too narrowly — the field that most needs
  correcting is the callsign, not the comment, because a call taken down wrong
  is wrong in the exported ADIF and in every upload made from it. "Hand-edit
  the file over SSH" is no recovery path from a park bench, which is where the
  mistakes get made.
