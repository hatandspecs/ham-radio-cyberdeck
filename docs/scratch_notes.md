# Scratch notes — pending deploy

**Everything below is tested and uncommitted as of 2026-10-23.** Six rounds
of work are pending and one deploy carries all of them, because the
procedure replaces the whole directory rather than patching it:

- **2026-10-23e — the fourth hardware session.** An aborted over leaving
  its tail for the next one, the interlock scoped to digimodes and WSPR,
  the transcript cleaned out, the tuner's dwell timed from arrival.
- **2026-10-23d — the third hardware session.** The tuner's silent CAT
  failure, the map's performance, the callbook's grid, the backfill.
- **2026-10-23c — the second hardware session.** The map simplified to one
  key, the tuner's dwell made reachable, the bulk selections and locks
  removed.
- **2026-10-23b — the first hardware session.** A crash in the auto tuner,
  a map the panel erased, the WSPR session list.
- **2026-10-22 — the seven features** from `docs/next_steps.md`.
- **2026-10-18 — transmitter safety and a crash fix**, which may or may not
  have reached the deck.

**The 2026-10-23d round is still in the full automated suite as this is
written.** Every file that runs without a pty passes, including the new
`test_backfill.py`; the six pty-driven files have not been re-run against
it.

## Deploy

**The whole `src/` tree, not `src/*.py`.** Four of the files this deploy
needs are not Python:

```
src/bandplans.tsv        the band plan, from 47 CFR §97.301 and §97.305(c)
src/basemap_focus.bin    the two map outlines, 1-bit, zlib, 800x432
src/basemap_global.bin
```

`bandplan.segments()` and `wsprmap.load()` both raise `FileNotFoundError`
when their asset is absent, and neither `_draw_alloc` nor `_build_map`
guards it. The band plan is on the default ring, so a `*.py`-only deploy
takes the panel down on the first `^O` from the boot screen. The image build
copies the directory (`build_deck_image.sh` rsyncs `src/`), so a freshly
flashed card is unaffected; a live deploy is not.

On the laptop:

```bash
cd ~/git_repos/ham-radio-cyberdeck
rsync -av --exclude '__pycache__/' src/ deck@cyberdeck.local:/tmp/deckupd/
```

Ends with a `sent … bytes` summary. `bandplans.tsv` and all three
`basemap_*.bin` must appear in the file list.

On the deck — confirm they arrived:

```bash
ls /tmp/deckupd/bandplans.tsv /tmp/deckupd/basemap_*.bin
ls /tmp/deckupd/*.py | wc -l
```

THREE files, then `32`. `basemap_wide.bin` is gone -- the third map view was
dropped -- so a stale copy on the deck is harmless but no longer read.

Snapshot — this is what the revert restores:

```bash
sudo rm -rf /opt/cyberdeck-restore
sudo mkdir -p /opt/cyberdeck-restore
sudo cp -a /opt/cyberdeck/. /opt/cyberdeck-restore/
ls /opt/cyberdeck-restore/*.py | wc -l
```

A non-zero count, or stop. **`cp -a` of the directory, not `*.py`:** the
snapshot has to carry the data files too, or a revert restores code whose
assets have been overwritten.

Then:

```bash
sudo cp -a /tmp/deckupd/. /opt/cyberdeck/
sudo systemctl restart cyberdeck-ui
sleep 5
systemctl is-active cyberdeck-ui
```

Prints `active`.

Verify the assets landed where the code looks for them — beside the module,
through `os.path.join(HERE, ...)`:

```bash
ls -la /opt/cyberdeck/bandplans.tsv /opt/cyberdeck/basemap_*.bin
```

Three files: the TSV about 3.3 kB, the basemaps 5.8 and 10.1 kB.
**All three changed again on 2026-10-23c.** The basemaps were regenerated
for a two-row overlay, so a deploy that carries the Python and leaves them
behind puts the wrong-sized picture under the screen.

