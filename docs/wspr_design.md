# WSPR on the deck — design

Status: **design only, 2026-10-16.** No code. Branch `add-wspr`.

One of four function design documents. The others are
[`digimodes_design.md`](digimodes_design.md),
[`qso_log_design.md`](qso_log_design.md) and
[`deck_rig_design.md`](deck_rig_design.md). Hardware, rig control,
transmit safety and the rest of the platform are in
[`platform_design.md`](platform_design.md).

WSPR is the first function on the deck that does not go through fldigi.
Everything else reaches the radio through fldigi's XML-RPC seam; WSPR reaches
the sound card and the rig directly, and takes the whole deck while it runs.

## 1. Scope

**Transmit and receive together**, in one increment. Beaconing, decoding,
band hopping, a session log of its own, and spot upload when there is
network.

What that pulls in, in rough order of how much is new:

| Piece | New? |
|---|---|
| WSPR message encoder — call, grid, power to 162 symbols | **entirely new**, and the largest single piece |
| Tone generation and playback | new |
| PTT | nearly new — `rigctld_client` carries everything but PTT today |
| Audio capture | new |
| `wsprd` invocation and parsing | new, but a familiar shape |
| Band hopping schedule | new |
| Spot upload | new |
| Session, log format, menus, interlock, timers | **reuses what the logger and the digimode screens already do** |

## 2. Exclusivity is the governing property

**While WSPR is running, nothing else on the deck runs or is reachable.**
Not a mode that shares, not a fourth peer on the ring — a state the deck
enters and leaves deliberately.

That means, on start:

* **fldigi is stopped.** Not asked to release the audio: stopped.
  `systemctl stop cyberdeck-fldigi` is the mechanism, and the deck already
  has the machinery to put it back — `_restore_mode` reapplies the
  remembered modem and carrier, and `test_cold_boot.py` guards it.

  **Measured on the deck, 2026-10-16, rather than assumed.** Sharing the
  card was the cheaper design if it worked, and it does not:

  - `arecord -D plughw:1,0` with fldigi up fails with **"Device or resource
    busy"**, immediately.
  - `arecord -l` reports the codec as `Subdevices: 0/1` — zero free of one —
    while fldigi holds it.
  - There is nothing to share through: `/etc/asound.conf` and `~/.asoundrc`
    are both absent, so ALSA is at its defaults with no `dmix` or `dsnoop`.
  - With fldigi stopped the same capture succeeds at once and exactly: five
    seconds at 12 kHz mono wrote 120,044 bytes, which is
    `12000 x 5 x 2 + 44` to the byte.

  So this is not a precaution. It is the only arrangement that works on this
  hardware.
* **The ring is locked.** `^O` and `^P` do not leave the WSPR screen. The
  deck already has this concept: `AREA_LOCKED` holds the screens the ring
  refuses to leave, and WSPR-while-running joins it.
* **Leaving requires stopping.** The ring key, pressed while beaconing, says
  what is in the way rather than doing nothing — the same shape as the
  refusal when a schema change meets a part-typed contact (§7i of the log
  design).

And on stop: fldigi comes back, the ring unlocks, and the radio is left in
the mode and on the frequency WSPR was using. Not restored to what it was
before — the operator can see the radio, and silently retuning a transceiver
out from under somebody is worse than leaving it where the last thing that
ran put it.

### Stopping fldigi needs a sudoers rule

`cyberdeck-ui` runs as `deck`. `sudo systemctl stop cyberdeck-fldigi` from
inside it asks for a password, has no tty to ask on, and exits non-zero —
fldigi keeps the codec and every capture fails `Device or resource busy`.
**The rule in `docs/wspr_deploy.md` §4b is a dependency of the feature, not
a hardening step.**

Two defenses in the deck itself, because the failure was silent for a whole
session: `_service` reports a non-zero exit with systemctl's own last line
rather than only catching exceptions, and **`_wspr_start` refuses to start
when fldigi is still active** instead of running a slot clock over a codec
it does not have. WSPR without the codec is not a degraded WSPR; it is none.

## 2a. Getting `wsprd` onto the deck

**It is not installed**, confirmed on the deck 2026-10-16. That is a
deployment problem rather than a design one, and it is a small one.

**`wsprd` is a 100 KB binary with no Qt.** Checked with `ldd`: it links
`libfftw3f`, `libgfortran`, `libm`, `libc` and `libgcc_s` and nothing else.
No Qt, no Hamlib, no audio library, no X. The full `wsjtx` package is 36 MB
installed and the deck needs almost none of it — which matters on a 512 MB
board whose whole design avoids a desktop stack.

So the deck does not install `wsjtx`. It takes the binary and the two
libraries it needs:

* `wsprd` itself, extracted from the distribution's `wsjtx` package with
  `dpkg-deb -x` rather than installed,
* the single-precision FFTW runtime and the gfortran runtime, whichever
  packages the deck's own `apt` says provide them.

**The dependencies are discovered, not assumed.** Running `ldd` on the
extracted binary on the deck lists exactly what is missing there; naming
packages from memory is how a build breaks on a distribution version nobody
tested. The commands belong in the runbook, not here.

**Precedent, and the reason this is routine.** The image already builds
hamlib 4.7.2 from source because Raspberry Pi OS ships 4.6.2 with no FTX-1
backend — twenty minutes of first-boot compile, accepted deliberately
because the alternative is rig control that looks healthy and is not. A
100 KB binary extracted from an official package is a far smaller
intervention than that, and it goes in the same place in the build.

**Building from source is the fallback**, not the plan: WSJT-X's `wsprd` is C
and Fortran and needs `libfftw3-dev` and a compiler, both of which the image
already pulls in for the hamlib build. Worth doing only if the packaged
binary will not run.

## 2b. The capture device and its format

Card 1, a C-Media USB codec — `USB Audio Device` on `usb-3f980000.usb-1.2` —
and the **only capture device on the board**. Cards 0 and 2 are the Pi's own
headphone jack and its HDMI output, both playback only.

**`plughw:1,0` at 12000 Hz mono 16-bit works directly**, confirmed on the
deck. So there is no resampling to write: ALSA converts from whatever the
codec runs natively and `wsprd` receives exactly the 12 kHz mono it requires.
That removes a whole class of code the design had allowed for.

The device is a **setting** with `plughw:1,0` as its default, not a constant.
A card number moves the moment anything else is plugged in, and a WSPR mode
that captured silence from the HDMI output because a monitor was attached
would be very hard to diagnose from the panel.

## 3. Rig control without fldigi

