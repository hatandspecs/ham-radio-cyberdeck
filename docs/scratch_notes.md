Both faults are fixed. Here's the picture.

## The crash — diagnosed from your traceback, no guessing needed

A **NUL byte reached the transcript**. You were logging SSB, so the rig was out of a data mode, so the deck had parked the decoder onto fldigi's `NULL` modem — and the text coming back from the RX buffer carried a `\x00`.

Two things made that fatal rather than cosmetic:

- `curses.addstr` raises **`ValueError`** for an embedded NUL, not `curses.error`. `_put` caught only `curses.error`, so it escaped.
- `errors="replace"` on the decode doesn't help. It handles bytes that aren't valid UTF-8; `0x00` **is** valid UTF-8 and decodes to `"\x00"`.

And `_put` is what *every* screen draws through, so it took the whole deck down — then systemd restarted it, the transcript came back, and it crashed again on the same byte.

**Fixed at both levels:** control characters are stripped where the text enters (keeping `\n`, `\r`, `\t`, which the line-based transcript needs), and `_put` now survives an undrawable byte from *any* source — it strips and retries, then skips the segment rather than dying. A panel missing a character is a nuisance; a panel that's gone is an operator with no radio.

## No further diagnostics needed

Your traceback settled the crash. The PTT/audio chain I'd already traced through the code. **One thing worth doing anyway**, because it cost us evidence earlier:

```bash
sudo mkdir -p /var/log/journal
sudo sed -i 's/^#\?Storage=.*/Storage=persistent/' /etc/systemd/journald.conf
sudo systemctl restart systemd-journald
journalctl --disk-usage
```

Without it the journal lives in RAM and every power cycle discards exactly the tracebacks we need.

## Deploy

```bash
cd ~/git_repos/ham-radio-cyberdeck
rsync -av src/*.py deck@cyberdeck.local:/tmp/deckupd/
```

On the deck:

```bash
sudo rm -rf /opt/cyberdeck-restore
sudo mkdir -p /opt/cyberdeck-restore
sudo cp /opt/cyberdeck/*.py /opt/cyberdeck/cyberdeck.conf /opt/cyberdeck-restore/
ls /opt/cyberdeck-restore/*.py | wc -l
```

Expect a non-zero count. Then:

```bash
sudo cp /tmp/deckupd/*.py /opt/cyberdeck/
sudo systemctl restart cyberdeck-ui
sleep 5
systemctl is-active cyberdeck-ui
```

## Revert

```bash
sudo cp /opt/cyberdeck-restore/*.py /opt/cyberdeck/
sudo cp /opt/cyberdeck-restore/cyberdeck.conf /opt/cyberdeck/
sudo systemctl restart cyberdeck-ui
sleep 5
systemctl is-active cyberdeck-ui
```

## What this deploy carries

**Three transmitter-safety fixes**, which is why I'd put it on before the next session rather than after:

- Killed `arecord`/`aplay` children are now **waited for** before the card is handed back. Not doing so is what let fldigi restart into a still-busy codec and come up deaf — a deaf fldigi keys the radio and never completes the over, which is your stuck PTT.
- **The unkey is verified.** It asks, reads PTT back, and asks again up to four times, reporting *"the radio is still keyed after 4 attempts"* instead of silently returning. Previously it fired once and discarded the result.
- **Shutdown returns WSPR's borrowings** — fldigi, the capture gain, the AGC, and any band left in DATA-U.

Plus the NUL crash fix, and the color order (Hal → Deckard → Matrix → Tron → Ripley) which was already staged.

1,289 checks green across the fast tier including 46 new ones for the NUL fault; the pty tier covering the transcript-drawing paths is running and I'll flag anything it finds.