The deck may still hold `basemap_wide.bin` from an earlier deploy. Nothing
reads it; removing it is tidiness, not a step:

```bash
sudo rm -f /opt/cyberdeck/basemap_wide.bin
```

And that they load under the deck's own Python:

```bash
cd /opt/cyberdeck
python3 -c "import bandplan, wsprmap, export, decall, tuner, fbdraw; print(len(bandplan.segments('us_general')), 'segments;', wsprmap.load(view='global').width, 'px map')"
```

Prints `21 segments; 800 px map`. A traceback here means an asset is
missing or truncated — revert. A segment count of 19 means the OLD band plan
is still in place; 29 or 32 means Technician and the reference plans are.

**Do not deploy during a WSPR session.** Staging to `/tmp/deckupd` is safe at
any time, but copying into `/opt/cyberdeck` while the deck runs mixes new
modules into an old process -- several imports happen inside functions -- and
the restart stops WSPR mid-slot.

## Revert to the version running before this deploy

```bash
sudo rm -rf /opt/cyberdeck
sudo mkdir -p /opt/cyberdeck
sudo cp -a /opt/cyberdeck-restore/. /opt/cyberdeck/
sudo systemctl restart cyberdeck-ui
sleep 5
systemctl is-active cyberdeck-ui
```

Prints `active`.

**The `rm -rf` is deliberate.** A plain copy back leaves this deploy's new
modules in place beside the restored ones — `export.py`, `tuner.py`,
`bandplan.py`, `decall.py`, `fbdraw.py`, `wsprmap.py` and the four data
files. Harmless while the restored `cyberdeck.py` never imports them, and
not worth relying on.

Settings are not in `/opt/cyberdeck`. The state file holds `RING_ORDER`,
`LOG_HOTKEY` and `MAP_VIEW` after this deploy; restored code ignores keys it
does not know, so reverting needs nothing further. For a clean one:

```bash
rm -f ~/.local/state/cyberdeck.json
sudo systemctl restart cyberdeck-ui
```

That also resets mode, carrier, colors and the WSPR audio levels to whatever
`cyberdeck.conf` says.

If the panel does not come back either way:

```bash
journalctl -u cyberdeck-ui -n 60 --no-pager
```

## What this carries

### 2026-10-23d — what the third hardware session found

**The auto tuner stepped through and nothing reached the radio.**
`send_cat` and `set_frequency` return False when rigctld cannot be reached
-- they do not raise -- and the sweep ignored what they returned. A run with
no rig behind it counted up on the panel while the VFO never moved. Every
CAT call is checked now and a run that cannot reach the radio fails on the
first command, saying so.

**This does not explain why the radio stopped answering.** The digimode band
change reported `VFO refused` in the same session, and that path goes
through fldigi rather than rigctld. Two different routes failing together
put the cause below both — rigctld, the USB serial link, or the radio. See
the note at the end of this section.

**The map is fast.** Three caches: the staleness check is `os.stat` rather
than a full parse of the spot log, geocoding is separated from projecting so
a view change does not redo it, and the rendered canvas is kept rather than
rebuilt from 345,600 basemap pixels every frame. Measured with 6,000 spots:
247 ms to open, 125 ms to change view, nothing per frame. It was doing the
247 ms five times a second.

**The transcript carries only what went over the air.** Switching the band
plan's license class, saving a ring order, and the export server closing
itself each wrote a line into it. Each now goes to its own screen.

**The callbook's grid reaches the log.** `logform.LOOKUP` has always asked
for a grid and the callbook has always answered with one, but the answer was
written only into the FORM and the general schema has no grid field -- so
every contact logged under it reached the file without one, and the contact
map had nothing to plot. A looked-up field the schema cannot show is kept
aside and written onto the record at commit.

