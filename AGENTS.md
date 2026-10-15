# AGENTS.md — keyboard-to-keyboard cyberdeck

A single-purpose HF text terminal: a Raspberry Pi 3A+ behind a 5-inch DSI panel,
66x20 characters, driving fldigi headless over XML-RPC. It also runs on an
ordinary laptop — start fldigi, run `./src/cyberdeck.py`, nothing else needed.

## Start here

| Read | For |
|---|---|
| `README.md` | What it is, what each file does, the test table |
| `docs/design_doc.md` | Numbered FR/NFR with honest status |
| `docs/` | Runbook and operating tutorial |
| `docs/screens/` | Rendered screenshots of every screen |
| `docs/logging_tutorial.md` | Operating the contact log, with screenshots |
| `docs/logger_branch_deploy.md` | **Deploying this branch, and the recovery sequence back to `main`.** Read before touching the deck |
| `slides/cyberdeck-talk.md` | The talk, as Marp markdown; `slides/diagrams/` holds the mermaid sources |

## Things that cost a lot to rediscover

- **Run the laptop test rig in foot: `./deck --foot`.** That is what the
  sessions that worked used. The rig is the real `src/cyberdeck.py` in a pty at
  the panel's 66x20, with a pretend fldigi and rigctld behind it, and nothing it
  writes touches the real log, saved state or `activities.conf`. The terminal
  matters: `--foot` sets `Terminus:style=Bold:pixelsize=24`, which is not an
  approximation but the deck's own font — the panel runs
  `Uni3-TerminusBold24x12`, Terminus Bold 24px on a 12x24 cell, and 66x20 of
  those is 792x480, the panel's resolution. `pad=0x0` removes the border. Run
  in the editor's own terminal instead and the window is whatever size that pane
  is, in a desktop font, so glyph width and layout are both wrong — which is the
  only thing the rig is for. An earlier attempt in a small, glitchy window was
  unreadable and the glitching turned out to be `os.write` short writes.
- **`./deck --console` prints instructions and MUST NOT launch a console.** It
  once ran `sudo openvt -s -w -- runuser -u "$USER" -- ...`, which killed the
  graphical session, VS Code and the agent session with it: `runuser` opens a PAM
  session and `pam_systemd` registering a logind session on a VT while a
  graphical seat is active takes down the seat. That is the second console this
  project has lost to a program claiming a tty it did not own. A real console is
  still the best place to judge glyphs — log into one by hand, Ctrl+Alt+F3.
- **Do not write signal processing.** fldigi does all of it; this program is a
  terminal that drives fldigi over XML-RPC on the loopback interface. A better
  PSK31 demodulator is not the project.
- **Run tests with `tools/run_tests.sh`, not pytest.** Each test file is a
  standalone script that prints its own checks and ends with `ALL PASS`.
  Invoking pytest on them wastes minutes and ends in `INTERNALERROR`.
- **fldigi must be running for the tests** — four of them drive the real
  program through a pseudo-terminal and read the screen back. No radio is
  needed, but a modem is.
- **The pty tests flake, roughly one check per full run.** They drive the one
  live fldigi on port 7362 with fixed `settle=` delays, so a slipped timing
  shows up as a single failed check somewhere in `test_menu_arrows`,
  `test_menu_nav`, `test_screen*` or `test_state` — a different one each run
  (observed: `the transcript is emptied`, `fldigi is now on RTTY`, `the
  restarted deck comes back on that carrier`). Re-run that file on its own
  before believing it: they pass in isolation. Never run two test files at
  once, for the same reason — they share the modem and the carrier.
- **The log is no longer append-only, and is still never written in place**
  (2026-10-14). `qsolog.update` corrects one field of a logged contact by
  replacing the file WHOLE: temp file, `fsync`, `os.replace`, then an `fsync`
  of the DIRECTORY, because the rename is metadata and is not durable without
  it. A pulled plug leaves the old log or the new one, never part of one. The
  contact is found by its timestamp and guarded by its callsign, never by a
  line number — the file is hand-editable over SSH, so an index that shifted
  would rewrite somebody else's contact, and a guard that does not match is a
  refusal rather than a guess. `when` is the only field that cannot be edited;
  the callsign can, and is the reason the feature exists. `docs/qso_log_design.md`
  §7e carries the reversal and §12 records the decision as closed.