Stopping fldigi takes fldigi's rig control with it. Everything WSPR needs
from the radio therefore goes through **`rigctld_client`** directly:

* `cyberdeck-rigctld.service` is a separate unit from
  `cyberdeck-fldigi.service`, so rigctld stays up when fldigi goes down.
* The log already reads frequency, mode and power through this client, so
  the path is proven.
* **Verified on the deck, 2026-10-17.** With fldigi **stopped** — the
  arrangement WSPR runs in — the client returned `connected: True`,
  `7038600.0`, `('PKTUSB', 3000)` and `0.5` W from `power(max_watts=10)`.
  Identical with fldigi up. So `cyberdeck-rigctld.service` keeps the serial
  port when fldigi goes down, and **WSPR's radio control works**. This was
  the last structural assumption in the design and it holds.

  Two things fell out of that run. `PKTUSB` is in `qsolog.RIG_DATA_MODES`,
  so **the transmit interlock passes** on the radio as configured. And
  0.5 W is **27 dBm exactly**, one of the encodable values — so the power
  display would highlight (§6) without the operator touching anything.

* ~~PTT is the one thing missing.~~ **Added 2026-10-17**: `set_ptt(on)`
  sends `T 1` / `T 0`, and `ptt()` reads the state back.

  **`ptt()` returns None when the radio cannot be read, not False.** A radio
  that cannot be read is not a radio known to be receiving, and a caller
  treating the two alike would read "cannot reach the radio" as "the radio
  is not transmitting" — the one wrong answer that matters when the failure
  mode is a transmitter left keyed.

  **`set_ptt()` returning True means the command was SENT, not that the
  radio is keyed.** A Yaesu set command answers with silence, so there is
  nothing to confirm from. Anything keying the radio reads `ptt()` back
  rather than assuming; `tests/test_rigctld.py` pins that distinction with a
  stand-in that accepts `T 1` and then reports still receiving, which is
  exactly the shape of a PTT that did not take.

## 4. Bands and frequencies

The eleven bands the deck offers. A WSPR signal sits 1400–1600 Hz above the
dial, inside a 200 Hz window.

| Key | Band | WSPR dial (MHz) |
|---|---|---|
| `1` | 80 m | 3.568600 |
| `2` | 40 m | 7.038600 |
| `3` | 30 m | 10.138700 |
| `4` | 20 m | 14.095600 |
| `5` | 17 m | 18.104600 |
| `6` | 15 m | 21.094600 |
| `7` | 12 m | 24.924600 |
| `8` | 10 m | 28.124600 |
| `9` | 6 m | 50.293000 |
| `0` | 2 m | 144.489000 |
| `a` | 70 cm | 432.300000 |

**Confirmed twice.** The published list at sigidwiki.com/wiki/WSPR gives
every one of these, and the eight HF figures were independently derived from
8,111 real spots in the `wspr_7510_analysis` wspr.rocks exports: the observed
signal frequencies sit 1.39–1.62 kHz above each dial frequency, which is the
WSPR window. Two sources agreeing, one of them the operator's own traffic.

**Bands deliberately not offered**, though the published list carries them:
136 kHz (2200 m), 474.2 kHz (630 m), 1.8366 MHz (160 m), 70.0910 and
70.1510 MHz (4 m, Region 1) and 1.2965 GHz (23 cm). The eleven above are the
bands this station works, and a picker padded with bands the radio cannot
reach is a list to scroll past forever — the same reasoning that keeps the
digimode band menu to eleven.

**The keys match `menus.BANDS`** — same eleven bands, same digits, `a` for
70 cm — so a band key an operator already knows means the same band on the
WSPR screen. The frequency tables differ because that one holds digimode
calling frequencies and this one holds WSPR dial frequencies.

Selecting a band tunes the radio through `rigctld_client.set_frequency` and
reports what the radio actually did — the existing `_set_vfo` pattern, which
reads the frequency back and says so when the radio refused.

## 5. Sessions, and what is recorded

The logger's concepts, reused, with one deliberate subtraction.

### What is taken from the logger

* **A session is `(name, start)`.** The operator names it; the start is an
  ISO timestamp pinned when it begins. A night of beaconing is one session
  whatever the UTC date does, for the same reason an activation from 23:50
  to 00:30 is one activation (§7f of the log design).
* **One file, `key=value` per line, carrying only the fields that have a
  value.** The format carries no schema, which is what lets records of
  different shapes share a file — and WSPR needs exactly that, because a
  beacon sent and a spot heard are different shapes.
* **Session attributes are DERIVED from the records, not stored beside
  them.** `qsolog.sessions_in` is the pattern: a file that records what
  happened cannot drift from what happened, and a power cut cannot lose it.
  The rig, the antenna, the bands used and the counts all come out of the
  records.
* **Newest wins** where a session's attribute changed mid-run, as §7i
  resolves a session's schema.
* **Atomic whole-file replace** for any correction — `qsolog._rewrite`.

### What is deliberately NOT taken

**No custom schemas.** One fixed field set, as WSJT-X has. The logger's
schemas exist because `599` is both a report and a serial and only the
operator knows which — a contact's grammar is genuinely theirs to define.
A WSPR spot has no such ambiguity: `wsprd` decides what the fields are, and
there is nothing for an operator to choose. So there is no schema picker, no
field selector, and no `activity_type` on a WSPR record.

That also frees `F3` on the WSPR screen for the band selection (§10), where
on the log screen it picks a schema.

### The fixed field set

Two record kinds in one file, told apart by `kind`:

| Field | On | From |
|---|---|---|
| `kind` | both | `tx` or `rx` |
| `when` | both | the deck's clock, full ISO UTC |
| `activity`, `activity_start` | both | the session |
| `band` | both | **recorded with the capture, not derived at decode** (§8) |
| `freq` | both | hertz, following the log's `HERTZ_FIELDS` convention |
| `mode` | both | `WSPR2` |
| `my_call`, `my_grid` | both | Station settings |
| `my_rig`, `my_antenna` | both | Station settings |
| `my_dbm` | both | this station's announced power |
| `tx_power` | both | watts actually read from the radio |
| `call`, `grid`, `dbm` | `rx` | the station heard, and the power it claims |
| `snr`, `dt`, `drift` | `rx` | `wsprd` |

**Both kinds carry the rig and antenna**, per record rather than per session,
because that is how the contact log does it and because it is what makes a
session's attributes derivable. An antenna changed halfway through a night is
then a fact in the file rather than a fact that was overwritten.