**The logger's danger zone fills in what is already logged.** `F1` `z` `f`
looks up every callsign missing a grid, name or QTH and fills the gaps from
HamQTH. One query per callsign, collected in the background, one atomic
rewrite at the end. It fills gaps and never corrects: a callbook is
evidence, what was typed at the time is testimony.

#### If the radio is still not answering

Neither of the two paths to it is in this deploy's control. On the deck:

```bash
systemctl is-active cyberdeck-rigctld
```

Should print `active`. Then, with the radio on:

```bash
rigctl -m 2 -r 127.0.0.1:4532 f
```

Should print the dial frequency in hertz. An error or a hang is the radio,
the USB lead or rigctld — not the deck software, and the tuner will now say
so rather than pretending to sweep.

### 2026-10-23e — the fourth hardware session

**An aborted over left its tail for the next one.** `start_over` and
`send_more` reach fldigi through `text.add_tx`, which APPENDS, and
`main.abort` drops the carrier without emptying the widget -- so the next
over went on the air behind a fragment of the abandoned one. `Fldigi.abort`
now stops the transmitter and then discards the unsent text, in that order.
**This put wrong text on the air** and is the reason to deploy before the
next session.

**The data-mode interlock belongs to digimodes and WSPR.** `^B` refused to
ARM transmit whenever the radio was not in a data mode, on every screen. The
auto tuner keys the radio to match an antenna and does not care what mode it
is in, so refusing there made `^B` look dead on the one screen whose header
had just been given an INH indicator. Inhibiting is still never refused
anywhere: a safety control that can fail to engage is not one.

**Every refusal is readable from the screen that raised it.** `^B` reaches
every screen and its refusal went to the transcript, which most of them do
not draw.

**The transcript carries only what went over the air.** WiFi, Bluetooth
pairing, the keyboard notice, a failed settings save and the auto tuner's
own progress each went into it. They go to their own screens now. The band
plan gained a message line, which it had not had.

**The tuner's dwell starts when the VFO arrives.** It ran from a fixed 0.3 s
settle, which is a guess: too short and the tuner matches the previous
frequency, too long and every step pays for the worst case. The radio is
read back instead. A rig that cannot be read falls back to the fixed settle;
one that can be read and never arrives is a fault and says so.

### 2026-10-23c — what the second hardware session found

The repairs below held: the map drew, the tuner swept 17 m, the interlock
showed. What this round does is mostly take things away.

**The map is the session's, not the whole log.** It was plotting every
record the deck had ever written and reporting six thousand spots, which
answered no question. A session is the deployment.

**The band toggles are gone**, with the row they needed, and so is the lag
they caused -- they were what made the map re-read and re-project the log on
every frame. Within one session every band answers the same question, and
which band a spot arrived on is a column in the spot list.

**The heard / heard-by filter is gone, because the deck has no heard-by
data.** The spot log holds what the deck decoded and what it sent; who heard
IT is on wsprnet. One of that filter's two positions was always empty.

The map screen is now `v` and `Esc`, with the summary on the top row and the
keys on the bottom row. **`Esc back` is no longer clipped to `Esc bac`.**

**Spots are `+` in the bright color; this station is an `×`.** The `×` used
to mean a direction and read as the fainter marker -- a diagonal cross puts
no pixel on the row or column through its center. Home was white, which is
not one of the phosphor colors.

**The right-edge stripe is wiped.** The console is 66 columns of a 12-pixel
font -- 792 of the panel's 800 -- so the last 8 pixels belong to no cell and
`clearok` cannot reach them. Leaving a map blanks the framebuffer first.

**The contact map shows the current activity**, not every contact in the
log, and names it on the top row so the two maps cannot be mistaken for each
other.

**The third map view is gone.** `wide` was `global` plus twelve degrees at
each pole.

**The tuner's bulk selections and locks are gone.** `Space` is the only way
to pick a segment. **`+` and `-` step the dwell** in half seconds between
0.5 and 5.0 -- the same keys the squelch uses on the tuning screen -- and
the footer carries the current value. It was bound to `d` and advertised
nowhere.