- **On the log screen the arrows pick a contact, not a form field.** Tab and
  Shift-Tab move between fields and always did; the arrows were a redundant
  second way to do that, which is why reading the log back had no keys at all.
  Three rules keep the fast path intact, and breaking any of them is a
  regression: Esc deselects before it leaves the screen, typing always goes to
  the form and drops the selection (so a nudged arrow cannot eat the first
  letter of a callsign), and the footer says `Enter open` instead of
  `Enter log` exactly when Enter has changed meaning. `LOG_LINES` is 1, 2 or 3
  rows per contact, and a contact always takes exactly that many rows — blank
  ones included — because a row height that varied with how much was filled in
  could not be walked predictably.
- **Logger messages do not go to the transcript.** `session.note` writes into
  the keyboard-to-keyboard transcript, which is a record of what was said on
  the air. Twenty logger notes were filling it with lines nobody ever sent, and
  they were invisible where they mattered: the log screen draws `log_message`,
  not the transcript. Use `self._log_note()` from anything in the logger, which
  routes to the log screen and to the picker or activities list when that is
  where the message was raised.
- **A field can be stored, exported, and still invisible.** A log field needs
  an entry in THREE places: `activities.ENTRY_FIELDS` to be selectable,
  `qsolog._FIELD_ORDER` to be written to the line, and `qsolog._ADIF_FIELDS` to
  survive an export. `comment`, `my_rig` and `my_antenna` had the last two for
  months and not the first, so every contact carried them and no activity could
  put them on the form. `field_choices()` derives from `ENTRY_FIELDS`; it used
  to keep its own copy, and seven fields added to one were selectable nowhere.
- **`ENTRY_FIELDS` order IS the selection screen, and it pages.** 28 fields,
  `render.FIELDS_PER_PAGE` = 14, two pages. Page one is general and POTA
  logging — which is also QRZ's own QSO record, minus the six fields QRZ wants
  that the deck fills in and never offers (call, date, UTC, band, frequency,
  mode). Page two is the contest exchange, the zones and the non-POTA programs.
  Inserting a field in the middle silently pushes the last of page one onto page
  two, where nobody will find it, so `tests/test_activities.py` asserts both
  pages as ordered lists.
- **Never hardcode a row key or a picker number in a test.** Both move when
  `ENTRY_FIELDS` is reordered or a type is added. `type_key()` and
  `field_keys()` in `tests/test_log_panel.py` derive them. Hardcoding `"2"` once
  deleted the wrong activity type and the test passed; hardcoding `"6"` for
  `name` later toggled `grid`. The keys are per-PAGE positions, not positions in
  the whole list.
- **`session.note` is invisible on the full-screen pickers.** SELECT FIELDS,
  ORDER FIELDS, the activities list and a confirmation all cover the transcript,
  so a refusal written only with `note()` reads as a key that did nothing. Those
  screens take a `message` / `footer`; use it as well. This bit the
  "choose at least one field" refusal, which an activity type started from
  scratch hits on its very first Enter.
- **This station's own reference is asked once per activity, not per contact.**
  `my_park` is a sticky own-side field, not in `ENTRY_FIELDS`. Naming a new
  activity CLEARS it and the type picker that follows asks for it again when the
  type has a `park` field — carrying last week's park onto today's contacts
  without saying so is worse than a question. Their park (`park`, exported as
  `SIG`/`SIG_INFO`/`POTA_REF`) and this station's (`my_park`, the `MY_` forms)
  are separate fields because a park-to-park carries both.
- **Saving an activity type over a name that exists asks first.**
  `activities.save` replaces that section on purpose — revising a definition is
  what saving twice under one name means — but it did it silently, so a
  collision destroyed the earlier type with no sign of it.
- **F4 cycles the color scheme from every screen**, handled before the menu and
  screen dispatch in `handle()` and after the editor. It was bound once, on the
  fallthrough below the screen handlers, so it worked on the conversation and
  was a dead key everywhere else. Only a confirmation and the no-keyboard notice
  keep it out, because on those a keystroke already means something.
- **Card-durability settings live in two places and neither is obvious.**
  `rootflags=data=journal` has to be on the kernel command line, because `data=`
  cannot be changed by the remount `fstab` drives. The swap writeback file is
  disabled by `[Main]\nMechanism=zram` in `/etc/rpi/swap.conf.d/` — stock Pi OS
  defaults to `zram+file` and keeps a `/var/swap` file on the card that
  `swapon --show` does not reveal; check `/sys/block/zram0/backing_dev` instead.
  Both are written by `tools/build_deck_image.sh`.
