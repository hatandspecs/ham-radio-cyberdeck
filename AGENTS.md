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
| `slides/cyberdeck-talk.md` | The talk, as Marp markdown; `slides/diagrams/` holds the mermaid sources |

## Things that cost a lot to rediscover

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

1300 checks across 26 files, all passing (one pty check flakes per run; see
above). The deck has worked real DX on PSK31 and RTTY. A DS3231 real-time
clock is fitted and verified across a power cut with NTP disabled. The WiFi
screen joins networks from the panel.

A general-purpose QSO logger is on the local branch `logger` (2026-10-11),
uncommitted, and **reachable from the panel**: Ctrl-N opens a tabbed entry
form, Enter logs, Esc returns. `tests/test_log_panel.py` drives the real
application through a pty under TERM=linux as well as xterm and checks a
contact reaches the disk. Not yet wired: the root-menu entry, so logging is
switched on and the activity chosen in `cyberdeck.conf` only. The pure cores — `src/qsolog.py`, `src/callbook.py`,
`src/qrzlog.py`, `src/lotw.py`, `render.log_screen`, `menus.log_menu`,
`tools/qso.py` — are written and tested offline; nothing is wired into
`cyberdeck.py` yet, so the feature is unreachable from the panel.
`docs/qso_log_design.md` carries the design and the open decisions.

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