### 2026-10-23b — what the first hardware session found

**The auto tuner crashed the deck.** `_start_tuner_sweep` passed `self.rig`,
which does not exist -- every other call site uses `self._log_rig()`. Enter
on that screen raised `AttributeError`, systemd restarted the terminal, and
the symptom on the panel was a pause, a flash, and the tuner screen
"escaping" with the radio untouched. **No test called that method**: the
sweep engine was tested against a fake rig and the screen was tested on its
own, and nothing exercised the wire between them.

**The maps were erased by curses one frame after being drawn.** `draw` opens
with `scr.erase()`, so a picture written before the refresh is wiped by it;
what survived were the cells curses happened to think unchanged, which read
as a map squeezed into the top of the screen with fragments left behind on
the way out. Three changes: the blit runs after `scr.refresh()`, it starts
below the two text rows so curses never has a cell overwritten, and leaving
a map sets `clearok` so the next frame repaints every cell and takes the
residue with it.

**The basemaps are regenerated at 800x432** -- the panel less its two
24-pixel text rows -- so the picture and the text no longer share pixels.
`fbdraw` also reads the framebuffer's `stride` now rather than assuming
`width * bytes_per_pixel`, because a padded scanline would shear the image.

**The auto tuner shows the interlock.** `^B` always worked there -- it is
handled before any screen's own keys -- but the header had no status field,
so nothing changed on screen and the key read as dead.

**WSPR sessions can be resumed.** `F2` opens a session list rather than the
name editor, with the contact log's own keys: `Enter` resume, `n` new, `r`
rename, `d` forget, `Esc` back. A session and a logger activity are the same
idea, so they get the same keys; it is simpler by one thing, because a
session has no schema to choose. The spot list also loads the current
session's spots on entering the area -- the deck came up on `general`,
reported 5,992 heard, and drew an empty list, because `wspr_spots` only ever
held what that RUN had decoded.

**`WSPR_FORGOTTEN` is read for the first time.** The danger zone has been
writing it and no screen honoured it, so "forget all sessions" set a value
that changed nothing.

**Both maps are on `F5`.** It was `m` on the WSPR screen and `F5` on the log
screen -- two keys for one idea.

**The contact map counts contacts.** `SpotMap.summary` took a noun; a
contact map reporting "11 spots" described the wrong thing.

**The band plan is US General and US Extra only**, and every band is split at
its §97.305(c) phone edge. Technician and the four stray reference plans are
gone. Corrections along the way: 17 m and 12 m were "All Modes" across the
whole band for General, which is true of the privilege and false of the
emissions; and General's 80/40/20/15 m rows cited §97.301(b), the Amateur
Extra paragraph, where General is (d).

### 2026-10-22 — seven features from `docs/next_steps.md`

The ring is five areas and in an order the operator sets.

| | Feature | Where |
|---|---|---|
| 1 | Ring order editor | deck & rig `F1` `4` |
| 2 | Band allocation tables | a fifth ring area |
| 3 | FTX-1 auto tuner | deck & rig `F1` `3` |
| 4 | `^G` logs the station heard | digimodes, `F1` `5` picks what it does |
| 5 | WSPR map | `m` on the WSPR screen |
| 6 | Contact map | `F5` on the log screen |
| 7 | Export to a phone | deck & rig `F1` `5` |

New settings, all with defaults, so `cyberdeck.conf` needs no edit:
`RING_ORDER`, `LICENSE_CLASS`, `TUNER_DWELL_S`, `MAP_VIEW`, `LOG_HOTKEY`,
`EXPORT_DIR`, `EXPORT_PORT`, `EXPORT_IDLE_MIN`, `WSPR_FORGOTTEN`.
(`TUNER_LOCKED` was added in that round and removed in 2026-10-23c with the
locks it configured; a stale value in the state file is ignored.)