**`my_dbm` and `tx_power` are both kept, and they are not the same number.**
One is what the beacon announced, snapped to a value WSPR can carry; the
other is what the radio was actually making. 3 W announces 33 dBm, which is
2 W. Keeping both is what makes that discrepancy visible afterwards instead
of being quietly rounded away — and it is the same reason the screen shows
both (§6).

### What a session reports

Derived, and shown on the session list the way the logging activity list
shows its counts:

* the name and the start date-time,
* the rig, the antenna and **this station's grid** (newest, if they changed),
* **which bands were used**, which falls out of the `band` field,
* **how many spots were heard and how many beacons were sent**, which is the
  count of each `kind`.

**The grid is a session attribute and not only a station setting**, because
it is the one that changes when the station moves. A portable operation from
a different grid is a different session in the only sense that matters to
WSPR — every distance computed from those spots depends on it — so `my_grid`
goes on every record and the session reports it, exactly as the rig and the
antenna do. A grid taken from the Station settings at display time would
report today's grid against last month's spots.

**A WSPR spot is not a QSO and never enters the contact log.** Nothing about
a beacon reception is a two-way contact, and putting them in the file that
feeds an ADIF export would be wrong in the one direction that matters.
`wsprd`'s own `ALL_WSPR.TXT` is kept untouched beside the deck's file as the
raw record.

## 5a. Danger zone for the WSPR log

The same shape as the logger's (§7h), for the same reason: a WSPR session
accumulates records faster than anything else on the deck — a night of
beaconing is hundreds of spots — and a clean slate on demand is what makes
the difference between a bug and a leftover checkable.

Behind `z` on the WSPR menu, named so nobody arrives in it by accident:

| Key | Does | Destroys |
|---|---|---|
| `a` | Forget all WSPR sessions | nothing — every record keeps its label |
| `s` | Delete this session's records | the spots and beacons of the session on screen |
| `m` | Delete EVERY WSPR record | the whole WSPR log |

Each line states the count it would destroy and each asks before doing it,
with the count in the question — because "clear the log" and "delete 412
spots and 61 beacons" are different sentences and only the second says what
is about to be lost.

Three things it does differently from the logger's:

* **The counts are broken out by kind.** A session holds spots heard and
  beacons sent, and "37 records" hides which. The question says "412 spots
  and 61 beacons", because an operator who is about to lose a night of
  received data cares about a different number than one who is clearing
  their own transmission history.
* **`a` destroys nothing**, exactly as in the logger: the labels stay on
  every record, so the sessions remain exportable and logging under a name
  again brings them back (§7i).
* **It requires WSPR to be stopped.** The other danger zone has no such
  rule, because nothing is appending to the contact log while the menu is
  open. Here a capture is writing every two minutes, and emptying a file
  that a running decoder is about to append to is a race with no useful
  outcome. The refusal is the same shape as the one on leaving the screen:
  it says what is in the way rather than doing nothing.

The WSPR log is its own file, so none of this can touch the contact log —
which is the other half of "a spot is not a QSO".

## 6. Transmit

### Encoding

The message is callsign, grid and power in dBm, encoded to 162 four-level
symbols: a 50-bit payload, a rate-1/2 K=32 convolutional code, interleaving,
and a fixed sync vector. **No encoder ships with the local WSJT-X package** —
`wsprd` decodes and there is no `wsprsim` — so this is implemented, and it is
the largest new piece of code in the feature.

It is also the most testable thing in it: pure, deterministic, with published
test vectors. A known call/grid/power triple produces one known symbol
sequence, and that is a unit test with no radio, no audio and no clock.

### Power, and the dBm the message carries

WSPR encodes power as dBm and only from a fixed set — 0, 3, 7, 10, 13, 17,
20, 23, 27, 30, 33, 37, 40, 43, 47, 50, 53, 57, 60. Since
`dBm = 10·log10(watts) + 30`, only a few wattages land on one exactly:

| Set the radio to | dBm | |
|---|---|---|
| 1 W | 30 | exact |
| 2 W | 33 | exact |
| 5 W | 37 | exact |
| 10 W | 40 | exact |
| 20 W | 43 | exact |
| 50 W | 47 | exact |
| 100 W | 50 | exact |

Everything between is off by as much as 1.8 dB: 3 W is 34.77 and encodes as
33, 15 W is 41.76 and encodes as 43.

**The screen shows all three numbers at once and highlights the dBm when it
is exact.** The ceiling (`TX_POWER_MAX`), the power actually read from the
radio, and the dBm that implies — with the dBm highlighted the moment the
reading lands on an encodable value, and shown plainly as snapped when it
does not. That makes the display an instrument rather than a readout: an
operator adjusting the radio's power control watches for the highlight, and
the highlight is the confirmation that what the beacon announces is what the
radio is doing.

This is why the three numbers are together and not spread across screens. A
ceiling without a reading cannot be checked, and a reading without the dBm
does not say what will go on the air.

Two existing facts it depends on, both already documented gotchas:

* **`TX_POWER_MAX` is what turns the radio's RFPOWER fraction into watts.**
  It is on the deck-and-rig screen for this reason, and without it the deck
  cannot report power at all. A WSPR session started with no ceiling set
  cannot announce a power, and says so rather than guessing.
* **`_power_now()` falls back to the configured value when the radio will
  not answer.** A beacon announcing a wattage the radio is not using is
  worse than one announcing nothing, so a reading that had to fall back is
  **marked as a fallback on the display**, never shown as though it came
  from the radio.

**Transmit is allowed when the dBm is not exact**, decided 2026-10-16. It
shows the snap rather than refusing: a 0.8 dB error in a reported power is
not a reason to stop a beacon, and the highlight is what makes an operator
want to fix it. Refusing would turn a readout into an obstacle.

### Keying, and the four ways out

`src/wsprtx.py` keys the radio, plays the rendered audio and unkeys. Three
properties come before every feature in it, because the worst failure the
deck has is a transmitter left keyed:

1. **Every path out of a transmission drops PTT** — completion, a failed
   `aplay`, a player that wedged past its deadline, `stop()` from the middle,
   and a player that could not be started at all. That last is the case that
   would otherwise leave the radio keyed with nothing going out.
2. **It is time-bounded.** `TX_TIMEOUT_S` is 118 s: longer than the 110.6 s
   signal, shorter than the 120 s slot. Nothing legitimate reaches it, and a
   wedged player cannot hold the air into the next slot.
3. **PTT is read back.** `set_ptt` returning True means the command was
   sent; a Yaesu answers a set command with silence. So the state is
   confirmed, and the three answers are distinguished: **False means the
   radio did not key** and nothing is played, while **None means the state
   could not be read** and the transmission proceeds with a note — refusing
   on None would take transmit away from a radio whose readback is simply
   unsupported, which is a worse failure than the one being prevented.

