Deploy once the pty check comes back (I'll confirm), or now if you want it sooner — the change is well covered by the fast tier.

## Snapshot the current state

```bash
sudo rm -rf /opt/cyberdeck-restore
sudo mkdir -p /opt/cyberdeck-restore
sudo cp /opt/cyberdeck/*.py /opt/cyberdeck/cyberdeck.conf /opt/cyberdeck-restore/
ls /opt/cyberdeck-restore/*.py | wc -l
```

## Deploy

On the laptop:

```bash
cd ~/git_repos/keyboard-to-keyboard-cyberdeck
rsync -av src/*.py deck@cyberdeck.local:/tmp/deckupd/
```

On the deck:

```bash
sudo cp /tmp/deckupd/*.py /opt/cyberdeck/
sudo systemctl restart cyberdeck-ui
sleep 5
systemctl is-active cyberdeck-ui
```

## Reset to current state

```bash
sudo cp /opt/cyberdeck-restore/*.py /opt/cyberdeck/
sudo cp /opt/cyberdeck-restore/cyberdeck.conf /opt/cyberdeck/
sudo systemctl restart cyberdeck-ui
sleep 5
systemctl is-active cyberdeck-ui
```

**The test for this one is the exact thing you hit:** reboot, go straight to WSPR, `F1`, `w`. The menu should stay responsive. You may see `fldigi still has the audio — skipping this window` for the first slot or two while systemd finishes stopping fldigi, and then captures should begin — that message is the deck telling you what it's waiting for instead of freezing while it waits.

On the stale files: all fourteen are tools and test scripts, no source modules, so nothing shadows anything and they're safe to leave. Worth knowing that `wspr_level.py` is among them — when I had you run it earlier and it wasn't found at `~/tools`, it was sitting at `/opt/cyberdeck/wspr_level.py` the whole time. That's my error in the path I gave you, not a missing tool.