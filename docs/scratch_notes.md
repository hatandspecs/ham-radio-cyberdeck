# Scratch notes — pending deploy

**Everything below is tested and uncommitted as of 2026-10-23.** Two rounds
of work are pending: the seven features from `docs/next_steps.md`, built
2026-10-22, and the transmitter-safety and crash fixes from 2026-10-18 that
may or may not have reached the deck. One deploy carries both, because the
procedure replaces the whole directory rather than patching it.

**3912 checks across 52 files pass off the deck.** Nothing here has run on
the panel. The framebuffer writes, the CAT tuner sequence and the WiFi bind
are the three things the tests cannot reach.

## Deploy

**The whole `src/` tree, not `src/*.py`.** Four of the files this deploy
needs are not Python:

```
src/bandplans.tsv        the band plan, from 47 CFR §97.301
src/basemap_focus.bin    the three map outlines, 1-bit, zlib
src/basemap_global.bin
src/basemap_wide.bin
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

Four files, then `32`. Anything missing, stop.

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

Four files: the TSV about 10.8 kB, the basemaps 6.4, 11.2 and 10.9 kB.

And that they load under the deck's own Python:

```bash
cd /opt/cyberdeck
python3 -c "import bandplan, wsprmap, export, decall, tuner, fbdraw; print(len(bandplan.segments('us_general')), 'segments;', wsprmap.load(view='global').width, 'px map')"
```

Prints `19 segments; 800 px map`. A traceback here means an asset is
missing or truncated — revert.

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
`RING_ORDER`, `LICENSE_CLASS`, `TUNER_LOCKED`, `TUNER_DWELL_S`, `MAP_VIEW`,
`LOG_HOTKEY`, `EXPORT_DIR`, `EXPORT_PORT`, `EXPORT_IDLE_MIN`.

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

1. `^O` once from the boot screen reaches **BAND PLAN**. This is the check
   that catches a `*.py`-only deploy. `Space` cycles the license class.
2. `^O` again reaches WSPR; `m` draws the map. `v` cycles the three views,
   `1`-`0` toggle bands, `Esc` returns. A black screen carrying only the two
   text rows means `fbdraw` could not open `/dev/fb0`.
3. `F1` `4` from deck & rig opens the ring editor. `Esc` cancels without
   saving; nothing is written until `Enter`.
4. `F1` `5` opens the export page. The address goes into a phone browser,
   one file downloads, `Esc` takes the server down.
5. `F1` `3` opens the auto tuner. **Transmit stays inhibited (`^B`) for the
   first look**, and the first real run gets one segment, not a band plan.

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