`stop()` is the single route used by `Ctrl-C`, leaving WSPR, the time-out
timer and shutdown, so it works from every state and never raises.

### The audio is rendered once

A WSPR message is identical for every transmission of a session — same call,
same grid, same power — and rendering costs about two seconds on a Pi 3A+.
Rendering per beacon would spend that in every slot for nothing, so the WAV
is cached, keyed on everything the audio depends on.

**A power change invalidates it**, which is the one of the three an operator
adjusts mid-session. A cache that beaconed the old wattage would announce a
power the radio is not making, which is the same fault §6 keeps `my_dbm` and
`tx_power` separate to make visible.

The file carries **one second of silence first**, because WSPR starts at the
even minute plus one and padding the file is more reliable than timing the
start of playback to a tenth of a second.

### Tones and timing

162 symbols at 8192/12000 s each — 0.6827 s per symbol, 110.6 s total —
4-FSK at 1.4648 Hz spacing, starting 1 s after the even minute. Generated to
a WAV and played, which keeps the audio path symmetrical with capture
(`arecord` in, `aplay` out) and keeps both fakeable in tests.

## 6a. The four toggles

What WSPR is doing is four independent switches, not one run button. Each
does one thing and each is readable from the screen:

| Toggle | Does |
|---|---|
| **WSPR** | on starts the slot clock and the audio capture — the deck is receiving |
| **Decode** | on runs `wsprd` over each captured window; off captures without decoding |
| **Transmit** | on lets the schedule beacon; off is receive-only |
| **Transmit next** | a one-shot: beacon on the next slot whatever the schedule says |

**Why Decode is separate from WSPR.** Capturing without decoding is what
makes the receive level checkable: the audio is flowing and its level is on
screen, and the Pi is not spending its cores on the Fano decoder while the
operator is turning a gain control. It is also the honest state when the
decoder is behind — capture is keeping up, decoding is not.

**Why Transmit next is its own switch.** A beacon is otherwise at the mercy
of a percentage, and "go on the next slot" is the thing an operator wants
when testing an antenna, checking a band opening, or asking somebody to
watch for them. It is WSJT-X's `Tx Next` and it is one-shot: it clears when
the slot it armed has passed.

**Transmit percentage** is a setting the operator changes: the fraction of
slots that beacon rather than listen, with the chosen slots randomized so
two stations on the same schedule do not collide every cycle. **The default
is WSJT-X's**, decided 2026-10-16 — matching the reference implementation
rather than inventing a number, for the same reason `wsprd` is the decoder.
Beaconing in every slot hears nothing and crowds a shared 200 Hz window.

The toggles compose, and the compositions are all meaningful: WSPR off is
idle; WSPR on with Decode off is a level check; WSPR and Decode on with
Transmit off is a receive-only monitor; all three on is a beacon.

## 6a1. The two audio levels, and why they are set differently

**Transmit is a digital amplitude. Receive is the ALSA mixer.** The asymmetry
is not an inconsistency; it follows from what each side can reach without
affecting the digimodes.

`WSPR_TX_LEVEL` scales the samples where the beacon is rendered
(`wsprtx.Transmitter.level`, a percent of full scale). The ALSA *playback*
mixer would have been the obvious place and is the wrong one: fldigi shares
it, so turning WSPR down there turns the digimodes down with it. Nothing but
WSPR plays the rendered file, so scaling it cannot affect anything else. A
level change drops the cached render, or the next beacon goes out at the old
amplitude and the operator watches a power meter that does not move. The
test tone uses the same amplitude, because a tone sent at a level the beacon
will not use calibrates a transmission that never happens.

Measured on the deck, 2026-10-17: at 50% the radio made close to 10 W with
its power control set to 5 W and the ALC half-scale. The level is the
control that was missing, not a refinement.

`WSPR_RX_GAIN` sets the capture mixer, which fldigi also uses — **and that is
safe only because WSPR owns the codec exclusively.** fldigi is stopped before
anything is captured (§2), so the control is unobserved for the length of a
session. `wsprgain.Gain` reads the value before writing, once per session,
and restores it on stop; that is what makes this a per-function level rather
than a change to the station. A digital gain on the captured samples was the
alternative and does nothing useful: the ADC has already decided how much of
its range the audio used, and multiplying a quiet recording makes a loud
recording of the same noise.

Percent rather than raw steps, because this codec's range is 0–16 and
another's is not, and `amixer` speaks percent on all of them.

**What makes the receive level judgeable** is the figure beside it: every
capture is measured and its dBFS shown, marked when it falls outside roughly
-32 to -18. That is the WSJT-X analog the operator asked for, and without it
a gain control is a knob with no meter.

## 6b. Calibrating the audio

Two levels decide whether WSPR works at all, and neither can be set by
guessing.

### Transmit: a test tone, and the radio's own meter

**A TX test toggle** sends a single steady tone at the current output level
so the operator can set the audio drive against the radio's power meter and
the deck's own power reading at the same time.

This is not optional polish. WSPR is constant-envelope 4-FSK, and an
overdriven audio input makes the radio's ALC act on it — which compresses a
signal that has no amplitude information to compress, generates spurious
products and widens the transmission across a 200 Hz window shared with
everybody else on the band. The drive level has to be set once, deliberately,
with something steady on the air to set it against. Without this the power
the beacon announces is a guess and the signal may be dirty.

Three properties it has to have:

* **It is behind the same interlock as a beacon.** It keys the transmitter,
  so the data-mode check and the transmit inhibit apply unchanged.
* **It is time-bounded.** A test tone is a transmitter left keyed, which is
  the one failure mode worse than a bad drive level. It stops by itself.
* **It shows both numbers.** The deck's power reading and the dBm it maps
  to, highlighted when exact (§6) — so the operator is turning the control
  until the highlight appears rather than until a needle looks right.

### Receive: read the level off the capture, do not build a mode

**Not with `audioop`.** It was removed from the standard library in Python
3.13; the deck's Python is newer than that and the development laptop's
(3.14 on Fedora) still has it. An implementation built on it passes every
test on the laptop and raises `ModuleNotFoundError` on the panel — the same
shape of fault as `kspd=^Z` turning Ctrl-Z into KEY_SUSPEND, and the console
font having no ellipsis. `wspr.audio_level` is pure Python for that reason,
and samples every sixteenth frame: a level meter for a human turning a gain
control does not need 1.37M samples, and measuring them all costs about a
second of a Pi's time per slot.


