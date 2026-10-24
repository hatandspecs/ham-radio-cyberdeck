# AGENTS.md — ham radio cyberdeck

Renamed from "keyboard-to-keyboard cyberdeck" on 2026-10-16: the digital modes
are one of three applications now, beside the contact log and the station's own
settings. The git remote and the directory keep the old name.

A single-purpose HF text terminal: a Raspberry Pi 3A+ behind a 5-inch DSI panel,
66x20 characters, driving fldigi headless over XML-RPC. It also runs on an
ordinary laptop — start fldigi, run `./src/cyberdeck.py`, nothing else needed.

## Start here

| Read | For |
|---|---|
| `README.md` | What it is, what each file does, the test table |
| `docs/platform_design.md` | Numbered FR/NFR with honest status |
| `docs/` | Runbook and operating tutorial |
| `docs/screens/` | Rendered screenshots of every screen |
| `docs/logging_tutorial.md` | Operating the contact log, with screenshots (its images predate the entry form and are stale) |
| `docs/wspr_operating_tutorial.md` | **Operating WSPR**, and pulling the spot log off the deck (§11). Screens are the generated ones, so they stay true |
| `docs/logging_tutorial.md` §6 | Pulling contacts off the deck and importing to QRZ by hand |
| `docs/qso_log_design.md` | The logger's design and every decision in it — §7f one log and sessions, §7g the schema decides the columns, §7h danger zone, §7i what follows an activity |
| `docs/wspr_deploy.md` | **Installing `wsprd` on the deck and benchmarking it.** Decode only; nothing in it transmits |
| `docs/wspr_design.md` | **WSPR: design and decisions, all of it built and on `main`.** Read §4 and §8 first — the audio device contention with fldigi and the five open questions are what the shape depends on |
| `docs/logger_branch_deploy.md` | The logger deploy and recovery sequence, written when the logger was a branch. Merged to `main` since; `docs/scratch_notes.md` carries the current deploy and revert |
| `docs/next_steps.md` | **Seven features specified 2026-10-22, none built.** Ring reordering, frequency allocation tables, the FTX-1 auto tuner, logging a digimode contact by hotkey, the WSPR and logger maps, and export off the deck. Grounded in two sibling projects: `ftx1-tuner-sweep` has the verified tuner CAT work, `wspr_7510_analysis/terminal_map_prototype` has a working map renderer |
| `slides/cyberdeck-talk.md` | The talk, as Marp markdown; `slides/diagrams/` holds the mermaid sources |

## Things that cost a lot to rediscover

- **The no-keyboard screen is a startup answer and nothing else.** An
  in-session watcher polled /proc and raised it whenever a keyboard went
  away; it was removed deliberately on 2026-10-18. A Bluetooth keyboard that
  idles asleep drops its input device and is indistinguishable from one
  switched off, so the watcher either interrupted an operator who had merely
  paused or needed a delay long enough to be useless. Worse, to be useful it
  had to reach across all four areas, remember which one it interrupted and
  hand it back -- and dismissing it sent the operator to the conversation
  unconditionally, which from WSPR meant a dead digimodes screen reached by
  stepping past the ring lock. That is a lot of mechanism for a problem the
  operator is already looking at: a keyboard that dies mid-session announces
  itself by nothing happening. **If a watcher reappears, this is the
  reasoning it has to beat.** `tests/test_pair.py` asserts its absence.
- **`x  Export this session` in the WSPR menu is rendered but has no
  handler.** `menus.py` lists it; the `m == "wspr"` key branch in
  `cyberdeck.py` handles `w d t n e b p o u f a z` and not `x`, so the key
  does nothing. The spot log comes off with `rsync`, which is what both the
  README and the WSPR tutorial document. Either wire it or drop the item --
  a menu line that does nothing is worse than no line.
- **Logs come off the deck into `~/Downloads/deck-exports/`**, by `rsync`.
  `qso.log` plus an ADIF that must be exported on the deck first (`F1 a`),
  and `wspr.log` which has no export at all. Documented in README
  "Getting data off the deck" and in both operating tutorials.

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
- **`code=exited, status=1/FAILURE` in the journal after a restart is
  ncurses, not a crash** (diagnosed 2026-10-16). **ncurses installs its own
  SIGTERM and SIGINT handlers in `initscr` and they call `exit(1)` from
  inside the handler** — a plain curses program with no deck code in it does
  exactly the same thing, which is how this was confirmed. So every
  `systemctl restart` logged a FAILURE that looked precisely like the crash
  loop the journal is read for. **Tell them apart by what comes FIRST:** a
  `Stopping …` line before the exit is systemd stopping the unit, and a
  `restart counter is at N` climbing with no `Stopping` is the real thing. A
  unit that ran for hours and consumed minutes of CPU did not crash.

  The consequence was the actual bug: `exit()` from a signal handler does not
  unwind, so `main`'s `finally` never ran on a stop — transmit was not
  aborted, the console palette was not restored for whatever owned tty1 next,
  and the decoder was left parked on `NULL` whenever the radio happened to be
  in SSB at that moment. `_leave_cleanly` raises `SystemExit(0)` instead, and
  is installed **before `curses.wrapper`** because ncurses only claims a
  signal whose disposition is still the default (`CatchIfDefault` in its own
  source) — installed afterwards it would simply be overridden. SIGHUP too,
  since the unit sets `TTYVHangup=yes`. `tests/test_decode_park.py` drives
  both signals at the real program and checks the exit status and that the
  modem came back.

- **The deploy preflight cannot catch a crash that needs a keystroke.** It
  imports the modules and loads the config, which proves the code starts —
  and on 2026-10-16 it passed cleanly while the deck then crash-looped three
  times, because `_open_editor` raised `TypeError: object of type 'int' has no
  len()` only once a key was pressed on an `int`-typed setting. `systemctl
  is-active` said `active` throughout. **After any deploy, press keys on the
  screens that changed**, and read `journalctl -u cyberdeck-ui` rather than
  `is-active`. A `restart counter is at N` line climbing in the journal is the
  signature.
- **`TX_POWER_MAX` is not cosmetic and is not the same as `TX_POWER`.** The
  radio reports RFPOWER over CAT as a fraction between 0 and 1, so the ceiling
  is what turns that into watts — without it the deck cannot report power at
  all. On the FTX-1 the ceiling genuinely changes with the configuration:
  field head on its own battery, field head on external power, and the Optima
  are three different maxima, so it is a setting the operator has to be able
  to type. It is on the deck-and-rig screen for that reason.

  `TX_POWER` is the opposite and is deliberately NOT on that screen. It is
  read from the radio by `_power_now()`, which falls back to the configured
  value only when the radio will not answer, so a row for typing it invites
  setting a number the radio immediately contradicts. The `{power}` memory
  token substitutes `_power_now()`, not the setting, so removing the row cost
  the token nothing.
- **This project is GPLv3 as of 2026-10-15, and was MIT before that.** Do not
  "restore" the MIT license or copy a permissive header into a new file: the
  change was deliberate. The reason is the stack — fldigi is GPLv3, hamlib is
  LGPL, and the WSPR area runs `wsprd` out of WSJT-X, which is GPLv3,
  so bundling any of it under a noncommercial or permissive license would
  conflict. A noncommercial license was considered and rejected for exactly
  that reason: GPLv3 §10 forbids adding restrictions, so "noncommercial only"
  cannot be combined with GPL code at all. **The APRS iGate stays MIT** —
  different project, different call. The MIT grant already made cannot be
  withdrawn, so commits before 2026-10-15 remain MIT for whoever has them.