- **The QSO logger is general-purpose, and that is a constraint.** The log is
  a plain list of contacts; nothing above `src/qsolog.py` knows what kind of
  operating produced one. POTA is a **mode**, off by default, that adds two
  fields otherwise omitted from a record entirely; `SOTA`/`WWFF` would be a
  lookup-table entry rather than a design change. Hunting works in either
  mode, because a park reference is recognized by shape. Do not let the
  framing drift back toward POTA as the organizing principle — it already did
  once, and `docs/qso_log_design.md` §6a records the corrected shape.
- **POTA is an activity, not a setting. Do not add the toggle back.** There
  was briefly both a `POTA` config key and `ACTIVITY = POTA`; the key is gone
  (2026-10-11) along with `log_screen(pota=)` and the POTA menu item. Two
  controls meaning "show the park fields" drift apart. The menu asks the
  activity whether it has a `park` field rather than checking for the name
  "POTA", so a WWFF or IOTA activity gets the reference setting for free.
- **Three built-in activities, and only three** — GENERAL, POTA, CONTEST.
  SOTA, WWFF, Field Day, Sweepstakes and the state QSO parties are examples in
  `activities.conf.example` to copy with `like =`. A built-in nobody uses is a
  line in the picker to scroll past forever.
- **Rig, antenna and power go on every contact, from the Station menu.** `RIG`
  and `ANTENNA` are station fields (`MY_RIG`, `MY_ANTENNA`), not logger
  settings — a second place to set them is a second place for them to be
  wrong. Power prefers a CAT reading over configured `TX_POWER`.
- **hamlib reports power as 0.0-1.0, not watts, and the ceiling is not a
  property of the radio.** `l RFPOWER` gives the position of the power
  control. Turning it into watts needs a ceiling, and this station has three
  for one radio: 6 W on the internal battery, 10 W on external power, 100 W
  with the SPA-1 amplifier. That rules out hamlib's `power2mW`, whose power
  curve is static per backend and would log a full-scale control position as
  100 W on a 6 W setup — a sixteen-fold error, silently. Hence
  `TX_POWER_MAX`: one setting, scaled by the position, working on any rig.
- **Keep the rig-specific power read behind the generic one.**
  `rigctld_client.power_control()` reads the FTX-1's `PC` command, which
  answers in watts and names the back end (CAT reference p. 21). It is an
  optimization, not a dependency: other radios return `(0, "")` and the
  generic path carries on, and the whole block is deletable. It does not
  distinguish the 6 W battery case from the 10 W external one — both are
  `P1=1` — which is a further reason the setting is primary.
- **The power chain is VERIFIED against the radio (2026-10-11).** Measured on
  the deck with the FTX-1 on external power, front panel set to 6 W:

    | Command | Reply |
    |---|---|
    | `m` | `PKTUSB\n3000` |
    | `l RFPOWER` | `0.6` |
    | `w PC;` | `PC1006;\x00` |
    | `power2mW 1.0 14074000 USB` | `RPRT -1` |

  at 10 W: `1` and `PC1010;`; at the 0.5 W minimum: `0.05` and `PC10.5;`.

  Three points, all agreeing, and **linear from zero** — not from the rig's
  5 W floor, which would have put 6 W at 0.2 rather than 0.6. So
  `watts = level × TX_POWER_MAX` is exact, not an approximation. RFPOWER
  answers `1`, not `1.0`; the parse has to tolerate either.
- **The CAT manual is WRONG about `PC`, and wrong in the QRP direction.** It
  documents P2 as three digits (`005 - 010`). At the field head's 0.5 W
  minimum the radio sends `PC10.5;` — a decimal. A `\d{3}` pattern simply
  fails to match there and reports "no answer", so full power reads correctly
  and QRP does not. Never round transmit power to `int` either: `max(1, ...)`
  turned every sub-watt contact into 1 W. ADIF's `TX_PWR` is a Number, so
  `0.5` is valid and is what gets written.
- **`power2mW` is not implemented in the FTX-1 backend** — it answers
  `RPRT -1`. The hamlib-curve fallback is dead on this radio, which is why
  `TX_POWER_MAX` has to be the primary path rather than a convenience.