The received audio level is **computed from the window the deck already
captured** and shown on screen every slot. No calibration mode, no separate
state.

The information is identical — the level of the audio `wsprd` is about to
read — and it has two advantages over a mode. It is visible every slot
rather than only when somebody goes looking for it, so a gain that drifts or
a cable that comes loose shows up during ordinary operating. And it adds no
state to a screen that already has four toggles, a band, a schedule and a
timer on it.

Pairing it with the Decode toggle gives the calibration workflow without a
calibration screen: WSPR on, Decode off, watch the level, set the gain, turn
Decode on.

## 7. The interlock, and the time-out timer

**Transmit inhibit cannot be lifted until the radio reads a data mode.**
This is the rule the deck already has — `_toggle_inhibit` refuses to arm in a
voice mode and `_watch_rig_mode` drops the arm when the radio leaves one —
applied to a function that keys itself. `qsolog.RIG_DATA_MODES` is the set,
and `Deck._rig_mode_held` is what reads it without being fooled by a dropped
CAT read.

Unattended keying makes this stricter rather than looser: the operator is not
watching the radio when it transmits, so a mode change that would put a
digital signal into a voice allocation has to stop the beacon rather than
warn about it.

**A time-out timer stops WSPR by itself. Default 60 minutes, configurable.**
It exists because this is the one function that runs with nobody watching:
the failure it prevents is a deck left beaconing on a park bench for an
afternoon, or carried home still transmitting. The remaining time is on
screen, because a timer whose value cannot be seen is a timer nobody trusts.

Both the ToT and manual start/stop stop the same way — the session ends,
fldigi comes back, the ring unlocks.

## 8. Band hopping

The operator selects which of the eleven bands to hop through; the schedule
cycles them one band per slot, retuning in the gap between windows. Nothing
hops while a single band is selected.

The retune happens in the roughly six seconds between the end of one
114-second window and the start of the next, which is also when a decode may
still be running — so the retune cannot wait on the decoder, and the decoder
cannot be assumed to know what band its audio came from. **The band is
recorded with the capture, not read back at decode time.**

**The band is on every spot row and in every spot record.** Two spots an
hour apart on a hopping session answer different questions, and a session
log without the band is a list of callsigns.

### Selecting one band, and selecting a rotation

Two things are chosen in one picker, so each gets its own key:

* **A band number, or Enter on the highlighted row, selects that band alone
  and tunes the radio to its WSPR dial** — immediately, not at the next
  slot. Selecting a band is the operator saying "go there"; a picker that
  moved a label and left the radio where it was reads as a picker that does
  not work.
* **Space toggles the highlighted band in and out of the rotation**, and
  `[*]` marks the ones in it.

Two earlier idioms are recorded because each failed in a way worth not
repeating. Membership-toggling on a bare number meant pressing 20 m from a
default of 40 m produced a two-band rotation rather than 20 m. Replacing it
with `+` then a number fixed that and was undiscoverable — a two-key prefix
with nothing visible between the keys teaches nobody, and it was reported in
those words. Space acts on the row the arrows are already on and the
checkbox is in the menu, so the idiom is on screen rather than remembered.

**The rotation can never be empty.** Unselecting the last band is refused
and says why: the schedule has to have something to tune to.

### The per-band mode check

The radio holds one mode at a time but **remembers a mode per band**, so a
four-band rotation can be three bands in DATA-U and one in LSB. The only
symptom is a slot that transmits nothing useful an hour into a session.

`Check hop bands for DATA-U` on the menu tunes each band in the rotation in
turn, reads the mode back, and names the bands that are not in a data mode,
which is the manual fix the operator then makes on the radio. The starting
band is restored. It refuses while WSPR is running, because it retunes.

## 9. Uploading spots

**Three conditions, all of them the operator's, and all three required:**

1. WSPR is running,
2. the upload toggle is on,
3. there is network.

Nothing uploads unless all three hold. The toggle is the operator's decision,
the WSPR state is the operator's decision, and the network is a gate on both
— so this is an **armed** upload, not an automatic one. With the toggle on
and the network gone, uploading stops by itself and the state says `no wifi`
rather than failing quietly; when the network returns, it resumes.

`Deck._online()` already answers "is there a default route", cached for a few
seconds, and the three-state display matches the callbook's — `on`, `off`,
`no wifi` — so the distinction between "switched off" and "cannot right now"
is visible at a glance rather than inferred.

**How this sits with the standing rule.** The deck's rule is that uploading a
contact is always a manual action, pinned in `test_menus.py` as a property of
the source — no `qrzlog` import, no `upload(` call — so that any change is
deliberate rather than accidental. This is consistent with the rule's intent
rather than an exception to it: the operator arms the upload, and the spots
that follow are what arming it means. The three conditions are what make it
an act rather than a background behavior.

What remains worth stating: a deck under test, armed, on WiFi, transmits real
beacons under the operator's callsign and uploads real spots to a permanent
public database. The time-out timer bounds it, the session name makes a test
session identifiable afterwards, and the toggle is one keystroke away — but
nothing about it is undoable once sent, and the interface should not suggest
otherwise.

### The protocol, pinned

Read out of **WSJT-X's own `Network/wsprnet.cpp`**, which is what every other
WSPR station is running:

```
POST http://wsprnet.org/post/
Content-Type: application/x-www-form-urlencoded
```

| Field | Carries |
|---|---|
| `function` | `wspr` for a spot, `wsprstat` for a slot that heard nothing |
| `rcall`, `rgrid`, `rqrg` | the receiver — this station, and **the dial frequency** |
| `date`, `time` | the slot, `YYMMDD` and `HHMM` |
| `sig`, `dt`, `drift` | the measurements |
| `tcall`, `tgrid`, `tqrg` | the transmitter, as decoded — `tqrg` is **where it was found**, not the dial |
| `dbm` | the power the other station claims |
| `version`, `mode` | `mode` is `2` for WSPR-2, `15` for WSPR-15 |

Three things in there that are easy to get wrong:

* **`rqrg` and `tqrg` are different frequencies.** One is where this station
  was listening and the other is where the other station was found, 1.4 kHz
  up. Sending the dial as both is a wrong report rather than a missing one.
* **A slot that decoded nothing still reports.** `function=wsprstat` with the
  receiver's side and `tpct`, and no transmitter fields. An absent report and
  a report of silence are different facts — the first says nothing about
  whether anybody was listening on that band.