- **Do not write signal processing.** fldigi does all of it; this program is a
  terminal that drives fldigi over XML-RPC on the loopback interface. A better
  PSK31 demodulator is not the project.
- **Run tests with `tools/run_tests.sh`, not pytest.** Each test file is a
  standalone script that prints its own checks and ends with `ALL PASS`.
  Invoking pytest on them wastes minutes and ends in `INTERNALERROR`.
- **fldigi must be running for the tests** — six of them drive the real
  program through a pseudo-terminal and read the screen back. No radio is
  needed, but a modem is. Without it, `test_menu_arrows`, `test_menu_nav`,
  `test_menus`, `test_screen`, `test_state` and `test_wspr_panel` fail 17
  checks between them, every one naming fldigi or the state it leaves
  behind, and they fail the same way on a clean checkout of `HEAD`.
- **An innocent explanation covering most of a failure list will be assumed
  to cover all of it. Check every failing file against `HEAD`, not a
  sample.** On 2026-10-18 a run failed 18 checks; 17 were the fldigi set
  above and the eighteenth, `test_wspr_panel`'s `the time-out to 60
  minutes`, was a real regression from the 12-hour ToT work. Four of the six
  files were compared against `HEAD`, the pattern looked settled, and the
  odd one out was reported as environmental.
- **`tests/test_log_panel.py` takes 903 seconds for 225 checks** (measured
  2026-10-16) and so was being killed three seconds inside a 900-second
  timeout. **A run that stops mid-screen with no traceback and no `ALL PASS` is
  the timeout, not a crash** — and the wrapper still exits 0, so check for the
  `ALL PASS` line rather than the exit code. Give it 1800 seconds.

  It drives the real application through a pty once per scenario, each with a
  settle of three seconds or more, so its runtime is roughly three seconds
  times the number of scenarios and it grows every time one is added. Before
  adding another, ask whether the property is pure enough for
  `test_log_screen.py`, `test_render.py` or `test_qsolog.py`, which run in
  seconds — a pty scenario is for key DISPATCH and for what reaches the disk,
  not for layout.
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
- **The deck's callsign is in the STATE file, not `cyberdeck.conf`.** The
  station identity was entered on the panel, so it lives in `station` inside
  `STATE_PATH` (`~/.local/state/cyberdeck.json` on the deck) and
  `_restore_state` applies it at startup from `menus.STATION_FIELDS`. A
  preflight that calls `config.load()` and prints `CALLSIGN` gets an empty
  string, and that is CORRECT — it is not a broken deck. Two deploys on
  2026-10-15 were stopped over it. Read both places and say which answered;
  `docs/logger_branch_deploy.md` §2a does.
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
- **A pty assertion that greps the whole screen can match the FOOTER.** Three
  checks in this suite passed without testing anything because of it: one
  looked for `DELETE` to prove a confirmation was up and matched the
  activities screen's own `d delete` footer; one used `"Tab field" not in
  body` to prove the log screen was gone, which stopped meaning anything when
  that hint left the footer; one asserted `"Tab" in flat` for the same reason.
  **Assert the outcome, or scope the match** — `body[:200]` for a header,
  `body[-120:]` for a footer, the file's contents for anything written. The
  harness quits with Ctrl-Q and a confirmation treats every key but Enter as
  "no", so a question is NEVER the last screen: what distinguishes a blocked
  key from one that got through is which screen the deck ended up on.
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

- **An activity carries its schema and its own reference with it**
  (2026-10-16, §7i). They used to be independent global settings, so resuming
  last weekend's park activation left the operator logging it under whatever
  schema they were using an hour before. `_follow_activity` applies the
  schema and `my_park` the session's **newest** contact carries — newest,
  because §7g lets one session hold contacts under several schemas and the
  latest is the operator's most recent decision. Three rules that are easy to
  get wrong here:

  - **An empty `activity_type` means GENERAL, not "unknown".** `make_record`
    writes no `activity_type` for the general schema, so `""` has to resolve
    to the built-in rather than being treated as "leave the schema alone".
  - **The reference is set BEFORE the schema.** `_set_activity_type` ends by
    calling `_ask_my_park`, which opens an editor when the schema wants a
    reference and none is set — so setting the park afterwards left that
    editor open over the log screen on every resume of a park activation.
  - **A session with no contacts, and the master log, keep what is set.**
    There is nothing to infer from, and for a new activity guessing would
    undo the choice the picker asked for a keystroke earlier.

- **A stand-in's worker thread is a race, and the suite is where it shows.**
  `tests/test_rigctld.py` read `fake.seen[-1]` straight after `set_ptt`.
  The client returns when its socket closes; the stand-in's server thread
  appends to `seen` some microseconds later. It passed every interactive
  run and raised `IndexError` in a full suite run, then passed on rerun —
  **the worst way for a test to be wrong**, because a rerun "fixes" it.

  The fix is `waited(count)`, which polls until the thread has recorded what
  it should, with a deadline. **A `sleep` would have hidden it rather than
  fixed it.** `tests/test_wsprnet.py` was already safe because it reads only
  after `Uploader.wait()`, which blocks until the queue drains and the worker
  exits — that method exists for this reason and not for production use.

  Any new test with a background thread in its fixture: synchronize on the
  thread's own progress, never on elapsed time. Hammering a suspect file —
  `for i in $(seq 20); do python3 -u tests/x.py >/dev/null || echo FAIL; done`
  — is how to tell a flake from a pass.

- **Leaving a menu must disarm a pending two-key action, not only arriving
  at one.** `_open_menu` has always cleared `_pending_type_delete`; nothing
  cleared it on the way OUT, and that was covered by accident while Esc from
  the schema picker went UP to the logging menu, because that is an
  `_open_menu` call. The moment Esc began closing the picker to the log
  screen (§7i, so Esc can mean "keep the schema I have"), `d` then Esc left
  the delete ARMED and the next number pressed in the picker deleted that
  schema instead of selecting it. `_close_menu` disarms all three flags now.
  The scenario that caught it is `test_log_panel`'s "d then Esc then a number
  selects", and it caught it only because its key sequence had to be rewritten
  for the new Esc — a test that had kept passing would have hidden it.

- **`r` renames a session; `e` + number edits a schema in place.** Both were
  missing and both were reachable only by a detour — renaming not at all, and
  editing by copying a schema and then typing its own name back to trigger
  the replace confirmation. `_editing_type` is what makes the save skip that
  confirmation, and it has to be cleared on a copy, on a new schema and after
  a successful write, or a later copy silently overwrites something.

- **A schema change is refused over a part-typed contact**, because the
  change rebuilds the form and carries only the sticky fields. `LogForm.typed`
  decides what counts, and what it deliberately does NOT count is the point
  of it: sticky fields, untouched radio fields, and anything still equal to
  what the deck prefilled — a `599` nobody edited, a serial the log handed
  out, a rig name off the Station settings. A guard that counted those would
  refuse every schema change on a freshly cleared form.

- **The log display is driven by the SCHEMA, not by the records** (2026-10-16,
  `docs/qso_log_design.md` §7g). A field the selected schema does not ask for
  is absent from the heading row, the contact rows and the continuation rows,
  whatever the records carry; a field it does ask for is shown blank where a
  contact never captured it. The rule it replaced was "the schema asks for it
  OR a contact on screen has it", which failed in both directions at once: the
  columns moved as the list scrolled and did NOT move when the schema changed,
  so a contest session kept its `NR` and `EXCH` columns after switching back
  to general logging. Nothing is hidden by this — the contact screen lists
  every field a record holds, and ADIF export writes the record, not the
  screen. The AUTOMATIC fields are the exception and barely one: band,
  frequency, mode, power, rig and antenna are never typed, so no schema lists
  them, and `render._AUTOMATIC` appends them to every schema's continuation
  rows.

- **Name, QTH and comment are three columns under three headings.** They used
  to share one trailing column headed `QTH`, which put every typed comment in
  a column labeled QTH on general logging — the schema asks for a comment and
  deliberately does not ask for a QTH. If a column heading and the value under
  it ever disagree again, this is the shape of the bug.

- **`GENERAL` gained a `qth` field on 2026-10-16, and the entry grammar
  changed with it.** It had none before, on the reasoning that an operator
  who wanted one could add it from the field selector — wrong about how often
  it is wanted, since the QTH is what gets read back beside a name and the
  callbook lookup returns one. **The field list IS the grammar**, so
  `W3ABC 59 57 Bob Pittsburgh` now logs a QTH where the trailing word used to
  be dropped. One word per field, so `... Bob Pittsburgh PA` still drops the
  `PA`: the parser is positional and a two-word QTH is typed into the field.
  Four test files encode the general field tuple or the parse of that line —
  `test_activities`, `test_logform`, `test_qsolog`, `test_log_screen` — so
  changing `GENERAL.entry` means changing all four.

- **The comment is never on the first row of the list.** It is the one field
  whose length is unbounded, so there it was always the one clipped, and it
  held the open-ended last column that the QTH needs. `render._LINE1_FIELDS`
  is what decides this: a field named there is a first-row column and is
  skipped on the continuation rows, and `comment` is deliberately absent. A
  one-line list therefore shows no comment at all.

- **A dropped CAT read is not a mode change.** `rig.mode()` returns `""` when
  the read times out, and `""` is the absence of an answer, not a mode.
  Treated as an answer it sent `resolve_mode` and `_shown_mode` to the MODEM,
  so the logging screen showed `USB`, then `BPSK31`, then `USB` again every
  several seconds — which is how often a read fails over a serial port on a
  Pi, redrawn five times a second. `Deck._rig_mode_held` holds the last good
  reading for `_RIG_MODE_HOLD` (8 s) and then admits the absence, so a radio
  switched off is not asserted to be in the mode it was in an hour ago.

- **Decoding stops with transmit when the radio leaves a data mode**
  (2026-10-16). fldigi decodes whatever is on the sound card whether or not
  the radio could be carrying it, and on a Pi 3A+ that DSP is the deck's
  largest continuous cost. `fldigi_client.park_decoder` loads the `NULL`
  modem, which is the nearest thing fldigi has to "stop decoding", and
  remembers the modem AND the carrier to come back to — fldigi moves the
  carrier to the new modem's sweet spot on every modem change, so without
  that the operator comes back somewhere other than the signal they tuned
  onto. Three things to know before touching it:

  - **`modem()` reports the OPERATOR's modem, `modem_loaded()` the truth.**
    While parked they differ. Every caller wants the first — the panel shows
    what the operator chose, the picker marks it current, the log records what
    the contact was made on — and a screen reading `NULL` would say the deck
    had lost its mode.
  - **`set_modem` while parked records the choice instead of applying it.**
    Applying it would start the decoder the park exists to stop and the next
    poll would park it again, so the deck would fight the operator.
  - **Transmit and decoding resume differently, on purpose.** Decoding comes
    back by itself the moment the radio is in a data mode — a running decoder
    puts nothing on the air. Arming transmit stays the operator's act, which
    is what `Ctrl-I` is for.

  `_watch_rig_mode` used to `return` early whenever transmit was ALREADY
  inhibited, which is the common case. Park before that check or the decoder
  is never stopped.

- **Three test traps around the logger, all of which produced vacuous
  passes.** (1) A confirmation is never the last screen in a pty test: the
  harness ends every run with Ctrl-Q and any key but Enter cancels a
  confirmation, so assert the OUTCOME and check the wording against the pure
  renderer. (2) A log value containing a space must be QUOTED in a seeded
  fixture — the format is whitespace-separated `key=value`, so
  `activity=Bald Eagle SP` parses as the activity "Bald" plus two keyless
  words, and every session assertion then reports zero contacts. (3) F1 is
  `\x1b[[A` under `TERM=linux` and `\x1bOP` under xterm; `deck()` in
  `tests/test_log_panel.py` defaults to `linux`, so an xterm F1 is simply
  typed into the callsign field.

## What is being worked on now

### Seven features from `docs/next_steps.md`, built 2026-10-22

Specified and built the same day, all uncommitted in the working tree. The
specification is `docs/next_steps.md`; each of its sections now ends with a
**Built** note recording what was made and where the implementation departed
from the spec.

| # | Feature | Where | Tests |
|---|---|---|---|
| 1 | Ring order editor | `RINGED` screen, deck & rig `F1` item 4 | `test_ring_editor.py` 57 |
| 2 | Band allocation tables | `ALLOC`, a fifth ring area; `src/bandplan.py` | `test_bandplan.py` 54, `test_bandscreens.py` 70 |
| 3 | FTX-1 auto tuner | `TUNER` screen, deck & rig `F1` item 3; `src/tuner.py` | `test_tuner.py` 97 |
| 4 | `^G` logs the station heard | `src/decall.py`, digimodes `F1` item 5 | `test_decall.py` 50, `test_logfromchat.py` 61 |
| 5 | WSPR map | `WSPRMAP`, `m` on the WSPR screen; `src/wsprmap.py`, `src/fbdraw.py` | `test_wsprmap.py` 90, `test_fbdraw.py` 37, `test_mapscreen.py` 40 |
| 6 | Logger map | `LOGMAP`, `F5` on the log screen | shares the above |
| 7 | Export to a phone | `EXPORT` screen, deck & rig `F1` item 5; `src/export.py` | `test_export.py` 135 |

Three test files came out of the panel sessions rather than the
specification: `test_wsprsessions.py` 42, `test_backfill.py` 39 and
`test_txbuffer.py` 8.

**The ring went from four areas to five**, which broke eight test files
through the ring-hop trap below. The new counts: `^O`x3 reaches the
conversation, `^O`x2 reaches WSPR, both regardless of whether logging is on.

**All seven have run on the deck**, over four panel sessions on 2026-10-23,
and eleven faults came out of them. The three features that could not be
believed off hardware are where most of the faults were: the maps write to
the framebuffer directly (`src/fbdraw.py` -- no `fim`, no `fbi`, no keyboard
handover) and were erased by curses on every frame, the auto tuner crashed
the deck on `Enter` and then swept against a radio that was refusing its
commands, and the export server binds to the WiFi address. The faults and
what each one cost are written up in the panel-session notes below and in
`docs/scratch_notes.md`.

**The lesson that generalizes: if a key starts something, a test should press
the key.** The tuner crash was one line -- `self.rig` where the rest of the
file uses `self._log_rig()` -- with the sweep engine tested against a fake
rig on one side and the renderer tested on the other, and nothing calling the
method between them.

**Four new config keys outside the tuner's**: `RING_ORDER`, `LOG_HOTKEY`,
`MAP_VIEW`, and the export's `EXPORT_DIR` / `EXPORT_PORT` / `EXPORT_IDLE_MIN`.
All but the export paths are in `_REMEMBERED`; a setting a menu can change
and this tuple does not list silently reverts on the next power cycle, which
reads as the panel forgetting rather than as a bug.

#### The export server is the one with a security surface

`src/export.py` stands an HTTP server on the WiFi address for five minutes so
a phone can download the logs. Three properties keep that safe, and all three
are tested:

- **The request names a position, never a file.** `/a7f3/2` is the third item
  on a list the deck handed the server. `BaseHTTPRequestHandler`, not
  `SimpleHTTPRequestHandler` -- the latter maps request paths onto the
  filesystem, which is the single thing this must not do. There is no path to
  traverse, which is why `../cyberdeck.secrets` and its encodings are a 404
  rather than something a filter has to catch.
- **`cyberdeck.secrets` is not on the list and must never be added to it.**
  `Deck._export_files` offers the ADIF, the contact log, the WSPR spots, the
  transcript and `cyberdeck.conf`. The secrets are a separate file for
  exactly this reason.
- **It closes itself**, on a timer polled from the main loop rather than from
  its own screen, and in the `finally` that un-keys the transmitter. A server
  that only expired while being looked at would stay up for as long as the
  operator was anywhere else.

The handler logs nothing: `http.server` writes a request line to stderr, and
on the deck stderr is tty1 -- the console curses draws the panel on.


**WSPR, merged to `main` and proven on the air.** Transmit and receive,
exclusive while running, band hopping, a session log, spot upload. The design
is `docs/wspr_design.md`, the install runbook is `docs/wspr_deploy.md`, and
operating it is `docs/wspr_operating_tutorial.md`.

`add-wspr` and the logger branch no longer exist -- `main` is the only branch.
What is uncommitted is working-tree work, not a branch.

### Built, tested, and proven on real hardware

| Piece | File | State |
|---|---|---|
| message encoder | `src/wspr.py` | **validated: the real `wsprd` decodes its output** |
| `wsprd` output parser | `src/wspr.py` | **reads real off-air 2.7.0 output** |
| spot dedupe | `src/wspr.py` | a window can decode one transmission twice |
| power to dBm | `src/wspr.py` | with the exactness flag the display highlights |
| audio level | `src/wspr.py` | pure Python, no `audioop` |
| band table | `src/wsprbands.py` | all 11 dials confirmed three ways |
| slot schedule, hopping, ToT | `src/wsprsched.py` | injected clock |
| spot upload | `src/wsprnet.py` | protocol from WSJT-X's source, no network in tests |
| grid distance and bearing | `src/grid.py` | **validated against this station's own wsprnet rows**, 498 to 6855 km |
| capture mixer | `src/wsprgain.py` | injected runner, so no sound card in tests; read before write, restored on stop |
| transmit level | `src/wsprtx.py` | digital amplitude, not the shared playback mixer |

255 checks in `tests/test_wspr.py`, `test_wsprsched.py`, `test_wsprnet.py`.
`tools/wspr_bench.py` benchmarks the decoder, `tools/wspr_rx.py` captures and
decodes one real slot, `tools/wspr_level.py` reads a WAV's level.

**The receive path is proven on the air** — 2026-10-17 0208 UTC, 40 m, two
stations decoded, `-36.8 dBFS`, offsets 1453 and 1515 Hz above the dial. See
`wspr_design.md` §12a for the seven things that established.

### NOT built — this is what is left

Nothing in `cyberdeck.py` imports any of it. The deck behaves exactly as it
did, which is why the install needed no service restart.

1. ~~The capture loop.~~ **DONE** — `src/wsprrx.py`, 53 checks, none of
   which touch a sound card or `wsprd` (`spawn=` is the seam). Capture and
   decode are **independent and polled**: a decode outliving its slot must
   not delay the next capture, and a `tick()` that waited for either would
   freeze the panel for 114 seconds.

   It distinguishes four things a simpler design conflates: **no end marker
   is a dead decoder, not an empty window** (recording silence for a killed
   decoder would be a fact somebody uploads); an empty window IS a success;
   a capture that wrote nothing or exited busy is a failure with `arecord`'s
   own message kept; and a wedged decoder is killed at 110 s.

   **What is left to wire** is calling it from the draw loop with
   `wsprsched`'s decisions and putting the spots through `wsprlog`.
2. ~~The transmit path.~~ **DONE** — `src/wsprtx.py`, 55 checks, no radio
   in any of them. Renders (cached), keys, plays via `aplay`, unkeys.

   **Six of its eleven test blocks are about PTT rather than WSPR**, which
   is the right proportion for the module that keys a transmitter. Every
   path out of a transmission unkeys: completion, a failed `aplay`, a
   wedged player past `TX_TIMEOUT_S` (118 s — longer than the 110.6 s
   signal, shorter than the 120 s slot), `stop()` from the middle, and a
   player that could not be started.

   **`ptt()`'s three answers are distinguished**: False means the radio did
   not key and nothing is played; None means unreadable and it proceeds with
   a note, because refusing would take transmit away from a radio whose
   readback is unsupported.

   **The audio is cached** and a POWER CHANGE invalidates it. A cache that
   beaconed the old wattage would announce a power the radio is not making.
3. ~~The spot log.~~ **DONE** — `src/wsprlog.py`, 51 checks. Two record
   kinds in one file (`kind=rx` a station heard, `kind=tx` a beacon sent),
   sessions keyed `(name, start)` and DERIVED from the records with
   newest-wins, counts broken out by kind for the danger zone.

   **`qsolog.read` would have discarded every beacon**, because it requires
   a callsign and a transmission has no other station's call in it. That is
   why `wsprlog.read` has its own predicate. The two log formats share one
   quoting implementation — `qsolog.format_line` and `qsolog.read_lines` were
   generalized out for this, and `format_record`/`read` now call them — so
   there is one place the format lives.
4. ~~The screen, the menus, the four toggles, the danger zone.~~ **DONE** —
   `render.wspr_screen`, `render.wspr_toggles`, `render.wspr_power`,
   `menus.wspr_menu`, `menus.wspr_danger_menu`. 93 checks in
   `tests/test_wspr_screen.py`, every row asserted to be exactly the screen
   width at 40, 50, 66 and 80 columns.

   **`render._pad` was needed and is worth knowing about**: a row built from
   several `(text, attr)` segments has no single string to `ljust`, and an
   earlier version padded by a whole WIDTH rather than the remainder,
   producing rows wider than the screen that curses refuses to draw. The
   danger menu also cut a session name mid-word at 63 columns ("from Satu"),
   so the name moved to the footer — the same fault the log columns were
   rebuilt to avoid, found again in a new place.
5. ~~The exclusive lock.~~ **DONE** — WSPR is a fourth ring area and
   `_ring` refuses to leave it while running, saying what is in the way
   rather than doing nothing. `_wspr_start` stops `cyberdeck-fldigi` and
   `_wspr_stop` restarts it, ordered so the transmitter is unkeyed first.
6. ~~The TX test tone.~~ **DONE** — behind the menu and a confirmation that
   states the current reading, time-bounded by construction.

**All of it is wired, deployed and passing**: `tests/test_wspr_panel.py` is
62 checks through a real pty under both terminals, and the whole feature is
604 checks across nine files. Deployed to the deck 2026-10-17 — the
preflight printed four ring areas and no config notes.

### Eleven things the first session on the panel found — 2026-10-17

Driving the real UI turned up what no test had: one dead feature, one
undiscoverable idiom, two labels that said the opposite of the truth, and
seven gaps. All are fixed and tested.

| What | Why it happened |
|---|---|
| **`arecord: Device or resource busy`, every slot** | **No sudoers rule exists.** `cyberdeck-ui` runs as `deck`; `sudo systemctl stop cyberdeck-fldigi` from inside it has no tty for a password prompt, exits non-zero, and fldigi keeps the exclusive codec. `docs/wspr_deploy.md` §4b is the rule — **a dependency of the feature, not hardening.** `_service` now reports the non-zero exit and `_wspr_start` refuses rather than running a slot clock over a codec it does not have |
| Selecting a band did not tune the radio | `_wspr_tune` was called only from the scheduler, so with WSPR stopped the picker moved a label and left the radio where it was |
| `+n` to add a hop band was undiscoverable | A two-key prefix with nothing visible between the keys. **Space toggles the highlighted row and `[*]` is the checkbox.** `+` was NOT kept as a synonym: its meaning would have changed silently |
| No slot clock | WSPR is a schedule before it is a mode. `render.wspr_slot` reads the scheduler's own arithmetic, so the clock and the capture cannot disagree |
| `Time-out` named neither what nor whose | Three clocks exist on that screen. It is **`Session ToT`** on the menu and `session m:ss left` on the screen |
| "Calibrate transmit audio does nothing" | It was refusing correctly — transmit is inhibited until the rig reads DATA-U — and writing the reason to the message line **underneath the still-open menu.** Every refusal reached from a menu now closes it first |
| `snapped` on a power that was not | The word appeared only when the value had been snapped *down*, which reads as the opposite. **Both states are named.** The test said `"snapped" in flat`, which matches `"not snapped"` — a vacuous pass of the kind this project keeps finding |
| Hopping invisible when off | Its absence had to be read as "off" rather than "no such feature". The header says `hop 3` or `no hop` |
| No band on a spot row | Two spots an hour apart on a hopping session answer different questions. The log file always had it; the screen did not |
| Older spots unreachable | A session gathers hundreds, the screen holds ten. **The arrows select and scroll**, PgUp/PgDn by eight, Home/End to the ends, Esc back to following the newest |
| A hop band in the wrong mode is silent | The radio holds one mode but **remembers one per band**. `Check hop bands for DATA-U` on the menu visits each, reads the mode back, and names the ones to go and set |

**The five "pre-existing red" test files were the fourth ring area.** Six
files hard-coded one `^O` from the boot screen to reach the digimodes or the
conversation; with WSPR on the ring that hop lands on WSPR, so every
scenario below it read the wrong screen. `test_area_ring.py` also asserted
the ring's *size* three times. A fifth area costs one edit per file plus
those three checks — the constants are named `TO_CHAT`/`TO_DIGI` at the top
of each file for exactly that reason.

### WSPR works on the air — 2026-10-17

**Transmitting and being spotted worldwide.** From this station on 40 m at
5 W: `HB9VQQ` in Switzerland at 6599 km, `WI6P` at 3617 km, `W7BJH` at
3669 km, seven receivers in one slot. Receiving at the same time —
`N3AIU`, `WW0WWV`, `W9RAG` at 0.2 W, `KF9KV` at -4 dB. The uploader's
`version=cyberdeck` is visible in wsprnet's own records.

**The audio failure was authorization, and sudo was the wrong tool.**
`cyberdeck-ui` runs as `deck`, and stopping fldigi needs privilege. A
sudoers `NOPASSWD` rule parses, works from a login shell, and still fails
from inside the service — which has no tty, no PAM session, and a
`CapabilityBoundingSet` narrowed to `CAP_SYS_TTY_CONFIG`. The route that
works is **polkit**, which is what this deck already uses for WiFi:
`polkit/10-cyberdeck-services.rules`, scoped to one user, one action
(`manage-units`), one unit and three verbs. `docs/wspr_deploy.md` §4b is the
install, and it is **a dependency of the feature, not hardening**. Verified
on the deck: the stock policy for `manage-units` is `auth_admin_keep`, so a
grant that does not prompt could only have come from the rule.

### The second round of panel findings — same day

| What | Why |
|---|---|
| **Scrolling the spot list was laggy** | `_draw_wspr` read and parsed the whole spot log on every draw, and the draw loop runs on every keypress. The menu did the same through `_menu_for`. Both cached, invalidated on write |
| **No way out of the selected list** | Esc tested the running check first, so it always answered "^X stops it". The selection is released first now, and the footer changes to list keys while a spot is selected |
| **TX audio ~2x too hot** | 50% amplitude made close to 10 W against a 5 W setting with the ALC half-scale. `WSPR_TX_LEVEL` scales the rendered samples — **not the playback mixer, which fldigi shares.** The test tone uses the same level, or it calibrates nothing |
| **No RX gain from the deck** | `WSPR_RX_GAIN` sets the capture mixer, which IS shared — safe only because WSPR owns the codec exclusively. Read before write, restored on stop. Every capture's dBFS is shown beside it, which is what makes a gain control judgeable |
| **No inhibit indicator** | Transmit was refused with nothing on screen to say why, while every other screen carries it. In the header, displacing `next: TX` — which under an inhibit is a false statement |
| **KM empty** | WSPR carries a grid and no distance. `src/grid.py` computes it, **validated against this station's own wsprnet rows**: inside 0.5 km on every six-character path from 498 to 6855 km. Not stored — both figures are derivable from the two grids already in each record |
| **The screen was tight** | The spot row used 44 of 66 columns with no gaps. Respaced, with KM and AZ |

### Building the slide deck: there is no `npx` on this machine

`nodejs` and `npm` are not installed and nothing named `npx` is on the PATH,
yet `slides/cyberdeck-talk.pdf` has been rebuilt many times. The route is the
**VS Code Marp extension**, which bundles its own `marp-cli`, and VS Code's
Electron run as a node interpreter:

```bash
cd ~/git_repos/ham-radio-cyberdeck/slides
MARP=~/.vscode/extensions/marp-team.marp-vscode-*/node_modules/@marp-team/marp-cli/marp-cli.js
ELECTRON_RUN_AS_NODE=1 CHROME_PATH=/usr/bin/google-chrome \
  /usr/share/code/code $MARP cyberdeck-talk.md --pdf --allow-local-files
```

`--allow-local-files` is not optional: the slides pull images from
`../docs/screens/` and `img/`, and without it they render blank while the
build still reports success. `slides/README.md` carries this too.

### The screens in the docs are GENERATED — do not hand-edit them

`docs/screens.md` is the output of `tools/capture_screens.py`, and
`docs/screens/*.png` is the output of `tools/capture_png.py`. Anything
written into `screens.md` by hand is destroyed the next time either runs.
New screens go in `tools/wsprgrid_fixture.py`, which both tools read.

The PNG path is the one the blog articles use: a generated screen in the
scheme's true colors beats ASCII art, and it cannot drift from the code. It
is also the only one that can show an ATTRIBUTE -- the maps' band digits are
reverse-video key caps, which `screens.md` renders as `180m 240m` and the PNG
renders correctly.

**The `▸` selection marker comes out as an empty box in the PNGs**, in every
screen that has one, because Liberation Mono has no U+25B8. Pre-existing and
cosmetic; the deck's console font is a different font and the panel is the
thing that matters. Worth knowing before chasing it as a new bug.

### On-air, and what the second day of panel testing found — 2026-10-17

**WSPR works, confirmed by wsprnet.** 5 W on 40 m reached 43 receivers in one
slot; 20 m reached ON5KQ in Belgium (6060 km), HK4CZE in Colombia, and the
whole US west coast. Receive decoded eleven stations in a slot, including
K5NAV at 0.2 W over 2781 km.

**The single most expensive discovery: the ALSA card index moves.** The
C-Media codec was card 1 in the morning and card 2 after a reboot, with HDMI
taking 1. `plughw:1,0` was compiled into `wsprrx`/`wsprtx` AND `WSPR_DEVICE`
was never read, so capture pointed at the HDMI card and failed "No such file
or directory" -- a different fault from "Device or resource busy" and one no
amount of stopping fldigi fixes. **Everything now addresses the card by name
(`plughw:CARD=Device,DEV=0`, `amixer -c Device`).**

The same bug hid a second one: `WSPR_RX_CARD` defaulted to `1`, so every
capture-gain `amixer` call went to the HDMI card and silently did nothing
while the deck reported a percentage it had never set. `Mic Capture Volume`
on this codec runs 0-35 spanning -12 to +23 dB and ships at 20 (+8 dB), so
there is 15 dB of real headroom. **AGC ships ON and is now turned off for a
session and restored after** -- a correctness fix, not a level one: it
compresses a constant-envelope signal and corrupts the SNR uploaded to
wsprnet as a measurement.

**And a trap I set myself:** adding the four hardware addresses to
`_REMEMBERED` meant a state file written when the codec was card 1 beat the
corrected default, so the fix could not take effect. A device address is not
a preference. They are excluded, with the reason in the code.

| Finding | Resolution |
|---|---|
| **15 test files called `report()` without `sys.exit()`** | They exited 0 with failures, so the suite could not fail and several of my own "OK" reports were unverified. All now exit non-zero; re-running by COUNTING failures found two real breakages |
| `TX_POWER` was typed `int` | `0.5` truncated to `0`, so a QRPp station could not state its power. New `config.watts` type keeps fractions, whole numbers whole |
| `_power_now` ended with `int(watts)` | Half a watt became `"0 W"`, which `dbm_for_watts` refuses -- surfacing as "power unknown" from a radio answering perfectly. Keeps 3 decimals now (1 mW is 0 dBm) |
| `_draw_wspr` called the radio every draw | A CAT round trip with a 2 s timeout, five times a second: every arrow keypress waited on the radio. Cached 1.5 s, the discipline `_radio_now` already documented |
| The spot counts were re-parsed every draw | And again by `_menu_for` while a menu was open. Both cached, invalidated on write |
| `rigctld_client.mode()` returns a TUPLE | My hop-check compared it against a set of strings, so it could only ever report "could not read". Uses `mode()[0]` |
| `_key` read PTT back instantly | The FTX-1 had not reported it yet, so the deck keyed, read "not keyed", unkeyed and refused -- a brief click then "the radio did not key". Polls up to 600 ms |
| `tx next` plus the random choice transmitted twice running | The random choice is suppressed in any slot straight after a transmission. An explicit one-shot still fires: it was asked for |
| The ToT ended the whole session | It is a transmitter timer. It now disarms transmit and leaves receive, decode and hopping running; re-arming restarts the clock |

**Keys settled, and both were mine to get wrong:**

* **`Ctrl-B` is transmit inhibit**, from any screen. It was `Ctrl-I`, which IS
  byte 9, which IS `Tab` -- indistinguishable on any terminal and especially
  the console, where `modifyOtherKeys` does not exist. So `Tab` armed and
  inhibited the transmitter, including on a form where `Tab` means "next
  field". Byte 9 now toggles nothing.
* **`Ctrl-C` stops WSPR.** It already aborts an over on the conversation
  screen -- `curses.raw()` disables ISIG so byte 3 reaches `getch` -- while
  `Ctrl-X` means CLEAR everywhere on the deck. Using `Ctrl-X` for "stop" in
  one application was the inconsistency.

**Escape is a contract now, written into `docs/platform_design.md`:** one
level per press, by the route the operator actually walked (a menu stack,
not a fixed parent -- the WSPR band picker is reachable two ways and a fixed
parent has to be wrong for one of them), and **no Escape past the top of a
function may change state.** So mashing it always lands in the base state.

**`src/grid.py`** computes distance and bearing from two Maidenhead
locators, **validated against this station's own wsprnet rows**: inside
0.5 km on every six-character path from 498 to 6855 km. Shown on the spot
rows, never stored -- both are derivable from the two grids already in each
record.

**Layout, after two rounds of operator feedback:** only the counters row is
spread across the width; the toggles, power and level rows read better
packed. `HOP` is a toggle on the switch row, the interlock is `INH`/`INH off`
in the header corner, and the slot row says `to next: TX` with only the mode
highlighted -- `TX next` highlighted whole collided with the `TX NEXT`
toggle, which means something different.

### The ring-hop trap, in full

**Six test files hard-coded one `^O` from the boot screen** to reach the
digimodes or the conversation. WSPR made the ring four areas, so that hop
lands on WSPR and every scenario below it reads the wrong screen — 31
failures in `test_menu_arrows` alone, and the file that looked worst
(`test_console_keys`) was a *second* site in a file whose constant had
already been fixed. `test_area_ring.py` also asserts the ring's **size**
three times, which cannot hide behind a name.

A fifth area costs: one edit to the `TO_CHAT`/`TO_DIGI` constant in each of
`test_cold_boot`, `test_decode_park`, `test_screen`, `test_screen_toggles`,
`test_menu_nav`, `test_console_keys`, `test_state`, `test_menu_arrows`, plus
the three size checks in `test_area_ring`. **Grep for `\x0f` before
assuming the constants cover it.**

**The `_leave_cleanly` fix was confirmed on the hardware by that deploy.**
The journal now reads `Deactivated successfully` on a restart where every
earlier one read `code=exited, status=1/FAILURE`. So the shutdown path runs:
transmit aborted, decoder unparked, console palette restored. What is NOT tested there is starting WSPR for
real, because that stops fldigi and opens the sound card — the start path's
refusals are unit-tested instead.

### Three bugs the pty test found that the pure tests could not

All three were about key dispatch and screen transitions, which is the whole
reason that file exists:

* **The ring landed on WSPR without building the engines.** `_ring` set
  `self.screen = WSPR` directly, so `self.wspr` stayed None and every toggle
  reported `off` — including Decode, which defaults to on. It goes through
  `_open_wspr()` now.
* **`Esc` from the band picker went UP to the WSPR menu** when the operator
  had pressed `F3` from the screen. Same inconsistency fixed once already on
  the log screen: a picker reached from a screen returns to that screen.
  `wspr_band` has no `MENU_PARENT` entry; `wspr_danger` keeps one, because
  arriving there is deliberate.
* **A band key ADDED to the rotation instead of going to that band.** So
  pressing 20 m from a default of 40 m produced a two-band rotation. A
  number now selects that band alone and `+` then a number adds one — the
  same `c+n`/`d+n` shape the schema picker uses.

### And a vacuous assertion, for the third time this session

`check("the WSPR screen is drawn", "WSPR" in body)` **passed while the deck
was refusing to start**, because the error it printed named
`WSPR_LOG_PATH`. The underlying fault was mine: the WSPR settings were added
with `cfg.setdefault` but never to `config.SCHEMA`, so a conf naming them was
rejected outright. **A substring check against a screen that might be an
error message is not an assertion.** It now checks the header's shape and
that no `unknown setting` appears.

### What still needs the deck

* ~~`rigctld` while fldigi is stopped.~~ **VERIFIED 2026-10-17 and it
  works.** With fldigi stopped the client returned `connected: True`,
  `7038600.0`, `('PKTUSB', 3000)` and 0.5 W — identical to fldigi being up.
  `cyberdeck-rigctld.service` keeps the serial port, so WSPR's radio control
  is sound. That was the last structural assumption in the design.
  (An earlier run reported "radio could not be read"; that was the tool's
  own fault — `rigctld_client.py` had not been copied, the import failed,
  and a bare `except` reported it as an absent radio.)
* **A type 2 or type 3 decode off the air.** Both stations in the 2026-10-17
  capture sent type 1, so compound and hashed calls are still covered only by
  hand-written fixtures.
* **Transmit, into the dummy load**, once there is a TX path.

### Decisions not worth relitigating

Transmit and receive in one increment; `wsprd` as a subprocess; exclusive
while running with fldigi STOPPED (measured — the codec is exclusive);
rig control through `rigctld_client` because stopping fldigi takes its rig
control with it; upload armed by three operator conditions rather than
automatic; one fixed schema, no pickers; the four independent toggles; the TX
test tone is necessary and the RX calibration mode is not.

## Where it stands

**3994 checks across 55 files, all passing as of 2026-10-23** — a clean
serial run through `tools/run_tests.sh`, nothing edited while it was in
flight, nothing else touching fldigi. fldigi had been up about eleven hours
rather than freshly restarted, and was checked healthy first (`LISTEN 0 5`,
`fldigi.name_version()` answering in milliseconds) -- see the wedge note
below for why that check comes before believing any pty failure.

The 3146-check figure this replaced was measured 2026-10-18, before the seven
features from `docs/next_steps.md`. Those and the panel-session repairs
account for most of the 848 new checks: tuner 97, export 135, wsprmap 90, bandscreens
70, logfromchat 61, ring_editor 57, ring_order 54, bandplan 54, decall 50,
wsprsessions 42, mapscreen 40, backfill 39, fbdraw 37, txbuffer 8.

**Counts drift.** Take them from a run rather than from this paragraph --
`grep -c 'ALL PASS'` over the suite output, and the trailing total line --
and correct it here when they have moved.

Run it that way rather than looping over the files by hand. `run_tests.sh`
checks each file for its `ALL PASS` line, which is the only thing that proves
a file reached its end; counting `PASS` lines proves only that execution got
that far, and a file that dies two thirds of the way down still prints
plenty of them. `test_log_panel` needs its 1800-second timeout.

**Only one test process at a time, because there is only one fldigi.** The
six pty-driven files drive the real application against the real modem, and
two of them running at once fight over it: on 2026-10-22 a quick sweep
started alongside a full run reported `test_screen` failing on "fldigi
connected" and `test_state` failing three mode-change checks, and both files
passed in the serial run minutes later. A red pty file is worth nothing
unless it was the only thing running.

**A pty file that has not finished is not a file that failed.** The same
sweep put a 90-second timeout on every file and reported eight "failures",
all of which were files that needed longer. `run_tests.sh` has no per-file
timeout for this reason.

### `inactive` rigctld is usually the radio, and it does not come back

**Both of the deck's routes to the radio go through `cyberdeck-rigctld`** --
raw CAT from `rigctld_client` on port 4532, and fldigi's own frequency
control. So they fail together, which is what tells this apart from a bug in
either. On 2026-10-23 that surfaced as an auto tuner counting through a
sweep while the VFO never moved, and `VFO refused` on the digimode band
change, in the same session.

Two separate reasons it ends up `inactive`, and the status output tells them
apart:

- **`Duration:` present and `status=0/SUCCESS`** -- it ran and exited
  cleanly. **rigctld exits 0 when the serial device disappears**, and the
  shipped unit says `Restart=on-failure`, so systemd correctly does nothing
  and it stays dead until something starts it by hand. This is the common
  one: the radio was switched off mid-session.
- **"Condition check resulted in ... being skipped"** -- the unit never ran,
  because `ConditionPathExists` on the CAT device failed at boot.

```bash
systemctl status cyberdeck-rigctld --no-pager
ls -l /dev/serial/by-id/          # absent entirely = no USB serial at all
lsusb                             # is the CP2105 even enumerated?
```

**`/dev/serial/by-id/` missing as a directory means no USB serial device is
connected** -- udev creates it only when one is. That is the radio or the
cable, not the deck.

The durable fix is a drop-in clearing the condition and setting
`Restart=always` with `RestartSec=10` and `StartLimitIntervalSec=0`, so
rigctld returns within ten seconds of the radio coming back. It costs a
retry in the journal every ten seconds while the radio is off.

**Check this before reading the deck's own code.** The tuner now fails on
its first CAT command with "no rig control — is rigctld running?", which is
the question this answers.

### fldigi's RIG MODE persists between runs, and parks the decoder

`test_screen` failing on **"fldigi connected (modem in status)"** is usually
not a connection problem. The deck parks the modem when the rig reports a
voice mode -- that is `_watch_rig_mode` doing its job -- and a parked modem
leaves no name in the status line, which is what that check reads.

**`test_screen` and `test_menu_arrows` want OPPOSITE modes**, and for a
whole session neither set one: `test_screen` needs a data mode or the deck
parks the decoder, `test_menu_arrows` needs a voice mode to exercise the
`^B` refusal. Whichever ran last decided whether the other passed, which
cost four suite runs on 2026-10-23 before the pattern was seen. Both set
what they need now. **A pty test that depends on fldigi's state must set
it**, because fldigi keeps it between runs:

```bash
python3 -c "import xmlrpc.client as x; \
  print(x.ServerProxy('http://127.0.0.1:7362/').rig.get_mode())"
```

`USB` is the fault. Put it back and the file passes:

```bash
python3 -c "import xmlrpc.client as x; \
  x.ServerProxy('http://127.0.0.1:7362/').rig.set_mode('PKTUSB')"
```

The transcript full of garbage `RX` lines in that capture is unrelated and
normal: a live fldigi with no signal decodes noise.

### A wedged fldigi looks exactly like a broken deck

**Before believing any pty failure, check that fldigi is still answering.**
After about fourteen hours up and a long day of test runs, fldigi on
2026-10-22 kept its socket open and stopped answering XML-RPC: every call
blocked until the client timed out. The deck then spends its whole main loop
in `poll()`, never reads the keys the harness sent inside the settle window,
and the screen stays on whatever it booted to. `test_wspr_panel` reported 90
failures and `test_wifi` five, and **a pristine `git archive HEAD` tree
reported the same 88 failures**, which is what proved it was not the working
tree.

The symptom on screen is `NO MODEM` in the header and a deck that ignores
`^O` and `^P`. The way to tell in one command:

```bash
ss -ltnp | grep 7362      # a full accept queue -- "LISTEN 6 5" -- is wedged
```

A healthy fldigi shows `LISTEN 0 5` and answers `fldigi.name_version()` in
milliseconds. Restart it with `tools/dev-fldigi.sh stop` then
`tools/dev-fldigi.sh`, and re-run; do not go looking for the bug in `_ring`.

**The real cost of a wedge is not the noise, it is what the noise hides.**
With fldigi wedged, `test_wspr_panel` reported 90 failures. With it healthy
the same file reported **one** -- and that one was genuine: `^P` off the WSPR
screen was asserted to wrap round to DECK & RIG, which was true while the
ring was four areas and WSPR was last, and became wrong when the band plan
joined the ring behind it. Eight other files were fixed for that same
ring-hop at the time; this one was missed because the whole file was red and
the single true failure was buried in the spurious ones. **Fix the
environment first, then read the failures.**

The 2379-check figure this line used to carry was measured 2026-10-16 on
branch `add-wspr`, before WSPR's own tests and the audio-level work landed.
The WSPR modules account for 255 of those: `test_wspr.py` (the encoder, the
parser and dedupe), `test_wsprsched.py` (slots, hopping, the time-out) and
`test_wsprnet.py` (the uploader, with no network touched).

`main` was at 2124 checks across 29 files when the logger work merged.

The line this replaced claimed "1893 checks across 25 files, all passing as
of 2026-10-15", and that was not true when it was written. Seven files were
red: `test_log_panel` and `test_menu_arrows` from the single-log refactor and
the schema rename, and five — `test_screen`, `test_screen_toggles`,
`test_menu_nav`, `test_state`, `test_wifi` — from the boot screen moving to
DECK & RIG, which left every scenario that assumed the deck opens on the
conversation reading the wrong screen. **A suite summary is only as good as
the run behind it**: count the files that printed `ALL PASS`, because a file
that dies on an import prints no failures at all, which is how
`test_menu_arrows` went a whole session with every check in it skipped.

The logger merged to `main` on 2026-10-14; `pre-logger` tags the commit
before it, which is the rollback point for a deck that misbehaves. Run the
tests serially and **do not edit `src/` or `tests/` while a run is in
flight**: three successive runs during one session each reported a different
single failure, because what executed was not what was on disk. The deck has
worked real DX on PSK31 and RTTY. A DS3231 real-time clock is fitted and
verified across a power cut with NTP disabled. The WiFi screen joins networks
from the panel.

The QSO logger merged to `main` on 2026-10-14 and is one of the three areas
on the ring — there is no key that jumps to it. On the log screen the arrows
move between fields and Enter logs; the arrows also select a logged contact,
Enter opens it, and every field of it is editable, `d` deletes it. F1 opens
the logging menu, F2 the activities list.

An ACTIVITY is a named operating session; a LOG SCHEMA is the template of
fields it uses. The word in the interface is "schema" — "activity type" was
renamed on 2026-10-16 and survives only as internal identifiers
(`ACTIVITY_TYPE`, `activities.ActivityType`). Creating a schema happens on the
SCHEMA PICKER (`F1` → `v`), not on a menu line: `c` + number copies one, `n`
starts one with no fields, `d` + number deletes one, and the picker has ONE
exit — it closes to the log screen however it was reached. Naming a new
activity leads straight into that picker, so the flow is name → schema →
reference → log.

**One log, with sessions inside it** (§7f). The master log is the only file;
an activity is a label on its records and the activities screen is a filter
over it, keyed by `(activity, activity_start)` — an ISO timestamp pinned at
session start, so an activation running from 23:50 to 00:30 is one session
rather than two. Deleting an activity forgets the label from the deck's list
(`FORGOTTEN_SESSIONS` in the state file) and changes no record, so the
contacts stay exportable and logging under that name again brings the session
back. **`F1` → `z` is the danger zone** (§7h), which is the only place
contacts are destroyed in bulk: forget all activities (destroys nothing),
delete this activity's QSOs, delete every QSO. Each states its count and each
asks first. It exists so a clean slate is available on demand — without it
there is no telling a state the current software can reach from one left
behind by an earlier iteration.
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

**Three first-class areas, on branch `function-ring`.** Settings, logging and
digimodes are peers. **Ctrl-O** and **Ctrl-P** walk the ring, which reads as a
strip: `settings | log | digimodes`, wrapping, so every area is one keystroke
from both others. Adjacent keys, O left of P, and both were unbound — which is
why they won over the alternatives:

- **Ctrl-M cannot be bound at all.** It IS byte 13, carriage return, so no
  terminal distinguishes it from Enter.
- **Ctrl-N** was the jump to the log and is now free; the ring reaches every
  area, so a second way in was one key spent on nothing. Ctrl-E, G, K and V
  are the other unbound control characters.
- **Home/End** are the cursor-to-the-ends keys in all three places text is
  typed (log field, chat compose line, config editor), and since Left/Right
  moved to field-switching they are the last in-field cursor control there is.
- **PgUp/PgDn** page or scroll in four places: the transcript, the contact
  list, the field selector and the all-modes list. The "a screen is a page"
  mnemonic is good and the collision is what beat it.
- **Ctrl-O is `VDISCARD`** in the tty line discipline and can be eaten by it
  while IEXTEN is set. It is not, on this deck — `tests/test_area_ring.py`
  drives both keys through a real pty for exactly that reason. Do not take
  that on trust if the terminal setup changes.

Key choices beyond this are deliberately out of scope until someone does them
as one holistic pass; piecemeal rebinding is how a keymap stops being learnable.

**Arrow keys were ruled out by terminfo, and this is why it is written down:**
`infocmp linux` has NO modified cursor-key entries at all, and
`xterm-256color` defines only the SHIFT forms (`kLFT=\E[1;2D`). So Alt+arrow
reaches the framebuffer console as Esc followed by KEY_LEFT — and Esc is
load-bearing on every screen — while Shift+arrow would work in the laptop rig
and be a dead key on the deck, which is the exact fault class
`tests/test_console_keys.py` exists to catch. Control characters are 7-bit and
arrive identically everywhere. Still free: Ctrl-E, G, K, V. **Ctrl-Z is not
free** — linux terminfo maps `kspd=^Z`.

| | F1 | F2 | F3 | F4 | F5–F12 |
|---|---|---|---|---|---|
| Settings | DECK & RIG menu | Station | Band | color | — |
| Logging | logging menu | Activities | Activity type | color | — |
| Digimodes | DIGIMODES menu | Tuner | Mode | color | Memories |

F1 is always the menu for the area you are in, F4 is always the color cycle,
and F2 and F3 are always that area's two main sub-views. F5–F12 were already
scoped to the digimode screen — they sit in the fallthrough below every screen
guard, so a note in an earlier version of this file claiming they were global
was wrong.

Four things that are load-bearing:

- **`menus.ROOT` is gone, split into `menus.DIGI` and `menus.DECK`.** `ROOT`
  remains as an alias for `DIGI` so anything still asking by that name gets the
  menu it used to get. A line belonging to one area is not on another's menu.
- **`menus.MENU_PARENT` is what Esc walks up.** A menu absent from it is
  top-level and Esc closes it, landing on its own area's screen — so backing
  out can never cross an area boundary, which it did when every menu's parent
  was one shared root.
- **`AREA_OF` must list every screen, and is defined after all of them.** It
  referred to `ACTS` and `CONFIRM` before those were assigned, which raised
  `NameError` on import — and `py_compile` does not catch it, because compiling
  is not running. Only the pty tests saw it.
- **`AREA_LOCKED`** keeps the ring out of a confirmation, the pairing screen,
  the WiFi screen and the no-keyboard notice. The ring is handled after the
  editor and those screens so a half-typed field or an unanswered question
  cannot be cycled away from and silently discarded.

Settings is a **screen** (`SET`), not just a menu, because an area needs
somewhere to land: a menu is drawn over whatever screen was current, so
"arriving at the settings" used to mean arriving at the digimode screen with a
menu on top. It is read-only and answers "what is this station set to" in one
place, which nothing on the deck could do before — the callsign was in one
menu, the rig in another and the log in a third.

`docs/qso_log_design.md` carries the design and the open decisions.
**`docs/logger_branch_deploy.md` carries the deploy and recovery sequence**,
written while the logger was a branch; `docs/scratch_notes.md` carries the
current one. The two most expensive things in it still apply: the conf and the
code must move together, because a `config.py` that predates a key refuses it;
and `systemctl is-active` reports `active` for a unit crash-looping every
three seconds, so `journalctl -u cyberdeck-ui` is the only health check.

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
