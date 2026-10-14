# The `logger` branch on the deck — deploying it, and getting back

Working notes for the branch that adds the contact log. Two things live here:
the deploy sequence that is known to work, and the recovery sequence that puts
the deck back on `main` when it does not.

Everything in this file was measured on the deck, not reasoned about. Dates
mark when, because a note without one cannot be checked.

---

## 1. The recovery sequence — back to a working deck

This is first because it is the thing wanted in a hurry.

**Both halves have to move together.** `main`'s `config.py` refuses the keys
the logger adds (`ANTENNA`, `CALLBOOK`, `DUPE_CHECK`, `LOGGING`, …) because an
unknown key is a refused key. New conf plus old code is a `ConfigError` at
startup and a dead panel — reverting only the `.py` files produces exactly the
failure the revert was meant to undo.

On the laptop:

```bash
cd ~/git_repos/keyboard-to-keyboard-cyberdeck
rm -rf /tmp/mainsrc && mkdir -p /tmp/mainsrc
git archive main src | tar -x -C /tmp/mainsrc
rsync -av /tmp/mainsrc/src/ deck@cyberdeck.local:/tmp/deckrevert/
```

Prints a file list ending in `sent … bytes`. Note `/tmp/deckrevert` is in
`/tmp` on the deck, so a reboot clears it — the rsync is not optional on a
deck that has been power-cycled since the last revert.

On the deck:

```bash
sudo cp /tmp/deckrevert/*.py /opt/cyberdeck/
sudo sed -i '/^ANTENNA\|^TX_POWER\|^LOGGING\|^ACTIVITY\|^EXCHANGE_TX\|^MY_PARK\|^CALLBOOK\|^DUPE_CHECK\|^OPERATING/d' /opt/cyberdeck/cyberdeck.conf
sudo systemctl restart cyberdeck-ui
systemctl is-active cyberdeck-ui
```

Prints `active`, and the panel comes up on the conversation screen.

`is-active` printing `active` is **not** proof of a working deck — see §4.

---

## 2. The deploy sequence — `logger` onto the deck

The deck's own `cyberdeck.conf` is never copied over — see below. Only the
modules and the credentials move.

On the laptop:

```bash
cd ~/git_repos/keyboard-to-keyboard-cyberdeck
git checkout logger
rsync -av src/*.py cyberdeck.secrets deck@cyberdeck.local:/tmp/deckupd/
```

On the deck — **the `chown` is load-bearing**:

```bash
sudo cp /tmp/deckupd/*.py /opt/cyberdeck/
sudo cp /tmp/deckupd/cyberdeck.secrets /opt/cyberdeck/
sudo chown "$(id -un):$(id -gn)" /opt/cyberdeck/cyberdeck.secrets
sudo chmod 600 /opt/cyberdeck/cyberdeck.secrets
```

Then add the logger's settings to the conf that is already there. Delete and
re-append rather than edit, so running it twice is the same as running it once
and no key ends up duplicated. `CALLSIGN`, `LOCATOR` and `RIG_BANDS` are left
alone:

```bash
sudo sed -i '/^RIG *=\|^ANTENNA *=\|^TX_POWER\|^LOGGING *=\|^ACTIVITY *=\|^EXCHANGE_TX *=\|^MY_PARK *=\|^CALLBOOK *=\|^DUPE_CHECK *=\|^OPERATING *=/d' /opt/cyberdeck/cyberdeck.conf
sudo tee -a /opt/cyberdeck/cyberdeck.conf >/dev/null <<'EOF'

# --- Station equipment, logged on every contact ---
RIG = FTX-1
ANTENNA =
TX_POWER_MAX = 10
TX_POWER = 0

# --- Logging ---
LOGGING = yes
ACTIVITY =
EXCHANGE_TX =
MY_PARK =
CALLBOOK = yes
DUPE_CHECK = band+mode
OPERATING = auto
EOF
```

Then the preflight, before the restart, because a restart into a broken
configuration takes the console with it:

```bash
cd /opt/cyberdeck && python3 -c "
import config, activities, qsolog, logform, callbook, lotw
s = config.load()
print('conf ok:', s['CALLSIGN'] or '(NO CALLSIGN)', s['LOGGING'], s['CALLBOOK'])
print('activities:', sorted(activities.load()))
print('secrets readable:', bool(s['HAMQTH_USER']))
for n in config.NOTES: print('NOTE:', n)
"
```

Should print `conf ok: KD3CCO yes yes`, three activity names, and
`secrets readable: True`. Anything else — a traceback, `(NO CALLSIGN)`, a
`NOTE:` line — is a reason to fix before restarting, not after.

Only then:

```bash
sudo systemctl restart cyberdeck-ui
systemctl is-active cyberdeck-ui
```

### Why the conf is patched and not copied