**The export server opens a port on the WiFi address**, for five minutes per
export, at a path with a fresh four-character token. It serves five named
files by POSITION — the request never carries a filename — and
`cyberdeck.secrets` is not among them.

**The auto tuner keys the transmitter** for as long as the selected segments
take, about four minutes for five segments at the default dwell. The radio
cannot report that an external tuner has finished, so each frequency gets a
fixed dwell and too short a dwell fails silently.

### Check after deploying, riskiest last

Stop at the first that misbehaves and revert.

1. **`^O` once from the boot screen reaches BAND PLAN.** The check that
   catches a `*.py`-only deploy. `Space` cycles General and Extra, and only
   those two. Every band reads `(CW/Data)` or `(Phone)` except 160 m
   (All Modes) and 30 m (CW/Data only).
2. **`^O` again reaches WSPR; `F5` draws the map.**
   - The summary row at the top names the session; the key row at the
     bottom reads `v view   Esc back`, not `Esc bac`.
   - The picture fills everything between them. **Fragments, a squeezed
     picture, or a stripe left on the right edge after `Esc` mean the
     repair did not take.**
   - Spots are `+`; this station is an `×` in the same color as the
     coastline's brighter shade, not white.
   - `v` cycles two views, the USA and the world. There is no third.
   - **`F5` leaves the map as well as opening it**, and so does `Esc`.
   - The count is this SESSION's spots, not every spot the deck has.
3. **`F2` on the WSPR screen opens the session list.** `*` marks the one in
   use. `Enter` on another resumes it and the spot list fills with that
   run's spots. `n` new, `r` rename, `d` forget after a confirmation.
4. **`F5` on the log screen** draws the contact map, named for the current
   activity, and the line says "contacts".
5. `F1` `4` from deck & rig opens the ring editor. `Esc` cancels.
6. `F1` `5` opens the export page.
7. **`F1` `z` `f` from the log — fill in missing details.** It says how
   many callsigns it would look up, asks first, and runs in the background.
   Nothing already in the log changes. Afterwards `F5` should show contacts
   on the map that were not there before.
8. **The transcript carries only on-air traffic.** Cycling the band plan's
   class, saving a ring order, joining WiFi, pairing a keyboard, and the
   auto tuner starting and stopping should each leave it untouched and
   report on their own screen.
9. **Abort an over partway, then send a different one.** Only the second
   message goes out. A fragment of the first ahead of it is the fault this
   round fixed, and it put wrong text on the air.
10. **`^B` on the auto tuner arms transmit** with the radio in USB. On the
    digimodes and WSPR screens it still refuses until the radio is in a
    data mode, and says so on that screen rather than in the transcript.
11. **`F1` `3` opens the auto tuner.**
   - The header carries `INH` or `INH off`, and `^B` flips it without
     leaving the screen.
   - The footer reads `+ - dwell 5s`. `+` and `-` step it by half a second
     between 0.5 and 5.0.
   - `Space` is the only way to pick a segment. There is no `a`, `p`, `c`,
     `i`, `n` or `l`.
   - With the interlock off and rigctld answering, `Enter` sweeps: the VFO
     moves, the progress line counts, `^X` stops it. **One segment for the
     first run.**
   - The dwell starts when the radio reports itself on the new frequency,
     not a fixed moment after the command. A radio that accepts the command
     and never moves fails the run rather than tuning on the old frequency.
   - **If the radio is not answering it now fails immediately** with "no rig
     control — is rigctld running?" rather than counting through a sweep
     that reaches nothing. That message means the rig, not the deck: see the
     check at the end of the 2026-10-23d section.

### 2026-10-18 — transmitter safety, a crash fix, three features

**Transmitter safety — the reason to deploy before the next session.**

- **Killed `arecord`/`aplay` children are waited for** before the codec is
  handed back. `kill()` returns while the process still holds the card, and
  fldigi was being restarted into that window; fldigi opens the codec once at
  startup and never retries, so it came up deaf. A deaf fldigi keys the radio
  and never completes the over -- that is the stuck PTT of 2026-10-17.
