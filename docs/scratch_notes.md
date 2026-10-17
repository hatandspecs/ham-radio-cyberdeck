Deploy and then, next time the first-toggle failure happens, one command will tell us the cause.

```bash
cd ~/git_repos/keyboard-to-keyboard-cyberdeck
rsync -av src/*.py deck@cyberdeck.local:/tmp/deckupd/
```

```bash
sudo mkdir -p /opt/cyberdeck-backup-5
sudo cp /opt/cyberdeck/*.py /opt/cyberdeck-backup-5/
sudo cp /tmp/deckupd/*.py /opt/cyberdeck/
sudo systemctl restart cyberdeck-ui
sleep 5
systemctl is-active cyberdeck-ui
```

Revert:

```bash
sudo cp /opt/cyberdeck-backup-5/*.py /opt/cyberdeck/
sudo systemctl restart cyberdeck-ui
sleep 5
systemctl is-active cyberdeck-ui
```

**The diagnostic, run while the first toggle has just failed:**

```bash
systemctl is-active cyberdeck-fldigi; systemctl is-active cyberdeck-rigctld
journalctl -u cyberdeck-fldigi -u cyberdeck-ui --since '-3 min' --no-pager | tail -30
```

That shows whether fldigi came back up after WSPR stopped it, and what systemd did in between. The journal will settle it.

## On the first-toggle bug

I did not find it, and I want to be clear about that rather than imply I did. What I ruled out: the toggle isn't swallowed (`wspr_running` and the schedule's own flag agree), and the scheduler is symmetric across toggles. One thing I did find that partly explains "nothing happens": **`tick` deliberately skips the slot you're already inside** — pressing `w` 30 seconds into a slot means the first capture starts at the next even minute, so up to two minutes of a screen that looks dead. That's correct behavior but indistinguishable from broken.

What I changed is the audio takeover: it now waits for fldigi to actually be gone, checks it's *still* gone a second later, stops it once more if not, and refuses with a clear message rather than running a slot clock over a codec it doesn't have. That makes the deck check rather than assume — which was missing regardless of the cause.

I also have to correct something I wrote a moment ago: I attributed fldigi coming back to `Restart=always`. That's wrong — systemd clears the restart on a deliberate stop. The mechanism that *can* bring it back is `cyberdeck-ui.service`'s own `Wants=cyberdeck-fldigi.service`, which systemd re-satisfies whenever the UI restarts — i.e. right after a deploy, which is exactly when you've been testing. The code comment now says that instead.

Also in this deploy: sub-watt power no longer truncates to `0 W` (that was the real cause of "power unknown" from a radio answering fine), `PTT command failed` now names its cause, and the four hardware-address settings are out of remembered state so a stale state file can't override a corrected device again.

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