`cyberdeck.conf` and `cyberdeck.secrets` are both gitignored, so neither is on
any branch and neither is restored by a checkout. As of 2026-10-11 the copy in
the laptop checkout has `RIG`, the logging keys and the power ceiling, and has
**no `CALLSIGN`, `LOCATOR`, `NAME` or `QTH`** — it describes no deck in
particular. Rsyncing it over the deck's conf wipes the station identity, and
the log then records `my_call=` on every contact, which is a ruined log rather
than a visible failure.

Worth checking after any deploy, and after any earlier one that did copy it:

```bash
grep -E '^(CALLSIGN|LOCATOR)' /opt/cyberdeck/cyberdeck.conf
```

Two lines, both filled in. Nothing printed means they were overwritten away.

### The configuration the logger needs

```
RIG = FTX-1
ANTENNA =
TX_POWER_MAX = 10        # 6 internal battery, 10 external, 100 with SPA-1
TX_POWER = 0
LOGGING = yes
ACTIVITY =               # blank = general; POTA, CONTEST, or a saved name
EXCHANGE_TX =
MY_PARK =
CALLBOOK = yes           # sends every call worked to a third party
DUPE_CHECK = band+mode   # off | call | band | mode | band+mode
OPERATING = auto
```

`TX_POWER_MAX` scales the CAT power reading. Verified on the radio
2026-10-11 at three points: 6 W read `0.6`, 10 W read `1.0`, 0.5 W read
`0.05` — linear from zero, so one multiplier is correct.

---

## 3. Reading what went wrong

stderr goes to the journal and not to tty1, deliberately: a traceback painted
onto the panel is wiped by the restart three seconds later.

```bash
journalctl -u cyberdeck-ui -n 60 --no-pager
```

The last traceback in that output is the failure. `restart counter is at N`
with N climbing is a crash loop.

---

## 4. Failures seen, and what each looks like from the operator's chair

### A dead frame, with typed keys overwriting it

**Seen 2026-10-11.** `systemctl is-active` printed `active`. The panel showed
a cursor blinking at the bottom of the screen; typed keys overwrote the
existing text as far as the `menu` label in the transcript footer.

Cause: `PermissionError: [Errno 13] Permission denied:
'/opt/cyberdeck/cyberdeck.secrets'`, raised by `config.load()` before
`curses.wrapper` ever ran. `sudo cp` had made the file `root:root` and the
documented `chmod 600` then locked the service user out of its own
credentials. The unit crash-looped every three seconds — restart counter 29 by
the time the journal was read — and `is-active` caught it inside a start
window. tty1 was bare console between crashes, which is why keystrokes echoed
over the last frame the program had drawn.

Fixed twice: the `chown` in §2, and in the code — `config._load_secrets` now
records an unreadable secrets file in `config.NOTES` and continues. Credentials
are optional on every deck and the panel is the device, so an unreadable
credentials file costs callbook lookups and nothing else. The note is printed
to stderr at startup, so the journal says why lookups will fail. Pinned by
`tests/test_secrets.py`.

**The general lesson: `is-active` is not a health check.** A crash-looping unit
reports `active` about a third of the time. `journalctl` is the check.

### A blank screen immediately after an update

New `cyberdeck.conf` on the deck with `main`'s `config.py` installed. An
unknown key is refused, so `load()` raises `ConfigError`, `run()` prints to
stderr and exits 1. Recovery is §1 — *both* halves.

### The panel never comes back, and the console is unusable

Caused by advice to stop the unit owning tty1 and run another program there.
Do not; there is nowhere to type afterward. Work over SSH from the laptop.

### `rigctld --version` reports 4.6.2 on a deck running 4.7.2

The binary at `/usr/local/bin` links the system library unless
`LD_LIBRARY_PATH=/usr/local/lib` is set, which the unit sets and an
interactive shell does not. The running version comes from
`sudo grep libhamlib /proc/$(pidof rigctld)/maps`, not from `--version`.

---

## 4a. Uploading is always manual

**Nothing on the deck uploads a contact anywhere, and nothing on a timer
does.** A deck being tested is full of contacts that must not reach anyone's
permanent record, so "I did not press anything" has to be a complete defense.

What exists:

| Action | Where | What it does |
|---|---|---|
| `Export ADIF` | logging menu, `a` | writes `qso.adi` beside the log |
| `Export + print the LoTW command` | logging menu, `t` | writes the ADIF, prints the `tqsl` command, runs nothing |
| `qso.py lotw` | laptop | the same export and printed command |
| `qso.py lotw --upload` | laptop | **the only thing in this project that sends** |

A `Upload to QRZ  n waiting` item used to sit on the logging menu. It had no
handler, so the line did nothing, and "n waiting" described a queue that
drains by itself — exactly the impression this must not give. It is gone.

`tests/test_menus.py` pins this as a property of the source rather than as a
comment: `cyberdeck.py` must not import `qrzlog`, must not call any
`upload(`, and the menu must offer no QRZ item and no "waiting" count even
when a QRZ key is configured. A comment does not fail when somebody wires a
key to an uploader.

---

## 4b. The deck does not change the radio's mode

