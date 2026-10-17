# Deploying the Cyberdeck — Runbook

Blank SD card to a working terminal, in order. Every command is meant to be
run as written.

**Not building a deck?** The application runs on an ordinary laptop against an
ordinary fldigi, with no Pi and no panel. Skip to [Running it on a laptop, with
your own radio](#running-it-on-a-laptop-with-your-own-radio); everything before
it is hardware.

**Before starting, read this once:** the whole sequence has been run. The image
builds and flashes, the card verifies (Phase 2, step 4), the deck boots, and it
has made contacts from its own panel and keyboard — RTTY on 2026-09-19 and
BPSK31 on 2026-09-20. Phase 6 covers recovery from the failures that were hit
along the way, each of which is recorded where it bites rather than in a list
at the end.

**The two that cost the most time:** fldigi's audio device on the Pi (Phase 4,
step 3), and the radios arriving rfkill-blocked so that WiFi and Bluetooth both
appeared broken for unrelated-looking reasons (Phase 3). The DSI panel overlay
looked like a third; Waveshare's documentation confirms the shipped default is
correct (Phase 0, step 4).

Outputs shown in this document are the ones observed, not reconstructed.

---





## Contents

- [Phase 0 — on the laptop](#phase-0--on-the-laptop)
  - [1. Find the Bluetooth keyboard's address](#1-find-the-bluetooth-keyboards-address)
  - [2. Configure fldigi for the deck](#2-configure-fldigi-for-the-deck)
  - [3. Fill in the two configuration files](#3-fill-in-the-two-configuration-files)
  - [4. Check the panel overlay](#4-check-the-panel-overlay)
- [5. The real-time clock, if one is fitted](#5-the-real-time-clock-if-one-is-fitted)
- [Phase 1 — build the image](#phase-1--build-the-image)
- [Phase 2 — flash the card](#phase-2--flash-the-card)
  - [1. Identify the card](#1-identify-the-card)
  - [2. Unmount it](#2-unmount-it)
  - [3. Write it](#3-write-it)
  - [4. Verify the card before booting](#4-verify-the-card-before-booting)
- [Phase 3 — first boot](#phase-3--first-boot)
  - [The keyboard: pair it on the deck](#the-keyboard-pair-it-on-the-deck)
- [Phase 4 — the radio](#phase-4--the-radio)
  - [1. Devices](#1-devices)
  - [2. Is fldigi answering?](#2-is-fldigi-answering)
  - [3. Audio device](#3-audio-device)
- [Phase 5 — on the air](#phase-5--on-the-air)
- [Phase 5a — WSPR, if it is wanted](#phase-5a--wspr-if-it-is-wanted)
- [Phase 6 — when something fails](#phase-6--when-something-fails)
  - [The build stopped partway](#the-build-stopped-partway)
  - [Blank panel, but SSH works](#blank-panel-but-ssh-works)
  - [The terminal is not running](#the-terminal-is-not-running)
  - [Nothing installed, no keyboard, no hostname, wrong clock](#nothing-installed-no-keyboard-no-hostname-wrong-clock)
  - [The deck reads the radio's frequency but cannot change it](#the-deck-reads-the-radios-frequency-but-cannot-change-it)
  - [The panel says DRAIN and the radio is still keyed](#the-panel-says-drain-and-the-radio-is-still-keyed)
  - [A received RSID moves the carrier, or a mode change resets it to 1500](#a-received-rsid-moves-the-carrier-or-a-mode-change-resets-it-to-1500)
  - [Punctuation comes out wrong on the keyboard](#punctuation-comes-out-wrong-on-the-keyboard)
  - [The radio was power-cycled and rig control stopped](#the-radio-was-power-cycled-and-rig-control-stopped)
  - [No keyboard, no screen, no SSH](#no-keyboard-no-screen-no-ssh)
  - [Start again](#start-again)
- [Updating the code on a running deck](#updating-the-code-on-a-running-deck)
- [Running it on a laptop, with your own radio](#running-it-on-a-laptop-with-your-own-radio)
  - [What the application actually touches](#what-the-application-actually-touches)
  - [Which parts of the repository are involved](#which-parts-of-the-repository-are-involved)
  - [1. Get fldigi working with your radio, on its own](#1-get-fldigi-working-with-your-radio-on-its-own)
  - [2. Start fldigi with XML-RPC listening](#2-start-fldigi-with-xml-rpc-listening)
  - [3. Set the deck's own settings](#3-set-the-decks-own-settings)
  - [4. Run it](#4-run-it)
  - [What differs from the deck](#what-differs-from-the-deck)
  - [Confirm the install](#confirm-the-install)
  - [One honest limitation](#one-honest-limitation)
- [What has and has not been tested](#what-has-and-has-not-been-tested)

---

## Phase 0 — on the laptop

Everything here happens before the card is touched.

### 1. Find the Bluetooth keyboard's address

Put the keyboard in pairing mode — usually holding a channel or pairing key
until its LED blinks rapidly. A keyboard that is merely switched on and
connected elsewhere will not advertise.

```bash
bluetoothctl
```

```
scan on
# wait for a [NEW] Device line with the keyboard's name
devices
scan off
quit
```

Already found for this deck:

```
DF:3C:77:61:6C:21  Pebble K380s
```

That address begins `DF`, which makes it a **static random** Bluetooth LE
address: stable between scans, so pairing by address works. It changes only if
the keyboard is factory reset — rescan and update `deck.conf` if that happens.

### 2. Configure fldigi for the deck

Plug the **FTX-1** into the laptop first. This step decides what the card is
seeded with, and fldigi cannot be configured on the deck without a screen.

The FTX-1 enumerates as **three** separate USB devices:

```
$ lsusb
Bus 001 Device 010: ID 10c4:ea70 Silicon Labs CP2105 Dual UART Bridge
Bus 001 Device 011: ID 0d8c:0016 C-Media Electronics, Inc. USB Audio Device
Bus 001 Device 012: ID 26aa:0030 Yaesu Musen YAESU HRI USB I/F
```

| Device | Appears as | Carries |
|---|---|---|
| CP2105 dual UART | `/dev/ttyUSB0`, `/dev/ttyUSB1` | CAT — frequency and mode |
| Yaesu HRI USB I/F | `/dev/ttyACM0` | PTT |
| C-Media `0d8c:0016` | ALSA card 1, `USB Audio Device` | transmit and receive audio |

The audio interface is a generic C-Media codec, so it is named **`USB Audio
Device`** rather than anything mentioning Yaesu. That is the string to look for.

```bash
cd ~/git_repos/keyboard-to-keyboard-cyberdeck
tools/dev-fldigi.sh                             # Xvfb + fldigi, seeded from ~/.fldigi
python3 tools/configure_fldigi.py --show          # what is set now
```

On a fresh configuration `--show` prints only the identity fields — no audio or
rig keys yet:

```
fldigi-config/fldigi_def.xml:
  MYCALL             'KD3CCO'
  MYNAME             'Don Natale'
  MYQTH              'State College'
```

Find the radio's codec as PortAudio names it. **Stop fldigi first** — see the
warning below:

```bash
pip install sounddevice                     # only needed for the listing
tools/dev-fldigi.sh stop
python3 tools/configure_fldigi.py --list-audio
```

```
  [4] USB Audio Device: - (hw:1,0)  in=2 out=2
  [14] USB Audio Device Analog Stereo  in=4 out=2
```

Two entries for one radio. `[4]` is the **direct hardware device**; `[14]` is
the same codec reached through the desktop's sound server. Take the hardware
device: it reaches the codec without a sound server resampling in the middle,
which is what a modem wants. `--auto-audio` applies that preference itself.

> ⚠️ **Run the listing with fldigi stopped.** A device that is already open
> reports **zero input channels** rather than an error:
>
> ```
> card 1: Device [USB Audio Device], device 0: USB Audio [USB Audio]
>   Subdevices: 0/1                          ← 0 free: held by fldigi
> ```
> ```
>   [4] USB Audio Device: - (hw:1,0)  in=0 out=2      ← looks capture-less
> ```
>
> `--auto-audio` refuses rather than quietly falling through to the sound-server
> device, which would write a configuration that looks correct and decodes
> nothing. A healthy listing shows `Subdevices: 1/1` and `in=2`.

Then set both things that matter:

```bash
python3 tools/configure_fldigi.py --rigctld --auto-audio
python3 tools/configure_fldigi.py --show          # confirm
```

```
chose 'USB Audio Device: - (hw:1,0)'
fldigi-config/fldigi_def.xml  (previous kept as fldigi_def.xml.bak)
  set CHKUSEHAMLIBIS=1
  set HAMRIGMODEL=2
  set HAMRIGDEVICE=localhost:4532
  set PORTINDEVICE='USB Audio Device: - (hw:1,0)'
  set PORTOUTDEVICE='USB Audio Device: - (hw:1,0)'
  set AUDIOIO=1 (PortAudio)
```

`--show` afterwards:

```
  AUDIOIO            '1'
  PORTINDEVICE       'USB Audio Device: - (hw:1,0)'
  PORTOUTDEVICE      'USB Audio Device: - (hw:1,0)'
  CHKUSEHAMLIBIS     '1'
  HAMRIGMODEL        '2'
  HAMRIGDEVICE       'localhost:4532'
  HAMLIBPTTONDATA    '1'
```

Restart fldigi and confirm it came up against the radio rather than against
nothing:

```bash
tools/dev-fldigi.sh
python3 -c "
from fldigi_client import Fldigi
f = Fldigi()
print('connected:', f.connected, '|', f.version())
print('modem:', f.modem(), '| rig frequency:', f.frequency())"
```

```
connected: True | fldigi 4.2.13
modem: CW | rig frequency: 146850000.0
```

A **non-zero frequency that matches the radio's display** is the proof that the
whole chain works: fldigi → rigctld → CAT → FTX-1. `0.0` means rig control is
not connected, and no amount of audio configuration will fix it.

**Why `--rigctld` and not hamlib directly.** The FTX-1 presents CAT on one
serial port and PTT on another; fldigi's hamlib configuration has room for one
port. `rigctld` bridges both and fldigi connects to it over loopback as *Hamlib
NET rigctl* — that is what `HAMRIGMODEL 2` and `HAMRIGDEVICE localhost:4532`
mean. Pointing fldigi straight at the CAT port means it and the deck's
`rigctld` service fight over the same device.

**The `hw:` index does not travel.** `hw:1,0` is card 1 *on this laptop*, where
card 0 is the built-in `HDA Intel PCH`. The Pi has no built-in capture device,
so the radio is likely card 0 there and the seeded name will be wrong. Phase 4
step 3 re-runs the choice on the deck itself.

The previous configuration is kept as `fldigi-config/fldigi_def.xml.bak`.

### 3. Fill in the two configuration files

```bash
cp deck.secrets.example deck.secrets
$EDITOR deck.secrets        # DECK_USER_PASSWORD, DECK_WIFI_SSID_1, DECK_WIFI_PSK_1
$EDITOR cyberdeck.conf      # CALLSIGN, NAME, QTH, LOCATOR
```

`DECK_SSH_PUBKEY = ~/.ssh/id_ed25519.pub` in `deck.secrets` saves typing a
password on every login later.

`deck.secrets` is gitignored. Both the image and the finished card contain
these credentials in recoverable form — Raspberry Pi OS has no disk encryption
and the card pulls out with a fingernail.

**Only the first network has to go here.** `DECK_WIFI_SSID_1` is what the deck
needs to reach the internet on its first boot, to install fldigi and build
hamlib. Every network after that can be added from the panel instead — `F1`
`7` `w` lists what is in range and joins it — so a network at a park or a
friend's house is no longer a reason to edit a file and reflash a card.

### 4. Check the panel overlay

`deck.conf` ships with:

```
DECK_PANEL_OVERLAY = vc4-kms-dsi-7inch
```

**This is correct for the Waveshare 5" DSI LCD and needs no change.** The name
is misleading: the overlay is named for the official Raspberry Pi 7" panel, but
Waveshare's 800×480 DSI panels are compatible with that panel's DSI timing and
touch arrangement, so the same overlay drives them. Waveshare's own wiki
instructs exactly this line for the 5" display, and describes it generically as
"the 800×480 resolution DSI LCD display" overlay.

There is no `5_0_inch` parameter under `vc4-kms-dsi-waveshare-panel`. That
overlay covers the Waveshare panels that are *not* 800×480 — 2.8", 4.0", 7.9",
8.8" and so on. Ours is, so it uses the official-panel overlay instead.

The build writes two lines to `config.txt`:

```
dtoverlay=vc4-kms-v3d          # added only if not already present
dtoverlay=vc4-kms-dsi-7inch
```

The KMS driver line must come first — the panel overlay depends on it. It is
already enabled in a stock Raspberry Pi OS image; the build asserts it anyway,
because a `config.txt` where it has been commented out produces a blank panel
and no other symptom.

**The `,dsi0` variant does not apply here.** Waveshare documents
`dtoverlay=vc4-kms-dsi-7inch,dsi0` for the second DSI interface, which only the
Pi 5 and CM4 have. The 3A+ has one 15-pin DSI connector, so the plain form is
right.

**Hardware:** an FFC cable from the panel to the Pi's 15-pin DSI connector. The
panel draws about **1.2 W** from that connector — worth remembering when the
FTX-1 is also on the single USB port and something enumerates intermittently.

Two settings this deck does not need, recorded in case they come up:

* **Rotation** is not required — the panel is natively 800×480 landscape, which
  is the orientation the terminal is designed around. On a Lite image rotation
  is a `cmdline.txt` edit, not a `config.txt` one:
  `video=DSI-1:800x480M@60,rotate=90`.
* **Touch** is unused; this deck is driven entirely from the keyboard. It can
  be switched off with `disable_touchscreen=1` in `config.txt` if the Goodix
  controller ever misbehaves.

**Backlight** is adjustable at runtime, which matters for operating at night:

```bash
echo 100 | sudo tee /sys/class/backlight/*/brightness    # 0–255
```

### 5. The real-time clock, if one is fitted

A Raspberry Pi has no clock of its own. Without an RTC the deck's time from
power-on is whatever was saved at the last shutdown, until NTP corrects it —
so a field session with no WiFi is stamped wrong from end to end, and those
stamps are what the status line and every transcript line are drawn from.

`deck.conf` names the chip:

```
DECK_RTC = ds3231
```

The build then writes `dtparam=i2c_arm=on` and `dtoverlay=i2c-rtc,ds3231` into
`config.txt`, installs `i2c-tools` and `util-linux-extra`, removes
`fake-hwclock` on first boot, and writes the system time into the chip once
NTP reports synchronized. Leave the value blank for no RTC.

Tested on an **Adafruit PiRTC, product 4282** — a DS3231 that plugs onto header
pins 1-10 with nothing to wire. Fit the CR1220 with its printed side up, seat
the board on the corner end of the header with the deck powered **off**, and
check it is not shifted a row along before powering up.

Prefer a board like it over a common ZS-042 module: those trickle-charge their
coin cell, which is wrong for the non-rechargeable CR2032 usually found in one
and not something to carry in a bag.

After the first boot:

```bash
timedatectl                    # an "RTC time" line now exists
cat /sys/class/rtc/rtc0/name   # rtc-ds1307 1-0068
```

`rtc-ds1307` for a DS3231 is correct — one driver covers the whole
DS1307/1337/1339/3231 family. On a chip that has never been set, the boot log
carries `SET TIME!` and `hctosys: unable to read the hardware clock`; both stop
after the first `sudo hwclock -w`, and both returning after a power cycle mean
the cell is dead or unseated.

To prove it actually works, switch NTP off first — otherwise
`WIFI_ON_START` restores the radio at boot and the network sets the clock
within seconds of a chip that might be doing nothing:

```bash
sudo timedatectl set-ntp false
sudo poweroff
# ... wait several minutes, power on ...
date -u
dmesg | grep -i rtc            # "setting system clock to ..." is the proof
sudo timedatectl set-ntp true
```

---

## Phase 1 — build the image

```bash
tools/build_deck_image.sh check
```

It refuses until both configuration files are real, and prints a summary:
hostname, user, variant, keyboard, panel, and each WiFi network. Read that
summary — it is the last chance to catch a typo cheaply.

Review what will be written to the card:

```bash
tools/build_deck_image.sh units
less deck-build/units/cyberdeck-ui.service
less deck-build/units/cyberdeck-firstboot.sh
```

Then build. This downloads about 500 MB the first time and asks for `sudo`:

```bash
tools/build_deck_image.sh build
```

It ends with the path to `deck-build/cyberdeck.img`.

---

## Phase 2 — flash the card

### 1. Identify the card

```bash
lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT,TRAN
```

Identify the card by **size and label together**, not by device name. Device
names are assigned in the order things were plugged in and change between
sessions; `/dev/sdb` on Monday is not `/dev/sdb` on Tuesday.

Card readers show up under two different naming schemes:

| Reader | Device | Partitions |
|---|---|---|
| Built-in SD slot | `/dev/mmcblk0` | `mmcblk0p1`, `mmcblk0p2` |
| USB adapter | `/dev/sdb`, `/dev/sdc`, … | `sdb1`, `sdb2` |

A new card usually shows one FAT32 partition. A card already carrying Pi OS
shows two, labeled `bootfs` and `rootfs`.

**Read it twice.** The flash overwrites the device completely and there is no
undo. Confirm the root filesystem is somewhere else entirely before going on:

```bash
findmnt -n -o SOURCE /        # must NOT be the device you are about to flash
```

> **Check the label, not just the size.** A real example from this build: the
> intended device came up as
>
> ```
> mmcblk0p1  116.5G  exfat  ZOOM_H2E  /run/media/natale/ZOOM_H2E
> ```
>
> — a card belonging to an audio recorder, sitting in the same slot. It was
> empty and was flashed deliberately, but a card that size holding recordings
> would have lost them silently: the image is about 2 GB, so the rest of the
> card is not erased, merely unreachable, and nothing would look wrong until
> the recorder was next used.
>
> Before flashing any card that is not blank:
>
> ```bash
> ls -la /run/media/$USER/<LABEL>/
> du -sh /run/media/$USER/<LABEL>/
> ```

### 2. Unmount it

The desktop mounts removable cards automatically, so a card that was just
inserted is almost certainly mounted. The script refuses to write to it:

```
error: /dev/mmcblk0 has mounted partitions; unmount them first
```

That refusal is a guard, not a fault. Unmount **each partition** — the
partition (`mmcblk0p1`), never the whole device (`mmcblk0`):

```bash
udisksctl unmount -b /dev/mmcblk0p1
```

For a card with two partitions, or any card whose layout is unknown, unmount
everything on the device in one pass:

```bash
DEV=/dev/mmcblk0
findmnt -rno SOURCE | grep -E "^${DEV}(p?[0-9]+)?$" | sort -u \
  | xargs -r -n1 udisksctl unmount -b
```

Setting `DEV` once is deliberate: the device name is then typed exactly once in
this phase, and the same variable can be reused for the flash itself. The
regexp matches both naming schemes — `mmcblk0p1` and `sdb1` — and anchors at
both ends so a device named similarly is not caught by accident. It prints
nothing and exits cleanly when nothing is mounted.

`udisksctl` is the right tool here rather than `sudo umount`: it goes through
the same desktop mount service that mounted the card, so the desktop does not
simply remount it a moment later.

Confirm nothing is mounted before continuing:

```bash
lsblk -o NAME,SIZE,LABEL,MOUNTPOINT "$DEV"
```

The `MOUNTPOINT` column must be empty on every row.

If unmounting fails with *target is busy*, something still has the card open —
a file manager window, or a shell sitting in a directory on it:

```bash
lsof +D /run/media/$USER/<LABEL> 2>/dev/null
```

### 3. Write it

```bash
tools/build_deck_image.sh flash "$DEV"
sync
```

Substitute what `lsblk` actually showed — or reuse `$DEV` from the step above,
if it is still set in the same shell. The script asks you to type the path a
second time to confirm — that is the moment to compare it against the size and
label you read, not before.

Expect it to look idle. `dd` reports no progress, and `sync` at the end is
where the buffered writes reach the card, so that step can sit for a minute or
more after the copy appears finished. **Do not pull the card until `sync`
returns.**

A card much larger than the ~2 GB image is fine. Raspberry Pi OS expands the
root filesystem to fill the card on first boot; `df -h /` over SSH in Phase 3
confirms it did.

### 4. Verify the card before booting

Everything below is checkable while the card is still in the laptop, which is
far cheaper than diagnosing it on a Pi with no HDMI and no keyboard. The card
re-mounts by label after the flash:

```bash
udisksctl mount -b /dev/mmcblk0p1     # bootfs
udisksctl mount -b /dev/mmcblk0p2     # rootfs
B=/run/media/$USER/bootfs
R=/run/media/$USER/rootfs
```

**Boot settings:**

```bash
grep -n "dtoverlay\|^\[" "$B/config.txt"
cat "$B/cmdline.txt"
ls "$B"/ssh "$B"/userconf.txt
```

Expect `dtoverlay=vc4-kms-dsi-7inch` to appear **after the last `[all]`**, not
under `[cm4]`, `[cm5]` or `[pi5]` — a section filter above it would silently
exclude a 3A+. `dtoverlay=vc4-kms-v3d` must also be present and uncommented.

In `cmdline.txt`, expect `console=tty3` (not `tty1`), the quiet-boot options,
and the stock `resize` token left intact — that token plus `auto_initramfs=1`
in `config.txt` is what expands the root filesystem on first boot.

`ssh` and `userconf.txt` are what make the deck reachable before the panel
works. If either is missing, stop: there is no way in.

**Payload and services:**

```bash
ls "$R/opt/cyberdeck/" | head
ls "$R/etc/systemd/system/" | grep cyberdeck
ls "$R/etc/systemd/system/multi-user.target.wants/" | grep cyberdeck
ls "$R/etc/systemd/system/timers.target.wants/" | grep cyberdeck
```

Expect **seven unit files** — six services and one timer:

```
cyberdeck-btpair.service    cyberdeck-rigctld.service
cyberdeck-btpair.timer      cyberdeck-ui.service
cyberdeck-firstboot.service cyberdeck-xvfb.service
cyberdeck-fldigi.service
```

All six services appear in `multi-user.target.wants`; the timer appears in
`timers.target.wants`. A `.timer` is enabled into the timers target, not the
multi-user one, so looking for it in the wrong `.wants` makes it seem missing
when it is fine.

`cyberdeck-ui` is only enabled when `DECK_AUTOSTART = yes`. Its absence from
`multi-user.target.wants` means the terminal will not start on its own — that
is a setting, not a fault.

`systemctl enable` cannot run against an offline image, so these are plain
symlinks created by the build. A missing symlink means a service that exists
and never starts.

Then unmount both before pulling the card:

```bash
udisksctl unmount -b /dev/mmcblk0p2
udisksctl unmount -b /dev/mmcblk0p1
sync
```

---

## Phase 3 — first boot

1. **Put the keyboard in pairing mode.**
2. Card into the Pi.
3. Panel ribbon connected.
4. FTX-1 into the single USB port.
5. Power last.

Allow **five to ten minutes**. The Pi joins WiFi and installs fldigi, Xvfb,
hamlib, Python, console fonts and bluez over the network. The screen stays
blank until the terminal appears — that is the quiet boot working, not a fault.

Then, from the laptop:

```bash
ssh deck@cyberdeck.local
```

```bash
systemctl status cyberdeck-firstboot --no-pager
journalctl -u cyberdeck-firstboot -n 40 --no-pager
systemctl status cyberdeck-xvfb cyberdeck-fldigi cyberdeck-ui --no-pager
```

Firstboot takes five to ten minutes and shows `activating` throughout. When it
reads `active`, it has **finished** — for a oneshot with `RemainAfterExit`,
that is the completed state, not a running one.

```bash
ls -l /var/lib/cyberdeck-firstboot-done
which fldigi Xvfb rigctld
df -h /                      # rootfs should have expanded to fill the card
```

### The keyboard: pair it on the deck

**The deck pairs its own keyboard now, and this is the ordinary way to do it.**
Nothing below needs SSH; the older `bluetoothctl` procedure is kept at the end
of this section as a fallback for a deck whose panel or touchscreen is not
working yet.

With nothing bonded, the terminal notices at startup that no keyboard exists
and shows the **NO KEYBOARD** screen by itself — which it must, because every
other way in is behind `F1`, and `F1` needs the keyboard that is missing.

1. Put the keyboard into pairing mode: hold its pairing key, or a channel
   button on a keyboard that has them, until the light blinks quickly.
2. **Tap the panel.** Anywhere — the screen offers one action and asking
   someone with no keyboard to hit a target would be the wrong thing to
   insist on.
3. The pairing screen scans and lists what it finds. Tap the row you want, or
   use `↑` `↓` and Enter if another keyboard is attached.
4. A six-digit passkey appears **in block characters**. Type it on the keyboard
   being paired and press its Enter key. Nothing echoes anywhere.
5. `PAIRED, AND TRUSTED.` Type on the keyboard to confirm.

A keyboard with channel buttons shows **one entry per channel, all with the
same name** — the address tail is what distinguishes them. A Pebble K380 with
a phone on button 1 and this deck on button 3 lists both. The screen says so
in place rather than leaving it to be worked out.

To pair another keyboard later, or replace one: `F1` → `7` → `b`. `f` on the
pairing screen removes an existing bond, which is what makes a second attempt
possible — a half-made bond cannot be replaced, only removed and remade.

**If pairing attempts fail repeatedly, check what else the radio is doing.**
The Pi 3A+ shares one chip and one antenna between WiFi and Bluetooth. Pairing
attempts during the first-boot package download failed three times in a row and
succeeded immediately once apt had finished. Wait for `Setup complete.` before
troubleshooting anything else.

#### Why the deck can do this at all

A Bluetooth LE keyboard will not deliver input over an unbonded link — HID over
LE requires encryption — and bonding needs a passkey **displayed by the host
and typed on the keyboard being paired**. That is why a `NoInputNoOutput` agent
fails and `KeyboardDisplay` works, and it cannot be automated: typing the code
is what proves the device is a keyboard. The deck has a screen and the keyboard
types, so SSH was never fundamentally required — only convenient at 2am.

What made the first attempt fail was lifetime, not permission. BlueZ tracks an
agent **per D-Bus connection**, and the original script ran each `bluetoothctl`
command as its own process, so the agent was gone before pairing began. The
terminal holds one connection open for the whole operation instead.
`tools/bt_agent_probe.py` measured that this works on this hardware before any
of it was written.

#### Fallback: pairing over SSH

Only for a deck that cannot show the pairing screen. Check the state first:

```bash
bluetoothctl info DF:3C:77:61:6C:21 | grep -E 'Connected|Paired|Bonded'
```

`Paired: no  Bonded: no  Connected: yes` means the link is up and the keyboard
types nothing.

```bash
bluetoothctl
```

Inside that **single session** — the agent only exists for the lifetime of the
`bluetoothctl` process, so these cannot be separate commands:

```
remove DF:3C:77:61:6C:21
power on
agent KeyboardDisplay
default-agent
scan on
pair DF:3C:77:61:6C:21
```

Type the six-digit passkey on the keyboard and press Enter, then:

```
trust DF:3C:77:61:6C:21
scan off
quit
```

**The LED may keep blinking as though still pairing — ignore it; typing at the
deck's screen is the test.** From here `cyberdeck-btpair` reconnects an
already-bonded keyboard at boot, retrying every five minutes:

```bash
sudo systemctl start cyberdeck-btpair
journalctl -u cyberdeck-btpair -n 20 --no-pager
```

---

## Phase 4 — the radio

### 1. Devices

```bash
ls -l /dev/ttyUSB* /dev/ttyACM*     # CAT and PTT
lsusb                               # all three FTX-1 interfaces
arecord -l                          # the FTX-1's codec and its card number
systemctl status cyberdeck-rigctld --no-pager
```

Expect the same three devices the laptop saw in Phase 0 step 2 — `10c4:ea70`,
`0d8c:0016`, `26aa:0030` — and:

```
/dev/ttyUSB0  /dev/ttyUSB1     CP2105, CAT
/dev/ttyACM0                   Yaesu HRI USB I/F, PTT
```

**`arecord -l` is the line that matters.** The Pi has no built-in capture
device, so the FTX-1 is expected at **card 0** here where it was card 1 on the
laptop:

```
card 0: Device [USB Audio Device], device 0: USB Audio [USB Audio]
  Subdevices: 0/1                    ← 0 is correct here: cyberdeck-fldigi holds it
```

If fewer than three USB devices appear, suspect power before software: a 3A+
feeding a DSI panel and a radio interface from one port has little headroom.

### 2. Is fldigi answering?

```bash
python3 -c "
import sys; sys.path.insert(0,'/opt/cyberdeck')
from fldigi_client import Fldigi
f = Fldigi()
print('connected:', f.connected, '|', f.version())
print('modem :', f.modem(), '| carrier', f.carrier(), 'Hz')
print('rig   :', f.frequency(), f.rig_mode())"
```

Expect something like the laptop produced in Phase 0 step 2:

```
connected: True | fldigi 4.2.13
modem : CW | carrier 1000 Hz
rig   : 146850000.0 FM
```

A frequency of `0.0` means rig control is not working — check
`cyberdeck-rigctld` and that fldigi is set to `localhost:4532`. A frequency
that does **not** match the radio's own display means `rigctld` is talking to
the wrong serial port; the CP2105 presents two, and only one carries CAT.

### 3. Audio device

⚠️ **This is the step most likely to bite.** The seeded configuration names `hw:1,0`, which was the radio **on the laptop**.
The `hw:` index is assigned in enumeration order, and the Pi numbers the same
codec differently — almost certainly `hw:0,0`. A wrong index does not raise an
error: fldigi opens whatever is at that name, or nothing, and the deck looks
perfectly healthy while decoding silence.

```bash
python3 /opt/cyberdeck/configure_fldigi.py --config-dir /opt/cyberdeck/fldigi-config --show
```

If `PORTINDEVICE` is still `'USB Audio Device: - (hw:1,0)'` and `arecord -l`
put the radio on card 0, re-choose it on this machine:

```bash
sudo systemctl stop cyberdeck-fldigi        # it holds the capture device
python3 /opt/cyberdeck/configure_fldigi.py --config-dir /opt/cyberdeck/fldigi-config --auto-audio
sudo systemctl start cyberdeck-fldigi
```

Expect `chose 'USB Audio Device: - (hw:0,0)'`. Stopping fldigi first is
required, not tidiness — while it holds the device the listing reports zero
input channels and `--auto-audio` refuses rather than guess.

If `sounddevice` is not installed on the deck, name the device explicitly
instead, building it from what `arecord -l` reported:

```bash
python3 /opt/cyberdeck/configure_fldigi.py --config-dir /opt/cyberdeck/fldigi-config \
  --audio "USB Audio Device: - (hw:0,0)"
```

**Confirm the audio actually opened.** A restarted fldigi that failed to open
its device still answers XML-RPC:

```bash
grep -i "audio\|portaudio\|error" /opt/cyberdeck/fldigi-config/fldigi.log | tail -20
arecord -l        # Subdevices: 0/1 means fldigi has it open — correct
```

`Subdevices: 1/1` with fldigi running means it did **not** open the device.

If the name is hard to determine, run fldigi's own dialog over SSH — it runs on
the Pi and displays on the laptop:

```bash
ssh -X deck@cyberdeck.local
sudo systemctl stop cyberdeck-fldigi
fldigi --config-dir /opt/cyberdeck/fldigi-config
# set the sound card, quit
sudo systemctl start cyberdeck-fldigi
```

---

## Phase 5 — on the air

This is the phase that has actually been done: two RTTY contacts on 80 m,
2026-09-19. What follows is what worked, in order.

At the deck's own screen and keyboard:

1. **`F1` → `3`** to set a band, or tune the radio directly. 3.580 for 80 m
   RTTY, 14.070 for 20 m PSK31.
2. **`F3`** to pick the mode. `4` for RTTY, `1` for BPSK31. Leave **`a` AUTO
   (RSID)** on and the deck follows other stations into their mode.
3. **`F2`** for the tuning screen, then `↑`/`↓` to search for a signal.
4. **Set the squelch just above the noise floor** — `+` and `-` on the `F2`
   screen, watching the `decode` line as you go. This mattered more than
   anything else: too high and nothing decodes, too low and the transcript
   fills with noise. Getting it just over the floor was the difference between
   fragments and copy.
5. **On RTTY, try `v`** if you get plausible letters that never form words.
   Ham RTTY is conventionally lower sideband and the deck transmits AFSK
   through the radio's DATA-U path, which is upper, so the tones can arrive
   swapped. This is not optional on 80 m — it was needed for both contacts.

Before transmitting:

* **Set the radio's time-out timer.** PTT is a pin the interface holds; a hung
  host holds the radio keyed, and the radio's own timer is the only backstop.
* **Check `Ctrl-C` aborts** before relying on it. Verified against a live
  carrier.
* **Reduce power.** RTTY and PSK are near 100% duty cycle, unlike SSB, so a
  given wattage heats the finals far harder than the same figure on voice.
  Contacts have been made at **5 W** and at **20 W**; 5 W is enough far more
  often than it looks. At the higher setting, put the **final amplifier
  temperature** on the radio's meter for the duration rather than checking it
  afterwards.
* **Set the drive so the ALC never moves.** See §7.2 of the design document for
  the procedure and for why the setting is so sharp-edged.
* **`Ctrl-B` to arm.** Transmit starts inhibited at every power-on; the status
  line shows `INH` until you clear it.

To work someone: type while receiving — it buffers, nothing goes out — then
`Ctrl-T` to send the whole over at once, and `Ctrl-Y` to hand back. `Enter`
inserts a newline; it does not send.

`F5` to `F12` insert stored messages at the cursor, which is worth setting up
before a contest rather than during one — `F1` → `5` edits them on the deck.
`Ctrl-Z` undoes an insert.

**Caps Lock is normal here.** RTTY is Baudot and has no lowercase, so every
RTTY signal on the air is uppercase. Every command key on the deck is
case-folded and works either way.

[`digimodes_operating_tutorial.md`](digimodes_operating_tutorial.md) is the long version, written for a first
keyboard-to-keyboard contact: what to say, the abbreviations, and how a QSO is
structured.

---

## Phase 5a — WSPR, if it is wanted

**A flashed card does not get WSPR working.** The image carries the deck's
own modules, and those are enough for the screen to draw, but three things
have to be added on the deck before a session can capture or transmit.
`docs/wspr_deploy.md` is the runbook; this is what it covers and why each
part is not optional.

**1. `wsprd`, the decoder.** It is not packaged on its own. It comes out of
the `wsjtx` package, and extracting just the binary costs about 1 MB against
36 MB for the installed package:

```bash
apt-get download wsjtx
dpkg-deb -x wsjtx_*.deb /tmp/wsjtx
sudo install -m 755 /tmp/wsjtx/usr/bin/wsprd /usr/local/bin/wsprd
sudo apt-get install -y libgfortran5
wsprd 2>&1 | head -3
```

The last line prints a usage message. `libgfortran5` is required — `wsprd`
is Fortran and will not start without it.

**2. The polkit rule, which the feature cannot work without.** WSPR stops
fldigi for the length of a session, because the USB codec takes one capture
client and that is measured rather than assumed. `cyberdeck-ui` runs as
`deck` and needs authorization to stop a unit.

**sudo is not the route.** A `NOPASSWD` sudoers rule for the same command
parses, works from a login shell, and still fails from inside the service —
which has no tty, no PAM session, and a `CapabilityBoundingSet` narrowed to
`CAP_SYS_TTY_CONFIG`. polkit is, and it is the same route the WiFi screen
already uses for the same reason. See `docs/wspr_deploy.md` §4b for the
rule and its verification.

**3. The sound card addressed by NAME.** ALSA numbers cards in probe order,
so the index moves: this codec was card 1 one morning and card 2 after a
reboot, with HDMI taking 1. Nothing here should carry `plughw:1,0`. The
defaults are `plughw:CARD=Device,DEV=0` and `amixer -c Device`, and
`cat /proc/asound/cards` says what the id is on a given board.

If `WSPR_DEVICE` or `WSPR_RX_CARD` appear in `cyberdeck.conf` with a number
in them, delete those lines — a stale index points the capture at the wrong
hardware, and the symptom is `arecord: audio open error: No such file or
directory` rather than anything mentioning WSPR.

**What the deck does itself:** it turns the codec's AGC off for the session
and puts it back afterwards, and it sets the capture gain and restores that
too. AGC ships on and must be off — it compresses a constant-envelope signal
whose amplitude carries no information and corrupts the SNR that gets
uploaded to wsprnet as a measurement.

## Phase 6 — when something fails

### The build stopped partway

It leaves the image mounted on a loop device.

```bash
mount | grep /tmp/tmp
sudo umount /tmp/tmp.XXXX /tmp/tmp.YYYY
losetup -a
sudo losetup -d /dev/loopN
```

Then rerun `tools/build_deck_image.sh build`. The downloaded image is cached, so
only the customization repeats.

### Blank panel, but SSH works

Check the overlay lines survived the build, in this order:

```bash
grep dtoverlay /boot/firmware/config.txt
```

Both must be present and neither commented out:

```
dtoverlay=vc4-kms-v3d
dtoverlay=vc4-kms-dsi-7inch
```

If they are both there, the overlay is not the problem — it is the documented
configuration for this panel (Phase 0, step 4). Look at the physical layer
instead: the FFC cable's orientation and seating in the 15-pin DSI connector,
which is easy to get backwards and gives exactly this symptom. Then check the
terminal is actually running:

```bash
systemctl status cyberdeck-ui
ls /sys/class/backlight/            # a panel the kernel recognized appears here
```

A backlight entry with a blank screen means the panel is driven and the
terminal is not. Nothing under `/sys/class/backlight` means the panel was never
brought up — cable or overlay.

### The terminal is not running

```bash
journalctl -u cyberdeck-ui -n 40 --no-pager
journalctl -u cyberdeck-fldigi -n 40 --no-pager
```

`cyberdeck-ui` requires `cyberdeck-fldigi`, which requires `cyberdeck-xvfb`.
Check them in that order.

### Nothing installed, no keyboard, no hostname, wrong clock

Four symptoms, one cause, and worth recognizing immediately because it looks
like four separate faults: **both radios ship rfkill-blocked** on a Pi 3.

```bash
rfkill list
```

`Soft blocked: yes` on either entry means the deck has no network, so firstboot
installed nothing, the keyboard cannot pair, `cyberdeck.local` does not resolve
and NTP never set the clock.

The build unblocks both before NetworkManager starts, so a card built by the
current script should never show this. If one does, the oneshot did not run:

```bash
systemctl status cyberdeck-wifi-country --no-pager
journalctl -u cyberdeck-wifi-country --no-pager
sudo rfkill unblock wifi bluetooth
```

Setting the regulatory domain is **not** enough on its own — `modprobe.d` and
`/etc/default/crda` set the domain but do not clear the block.

### The deck reads the radio's frequency but cannot change it

The first-boot hamlib build did not complete. Check all three parts, because
each is individually necessary and each fails silently on its own:

```bash
LD_LIBRARY_PATH=/usr/local/lib /usr/local/bin/rigctl --version
LD_LIBRARY_PATH=/usr/local/lib /usr/local/bin/rigctl -l | grep -i ftx
systemctl cat cyberdeck-rigctld | grep -E "ExecStart|LD_LIBRARY"
```

You want `4.7.2`, a line reading `1051 ... FTX-1 ... Beta`, and a unit that
runs `/usr/local/bin/rigctld -m 1051` with `LD_LIBRARY_PATH` set.

**`rigctl --version` reporting 4.6.2 from the `/usr/local` binary is the
trap.** `ldconfig` is not enough: the loader's cache lists the multiarch
directory ahead of `/usr/local/lib`, so a correctly built `rigctl` links the
old library and offers no FTX-1 model. Everything looks installed.

```bash
journalctl -u cyberdeck-firstboot | grep -i hamlib
```

To confirm the radio and cabling are fine regardless, write the documented
command straight to the port — nine digits, zero-padded:

```bash
sudo systemctl stop cyberdeck-rigctld
CAT=$(ls /dev/serial/by-id/*CP2105*if00* )
stty -F "$CAT" 38400 raw -echo
printf 'FA014075000;' > "$CAT"
sudo systemctl start cyberdeck-rigctld
```

If the dial moves, CAT is healthy and the fault is in hamlib. See
platform_design.md §7.1.

### The panel says DRAIN and the radio is still keyed

Expected, up to a point. `Ctrl-Y` does not unkey the radio: it marks fldigi's
buffer "return to receive when drained", and everything already composed still
has to be sent. At 31 baud a long over legitimately takes minutes, and `DRAIN`
is the status line reporting that honestly rather than showing `RX` while the
transmitter runs.

It is a fault when it does not end. The transcript begins saying `still
transmitting Ns after hand back` twenty seconds in and repeats at widening
intervals; if that number climbs past a minute or two, `Ctrl-C` drops the
carrier. `TX_TIMEOUT` aborts it regardless, and that timer now stays armed
through the drain rather than being cleared by the hand back.

If the hand back itself failed — an XML-RPC call that did not land — the
transcript says `fldigi did not take the hand back`. Check that fldigi is
answering:

```bash
systemctl status cyberdeck-fldigi --no-pager
python3 -c "import xmlrpc.client; print(xmlrpc.client.ServerProxy('http://127.0.0.1:7362/').fldigi.name_version())"
```

### A received RSID moves the carrier, or a mode change resets it to 1500

fldigi, not the deck. Two of its settings move the carrier without being asked:

| Key | Set to | Effect |
|---|---|---|
| `STARTATSWEETSPOT` | 0 | No reset to the sweet spot when the modem changes |
| `DISABLERSIDFREQCHANGE` | 1 | A received RSID switches mode but cannot retune |

The card is built with both set. To apply them to a running deck, or after
restoring a configuration from elsewhere:

```bash
sudo python3 /opt/cyberdeck/configure_fldigi.py \
  --config-dir /opt/cyberdeck/fldigi-config --keep-carrier
sudo systemctl restart cyberdeck-fldigi
```

Check with `--show`; both values must be as above. The first was observed on
the air in both directions between two stations — change mode at 700 Hz and
the other end jumps to 1500 — and the same setting is available in fldigi's
own interface, under Configure → Modems, for a correspondent running a laptop.

### Punctuation comes out wrong on the keyboard

The console keymap is GB and the keyboard is US, or the reverse. On a US
keyboard against a GB keymap the signature is unmistakable:

| Pressed | Produces | Because GB has |
|---|---|---|
| Shift+2 | `"` | `"` on Shift+2 |
| the `"` key | `@` | `@` on Shift+apostrophe |
| Shift+3 | nothing visible | `£`, which is not ASCII |
| the `\` key | `#` | `#`/`~` at that key position |

**The backslash becomes untypeable**, because GB puts it on the extra ISO key
beside left Shift and a US keyboard has no such key. That also removes `\n`,
which is how a message memory is made multi-line (§5.6 of the design doc).

Raspberry Pi OS defaults to GB. `DECK_KEYBOARD` in `deck.conf` sets this at
build time and a card flashed before that setting was wired up will have
inherited the default. Fix a running deck in place:

```bash
grep XKBLAYOUT /etc/default/keyboard
sudo sed -i 's/^XKBLAYOUT=.*/XKBLAYOUT="us"/' /etc/default/keyboard
sudo sed -i 's/^XKBVARIANT=.*/XKBVARIANT=""/' /etc/default/keyboard
sudo setupcon --save
sudo reboot
```

`setupcon` applies the keymap to the console immediately, but the terminal
owns tty1 and has its own idea of the session; rebooting is the reliable way
to be sure. Confirm afterwards by typing `@ # \` on the deck — all three
should appear as themselves.

### The radio was power-cycled and rig control stopped

Power-cycling the FTX-1 detaches the CP2105, and the kernel hands out the next
free device numbers on re-attach — CAT moves from `ttyUSB0` to `ttyUSB1`.

`deck.conf` uses `/dev/serial/by-id/` paths, which survive this. If yours still
name `/dev/ttyUSB0`, that is why rig control died, and the service will be
inactive rather than failed because of its `ConditionPathExists`:

```bash
ls -l /dev/serial/by-id/
systemctl status cyberdeck-rigctld --no-pager | head -5
```

The `-if00` suffix is CAT and `-if01` is the second UART. The serial number in
the path belongs to one specific radio.

### No keyboard, no screen, no SSH

The one USB port holds the radio. Unplug the FTX-1, plug in a USB keyboard, and
work at the console. That is the recovery path, and it is the reason the build
refuses a placeholder Bluetooth address.

### Start again

Reflash. Nothing on the card is precious; everything that describes this deck
lives in `deck.conf`, `deck.secrets` and `cyberdeck.conf` on the laptop.

---

## Updating the code on a running deck

Reflashing is for changing the *machine*. For changing the terminal — which is
most iteration — copy the modules across and restart the unit. The deck keeps
its configuration, its fldigi seed, its Bluetooth bond and its hamlib build.

On the laptop:

```bash
rsync -av src/*.py tools/configure_fldigi.py deck@cyberdeck.local:/tmp/deckupd/
```

On the deck:

```bash
sudo cp /tmp/deckupd/*.py /opt/cyberdeck/
sudo systemctl restart cyberdeck-ui
systemctl is-active cyberdeck-ui
```

`/opt/cyberdeck` holds the flat set of modules the unit runs, plus
`configure_fldigi.py`, `cyberdeck.conf` and the fldigi seed. Tests, the rest of
`tools/`, and documentation stay on the build machine.

**The polkit rule is not a `.py` file and the copy above misses it.** A card
built before the WiFi screen existed has no
`/etc/polkit-1/rules.d/10-cyberdeck-networkmanager.rules`, and without it the
screen lists networks perfectly and refuses every key on it. Install it once,
from the laptop:

```bash
sed 's/@DECK_USER@/deck/' polkit/10-cyberdeck-networkmanager.rules \
  | ssh deck@cyberdeck.local 'sudo install -D -m 644 /dev/stdin \
      /etc/polkit-1/rules.d/10-cyberdeck-networkmanager.rules && sudo systemctl restart polkit'
```

Check it with `nmcli -t -f PERMISSION,VALUE general permissions | grep wifi` —
`enable-disable-wifi` and `wifi.scan` should read `yes`. A freshly flashed card
gets this from `install_polkit` and needs none of it.

**`configure_fldigi.py` is in that list and is easy to forget.** It lives in
`tools/` here and in `/opt/cyberdeck` there, so a copy of `src/*.py` alone
leaves the deck running an older version of it — which presents as the deck
rejecting an option that exists on the laptop:

```
configure_fldigi.py: error: unrecognized arguments: --keep-carrier
```

That is the command above being run with a stale tool, not a broken flag.

**If a module is renamed or removed, delete the old one.** A stale file beside
its replacement still imports cleanly and will be found instead of the new
name. `colors.py` replaced `colours.py` this way and the leftover had to be
removed by hand:

```bash
sudo rm -f /opt/cyberdeck/<old name>.py
```

To confirm the running process is the code you just copied:

```bash
md5sum /opt/cyberdeck/cyberdeck.py
systemctl show cyberdeck-ui -p ExecMainStartTimestamp
```

The process start must be **after** the file's timestamp. An hour was lost once
to debugging a deck that was running the previous copy.

## Running it on a laptop, with your own radio

This runbook builds a dedicated machine. That is not the only way to use the
project, and it is not the way to start. The application is an ordinary Python
program: it needs a terminal and a fldigi to talk to, and nothing else. No Pi,
no panel, no Bluetooth keyboard, no systemd unit.

Anyone who wants the interface without the hardware needs this section and
none of the phases above it.

### What the application actually touches

One thing: **fldigi, over XML-RPC on the loopback interface.** It does not open
a sound card and it does not open a serial port. fldigi owns the audio device
and the rig control, and the deck asks fldigi for text, carrier, mode and
frequency.

Two consequences, and they decide the whole procedure:

* **A radio fldigi cannot work, the deck cannot work.** There is no separate
  radio support to configure. If fldigi decodes and keys your rig from its own
  window, the deck inherits that; if it does not, fix that first and ignore
  this project until it is fixed.
* **Any radio fldigi supports is a candidate.** Nothing in `src/` names a
  radio. The FTX-1 appears in the defaults and in the documentation because it
  is the one this was built against and the only one it has been run against —
  see the honesty note at the end of this section.

### Which parts of the repository are involved

| Path | Laptop use |
|---|---|
| `src/*.py` | **The application.** All of it, run in place |
| `cyberdeck.conf` | **The settings.** Copy `cyberdeck.conf.example` and edit |
| `tools/configure_fldigi.py` | Useful — sets fldigi's audio and rig control without its dialogs |
| `tools/dev-fldigi.sh` | Optional — runs fldigi headless under Xvfb, if you would rather not see it |
| `tools/run_tests.sh`, `tests/` | Optional — confirms the install against your own fldigi |
| `tools/build_deck_image.sh`, `deck.conf` | **Ignore.** SD-card image build only |
| Phases 0–6 of this runbook | **Ignore.** Pi hardware, panel, Bluetooth bonding |

`deck.conf` is worth calling out because its existence is what makes the
configuration look monolithic from outside. It is read by the image builder and
never by the running application. The application's settings are in
`cyberdeck.conf`, and nothing in that file is Pi-specific.

### 1. Get fldigi working with your radio, on its own

Before this project is in the picture at all. Start fldigi normally, set your
callsign, choose the sound card, set up rig control, and confirm two things by
looking at fldigi's own window:

* text decodes off the air;
* the radio keys and unkeys from fldigi's T/R button.

The two arrangements for rig control, in the order to try them:

* **fldigi straight to hamlib.** One serial port for CAT, PTT by CAT or by a
  second method. This is most radios and it is the simple case.
* **fldigi to `rigctld`, over the network.** Needed when a radio presents CAT
  and PTT on *separate* serial ports, because fldigi's hamlib configuration has
  room for one. `rigctld` bridges both and fldigi connects to it as *Hamlib NET
  rigctl* on `localhost:4532`. The FTX-1 is this case:

  ```bash
  rigctld -m 1051 -r /dev/ttyUSB0 -s 38400 -p /dev/ttyACM0 -P RIG -t 4532 &
  ```

  Substitute your own model number, ports and baud rate. Pointing fldigi at the
  CAT port directly *as well* is the mistake to avoid: it and `rigctld` then
  fight over one device and one of them loses.

**fldigi crashes on a genuinely empty configuration directory** — an assertion
failure during first-run setup. Running it once as a desktop application, as
above, is what avoids that, which is why this step comes first.

### 2. Start fldigi with XML-RPC listening

The deck reaches fldigi on `127.0.0.1:7362`. Start fldigi with that turned on
explicitly rather than assuming the default:

```bash
fldigi --xmlrpc-server-address 127.0.0.1 --xmlrpc-server-port 7362
```

Check it answers before going further — this is the one dependency:

```bash
python3 -c "import xmlrpc.client; print(xmlrpc.client.ServerProxy('http://127.0.0.1:7362/').fldigi.name_version())"
```

A version string means everything downstream is configuration rather than
plumbing. A connection error means fldigi is not listening and nothing else
will work.

To run fldigi without its window taking over the screen, `tools/dev-fldigi.sh`
starts it against a virtual X display and leaves it running. It seeds its
configuration directory from an existing install; read the script before using
it, since it expects one.

### 3. Set the deck's own settings

```bash
cp cyberdeck.conf.example cyberdeck.conf
```

Then edit it. The ones that matter on a first run:

| Key | Set it to |
|---|---|
| `CALLSIGN` | Yours. The status line and the `{call}` token both use it |
| `NAME`, `QTH`, `LOCATOR` | Yours — the message memories substitute them |
| `RIG` | Your radio's name, for the `{rig}` token |
| `RIG_BANDS` | The bands your radio covers, e.g. `80 m, 40 m, 20 m`. Empty means all of them, which is right for an all-band radio and wrong for anything else — unsupported bands are marked in the `F1` → Band menu rather than hidden |
| `DEFAULT_MODE` | `BPSK31` unless you would rather start somewhere else |
| `FLDIGI_URL` | Only if fldigi is not on `127.0.0.1:7362` |

`tools/configure_fldigi.py` sets the fldigi side from the command line, which
is worth knowing even on a laptop:

```bash
python3 tools/configure_fldigi.py --show          # what is set now
python3 tools/configure_fldigi.py --list-audio    # PortAudio's device names
python3 tools/configure_fldigi.py --audio "USB Audio Device" --call YOURCALL
python3 tools/configure_fldigi.py --rigctld       # use Hamlib NET rigctl
```

### 4. Run it

```bash
python3 src/cyberdeck.py
```

It takes over the terminal it is started in. `Ctrl-Q` quits.

Transmit starts **inhibited** — the status line reads `INH` — and `Ctrl-B`
arms it. That is deliberate and it is not a laptop-only inconvenience: a
program that can key a radio should not be able to do so the instant it starts.

### What differs from the deck

* **Color.** The five schemes set true hues through the `PIO_CMAP` ioctl,
  which works only on a Linux virtual console. In a terminal emulator or over
  SSH the ioctl fails, the failure is caught, and the schemes render as their
  ANSI approximations — recognizable, not exact. Nothing breaks.
* **Size.** The layout is designed for the deck's 66×20. It adapts, and the
  hint line sheds bindings rather than truncating, down to a floor of 30×8
  below which it prints `terminal too small` and waits. A larger window is
  simply a larger transcript.
* **Touch and pairing are absent, and that is not an error.** The touchscreen
  reports no movement on a machine that has none, and the pairing screen is
  offered only where BlueZ and `python3-gi` are present. Neither is imported
  at startup. `TOUCH = no` and `PAIR_ON_NO_KEYBOARD = no` switch them off
  outright if a laptop happens to have a touchscreen you would rather the
  terminal left alone — it reads the device without grabbing it, so the
  desktop keeps working either way.
* **Keys.** The application inherits `TERM` from wherever it runs, and terminal
  types disagree about what some keystrokes mean. `TERM=linux` maps Ctrl-Z to
  `KEY_SUSPEND` where `xterm` delivers byte 26; both are handled, and
  `tests/test_console_keys.py` exists because that difference once cost a
  working key on the panel and nowhere else. If a key appears dead, run with
  stderr visible — every unhandled key is logged with its number.

### Confirm the install

With fldigi running:

```bash
tools/run_tests.sh
```

The suite drives the real application through a pseudo-terminal against your
own fldigi, so a pass means the application works on your machine, not merely
that it imported.

### One honest limitation

This has only ever been run against a Yaesu FTX-1. Nothing in the application
is specific to it — the radio is fldigi's problem, and the FTX-1 appears only
in default values and worked examples — but "should work with any rig fldigi
supports" is an argument from structure, not a report of it having been done.
Expect the defaults to need changing and the rig-control step to be where the
time goes.

---

## What has and has not been tested

Recorded honestly so that a failure is recognized rather than debugged from
first principles.

**Proven, on the real deck:**

| | |
|---|---|
| **Two-way contacts** | N3QE and K4ZW, 80 m RTTY, 2026-09-19, 5 W; N0DLR and KC3FL, 20 m BPSK31, 2026-09-20, 5 W; **FM4TI, Martinique**, 40 m BPSK31, 2026-09-21, 20 W. All from the deck's own panel and keyboard |
| `tools/build_deck_image.sh build` and `flash` | Run end to end; the card verifies before boot (phase 2 step 4) |
| The Waveshare 5" DSI panel on a Pi 3A+ | Console at 66×20, `vc4-kms-dsi-7inch`, powered from the DSI connector |
| Terminus 12×24 | Renders on the panel |
| WiFi, NTP, firstboot install, SSH | About five minutes, plus 20–30 for the hamlib build |
| Bluetooth keyboard | Paired **from the deck itself**, no SSH: scan, tap, passkey on the panel, bonded and trusted (phase 3) |
| Touchscreen | FT5x06, multitouch. Drag scrolls the transcript; a tap chooses on the pairing screen |
| Noticing the keyboard is gone | Switching the keyboard off raises the NO KEYBOARD screen within three seconds; switching it on clears it |
| fldigi 4.2.06 on a 3A+'s 512 MB | Under Xvfb, with the radio attached |
| Receive | Real off-air RTTY copy, tuned with `F2` and the reverse toggle |
| The `F2` tuning panel | Used on the air on three bands: search, carrier nudge, squelch level, reverse and the decode preview |
| Transmit | PTT, the over model, and `Ctrl-C` against a live carrier |
| The transmit state the panel shows | `RX`, `TX`, `DRAIN` and `INH`, read from fldigi rather than from the terminal's own intent |
| **PSK31 on the air** | The mode the deck was designed around. Two contacts on 14.070, both found with `Ctrl-W` / `Ctrl-S` |
| Rig control, reads and writes | Needs hamlib 4.7.2 and model 1051 |
| The color schemes | All four on the panel: Matrix and Deckard 2026-09-19/20, Hal and Tron 2026-09-22. True hues via `PIO_CMAP`; `OSC P` does not work here |
| **25 W on a 100% duty cycle mode** | A full PSK31 ragchew at 25 W with the final amplifier temperature watched throughout, 2026-09-22 |
| **RSID and TXID** | Both directions against a second station, 2026-09-22 |

**Not tested:**

| | |
|---|---|

| Console fonts 10×20 and 16×32 | Only 12×24 has been rendered |
| Pairing a keyboard that is not a K380 | One model, one bond. Nothing here is specific to it, but that is an argument rather than a report |
| A long session | Longest run so far is an evening; no thermal or memory data |
| Remembered state across a power cut | The `fsync` that makes it durable is in place and exercised by a clean restart; pulling the power on a freshly changed setting has not been tried |
| Off-mains operation | Never run off anything but a wall supply. The deck holds no battery by design — it takes 5 V over USB from whatever powers the station, a USB power bank or a LiFePO4 box. Its draw from one has not been measured |

Everything above the hardware line — the terminal, the modes, the menus, the
over model, line editing, the color schemes — is covered by **436 checks**
against a live fldigi (`tools/run_tests.sh`).
