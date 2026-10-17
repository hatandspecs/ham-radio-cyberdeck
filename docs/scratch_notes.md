## Step 1 — snapshot the deck as it is now

On the deck. **Do this first** — it's what "reset to current state" restores from.

```bash
sudo rm -rf /opt/cyberdeck-restore
sudo mkdir -p /opt/cyberdeck-restore
sudo cp /opt/cyberdeck/*.py /opt/cyberdeck-restore/
sudo cp /opt/cyberdeck/cyberdeck.conf /opt/cyberdeck-restore/
ls /opt/cyberdeck-restore/*.py | wc -l
```

Prints a file count. If it prints `0`, stop and tell me — nothing was snapshotted.

## Step 2 — deploy

On the laptop:

```bash
cd ~/git_repos/keyboard-to-keyboard-cyberdeck
rsync -av src/*.py deck@cyberdeck.local:/tmp/deckupd/
```

26 files. Then on the deck:

```bash
sudo cp /tmp/deckupd/*.py /opt/cyberdeck/
sudo systemctl restart cyberdeck-ui
sleep 5
systemctl is-active cyberdeck-ui
```

Prints `active`.

## Step 3 — check the conf isn't pinning the old card

```bash
grep -n 'WSPR_DEVICE\|WSPR_RX_CARD' /opt/cyberdeck/cyberdeck.conf
```

**If either line exists with a `1` in it, delete both** — the deck now reads these, so a stale value would point the audio back at the HDMI card:

```bash
sudo sed -i '/^WSPR_DEVICE *=/d;/^WSPR_RX_CARD *=/d' /opt/cyberdeck/cyberdeck.conf
sudo systemctl restart cyberdeck-ui
sleep 5
systemctl is-active cyberdeck-ui
```

## Reset to the state you're on now

```bash
sudo cp /opt/cyberdeck-restore/*.py /opt/cyberdeck/
sudo cp /opt/cyberdeck-restore/cyberdeck.conf /opt/cyberdeck/
sudo systemctl restart cyberdeck-ui
sleep 5
systemctl is-active cyberdeck-ui
```

That puts back both the code and the conf exactly as they are before Step 2.

If the panel doesn't come up after either direction:

```bash
journalctl -u cyberdeck-ui -n 40 --no-pager
```

Send me that and run the reset.

**What's new since your last deploy:** the slot row reads `to next: TX` with only the mode highlighted, the level says `measuring…` while the first window records instead of a bare dash, lines 1/2/4 of the lower block are packed as you preferred, `^B inhibit` is on the hints line, and the ToT now disarms transmit while receive, decode and hopping keep running.