**It used to**, at startup and on every band change, from `RIG_MODE`. The
reasoning was right about the radio — digital work is upper sideband on every
band, which is easy to forget on 40 and 80 — and wrong about whose decision it
is. A deck used as a logbook beside a microphone would put the radio into a
data mode nobody asked for, and a deliberate mode choice was reverted by a
band change.

Now: the deck reports the rig's mode and never writes it. Its side of the
bargain is the transmit interlock — `Ctrl-I` refuses to arm transmit while the
radio is positively reading a mode digital work cannot use, and says which
mode it is and that the radio is where to change it.

It refuses only on a positive reading. A rig that cannot be read at all still
arms, because taking transmit away from every deck without CAT control is a
worse failure than the one being prevented. `qsolog.RIG_DATA_MODES` is the
list, shared with the logged-mode logic so the two cannot drift.

`RIG_MODE` stays in the schema — an existing conf still loads, and the value
records what this station's data mode is — but nothing writes it to the radio.

---

## 5. Where the branch stands

Working on the deck as of 2026-10-11:

- Ctrl-N from the conversation screen opens the log screen.
- The tabbed entry form: Tab and Shift-Tab between fields, frequency and mode
  prefilled from CAT, reports defaulted from the mode, sticky comment, sticky
  own-exchange, next serial counted from the log.
- Ctrl-Z restores a prefill typed over by accident. Bound as
  `(26, curses.KEY_SUSPEND)` — `TERM=linux` defines `kspd=^Z`, so matching
  only byte 26 ships dead on the panel.
- F1 on the log screen opens the logging menu: activity, dupe rule, callbook,
  ADIF export, and activity copy → fields → order → name → save.
- A contact reaches `qso.log` carrying `my_rig`, `my_antenna` and a CAT power
  reading.
- Ctrl-X throws away the staged contact, keeping the park, exchange, comment
  and frequency — those describe the session, not the station.
- The callbook fills name, QTH and grid, and the answer is provisional: a
  changed callsign drops it, a newer answer replaces it, and anything the
  operator typed outranks it.
- The contact list shows only the selected activity's contacts, under named
  columns, and the columns follow the activity rather than only the contacts
  already logged.
- **An activity and an activity type are different things.** A *type* is a
  template of fields — General, POTA, Contest, or one built on the panel. An
  *activity* is one operating session that uses a type, carries the
  operator's name for it, and has a log file of its own. The record stores
  both: `activity` is the name, `activity_type` is the template.
- An activity's file is `activities/<name>_<YYYY-MM-DD>.log`, dated **once**
  from the DS3231 at creation and then left alone. Re-deriving it would fork
  a contest weekend across UTC midnight, so the path is stored with the
  activity and read back. Same name, later day, is a new activation; same
  name, same day, resumes.
- Serials and the duplicate check are scoped to the **activity**, so two
  weekends of the same QSO party each count from one.
- `F2` on the log screen lists activities: resume one, start one (`n`), or
  delete one (`d`). `d` then a number on the type picker deletes a type.
  Both ask first, on a screen of their own, and say what will be lost.
  Deleting an override of a built-in restores the built-in.
- The contact list scrolls — a touchscreen drag, as the transcript does, or
  PgUp/PgDn. The heading shows `-N` when the newest contact is off screen.
- The frequency is shown at the radio's own resolution, `7.185.000`, and
  `qsolog.parse_freq` reads that back as well as a hand-typed `7.185`.
- The callsign and any reference are held in upper case however they are
  typed. A grid square is not — Maidenhead is conventionally mixed case.

Not yet confirmed on hardware:

- `PC;` on the internal battery at maximum — whether the radio reports
  `PC1006;` or `PC1010;` with the 6 W cap in force.
- Why `f` reads 7.070 MHz while `FA;` reads 146.850 MHz. Different VFOs, and
  whether `set_frequency()`'s `FA` write targets the intended one.
- The callbook chain against a live network from the deck rather than the
  laptop.

`docs/logging_tutorial.md` and its screenshots still show the one-line entry
form the tabbed form replaced.

---

## 6. Tests

```bash
cd ~/git_repos/keyboard-to-keyboard-cyberdeck
for t in tests/test_*.py; do python3 "$t" >/dev/null 2>&1 || echo "FAIL $t"; done
```

Prints nothing when green. `tests/test_log_panel.py` drives the real program
through a pty under both `TERM=linux` and `TERM=xterm`; the linux console
entry is the one that matters, since it captures control bytes that xterm
passes through.

What a pty cannot catch is the class of fault in §4: the program never reached
curses. The preflight in §2 is the check that covers it.

**`tests/test_menu_arrows.py` and `tests/test_screen.py` read the repository's
own `cyberdeck.conf`** — the harness only uses a conf of its own when a test
passes one. So a `cyberdeck.conf` in the checkout with no `CALLSIGN` fails
`and its current value` in the Station-menu check. That happened on
2026-10-11, after a revert dropped the station identity out of the file, and
it is the same missing `CALLSIGN` that would have gone to the deck. The test
is right to fail; the fix is in the file, not in the test.