- **`w` returns replies, with a trailing NUL.** `w FA;` gives
  `'FA146850000;\x00'`. `str.strip()` does not remove a NUL — strip it by
  name. The field parsers use `search` and would have survived it silently.
- **The rig reports `PKTUSB` under fldigi, which is NOT an ADIF mode.**
  Writing it into MODE produces a record LoTW will not take. `resolve_mode`
  treats a rig data mode as *evidence* that fldigi's answer is the right one,
  never as the answer itself. This also settles the old §6 question: the FTX-1
  does report a data mode, so `auto` works without needing `fldigi_active`.
- **`rigctl -m 2` style checks must set `LD_LIBRARY_PATH=/usr/local/lib`.**
  Running `/usr/local/bin/rigctld --version` bare reports **4.6.2** — the
  packaged library — while the running service has `libhamlib.so.4.0.7` from
  /usr/local mapped and is really **4.7.2**. Check `/proc/<pid>/maps`, not
  `--version`, when the answer matters.
- **`rigctld_client` exposes `Rigctld`, not `RigctldClient`.** `tools/qso.py`
  had the wrong name inside a broad `except`, so every log line said "rigctld
  unreachable" on a machine where the radio was simply never asked. Same
  failure shape as the fldigi one below — check the names before the network.
- **Backfill never rewrites the log.** `qso.py backfill` looks calls up and
  stores them in the callbook *cache*; `list` and `adif` merge from it. The
  log stays append-only and byte-for-byte what was logged, which is the
  property that makes it safe across a power pull.
- **An activity's field list IS the log's entry grammar.** `599` is a valid
  signal report *and* a valid serial number, and nothing about the token says
  which — so a positional parser cannot work without knowing the activity.
  `src/activities.py` holds the field list; the operator chose the activity
  before they started typing, so the ambiguity is resolved once instead of
  guessed at per contact. Do not add a heuristic that tries to tell a report
  from a serial; that is the problem this design exists to avoid.
- **A number field is consumed only if the token is a number.** If a missed
  serial let the exchange slide into the numeric slot, every field after it
  would shift and the log would be quietly wrong rather than visibly wrong.
  Pinned in `test_activities.py`.
- **Serials come from the log, never a counter file.** `qsolog.next_serial`
  takes the highest `serial_tx` for that activity and adds one. A counter is a
  second source of truth that can disagree with the log, and its failure —
  a serial sent twice, twenty skipped — is invisible until the log is checked.
- **There are three callbooks and the order is about the grid.** callook.info
  (US, no account) then HamQTH (worldwide, free) then QRZ XML (worldwide,
  free) — QRZ last because a non-subscriber usually does **not** get `<grid>`,
  which is the field most worth having. The chain fills gaps per field rather
  than stopping at the first answer: callook has this station's own name and
  town but an empty `gridsquare` (the FCC record was never geocoded) while
  HamQTH has `FN10`, so stopping early silently dropped the grid.
- **QRZ has two unrelated APIs.** `xmldata.qrz.com` is callsign lookup
  (`QRZ_USER`/`QRZ_PASSWORD`, works as a non-subscriber minus the grid);
  `logbook.qrz.com/api` is QSO upload (`QRZ_API_KEY`, needs a paid
  subscription and currently returns AUTH). Different credential, different
  subscription. Do not conflate them.
- **URL-encode credentials.** This station's QRZ password contains `&`; raw in
  a query string it truncates the password and the server reports an incorrect
  password, which looks like a wrong credential rather than a client bug.
- **HamQTH's username is the callsign, not the email address.** Verified
  against the live API 2026-10-11: the email is refused with "Wrong user name
  or password", which looks exactly like a wrong password. Also `nick`, not
  `name`: HamQTH's `name` is private and usually empty, `nick` is the on-air
  name. And retry only on session expiry — "Callsign not found" is an
  `<error>` too, so retrying on any error doubles the traffic for dead ends.
- **`cyberdeck.conf` refuses credentials outright.** Anything in
  `config.SECRET_KEYS` raises if it appears there, rather than working quietly.
  That file is the one meant to be safe to hand over; a credential that works
  from it is a credential that travels. Secrets go in `cyberdeck.secrets`
  (gitignored, mode 600).
