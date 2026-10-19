# WSPR Operating Tutorial

Running WSPR from the deck: receiving, beaconing, hopping bands, reporting to
wsprnet, and getting the spots off afterward.

For an operator who knows radio but has not run WSPR before. Every key in
this document was read out of the deck's source rather than remembered, and
every screen is rendered by the same functions the deck draws with.

The deck has three other applications, each with a document of its own — the
digital modes, the contact log, and the deck-and-rig settings. This tutorial
is about WSPR only. The design behind it, and the reasoning for the decisions
it describes, is [`wspr_design.md`](wspr_design.md).

---

## Contents

- [1. What WSPR is, and what it is for](#1-what-wspr-is-and-what-it-is-for)
- [2. The governing fact: WSPR takes the sound card](#2-the-governing-fact-wspr-takes-the-sound-card)
- [3. Before the first session](#3-before-the-first-session)
- [4. Session one — receive only](#4-session-one--receive-only)
- [5. Reading the WSPR screen](#5-reading-the-wspr-screen)
- [6. The two audio levels, and why they are set differently](#6-the-two-audio-levels-and-why-they-are-set-differently)
- [7. Transmitting](#7-transmitting)
  - [Power, and the dBm the message carries](#power-and-the-dbm-the-message-carries)
  - [The transmit percent](#the-transmit-percent)
  - [The session time-out](#the-session-time-out)
- [8. Band hopping](#8-band-hopping)
- [9. Reporting spots to wsprnet](#9-reporting-spots-to-wsprnet)
- [10. Sessions](#10-sessions)
- [11. Getting the spots off the deck](#11-getting-the-spots-off-the-deck)
- [12. Full key reference](#12-full-key-reference)
- [13. What it has done, on the air](#13-what-it-has-done-on-the-air)
- [14. When something goes wrong](#14-when-something-goes-wrong)

---

## 1. What WSPR is, and what it is for

WSPR is a beacon mode. A transmission is 162 symbols carrying a callsign, a
Maidenhead grid square and a claimed power, sent in a 6 Hz-wide channel over
110.6 seconds inside a two-minute slot. It carries no message and supports no
conversation. The entire point is the report: who heard the beacon, where
they are, and at what signal-to-noise ratio.

That makes it the instrument for the question an antenna raises. A contact
proves a path existed at one moment between two stations, both of which were
trying. A night of WSPR produces hundreds of paths, at known times, on known
bands, from receivers that were listening anyway — which is what it takes to
say one antenna is better than another on a given band rather than that one
evening was luckier.

WSPR is also the reason the deck's receive side can be measured without
transmitting at all. Receiving costs nothing, breaks no rules, needs no
license class, and produces a usable dataset on its first night.

The deck decodes with `wsprd`, the decoder out of WSJT-X, and does its own
encoding, timing, keying, logging, grid math and uploading.

---

## 2. The governing fact: WSPR takes the sound card

**The USB codec in the radio accepts one capture client.** Not two with care,
one. This is measured, not assumed, and it is the single fact that shapes
everything about how WSPR behaves on the deck.

fldigi holds that codec from the moment the deck boots. So starting WSPR
**stops fldigi**, and stopping WSPR **starts it again**. While WSPR runs:

* `^O` and `^P` are locked. The function ring does not leave the WSPR area,
  because the other three applications it would walk to have no decoder
  behind them.
* The digital modes cannot receive, and the deck says so rather than
  pretending.
* The capture gain and the codec's AGC belong to WSPR, and are put back when
  the session ends.

The handover is the part that has actually broken. fldigi opens the codec once
at startup and never retries, so handing it a card that is still held comes up
**deaf** — and a deaf fldigi keys the radio and never completes the over,
which is a stuck transmitter. The deck now waits for every killed capture
child to release the device before starting fldigi, and checks the card is
free first.

The practical consequence for an operator: **stop WSPR from inside WSPR**, with
`^C` or the menu, and let it hand the card back. Do not restart the deck
mid-session to get out.

---

## 3. Before the first session

**Transmit starts inhibited at every power-on.** That is deck-wide and WSPR
does not change it. Nothing transmits until `^B` arms it, and the header
reads `INH` while it is inhibited and `INH off` once armed.

For a receive-only first session, leave it inhibited. There is no reason to
arm the transmitter to find out whether the deck decodes.

Three things to set once, in `cyberdeck.conf`:

| Key | What it is |
|---|---|
| `CALLSIGN` | The callsign the beacon carries |
| `MY_GRID` | A 4 or 6-character Maidenhead grid. WSPR sends 4; the deck uses what is configured for its own distance math |
| `TX_POWER` | Watts, and the deck converts — `0.5` is valid and means half a watt |

The WSPR keys all have defaults and none has to be set: spot log path, bands,
transmit percent, time-out, upload, device, the two audio levels, and the
capture mixer's control names. They are listed with their defaults in
[`src/config.py`](../src/config.py). **They are not in
`cyberdeck.conf.example`** — a gap in that file, not in the program.

**The radio's mode.** Selecting a band also reads the radio's mode and sets
DATA-U if it is not already there, remembering what it found, because the
radio keeps a mode per band. The deck reports `was USB — set to PKTUSB` when
it does this. Watch for that message the first time: if the radio does not
accept the command the message still appears and the dial does not move.

---

## 4. Session one — receive only

Reach WSPR with `^O` or `^P` — it is the fourth area on the function ring,
after the digital modes, the log, and deck & rig.

1. `F3`, then a number for the band. `4` is 20 m. The deck tunes to the
   band's WSPR dial frequency and sets DATA-U.
2. `F1`, then `w`. WSPR starts; fldigi stops; the slot clock appears.
3. Wait. Decodes arrive at the end of each two-minute slot, not continuously.

The first thing to look at is not the spot list, it is the level. `TX audio`,
`RX gain` and the measured `level -37 dBFS` are on the screen while WSPR
runs, and a capture that is far too quiet or clipping decodes badly no matter
how good the band is. §6 covers setting it.

The second thing is patience. An empty list after four minutes on 20 m in the
afternoon is normal. An empty list after twenty is a level or a tuning
problem.

---

## 5. Reading the WSPR screen

```
┌──────────────────────────────────────────────────────────────────┐
│ WSPR  general  20 m  14.095.600                    INH off  1748Z│
│──────────────────────────────────────────────────────────────────│
│ UTC     dB  CALL       GRID   dBm  BAND     KM   AZ              │
│ 17:46  -19  KD1SQ      FN67    23  20 m   1139   45              │
│ 17:46  -28  N9JNQ      EN34    23  20 m   1309  293              │
│ 17:46  -13  N4DPH      EM64    23  20 m   1565  258              │
│ 17:46  -17  W9LK       EM26    23  20 m   1203  272              │
│ 17:46  -14  G4HSB      IO94    23  20 m   5648   47              │
│ 17:44  -23  KD1SQ      FN67    23  20 m   1139   45              │
│ 17:44  -15  W9RAG      EN54    23  20 m   1005  298              │
│ 17:44  -29  K0PCG      JN49    23  20 m   6452   50              │
│                                                                  │
│──────────────────────────────────────────────────────────────────│
│ WSPR   DECODE   TX   TX NEXT   HOP                               │
│ max 100 W  5 W   37 dBm  snapped                                 │
│ slot 0:05 [#.............] 1:54 to next: RX                      │
│ TX audio 35%  RX gain 100%  level -37 dBFS                       │
│ heard 455    sent 1    upload on    session 46:42 left   decoding│
│ WSPR started on 20 m — ^O ^P are locked until it stops           │
│ F1 menu F2 session F3 band ↑↓ spots ^B inhibit ^C stop           │
└──────────────────────────────────────────────────────────────────┘
```

**The header** — the session name, the band, the dial grouped the way the
radio reads it, whether transmit is inhibited, and the clock in UTC. WSPR is
a UTC mode; slots are aligned to even minutes of UTC and nothing about it is
expressed in local time.

**The spot list** is newest first, which is the opposite of the contact log.
A log is read forward as a record; a spot list is watched, and what just
arrived belongs at the top.

`KM` and `AZ` are computed from the two grid squares at draw time. **Neither
is stored in the spot log**, because both are derivable from the grids that
are, and a stored derived field is a field that can disagree with its source.

**The four toggles plus HOP** read from their shape rather than from words:
highlighted is on, dim is off. `WSPR` is the application, `DECODE` is whether
`wsprd` runs on what is captured, `TX` is whether it beacons at all, and
`TX NEXT` beacons on the next slot once and then clears itself.

**The power block** reads `max 100 W  5 W  37 dBm  snapped`. The radio's
ceiling, the power being claimed, the dBm the message will carry, and whether
that wattage lands exactly on a value WSPR can encode. It says `not snapped`
when it does not — see §7.

**The slot clock** shows where the two-minute slot is, how long to the next
one, and what the next one does. Only `TX` is highlighted when the next slot
transmits, because that is the word worth seeing from across a picnic table.

**The counters**: heard, sent, the upload state, the time left on the session
time-out, and whether a decode is still running. A decode that overruns its
slot is normal on a Pi 3A+ and does not drop the next capture — capture and
decode do not wait for each other.

---

## 6. The two audio levels, and why they are set differently

`F1`, then `a`. Both are refused while WSPR is off, with the reason given:
they open the sound card, and fldigi holds it until WSPR takes it.

```
┌──────────────────────────────────────────────────────────────────┐
│ WSPR AUDIO                                                       │
│                                                                  │
│        TX audio 35%     RX gain 100%     -37 dBFS                │
│                                                                  │
│▸ c  Calibrate transmit        a tone, + and - to set             │
│  m  Calibrate receive         a meter, + and - to set            │
└──────────────────────────────────────────────────────────────────┘
```

These are two different kinds of thing and that is why there are two screens.

**Transmit is WSPR's own amplitude.** It scales the audio WSPR generates
before it reaches the card, and it affects nothing else on the deck. Set it
too high and the radio's ALC compresses a signal whose whole value is being
a clean tone. `c` plays a 40-second tone; `+` and `-` step the level while it
plays; the instrument is **the radio's own power meter**, not anything on the
screen. Set the radio's drive so its meter reads the wattage the deck claims.

```
┌──────────────────────────────────────────────────────────────────┐
│ WSPR CALIBRATE — TRANSMIT                                   20 m │
│──────────────────────────────────────────────────────────────────│
│   TX audio level   35%                                           │
│ max 100 W  5 W   37 dBm  snapped                                 │
│   transmitting — watch the radio's power meter                   │
│  + - level  Enter send a tone  ^B inhibit  ^C stop  Esc back     │
└──────────────────────────────────────────────────────────────────┘
```

**Receive is the shared capture mixer** — the same control fldigi uses. It is
safe to set only because WSPR owns the codec while it runs, and it is put back
when the session ends. `m` shows a live meter.

```
┌──────────────────────────────────────────────────────────────────┐
│ WSPR CALIBRATE — RECEIVE                                    20 m │
│──────────────────────────────────────────────────────────────────│
│   RX capture gain   100%                                         │
│ [############::::::::::::......]  -37.0 dBFS  good               │
│   Aim for the marked stretch of the meter.                       │
│   Too loud decodes worse than too quiet.                         │
│  + - level   ^B inhibit   Esc back                               │
└──────────────────────────────────────────────────────────────────┘
```

Aim for the marked stretch. **Too loud decodes worse than too quiet**: WSPR
lives below the noise floor and the decoder wants headroom, so a capture that
occasionally clips costs more than one that is 10 dB low. The deck also turns
the codec's AGC off while WSPR runs, and puts it back after, because automatic
gain fighting a weak-signal decoder helps neither.

---

## 7. Transmitting

Arm the transmitter with `^B` — it is inhibited at power-on and the header
says which it is. Then `F1`, then `t` for `Transmit`, or `n` to beacon on the
next slot only and then stop.

`t` and `n` are different intentions. `t` is "beacon for the evening at the
configured percentage." `n` is "send one, now, so I can watch the meter."

### Power, and the dBm the message carries

WSPR's power field is not free-form. It encodes a fixed set of dBm values —
0, 3, 7, 10, 13, 17, 20, 23, 27, 30, 33, 37, 40 and up — and the deck picks
the nearest one to the configured wattage.

| Watts | dBm | Lands exactly |
|---|---|---|
| 5 W | 37 | yes |
| 0.5 W | 27 | yes |
| 0.1 W | 20 | yes |
| 50 mW | 17 | yes |
| 10 W | 40 | yes |
| 4 W | 36 → 37 | no |

The screen reads `snapped` when the wattage lands on an encodable value and
`not snapped` when the deck had to round. Rounding is not a problem — it is
at most 1.5 dB and every WSPR station does it — but the report that goes to
wsprnet claims the dBm, so it is worth knowing when the number being
published is not quite the number being transmitted.

### The transmit percent

`F1`, then `p`, cycles 0, 10, 20, 30, 50, 100 percent. It is the fraction of
slots that beacon rather than listen, chosen at random per slot rather than on
a fixed cycle.

**20% is the default and it is the right default.** WSPR's convention is that
most stations mostly listen, because a band full of beacons has nobody left to
report them. The deck also refuses to transmit on two slots in a row.

### The session time-out

`F1`, then `o`, cycles off, 15, 30, 60, 120, 240, 480 and 720 minutes — up to
twelve hours. The default is 60.

**What happens when it expires:** transmit turns off, and decoding and band
hopping keep running. The timer exists to stop an unattended transmitter, not
to stop a receiver — the receive side is the part worth leaving alone
overnight, and it is also the part that costs nothing.

The timer restarts when transmit is armed, not when WSPR starts.

---

## 8. Band hopping

`F3`, or `b` from the menu.

```
┌──────────────────────────────────────────────────────────────────┐
│ WSPR BAND                                                        │
│                                                                  │
│  1  [ ] 80 m      3.568600 MHz                                   │
│  2  [ ] 40 m      7.038600 MHz                                   │
│  3  [ ] 30 m     10.138700 MHz                                   │
│▸ 4  [*] 20 m     14.095600 MHz <                                 │
│  5  [ ] 17 m     18.104600 MHz                                   │
│  6  [ ] 15 m     21.094600 MHz                                   │
│  7  [ ] 12 m     24.924600 MHz                                   │
│  8  [ ] 10 m     28.124600 MHz                                   │
│  9  [ ] 6 m      50.293000 MHz                                   │
│  0  [ ] 2 m     144.489000 MHz                                   │
│  a  [ ] 70 cm   432.300000 MHz                                   │
│──────────────────────────────────────────────────────────────────│
│ Esc back  Enter use this one  Space hop on/off  [*] in rotation  │
└──────────────────────────────────────────────────────────────────┘
```

Two different gestures on one screen:

* **A number, or `Enter`** — use that band alone, and tune to it now.
* **`Space`** — toggle the highlighted band in and out of the hop rotation.
  `[*]` marks the bands in it, `<` marks the one in use.

With two or more bands in the rotation, the deck moves between them on slot
boundaries. One band gives a deep picture of one path; a rotation gives the
shape of the whole evening, which is the thing a single band cannot show —
20 m closing while 40 m opens looks like nothing at all if 20 m is the only
band being watched.

Hopping checks the mode per band, because the radio keeps mode per band and
arriving on a band still set to USB means a slot of nothing.

---

## 9. Reporting spots to wsprnet

`F1`, then `u`.

Uploading is **armed, not automatic**. It needs three things true at once:
WSPR running, the upload toggle on, and a network. Any of the three missing
means spots accumulate in the local log and nothing is published — which is
the correct behavior in the field, where there is usually no network and the
log is the point.

The spots are the deck's half of the bargain. Every distance figure in any
WSPR result comes from somebody else having been listening and having
reported, so a station that receives and never reports is taking from the
network without putting anything back. Receiving and reporting costs no
transmit power and no band space at all.

---

## 10. Sessions

`F2`, or `e` from the menu, names the session. An unnamed run is logged as
`general`.

The name is written into every spot record, which is what makes the log
answerable afterward: "the 20 m spots from the Saturday night run" is a query
only if the run had a name. This matters most for the comparison the whole
exercise exists for — the same band, the same evening, two different antennas,
named so the two sets can be separated six months later.

The session name is taken from WSPR's own field, not from the contact log's
activity. They are different things: an activity defines which fields get
typed when logging a contact, and a WSPR session is a label on a block of
unattended beaconing.

---

## 11. Getting the spots off the deck

The spot log is **not** the same as what wsprnet holds. wsprnet has what was
uploaded; the deck's log has every decode, including the ones that never
uploaded because there was no network. For receive-side analysis the deck's
log is the better record, and it is the only record of what the deck itself
heard.

It lives at `~/.local/share/cyberdeck/wspr.log`, beside the contact log, as
append-only `key=value` text with one line per spot. `WSPR_LOG_PATH` moves it.

**On the deck**, to see what is there:

```bash
wc -l ~/.local/share/cyberdeck/wspr.log
tail -3 ~/.local/share/cyberdeck/wspr.log
```

**From the laptop**, into a Downloads subfolder:

```bash
mkdir -p ~/Downloads/deck-exports
rsync -av deck@cyberdeck.local:~/.local/share/cyberdeck/wspr.log ~/Downloads/deck-exports/
wc -l ~/Downloads/deck-exports/wspr.log
```

Read it with the project's own parser rather than by eye — `kind=rx` is a
station heard, `kind=tx` a beacon sent:

```bash
cd ~/git_repos/ham-radio-cyberdeck
python3 -c "
import sys, os, collections; sys.path.insert(0, 'src')
import wsprlog
recs = wsprlog.read(os.path.expanduser('~/Downloads/deck-exports/wspr.log'))
rx = [r for r in recs if r.get('kind') == 'rx']
tx = [r for r in recs if r.get('kind') == 'tx']
print(f'{len(recs)} records: {len(rx)} heard, {len(tx)} sent')
print('unique stations heard:', len({r.get(\"call\") for r in rx}))
for band, n in sorted(collections.Counter(r.get('band','?') for r in rx).items()):
    print(f'  {band:>6}  {n}')
print('sessions:', sorted({r.get(\"activity\",\"\") for r in recs}))
"
```

Add distance and bearing with [`src/grid.py`](../src/grid.py), which is what
the screen uses — `grid.distance_km(my_grid, their_grid)` and
`grid.azimuth_deg(...)`. Both are validated against wsprnet's own figures to
within half a kilometer on 6-character grids.

**Expect corrupt decodes.** WSPR runs below the noise floor and a decode that
fails its checks can still produce a plausible-looking line. Callsigns that
are not callsigns — no digit, impossible prefixes — are decoder noise, not
stations, and they belong in no count. Filtering to stations decoded more than
once on a band removes nearly all of them.

**If the count looks far short of wsprnet**, the uploader was not armed: it
needs all three of WSPR running, the upload toggle on, and WiFi.

The WSPR menu lists `x  Export this session`. **That item is not wired up** —
pressing it does nothing. `rsync` above is the working path.

---

## 12. Full key reference

### The WSPR screen

| Key | |
|---|---|
| `F1` | The WSPR menu |
| `F2` | Name the session |
| `F3` | Band picker |
| `↑` `↓` | Pick a spot. Arrowing up off the top follows the newest again |
| `PgUp` `PgDn` | Page the spot list |
| `Esc` | Release the spot selection |
| `^B` | Transmit inhibit, from any screen |
| `^C` | Stop WSPR — the same key that aborts an over in the digital modes |
| `^O` `^P` | **Locked** while WSPR runs |

### The menu — `F1`

| Key | | |
|---|---|---|
| `w` | WSPR | Start or stop |
| `d` | Decode | Audio is still captured when off, so the level reading stays live |
| `t` | Transmit | Arms beaconing, and starts the time-out |
| `n` | Transmit next slot | One beacon, then clears itself |
| `e` | Session | Name it |
| `b` | Band | The band picker |
| `p` | Transmit percent | 0, 10, 20, 30, 50, 100 |
| `o` | Session ToT | off, 15, 30, 60, 120, 240, 480, 720 min |
| `u` | Upload spots | To wsprnet, when there is a network |
| `f` | Spot log | Where the file is |
| `a` | Audio levels | The two calibration screens |
| `z` | **Danger zone** | Clear spots. States the count and asks first |

`x  Export this session` is listed and does nothing — see §11.

### The band picker — `F3`

| Key | |
|---|---|
| `1`–`9`, `0`, `a` | Use that band alone, and tune to it |
| `Enter` | Use the highlighted band alone |
| `Space` | Toggle the highlighted band in the hop rotation |
| `Esc` | Back |

### The calibration screens

| Key | |
|---|---|
| `+` `-` (or `=` `_`, or `←` `→`, or `↑` `↓`) | Step the level |
| `Enter` | Send a tone — transmit screen only |
| `^C` | Stop the tone |
| `Esc` | Back |

Both spellings of each step key, because the console has no keypad
distinction and `=` is unshifted `+` on a small keyboard.

---

## 13. What it has done, on the air

**From the deck's own log**, one run of roughly 28 hours ending 2026-10-18,
FN10cs, a 75–10 m end-fed half-wave:

```
3,719 records: 3,612 stations heard, 107 beacons sent
412 unique stations heard
    10 m    21        17 m   165        40 m   563
    12 m    15        20 m  1556        30 m   733
    15 m   224        80 m   335
```

Furthest decoded: **VK6XT at 18,338 km**, in Western Australia, on both 30 m
and 20 m at −23 dB. **VK3QN** and **VK3MO** near Melbourne at 16,343 km.
20 m carried more than twice the traffic of any other band, which is what the
antenna's own analysis had already concluded by a different route.

**From wsprnet**, the transmit side over the same period at 5 W: 9,517
reception reports from 801 unique receivers, the furthest **VK6QS at
18,671 km**.

The receive and transmit figures are not symmetrical and should not be read
as though they were. 3,612 decodes is what this station heard with its own
noise floor; 9,517 reports is what hundreds of better-sited receivers heard
of it. The asymmetry between them is the measurement — on this station it
points at local receive noise rather than at the antenna.

---

## 14. When something goes wrong

| What you see | What it is |
|---|---|
| `arecord: audio open error: Device or resource busy` | fldigi still holds the codec. WSPR refuses to capture rather than fighting for it. Stop WSPR properly and start it again |
| **Nothing decodes, ever** | Check the level first (§6), then that the radio is in DATA-U and on the band's WSPR dial, not the band's calling frequency |
| **fldigi is deaf after WSPR** | The handover failed. Stop and start WSPR from inside WSPR. fldigi opens the codec once and never retries, so it has to be restarted onto a free card |
| **Transmit refuses** | The inhibit. The header says `INH`; `^B` arms it |
| `was USB — set to PKTUSB` **and the radio did not move** | `set_mode` is unverified against the radio. The message reports the command was sent, not that it was accepted |
| **A spot with a callsign that is not a callsign** | A corrupt decode. Normal, and not a station — see §11 |
| **The radio is still keyed** | The deck reports `the radio is still keyed after 4 attempts` when its unkey did not take. That is a rigctld or radio problem, and the front panel is the way out |

The deck says why it refused rather than refusing silently, and the refusal
appears on the line above the key hints where it can be read.

---

Design and decisions: [`wspr_design.md`](wspr_design.md). The other three
applications: [digimodes](digimodes_operating_tutorial.md) ·
[the log](logging_tutorial.md) · [deck & rig](deck_rig_design.md).