- **The unkey is verified.** It asks, reads PTT back, and asks again up to
  four times, reporting "the radio is still keyed after 4 attempts" instead of
  returning silently. It previously fired once and discarded the result, so an
  unreachable rigctld left the radio keyed with nothing noticing.
- **Shutdown returns WSPR's borrowings** -- fldigi, the capture gain, the AGC,
  and any band left in DATA-U. A restart mid-session used to leave all four.
- **`_wspr_give_audio` checks the card is free** before starting fldigi.

**The crash fix.**

- A NUL byte in fldigi's RX text crashed the deck: `curses.addstr` raises
  `ValueError` for an embedded NUL, not `curses.error`, so `_put` did not
  catch it -- and `_put` is what every screen draws through. Seen 2026-10-18
  while logging SSB, with the decoder parked on the NULL modem. Control
  characters are now stripped at ingest, and `_put` survives one from any
  source.

**Features.**

- **Color order is a brightness ramp**: Hal, Deckard, Matrix, Tron, Ripley.
  `F4` walks it, the Display menu lists it, `1`-`5` match. The default is
  still Matrix -- that is set separately now, so reordering cannot move it.
- **Session ToT reaches 12 hours**: 0, 15, 30, 60, 120, 240, 480, 720 min.
  The menu prints `12 h` rather than `720 min`, and the screen shows
  `session 11h 58m left` above an hour, `m:ss` below it.
- **The in-session no-keyboard watcher is gone.** The screen is raised at
  power-on only, which is the case an operator cannot answer any other way --
  the deck switched on before the keyboard, or without one. A keyboard that
  stops working mid-session announces itself by nothing happening, and the
  watcher's cost was a screen that could interrupt a WSPR session and then
  hand the operator to a dead digimodes screen.

### Check after deploying the 2026-10-18 work

- `F4` walks dark to bright and the deck still boots into Matrix.
- `F1` then `o` cycles the ToT up to `12 h`.
- WSPR start, stop, and leave the area: fldigi should come back and the
  digimodes should hear. That is the path that broke.
- `^B` toggles the inhibit from several screens; `Tab` does nothing to it.
- Switch the deck on with the keyboard off: the NO KEYBOARD screen should
  appear, name the bonded keyboard and offer pairing. Switch the keyboard on
  and press any key; it should clear. Switching a keyboard off *during* a
  session should now do nothing at all, which is the point.

## Pulling the WSPR spot log off the deck

What the deck itself decoded, as opposed to what wsprnet shows. The two
differ: wsprnet holds only what was uploaded, and the deck's own log holds
every decode including ones that failed to upload.

On the deck — the log is append-only `key=value` text, one line per spot:

```bash
ls -la ~/.local/share/cyberdeck/wspr.log
wc -l ~/.local/share/cyberdeck/wspr.log
tail -3 ~/.local/share/cyberdeck/wspr.log
```

From the laptop:

```bash
cd ~/git_repos/ham-radio-cyberdeck
mkdir -p ~/Downloads/deck-exports
rsync -av deck@cyberdeck.local:~/.local/share/cyberdeck/wspr.log ~/Downloads/deck-exports/
wc -l ~/Downloads/deck-exports/wspr.log
```

Read it with the project's own parser rather than by eye -- `kind=rx` is a
station heard, `kind=tx` a beacon sent:

```bash
cd ~/git_repos/ham-radio-cyberdeck
python3 -c "
import sys; sys.path.insert(0, 'src')
import wsprlog, collections, os
recs = wsprlog.read(os.path.expanduser('~/Downloads/deck-exports/wspr.log'))
rx = [r for r in recs if r.get('kind') == 'rx']
tx = [r for r in recs if r.get('kind') == 'tx']
print(f'{len(recs)} records: {len(rx)} heard, {len(tx)} sent')
print('unique stations heard:', len({r.get(\"call\") for r in rx}))
by_band = collections.Counter(r.get('band', '?') for r in rx)
for band, n in sorted(by_band.items()):
    print(f'  {band:>6}  {n}')
print('sessions:', sorted({r.get(\"activity\", \"\") for r in recs}))
"
```