* **One spot per request, spaced 200 ms**, which is what WSJT-X does. There is
  no documented bulk endpoint and a client does not get to invent one. A
  client that hammers a shared service faster than the reference client is a
  client that gets blocked.

The deck sends `version=cyberdeck`. Claiming to be WSJT-X would make every
bug reported against this somebody else's.

**A backlog is dropped, not kept.** `Uploader.MAX_PENDING` bounds the queue.
A queue that survived an afternoon off-grid would upload a thousand spots
hours late the moment WiFi returned, which is worse for the database than not
reporting them — and the deck's own log has every one of them regardless.

## 10. The interface

Matching the rest of the deck, which means the shape is already decided:

* **`F1` opens the WSPR menu**, as it opens the menu for whichever area the
  operator is in.
* **`F4` cycles the color scheme**, as on every screen.
* **`F2` and `F3`** are the area's two main sub-views, as they are on the
  digimode screen (tuner, modes) and the log screen (activities, schemas):
  **`F2` the session list, `F3` the band selection.** The parallel is exact —
  `F2` is "which session am I in" on both screens.
* **`Ctrl-I`** toggles transmit inhibit, as everywhere else, and refuses to
  arm outside a data mode.
* **The menu is grouped** the way the logging menu is — state, then session,
  then the schedule, then the file — with the counts and current values on
  the lines themselves, because that is what makes the logging menu readable
  without opening anything.
* **The four toggles are single keys on the menu**, each showing its own
  state on its line, the way the logging menu shows the dupe rule and the
  callbook state on theirs. The transmit percentage, the time-out timer and
  the upload toggle sit with them.
* **A danger zone** behind the same `z`, with the same confirmations that
  state their counts — see §5a, which also says why it refuses while WSPR is
  running.
* **The TX test is not on the main screen.** It keys the transmitter and is
  used once per station setup, so it belongs on the menu behind a
  confirmation, not under a key that can be brushed.

The status line reports what the radio is doing rather than what the deck
intends, which is NFR-20 and is the existing rule: the band, the dial
frequency, the power actually read, whether the next slot transmits or
listens, the remaining ToT, and the upload state.

### The slot clock

**WSPR is a schedule before it is a mode**, so the screen shows the position
inside the two-minute slot: the elapsed figure, a bar that fills over the
slot, the time to the next one, and whether that next slot transmits or
receives. WSJT-X shows the same thing for the same reason — without it a
dead band and a deck between slots look identical.

It reads from the same arithmetic the scheduler acts on rather than a second
copy, so what the operator watches and what fires the capture cannot
disagree. While WSPR is stopped the row says so rather than showing a clock
that is not driving anything.

### Three clocks, each named

The slot, the decode and the session all have clocks, so none of them is
labeled with a bare duration. The session time-out is **`Session ToT`** on
the menu and `session m:ss left` on the screen. `Time-out` on its own named
neither what times out nor what happens.

### Distance and bearing are computed, never stored

WSPR carries a grid square and no distance. `src/grid.py` places a locator
at the center of its rectangle and gives the great-circle distance and the
initial bearing, which is how wsprnet and wspr.rocks fill their own km
column from the same two grids.

**Validated against this station's own wsprnet records** rather than against
the formula alone: agreement inside 0.5 km on every six-character path from
498 to 6855 km, including a 6599 km path to Switzerland. Four-character
grids agree within a few km, which is all they can — a four-character square
is about 150 km across, so a distance between two of them is good to tens of
kilometers and no better. The decoder reports four characters for a type 1
message and six for a type 2, so both occur.

Neither figure is written to the spot log. Both are derivable from the two
grids that ARE in each record, and a log holding a derived figure beside the
data it came from invites the two to disagree.

### The spot list scrolls

A session gathers hundreds of spots and the screen holds ten. **The arrows
select and scroll**, PgUp/PgDn move by eight, Home and End reach the newest
and oldest, and Esc drops the selection so the list follows the newest spot
again. Without this the older spots of a session were logged and unreachable
without leaving the deck for the file.

### The counts are cached, because the draw loop is not free

`heard` and `sent` came from reading and parsing the whole spot log on every
draw — and the draw loop runs on every keypress, so scrolling the list
re-parsed a file that grows all session. The menu did the same, because
`_menu_for` is rebuilt on every keypress while a menu is open. Both now go
through `_wspr_counts`, invalidated by every path that writes the log.

A time-based cache was the alternative and is worse: it makes a spot that
has just been logged take a second to appear in a counter sitting next to
it.

### Esc releases the selection before anything else

Tested after the running check, Esc answered every press with "WSPR is
running — ^X stops it", and an operator who had scrolled into the list could
not get back out. The selection is released first, running or not. While a
spot is selected the footer is about the list, because that is what the keys
are doing and because Esc releasing the selection is the one thing there is
no other way to discover.

### A refusal is reported where it can be read

Every refusal reached from the menu closes the menu first. The messages go to
the WSPR screen's message line, which is *underneath* an open menu — so
`Calibrate transmit audio` appeared to do nothing at all when it was in fact
refusing, correctly, because transmit was inhibited. A refusal that cannot be
read is indistinguishable from a dead key.

### Power reads "snapped" or "not snapped", never just one

Both states are named. The word alone was shown only when the value had been
snapped *down*, which reads as "this one is on a snap point" — the opposite
of what it meant. See §5 of the power discussion: the highlight is the
confirmation, and the word has to agree with it.

## 10a. What is built

**All of it, as of 2026-10-17.** WSPR is a fourth ring area, wired into
`cyberdeck.py`, deployed to the deck and reachable from the panel. The
`_leave_cleanly` handler was confirmed on the hardware in the same deploy:
the journal reads `Deactivated successfully` where every earlier restart
read `code=exited, status=1/FAILURE`, which means the shutdown path — abort
transmit, unpark the decoder, restore the console palette — now actually
runs on a restart.

Nine test files, 604 checks. Only one of them needs a terminal.


| Piece | State |
|---|---|
| the message encoder | **done** — `src/wspr.py`, validated by `wsprd` decoding its own output |
| power to dBm, and exactness | **done** |
| the `wsprd` output parser | **done** — written against captured real output, and confirmed against the deck's own `wsprd` 2.7.0 |
| spot deduplication | **done** — a window can decode one transmission twice |
| the slot schedule, hopping, the ToT | **done** — `src/wsprsched.py` |
| capture and decode, polled | **done** — `src/wsprrx.py`, no sound card in any test |
| transmit: render, key, play, unkey | **done** — `src/wsprtx.py`, no radio in any test |
| the screen and menus | **done** — `render.wspr_screen`, `menus.wspr_menu`, `menus.wspr_danger_menu` |
| the uploader | **done** — `src/wsprnet.py`, protocol read from WSJT-X's source, 59 checks with no network |
| the band table | **done** — `src/wsprbands.py`, confirmed three ways (§4) |
| audio level | **done** — `wspr.audio_level`, no `audioop` (§6b) |
| the spot log | **done** — `src/wsprlog.py`, two record kinds in one file, sessions derived |
| PTT | **done** — `rigctld_client.set_ptt` / `ptt`, verified against a stand-in |
| **the whole receive path, end to end** | **proven on the air 2026-10-17** — see §12a |

