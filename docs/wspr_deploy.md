# Getting the WSPR capability onto the deck

Branch `add-wspr`. Nothing here transmits. The decoder is installed and
benchmarked; the capture, the beacon and the screen do not exist yet.

## Done, 2026-10-16: it cost 1 MB

Carried out on the deck, and the numbers are the argument for doing it this
way:

| | |
|---|---|
| Deck | Raspbian **trixie**, **armhf** (32-bit) |
| Package | `wsjtx 2.7.0+repack-1`, a **2.2 MB** download — never installed |
| `wsprd` on armhf | **55 KB** (102 KB on x86_64) |
| Missing libraries | **exactly one**, `libgfortran.so.5` |
| `libfftw3-single3` | **already present** — fldigi pulls it in |
| Installed cost | `libgfortran5`, 257 KB down, **1 MB on disk** |

So the whole of WSPR decode cost one package and a megabyte, against the
36 MB the `wsjtx` package installs. The predicted library names were right,
but §2 still discovers them rather than trusting that — it was right on
trixie/armhf and is not promised anywhere else.

**`wsprd 2.7.0` on the deck, `3.0.1` on the laptop.** The fixtures in
`tests/fixtures/` came from 3.0.1, so the parser is written against a
version the deck does not run. The sync vector is fixed by the WSPR protocol
and will not have moved, but the stdout FORMAT is not promised between
versions — and §4's benchmark is what tests it, because it encodes with this
project's encoder and decodes with the deck's own `wsprd`. Four decodes
there means both the encoder and the parser agree with 2.7.0 as well.

---

**`wsprd` was not on the deck** before this, and the deck must not install
`wsjtx` to get it. `ldd` says `wsprd` is a 100 KB binary linking
`libfftw3f`, `libgfortran`, `libm`, `libc` and `libgcc_s` — no Qt, no Hamlib,
no audio library, no X. The package is 36 MB installed. On a 512 MB board
whose whole design avoids a desktop stack, the binary and two small runtimes
are what goes on.

---

## 1. On the laptop — everything it has to do, once

```bash
cd ~/git_repos/ham-radio-cyberdeck
git rev-parse --abbrev-ref HEAD
rsync -av src/wspr.py src/wsprsched.py src/wsprnet.py tools/wspr_bench.py \
  deck@cyberdeck.local:/tmp/deckupd/
```

Prints `add-wspr` and four files sent. **The laptop is done.** Everything
below is on the deck, in order — an earlier version of this runbook
interleaved the two machines and sent the operator back and forth three
times for a job that needs one switch.

---

## 2. On the deck — get `wsprd` and discover what it needs

**Discover the dependencies rather than naming them.** Package names differ
between Debian releases, and a name from memory is how a build breaks on the
one version nobody tested. Extract first, then ask the deck's own `ldd`.

```bash
cd /tmp
apt-get download wsjtx
mkdir -p wsjtx-x && dpkg-deb -x wsjtx_*.deb wsjtx-x
ls -la wsjtx-x/usr/bin/wsprd
ldd /tmp/wsjtx-x/usr/bin/wsprd
```

Prints a binary of roughly 100 KB, then its library list. **Any `not found`
lines are the dependency list** — expect at most two, the single-precision
FFTW runtime and the gfortran runtime. No `sudo` and nothing installed yet.

If `apt-get download` cannot find the package, stop — the archive does not
carry it and §5 is the route instead.

---

## 3. On the deck — install the libraries and the binary

```bash
sudo apt-get install -y --no-install-recommends \
  libfftw3-single3 libgfortran5
sudo install -m 755 /tmp/wsjtx-x/usr/bin/wsprd /usr/local/bin/wsprd
ldd /usr/local/bin/wsprd | grep -c 'not found'
wsprd 2>&1 | head -3
```

Install whatever §2 actually reported missing; the two above are the expected
names on Debian. `--no-install-recommends` matters: without it apt pulls
suggestions this board has no room for.

The `grep -c` should print `0`, and `wsprd` should print its usage beginning
`Usage: wsprd [options...] infile`. If `ldd` still says `not found`, the
missing library is named there and nothing else works until it is installed.

---

## 4. On the deck — the deck's own modules, and the benchmark

Three pure modules. **No service restart**: nothing in `cyberdeck.py` imports
them, so the deck behaves exactly as it did before.