**If the counts look far short of wsprnet**, the uploader was not armed --
it needs all three of WSPR running, the upload toggle on, and WiFi.

## Pulling the contact log off and uploading to QRZ

The deck writes an append-only `key=value` log, and exports ADIF beside it.
**Export first, on the deck** -- the `.adi` is only written when asked:

```
F1  then  a      export the whole log      -> qso.adi
F1  then  x      export this session only  -> qso-<activity>.adi
```

The deck prints where it wrote. Then confirm and copy it off:

```bash
ls -la ~/.local/share/cyberdeck/*.adi
head -5 ~/.local/share/cyberdeck/qso.adi
```

From the laptop:

```bash
mkdir -p ~/Downloads/deck-exports
rsync -av deck@cyberdeck.local:'~/.local/share/cyberdeck/*.adi' ~/Downloads/deck-exports/
grep -c '<EOR>' ~/Downloads/deck-exports/qso.adi      # one per contact
```

That count is the number of records QRZ should report importing. Check it
before uploading and again after.

**Upload at qrz.com:** Logbook -> Settings -> **Import ADIF**, choose the
file, and confirm the count matches. QRZ will not import a contact without
a band and mode, and it rejects a record whose date is in the future -- if
the deck's clock was wrong when something was logged, that record is the one
it will refuse.

**Pull the raw log too**, not only the export. The ADIF is lossy: it carries
what ADIF has fields for, and the deck records more than that.

```bash
rsync -av deck@cyberdeck.local:~/.local/share/cyberdeck/qso.log ~/Downloads/deck-exports/
```

**Nothing here deletes anything on the deck.** `rsync` copies; the danger
zone in the logging menu is the only thing that removes records, and it asks
first.

## Known open, not in this deploy

- **A missing asset crashes the panel rather than saying so.**
  `_draw_alloc` calls `bandplan.segments()` and `_build_map` calls
  `wsprmap.load()` with no guard, so an absent or corrupt `bandplans.tsv` or
  `basemap_*.bin` raises `FileNotFoundError` inside a draw path. The deploy
  procedure above avoids it, and a card that loses a file in the field would
  not. Both screens should report the missing asset and stay up.
- **Nothing from the 2026-10-22 work has run on hardware.** The framebuffer
  writes, the `AC103;` tuner sequence and the export server's bind to the
  WiFi address are the three things the 3912 off-deck checks cannot reach.

- **The paired screen says "Try typing on it" and cannot show what you type.**
  There is no echo field, and `_handle_pair` does not branch on state, so the
  keys are still live pairing controls: a digit or `Enter` re-runs `Pair` on
  the bonded device and BlueZ answers `Already Exists`, and **`f` removes the
  bond that was just made**. Separately, a failed `_trust()` sets an error but
  leaves the state at PAIRED, so the screen claims `PAIRED, AND TRUSTED` and
  then reports it could not set trusted. Diagnosed 2026-10-18, not fixed.

- **`set_mode` is still unverified against the radio.** Selecting a band sets
  DATA-U and reports `was USB -- set to PKTUSB`; if the FTX-1 does not accept
  `M PKTUSB 0` the message appears and the radio does not move.
- **A type 2 or type 3 WSPR decode** (compound and hashed calls) still rests
  on hand-written fixtures. The parser handles them; none has been
  transmitted.
- **The logger article wants a field photo** -- the deck logging on a picnic
  table. The screens in it are generated, which is accurate but is not a
  photograph of the thing working.
- Both cyberdeck articles are `published: false`.
