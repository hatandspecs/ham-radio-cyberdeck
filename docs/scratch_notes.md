Every changed path is clean through a real pty. Here are the deploy and revert commands.

## Step 1 — on the laptop

```bash
cd ~/git_repos/keyboard-to-keyboard-cyberdeck
rsync -av src/*.py deck@cyberdeck.local:/tmp/deckupd/
```

Prints the file list — 20-odd `.py` files, `sent … bytes`.

## Step 2 — on the deck: back up, then install

```bash
sudo mkdir -p /opt/cyberdeck-backup-20261017
sudo cp /opt/cyberdeck/*.py /opt/cyberdeck-backup-20261017/
ls /opt/cyberdeck-backup-20261017/ | wc -l
```

The count is your safety net — it should match the number of `.py` files on the deck, not zero.

```bash
sudo cp /tmp/deckupd/*.py /opt/cyberdeck/
sudo systemctl restart cyberdeck-ui
sleep 5
systemctl is-active cyberdeck-ui
```

Prints `active`. The panel should come up on DECK & RIG.

## Step 3 — if it doesn't work, revert

```bash
sudo cp /opt/cyberdeck-backup-20261017/*.py /opt/cyberdeck/
sudo systemctl restart cyberdeck-ui
sleep 5
systemctl is-active cyberdeck-ui
```

`active` again, and you're back on the build you were just running. The polkit rule is independent of the code and can stay either way — it grants nothing the old build uses.

## If the panel doesn't come back

```bash
journalctl -u cyberdeck-ui -n 40 --no-pager
```

Send me that and revert with Step 3. A traceback goes to the journal rather than the screen by design, so this is where an import-time fault would show.

**What to check once it's up:** `^O` onto WSPR, then `F1` `w`. Within about two minutes you should see the slot bar filling and spots arriving with a `BAND` column — and no `Device or resource busy`. If the codec is still held, the deck will now refuse to start and say so rather than running a dead slot clock.