`tests/test_wspr.py` covers what exists: 91 checks, including the round trip
through the real decoder.

**What the fixtures do not yet cover**, and cannot without the air: a real
type 2 (compound call) or type 3 (hashed call) decode. The parser reads both
and is tested against hand-written lines in that format, which is a weaker
guarantee than the type 1 fixtures have. A capture from the deck with other
stations in it would fix that, and it is worth collecting when the receive
path exists.

## 10b. One spot per station per window

**A window can decode the same transmission twice.** Found on the deck, not
imagined: `wsprd -d` over a four-signal test window reported
`KD3CCO FN10 37` at both +23 dB and -10 dB — one transmission, found twice,
the weak copy an artifact of the strong one.

Left alone that would put a station in the log twice for one two-minute
slot, and **upload to wsprnet a signal nobody sent**. So decodes are
deduplicated before anything is written or reported: one spot per station
per window, strongest SNR winning, because the strong copy is the real
measurement.

Keyed on the **call and the grid together**, not the call alone: two stations
can share a hashed call, and a station that moved between slots is a
genuinely different report rather than a duplicate of itself.

Deep search makes duplicates likelier, which is a cost of `-d` worth knowing
alongside its 33.7 s — but not a reason to leave it off, since the fix is
four lines and a sort.

## 10c. Capture and decode do not wait for each other

`wsprsched` decides when; `src/wsprrx.py` does it. Two subprocesses, both
**polled** and never waited on, because the main loop draws five times a
second while `arecord` runs for 114 seconds and `wsprd` for up to 34 on a
Pi 3A+. A `tick()` that waited for either would freeze the panel for the
length of a slot.

**They are independent on purpose.** There are about six seconds between the
end of one window and the start of the next, and a decode routinely outlives
that. A decode still running when the next slot opens must not delay the
capture: the next window starts on time, and the decode finishes when it
finishes. So the receiver holds one capture and one decode and they are not
the same slot's.

Four conditions it distinguishes, where a simpler design would conflate
them:

* **No end marker is a dead decoder, not an empty window.** `wsprd` prints
  `<DecodeFinished>` whether or not anything decoded, so its absence means
  the run did not finish. Treating the two alike would record a silent band
  for a decoder that was killed — and silence is a fact somebody might
  upload.
* **An empty window is a success.** Nothing heard is the ordinary outcome
  on a quiet band and is counted as a decode, not a failure.
* **A capture that wrote nothing, or exited badly, is a failure** with
  `arecord`'s own last line kept for the screen — including the "Device or
  resource busy" that means fldigi still holds the codec.
* **A wedged decoder is killed** at `DECODE_TIMEOUT_S`, generous at 110 s
  against the 33.7 s a deep search measured. That exists so a stuck `wsprd`
  cannot accumulate, not to cut short one that is working.

**A second capture is refused rather than replacing the first.** Two
`arecord` processes on one exclusive codec is the second one failing, and a
capture that silently replaced the one in progress would lose a window
without saying so.

## 11. Testing

Nothing in the list below needs a sound card, a radio or a network.

| Layer | Tested by |
|---|---|
| the message encoder | **published test vectors** — a known call/grid/power to a known symbol sequence |
| power to dBm | a pure function against the valid-value set; 5 W is 37, 10 W is 40, and an unreadable radio is a fallback and says so |
| `wsprd` output parsing | a pure parser against **captured real output** |
| the slot schedule, hopping, the ToT | a state machine with an **injected clock**, like `session.py` |
| spawning and reaping `wsprd` | a **fake `wsprd`** that prints canned lines then `<DecodeFinished>`, the `fake_fldigi.py` pattern |
| capture and playback | a **pre-recorded WAV** and a fake `aplay` |
| the exclusive lock | a pty test: the ring key while beaconing must refuse and say why |
| the four toggles | the state machine: every composition of WSPR/Decode/Transmit is a defined state, and `Transmit next` clears after the slot it armed |
| power to dBm and the highlight | a pure function: 1, 2, 5, 10, 20, 50, 100 W are exact; 3 W encodes 33 and is marked snapped; no ceiling means no announced power |
| the TX test's time bound | the state machine with an injected clock — a test tone that does not stop by itself is the worst failure in the feature |
| the danger zone | pure: the counts in each question, broken out by kind; and a pty test that it refuses while WSPR is running |
| the interlock | a pty test with the stand-in rig in a voice mode: arming must be refused |
| the screen and menu | pure renderers returning `(text, attr)` segments |

**Step one of implementation is capturing real `wsprd` output** and
committing it as a fixture. A parser written against a remembered format is
written against a guess, and this project has lost a session to exactly that
— a test fixture with an unquoted `activity=Bald Eagle SP` made every
session assertion in a file report zero contacts while passing.

## 12. What `wsprd` is, measured

Verified against `wsjtx-3.0.1`, 2026-10-16:

```
wsprd [options...] infile        infile must have suffix .wav or .c2
  -a <path>   writeable data files, default "."
  -f x        transceiver dial frequency in MHz
  -d          deeper search, slower, a few more decodes
  -q          quick mode
  -w          wideband, +/- 150 Hz of center
```

* Expects **12 kHz mono 16-bit** audio of about 114 seconds.
* Terminates its stdout with the literal line `<DecodeFinished>`, present
  whether or not anything decoded. That is the parser's end marker.
* Writes five files into `-a`: `ALL_WSPR.TXT`, `wspr_spots.txt`,
  `hashtable.txt`, `wspr_timer.out`, `wspr_wisdom.dat`. The deck points `-a`
  at its own run directory so none of it lands wherever the process started.