- **tqsl hangs rather than failing.** With no callsign certificate in the
  keystore, `tqsl --batch --nodate --quiet <log>` blocks forever — no error, no
  exit — and unsetting `DISPLAY`/`WAYLAND_DISPLAY` does not change it. With a
  display it opens a GUI window despite `--batch`. `tqsl -v` prints the version
  and exits **255**, not 0, so a zero-status check reports tqsl as missing on a
  machine that has it. Every invocation in `src/lotw.py` therefore carries a
  hard timeout, and a timeout is classified as a missing certificate rather
  than a network problem. Measured on 2.8.6, 2026-10-10; do not re-derive it.
- **LoTW is free; QRZ is not.** LoTW needs a callsign certificate, which costs
  nothing. The QRZ logbook API needs a paid subscription for every call,
  including a read-only one. These get conflated; they are unrelated.
- **`fldigi_client` exposes `Fldigi`, `connected` as an attribute, and
  `modem()`.** Not `FldigiClient`, not `connected()`, not `modem_name()`.
  `tools/qso.py` had all three wrong and a bare `except Exception: pass` hid
  it, so the mode silently defaulted instead of being read. If a block that
  talks to fldigi seems to do nothing, check the names before the network.
- **A root-menu entry and its key handler go in together.** `("8", "Logging")`
  was added to `menus.ROOT` ahead of any handler in `cyberdeck.py`, which made
  a discoverable menu line whose Enter did nothing — strictly worse than an
  absent line, since being discoverable is the line's only job. It is commented
  out in `ROOT` until the handler lands. `test_menu_arrows.py` is what catches
  this, because Up-then-Enter from the first item lands on whatever is last.
- **Render the slides from the repository root, not from `slides/`.** Four
  slides pull screenshots from `../docs/screens/`, which is outside the mount
  if the container is given `slides/` as its root. Marp then prints a single
  `Some of the local files are missing` warning and emits those slides blank —
  there is nothing in the PDF to tell you which ones. The command is

  ```
  docker run --rm --init -v "$PWD":/home/marp/app -e MARP_USER="$(id -u):$(id -g)" \
    marpteam/marp-cli slides/cyberdeck-talk.md --pdf --allow-local-files \
    -o /home/marp/app/slides/cyberdeck-talk.pdf
  ```

- **Marp does not render mermaid, so diagrams are rendered to PNG first.**
  Sources are in `slides/diagrams/` with a shared `theme.json` and `style.css`
  that match the deck's typeface and line weights; the output lands in
  `slides/img/`. Mount the host fonts or the container falls back to something
  that is not Liberation Sans:

  ```
  docker run --rm -u "$(id -u):$(id -g)" -v "$PWD/slides":/data \
    -v /usr/share/fonts:/usr/share/fonts:ro \
    ghcr.io/mermaid-js/mermaid-cli/mermaid-cli \
    -i /data/diagrams/modem-chain.mmd -o /data/img/modem-chain.png \
    -c /data/diagrams/theme.json -C /data/diagrams/style.css -b white --size 2600 -s 2
  ```

  `mmdc` has no `-w`; the flag is `--size`. Give each node's sub-label an
  explicit `<br/>` so every box comes out the same height — mermaid's own
  wrapping leaves them ragged.

- **Never have a program claim a tty it does not own.** This has cost a
  working session twice. On the deck, advice to stop the unit owning tty1 and
  run something else there left no way to type. On the laptop,
  `sudo openvt -s -w -- runuser -u "$USER" -- ...` in `./deck --console` killed
  the graphical session outright, VS Code and the editor's Claude Code session
  with it: `runuser` opens a PAM session, and pam_systemd registering a new
  logind session on a VT while a graphical seat is active tears the seat down.
  `openvt` taking "the first free VT" is not the safe-sounding thing it looks
  like.

  The supported way to get a real console is to log into one by hand --
  Ctrl+Alt+F3, then run the program -- which is a session of its own rather
  than one grafted onto an active seat. `./deck --console` prints those steps
  and deliberately does nothing else. **Do not teach it to launch one.**

- **A laptop terminal cannot show you a font fault.** `tools/deck_local.py`
  pins the pseudo-terminal to the panel's 66x20 and audits every glyph the
  program drew against the set the console font actually has, because a
  desktop terminal renders all of Unicode and a missing glyph is invisible
  from there. A real console (above) is the only place the fault shows itself.