```bash
sudo cp /tmp/deckupd/wspr.py /tmp/deckupd/wsprsched.py \
        /tmp/deckupd/wsprnet.py /opt/cyberdeck/
cd /opt/cyberdeck && python3 -c "
import wspr, wsprsched, wsprnet
print('encoder  :', len(wspr.symbols('KD3CCO', 'FN10', 37)), 'symbols')
print('sync     :', len(wspr.SYNC), 'values,', sum(wspr.SYNC), 'ones')
print('5 W      :', wspr.dbm_for_watts(5), '(37, True) expected')
print('3 W      :', wspr.dbm_for_watts(3), '(33, False) expected')
print('schedule :', wsprsched.Schedule().timeout_minutes, 'minute default')
print('endpoint :', wsprnet.URL)
"
```

Should print 162 symbols, 162 sync values with 63 ones, `(37, True)`,
`(33, False)`, a 60-minute default and the wsprnet post path. An import error
means a file did not copy.

Then the benchmark, which answers the two measurements the design is missing.
It writes a WAV to a temporary directory, decodes it, and deletes it. **It
does not open the sound card, key the radio or touch the network**, so it is
safe with everything else running — which is also the pessimistic memory
case, since WSPR will stop fldigi.

```bash
mkdir -p /tmp/wsprbench/src /tmp/wsprbench/tools
cp /tmp/deckupd/wspr.py /tmp/deckupd/wsprsched.py /tmp/deckupd/wsprnet.py \
   /tmp/wsprbench/src/
cp /tmp/deckupd/wspr_bench.py /tmp/wsprbench/tools/
sudo apt-get install -y --no-install-recommends time
cd /tmp/wsprbench && python3 tools/wspr_bench.py
free -m
```

Prints the machine, how long generating a window took, then a line per
decoder pass: the time, the number of decodes, the peak RSS, and the four
beacons it found. **Expect four decodes in each pass** — if deep search finds
fewer than normal search, something is wrong with the window rather than with
`wsprd`.

For reference, the same benchmark on an x86 laptop: **3.9 s** normal,
**8.9 s** deep, **22 MiB** peak, window generated in **3.1 s**. The slot is
120 s and a decode may overlap the next capture, so the deadline is 120 s and
not the 6 s gap between windows.

The `free -m` gives the headroom with fldigi still up. 22 MiB against
whatever `available` reports is the question §13 of the design asks.

**The generation time is the figure to watch.** 3.1 s on x86 is pure
interpreted float arithmetic, and it is the number most likely to misbehave
on a 1.4 GHz A53. If it comes back at thirty seconds, the transmit path needs
the sample generation out of Python, which is a design change rather than a
tuning one — better known before the beacon is written than after.

## 4a. On the deck — the audio device, measured

Findings from 2026-10-16, recorded so the next session does not repeat them.

**The codec is exclusive and fldigi must be stopped.** `arecord` with fldigi
up fails "Device or resource busy", and `arecord -l` shows `Subdevices: 0/1`.
There is no `dmix`/`dsnoop` to share through — `/etc/asound.conf` and
`~/.asoundrc` are both absent. With fldigi stopped the capture succeeds
exactly: 5 s at 12 kHz mono is 120,044 bytes.

**The device is card 1**, a C-Media `USB Audio Device`, the only capture
device on the board. **`plughw:1,0` at 12000 Hz mono 16-bit works
directly** — ALSA converts from the codec's native rate, so there is no
resampling to write.

**The capture gain is correct as shipped.** On 7.038600 MHz with an antenna,
ATT off, IPO, DATA-U, a capture reads **-36.8 dBFS** and `wsprd` decodes:
`WW0WWV DN70 30` at -25 dB and `KC0MVF EN13 30` at -26 dB, 1453 and 1515 Hz
above the dial. No gain change is needed.

An earlier reading of **-59.7 dBFS** off the same path was taken with the
radio on a **dummy load** — a terminated antenna port with no signal in it,
which is what that figure measures. A level judged against a dummy load is
not a level.

**AUTO GAIN CONTROL ships ON and must be turned off**, and that conclusion
does not depend on there being a signal. AGC compresses a constant-envelope
signal whose amplitude carries no information and corrupts the SNR figures
`wsprd` reports.

To look at the mixer:

```bash
amixer -c 1
amixer -c 1 contents | grep -A6 -i 'capture\|mic'
```

Then, with the radio on and tuned to a band with activity:

```bash
sudo systemctl stop cyberdeck-fldigi
sleep 2
amixer -c 1 set 'Auto Gain Control' off
amixer -c 1 set 'Mic' 35 capture
cd /tmp && arecord -D plughw:1,0 -f S16_LE -r 12000 -c 1 -d 5 louder.wav
python3 tools/wspr_level.py /tmp/louder.wav
sudo systemctl start cyberdeck-fldigi
```

The control name varies between codecs; `amixer -c 1` is what says which it
is here. **This is one-time station setup, not something the deck does per
session** — but it has to be right before the receive path can be judged,
because a capture that decodes nothing because of a mixer setting looks
exactly like a capture path that does not work.

## 4b. On the deck — the polkit rule WSPR cannot work without

**WSPR stops fldigi to take the codec, and `cyberdeck-ui` runs as `deck`.**
Without authorization for that, fldigi keeps the codec, every `arecord`
fails `audio open error: Device or resource busy`, and a session runs its
slot clock for an hour decoding nothing.

**sudo is not the route.** Measured on the deck, 2026-10-17: a sudoers
`NOPASSWD` rule for `systemctl stop cyberdeck-fldigi` parses, and
`sudo -u deck sudo -n systemctl stop cyberdeck-fldigi` succeeds from a login
shell — and the identical call from inside `cyberdeck-ui.service` still
leaves fldigi holding the codec. The service has no tty and no PAM session,
and its `CapabilityBoundingSet` is narrowed to `CAP_SYS_TTY_CONFIG`, so the
setuid helper cannot hold what it needs after becoming root.

**polkit is**, and it is the route this deck already uses for WiFi — see the
comment at the top of `polkit/10-cyberdeck-networkmanager.rules`, which
states the same failure in full: a systemd service has no seat and no
session, polkit sees a subject that is neither active nor inactive, and the
call falls through to `auth_admin` with no agent to ask.

`polkit/10-cyberdeck-services.rules` is scoped to one user, one action, one
unit and three verbs. **Notably not `cyberdeck-ui` itself**, which would let
the terminal stop the thing asking.

On the laptop:

```bash
cd ~/git_repos/ham-radio-cyberdeck
rsync -av polkit/10-cyberdeck-services.rules deck@cyberdeck.local:/tmp/
```

On the deck:

```bash
sed 's/@DECK_USER@/deck/' /tmp/10-cyberdeck-services.rules \
  | sudo install -D -m 644 /dev/stdin \
    /etc/polkit-1/rules.d/10-cyberdeck-services.rules
sudo systemctl restart polkit
```

Then verify as the service user, which is the only account the answer
matters for. `systemctl` with no `sudo` is the call the deck makes:

```bash
sudo -u deck systemctl stop cyberdeck-fldigi
systemctl is-active cyberdeck-fldigi
sudo -u deck systemctl start cyberdeck-fldigi
systemctl is-active cyberdeck-fldigi
```

Nothing, `inactive`, nothing, `active`. An `Interactive authentication
required` from either `sudo -u deck` line means the rule is not in effect:
check that `polkit` restarted, and that the unit name in the rule matches
`systemctl list-units 'cyberdeck*'`.

A sudoers file from an earlier attempt grants privileges nothing uses and
can be removed:

```bash
sudo rm -f /etc/sudoers.d/cyberdeck-wspr
```

### Two defenses in the deck itself

Because this failure was silent for a whole session: `_service` reports a
non-zero exit with systemctl's own last line, turning an authorization
refusal into a sentence naming the rule file, and **`_wspr_start` refuses to
start while fldigi is still active** instead of running a slot clock over a
codec it does not have. WSPR without the codec is not a degraded WSPR; it is
none.

## 5. If the package is not in the archive

Building `wsprd` from WSJT-X source needs `libfftw3-dev`, `gfortran` and
`build-essential` — all of which the image already installs for the
hamlib-from-source step, so the ground is familiar. It is the fallback and
not the plan: an official binary extracted from an official package is less
to go wrong than a compile.

---

## 6. What is NOT deployed by any of this

The capture, the beacon, the band hopping, the screen and the menus do not
exist. Nothing in `cyberdeck.py` imports these modules, no service changed,
and the deck behaves exactly as it did before. The only lasting changes are
`wsprd` in `/usr/local/bin` and two library packages.

Removing it all again:

```bash
sudo rm -f /usr/local/bin/wsprd
sudo rm -f /opt/cyberdeck/wspr.py /opt/cyberdeck/wsprsched.py \
           /opt/cyberdeck/wsprnet.py
```

The two library packages are harmless and used by other things; leave them.