* **Measured on the deck itself, 2026-10-16** — a Pi 3A+, armv7l, with
  fldigi still running:

  | | x86 laptop | Pi 3A+ | of a 120 s slot |
  |---|---|---|---|
  | decode, normal | 3.9 s | **14.5 s** | 12% |
  | decode, `-d` deep | 8.9 s | **33.7 s** | 28% |
  | peak RSS | 22 MiB | **20 MiB** | — |
  | encode + render one transmission | 0.28 s | **~2 s** | ~2% |

  **Deep search is affordable** and is the default. Memory is a non-issue:
  20 MiB against 245 MB available, and WSPR stops fldigi so that figure only
  improves.

  **The render figure was nearly misread, and the mistake is worth
  recording.** The benchmark first reported one number for building a test
  window — 26.9 s on the deck — and that read as "the transmit path spends a
  fifth of a slot making its audio". It does not. `wspr.samples` is a
  twelfth of that; the rest was the harness fabricating a noise floor with
  1.37M `random.gauss` calls and packing a WAV with 1.37M `struct.pack`
  calls, neither of which the deck does to beacon. `tools/wspr_bench.py`
  reports the two separately and labels which is which, because a number
  that measures the test instead of the thing is worse than no number.

* **It reads the date and time from the FILENAME**, confirmed by renaming a
  file and watching the reported time change with it: `260616_1200.wav` is
  reported as `260616 1200`, and the same audio as `991231_2358.wav` is
  reported as `991231 2358`. **So the capture filename is load-bearing** and
  the convention `YYMMDD_HHMM.wav` is a requirement, not tidiness.
* Its stdout line, captured and committed as
  `tests/fixtures/wsprd_stdout.txt`:

  ```
  1200  40 -0.0  14.097102  0  KD3CCO FN10 37
  <DecodeFinished>
  ```

  `HHMM`, SNR, DT, frequency in MHz, drift, then the message. The
  `ALL_WSPR.TXT` line carries seventeen fields and is committed beside it.

## 12a. The receive path, proven on the air

2026-10-17 at 0208 UTC, 40 m, real antenna, attenuator off and IPO, DATA-U.
`tools/wspr_rx.py` ran one slot on the deck:

```
level:  -36.8 dBFS  (rms 475, peak 1941)  -> healthy
decoding: wsprd -a /tmp/wsprrx -f 7.038600 /tmp/wsprrx/261017_0208.wav
  8.8 s, 2 stations

0208 -25  0.7   7.040053  0  WW0WWV DN70 30
0208 -26  0.2   7.040115  0  KC0MVF EN13 30
<DecodeFinished>
```

Seven things that proves, none of which could be established from the
laptop:

1. **The exclusive-codec design works.** fldigi stopped, the capture ran,
   fldigi came back active — and the restart is in a `finally`, so a
   Ctrl-C would have done the same.
2. **`plughw:1,0` at 12 kHz captures correctly.** 114 s wrote 2,736,044
   bytes, which is `12000 x 114 x 2 + 44` to the byte.
3. **The filename convention works.** `261017_0208.wav`, and `wsprd`
   reported the slot as `0208`.
4. **The gain is fine** at -36.8 dBFS, settling the question above.
5. **The parser reads real `wsprd` 2.7.0 output from a different
   implementation's signals.** Every earlier fixture was hand-written or
   produced by this project's own encoder; this one came off the air.
6. **The dial frequency is right.** The two decodes sit **1453 Hz and
   1515 Hz above the dial**, inside the 1400-1600 Hz window. That is a third
   independent confirmation of the 40 m figure, after the published list and
   the archived spots — and it is the only one that would have caught a dial
   wrong by a kilohertz.
7. **Decode cost 8.8 s** for a real two-station window, against 14.5 s for
   the synthetic four-signal one. Fewer candidates, less work. Comfortable
   inside a 120 s slot.

Committed as `tests/fixtures/wsprd_stdout_real_40m.txt` and asserted in
`tests/test_wspr.py`.

**What it did not prove.** `rigctld` could not be read during the run —
"radio could not be read (rigctld down, or no CAT)" — but that was the
tool's own fault and not the deck's: `rigctld_client.py` was not among the
files copied to the scratch directory, so the import failed and the bare
`except` reported it as an absent radio. **The rigctld path for setting the
band with fldigi stopped is therefore still unverified**, and it matters,
because §3 makes it the only route to the radio in WSPR mode.

## 13. Open questions

**All three are answered.** Measured on the deck 2026-10-16 — see §12 for
the figures and §2a for the install.

1. ~~How long `wsprd` takes on a Pi 3A+.~~ **14.5 s normal, 33.7 s deep**, of
   a 120 s slot. Deep search fits and is the default.
2. ~~Whether 512 MB holds.~~ **Yes.** 20 MiB peak against 245 MB available,
   with fldigi still up — and WSPR stops fldigi.
3. ~~The wsprnet upload protocol.~~ **Pinned** from WSJT-X's own
   `Network/wsprnet.cpp`; see §9.

**The sound card is settled too**: it is exclusive, fldigi must be stopped,
and `plughw:1,0` at 12 kHz works — §2 and §2b.

What is open now is only what cannot be known before the rest is built:

* ~~the capture gain~~ **Measured with a real antenna, 2026-10-17: -36.8
  dBFS (RMS 475, peak 1941) on 40 m. Healthy, and it decoded.** The gain is
  not a problem.

  The record of how this went wrong is worth keeping. A first reading of
  -59.7 dBFS was written down as "about 35 dB low" and it was not a
  measurement of the gain at all: the radio was on a **dummy load**, so
  almost no RF reached the receiver and -59.7 dBFS is what a receiver with
  nothing to hear correctly produces. With an antenna on a live band the
  same deck, the same codec and the same mixer settings read -36.8 dBFS.
  **A level reading means nothing without knowing what the antenna was
  connected to**, and the mixer had 15 dB in hand that turned out not to be
  wanted.

* **AUTO GAIN CONTROL is on by default and must be off.** Found in the same
  `amixer` output, and unlike the gain this conclusion does **not** depend on
  there being a signal. AGC compresses a constant-envelope 4-FSK signal whose
  amplitude carries no information, pumps with band noise, and corrupts the
  SNR figures `wsprd` reports — and those figures are the measurement WSPR
  exists to produce. A station beaconing with AGC on reports numbers
  describing its own codec rather than the propagation.

  One-time station setup, and it does not survive a reboot without
  `alsactl store`. Where that belongs — the image build, a first-run check,
  or the runbook — is a decision for when the capture path is written.

* whether `aplay` to the same device drives the radio's input as expected,
  which cannot be answered without transmitting.
* whether a **type 2 or type 3** decode off the air parses as the
  hand-written fixtures assume. The 2026-10-17 capture held two stations and
  both sent type 1, so this is still the one untested shape. It needs a
  capture that happens to contain a compound or hashed call.