- **Key bytes differ between the host terminal and the child's TERM.** The rig
  runs the child as `TERM=linux`; an xterm sends `ESC O P` for F1 where `linux`
  expects `ESC [ [ A`, and F6 upward happen to agree -- so the failure looks
  partial. `deck_local.key_translation` reads both terminfo entries with
  `infocmp` and rewrites the 12 sequences that differ. Read the capabilities;
  never hard-code them.

- **The console font has no emoji.** Only glyphs already proven on the shipped
  panel are safe: `█ · ✓ ▸ ✗ ↑↓` and box drawing. Anything else renders as a
  blank or a replacement box, and you will not see it from here.
- **nmcli quirks** the WiFi screen depends on: it answers `enabled`/`disabled`
  but accepts `on`/`off`; `IN-USE` is empty in terse mode, so use `ACTIVE`; and
  it emits one row per access point, not per network.
- **polkit grants NetworkManager actions to an active local session.** A
  systemd service has no seat, so group membership such as `netdev` changes
  nothing — the rule file is what matters.
- **Startup order matters.** Restoring the saved mode sits behind an
  `if self.fldigi.connected` guard, and `_persist_settled` must not write
  before `_startup_done`, or a cold boot silently overwrites the saved mode
  with CW. There are tests for exactly this; run them before touching startup.

## Where it stands

1743 checks across 24 files, all passing as of 2026-10-14 on the `logger`
branch — a clean serial run, every file green. Run them serially and do not edit `src/` or `tests/` while a run is in
flight: three successive runs during that session each reported a different
single failure, because what executed was not what was on disk. A clean serial
run had no flakes. The deck has worked real DX on PSK31 and RTTY. A DS3231 real-time
clock is fitted and verified across a power cut with NTP disabled. The WiFi
screen joins networks from the panel.

A general-purpose QSO logger is on the local branch `logger` (2026-10-11),
uncommitted, and **reachable from the panel**: Ctrl-N opens a tabbed entry
form, Tab moves between fields, Enter logs, Esc returns. F1 on that screen
opens the logging menu — activity, dupe rule, ADIF export — and F2 the
activities list.

An ACTIVITY is a named operating session with its own dated log file; an
ACTIVITY TYPE is the template of fields it uses. Creating a type happens on the
TYPE PICKER (`F1` → `v`), not on a menu line: `c` + number copies that type,
`n` starts one with no fields, `d` + number deletes one, and the picker has ONE
exit — it closes to the log screen however it was reached. Naming a new
activity leads straight into that picker, so the whole flow is name → type →
reference → log.
`tests/test_log_panel.py` drives the real application through a pty under
TERM=linux as well as xterm and checks a contact reaches the disk. The pure
cores are `src/qsolog.py`, `src/activities.py`, `src/logform.py`,
`src/callbook.py`, `src/qrzlog.py`, `src/lotw.py`, `render.log_screen`,
`menus.log_menu` and `tools/qso.py`.

**Uploading a contact is always a manual action.** Nothing on the deck sends
anything and nothing on a timer does; `tools/qso.py lotw --upload` on the
laptop is the only code path that transmits a log to a third party. A deck
being tested is full of contacts that must not reach a permanent record. This
is pinned in `tests/test_menus.py` as a property of the source — no `qrzlog`
import in `cyberdeck.py`, no `upload(` call, no QRZ menu item — because a
comment does not fail when somebody wires a key to an uploader.

**Open design decision, not yet built: three first-class areas.** Settings,
logging and digimodes as peers on a ring, cycled with **Ctrl-B / Ctrl-F**
(settings → log → digimodes, wrapping). Arrow keys were ruled out by terminfo,
which is the whole point of recording it: `infocmp linux` has NO modified
cursor-key entries, and `xterm-256color` defines only the SHIFT forms
(`kLFT=\E[1;2D`). So Alt+arrow arrives on the framebuffer console as Esc
followed by KEY_LEFT — and Esc is load-bearing on every screen — while
Shift+arrow works in the laptop rig and is a dead key on the deck. Control
characters are 7-bit and identical everywhere; free ones are Ctrl-B, E, F, G,
K, O, P, V (Ctrl-Z is not free: linux terminfo maps `kspd=^Z`).

The agreed F-key map, with F1 the menu and F4 the color cycle on every screen:

