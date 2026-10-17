Unit tests are green (513 checks across the eight affected files). While the pty smoke finishes, here are the commands — the unit tier plus a compile check is the minimum you asked for, and I'll flag immediately if the pty run turns anything up.

## Deploy

```bash
cd ~/git_repos/keyboard-to-keyboard-cyberdeck
rsync -av src/*.py deck@cyberdeck.local:/tmp/deckupd/
```

```bash
sudo mkdir -p /opt/cyberdeck-backup-3
sudo cp /opt/cyberdeck/*.py /opt/cyberdeck-backup-3/
sudo cp /tmp/deckupd/*.py /opt/cyberdeck/
sudo systemctl restart cyberdeck-ui
sleep 5
systemctl is-active cyberdeck-ui
```

## Revert

```bash
sudo cp /opt/cyberdeck-backup-3/*.py /opt/cyberdeck/
sudo systemctl restart cyberdeck-ui
sleep 5
systemctl is-active cyberdeck-ui
```

## What changed

**The menu showing no on/off states was a regression I caused** — adding three rows took it to 16 items, and `menus.render` goes two-column above 14, where there's no room for the values. That's also why the TX level "didn't work": it *was* working, you just couldn't see the number change. The three audio rows are now one **Audio levels** submenu (`F1` then `a`), so the menu is back to 13 items with every value on its line.

**The test tone failure was a real bug.** `_key` set PTT and read it back immediately — the FTX-1 hadn't reported it yet, so the deck concluded "the radio did not key", unkeyed, and refused. That's exactly the brief click you saw. The readback now polls for up to 600 ms.

**Calibration is now a screen, not a one-shot**, reachable from the audio menu:
- `c` — transmit: `+`/`-` step the level *while the tone is playing* (it re-sends at the new level, which is what adjusting under the tone means for rendered audio), `Enter` sends a 40-second tone, `Ctrl-X` stops it.
- `m` — receive: a live dBFS meter updating about once a second, with `+`/`-` on the gain. The meter marks the stretch `wsprd` wants, so you can see which way to go. It takes the codec itself if WSPR isn't running, and gives both the gain and fldigi back on Esc.

**Mode handling replaced as you asked.** The check is gone. Selecting a band now reads the mode, and if it isn't a data mode, remembers it and sets DATA-U. Leaving a band restores it while the radio is still there; stopping WSPR visits every band it changed, restores each, and returns you to the band you were on. Bands already in a data mode are never recorded, so WSPR won't "restore" something you set yourself.

I also found that `rigctld_client.mode()` returns a `(mode, width)` **tuple**, which my hop-check had been comparing against a set of strings — it could only ever have reported "could not read". That code is gone, and the new mode logic uses `mode()[0]`.

One caveat worth stating: `set_mode` is new and **unverified against your radio.** The DATA-U set-and-revert is the one thing in this deploy I can't test here — if `M PKTUSB 0` isn't what the FTX-1 wants, band selection will report "was USB — set to PKTUSB" and the radio won't have moved. That's the first thing to check.








# TO DO: The Discrete WSPR Power Levels up to 100 watts


when in ftx-1 optima configuration, the minimum selectable RF power on the radio is 5 watts. The ftx-1 field configuration when on attached batter or external 12vdc, can do at least down to 1 watt, and I think fractions of a watt, possibly 100s of mw or at least 500mw. I need to update the cyberdeck to accomodate these lower power settings so they are selectable when in ftx-1 field configuration.

Power (dBm)	Approximate Wattage Equivalent
0 dBm	1 mW
3 dBm	2 mW
7 dBm	5 mW
10 dBm	10 mW
13 dBm	20 mW
17 dBm	50 mW
20 dBm	100 mW
23 dBm	200 mW
27 dBm	500 mW
30 dBm	1 W
33 dBm	2 W
37 dBm	5 W (Standard QRP limit for WSPR)
40 dBm	10 W
43 dBm	20 W
47 dBm	50 W
50 dBm	100 W

# To Do: consistency, calibration, and simplification items

when i turn RX audio up to 100%, it's still slighly below the target range on the meter. I think i need more headroom in the RX audio. I'd like 100% to end up above the ideal range on the meter.

ctrl i should inhibit or arm TX regardless of what screen I am on.

i get an audio error when wspr is off.  I think instead wspr should be on as long as I am on the wspr screen and then turn wspr off when I am not on the wspr screen.  band modes that were changed during the wspr session should change back when leaving the wspr screen. entering or leaving the wspr screen should be the thing that turns it on and off and then we can get rid of that from the f1 menu for wspr.  this will also clear up an error where if wspr is not on and I try to calibrate audio, i get capture device errors. when i turn wspr on on hte f1 menu I don't get this error.

I also don't think there is value in having the t TX audio level and the r rx capture gain items on the audio levels sub-menu. I think just showing what the audio levels are on that screen concicsely and then being able to modify them inside the clalibrate tx audio and calibrate rx audio sub-screens is idea and good enough.

Finally, I think that if no session is set a named default session should be active. rather than "no session.