| | F1 | F2 | F3 | F4 | F5–F12 |
|---|---|---|---|---|---|
| Settings | menu | Station | Band / rig | color | — |
| Logging | menu | Activities | Activity type | color | — |
| Digimodes | menu | Tuner | Mode selector | color | Memories |

F2 and F3 are always that area's two main sub-views. F5–F12 are to be scoped to
digimodes: they are global today, so F7 on the log screen inserts a transmit
macro into a log field.

`docs/qso_log_design.md` carries the design and the open decisions.
**`docs/logger_branch_deploy.md` carries the deploy sequence and the recovery
sequence back to `main`** — read it before putting this branch on the deck.
The two most expensive things in it: the conf and the code must move together,
because `main`'s `config.py` refuses the keys this branch adds; and
`systemctl is-active` reports `active` for a unit crash-looping every three
seconds, so `journalctl -u cyberdeck-ui` is the only health check.

It is a **general** log and that is a constraint, not a description. Activity
types (`src/activities.py`, `activities.conf`) are named, ordered field lists
that double as the entry grammar, so POTA, a state QSO party and Field Day are
the same record with different fields — see §6b. `ACTIVITY` selects one and
blank is general logging; a park typed into an entry is honored in any
activity, because its shape is unmistakable. The logged mode comes from
`qsolog.resolve_mode` — fldigi's modem on digital, the rig on voice, because
fldigi always has a modem loaded whether or not it is in use. `OPERATING`
picks the policy; `auto` leans digital when the rig is unreachable, which is
the one case an SSB operator has to override.

Callsign lookup has two providers: callook.info for US calls (no account) and
HamQTH worldwide (free account, credentials in `cyberdeck.secrets`), tried only
when callook has nothing. Both verified against the live APIs.

QRZ upload is **paused**: the code is complete and the account has no QRZ
subscription, which their API requires for every action (§7.7a). LoTW export
works and signing is deliberately left off the deck (§11). What still needs
the rig: which hamlib mode string the FTX-1 reports under fldigi, and
`rigctld_client.mode()`, which is written and has never seen a real reply.

Reach the deck over ssh when I ask for it — the address is in the runbook.

## How I work — standing preferences

These are the same in every repository of mine. They are restated in each one
so that any assistant reads them, not only the one configured on my machine.

**Git is mine.** Never run `git commit` or `git push`, in any repository, for
any reason. Reading history is encouraged — `log`, `diff`, `status`, `show` —
and so is telling me when a good commit point has been reached, or drafting a
commit message for me to use. Finish the work, leave it uncommitted, and say
what changed and where.

**Hardware is mine.** Do not build SD-card images, `rsync` to a device, open an
`ssh` session to one, or run anything on a Raspberry Pi or the cyberdeck unless
I ask in that message. Hand me the exact commands to copy and paste — one block
per step, in order — say what each should print, and stop. I will run them and
paste the output back. Local work in the repository needs no such restraint.

**Writing.** No British spellings; US throughout. Design documents are
declarative: no hero's-journey narrative, no second-person "you", and never
state something as fact and then refute it a few lines later. For an article
already published, add a dated update section rather than rewriting the
narrative — the wrong turns are part of why it is worth reading. Do not repeat
a warning I have already acknowledged.

**Images.** Look at any photograph or screenshot before adding it to an
article, a slide deck, or a repository. Phone numbers show up in radio screens
and log captures, coordinates show up in beacon lines and station pages, and
backgrounds show rooms. Say what you found and redact it rather than guess.

**Destructive commands.** `/dev/sdX` stays a placeholder in any flashing or
disk-writing instructions. Never substitute a real device node.

**Amateur radio.** Test traffic uses my own callsign and its SSIDs — never
another operator's call, unless I explicitly ask for one.

**Working style.** I start fresh sessions often rather than carrying one for
weeks, so assume no memory of previous conversations. Everything you need
should be in this file or in the documents it points at.

**Keeping this file true is part of the work.** Anything dated here records
what was true on that date, not what is true now — check it against the
repository before relying on it, and correct it when it is wrong. When a
session has changed how the project works, turned up a gotcha worth the next
session not rediscovering, or outdated something in a "where it stands"
section, propose the edit to this file before the session ends. Do not wait to
be asked, and do not save it for a tidy-up later: the next session starts cold,
and this file is most of what it gets.
