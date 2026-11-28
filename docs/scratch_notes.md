# operator observations

## 2026 11 27

Written for: you, at the deck, reporting back by number.

**Before you start:** the transmit steps (8, 9, 14, 15) key the radio about a dozen times each with your hand on nothing. Dummy load or low power for the first pass. Where a step prints a trail in brackets, paste it verbatim — that's the evidence, not the summary.

RF Power set to 5 watts with antenna attached (75-10 efhw and ATU on)

---

### A. Display honesty — no transmit

**1.** Go to the WSPR screen. Read the levels row.
*Expect:* `TX audio N%` and either `RX gain N%` or `RX gain N% (set M%)` highlighted. Report both numbers.

first time around
tx audio 20%, RX gain 52% (set 100%)

second time around
tx audio 20%, RX gain 52% (set 100%)

(i don't get what rx gain 52% (set 100%) means...)

**2.** In a shell: `amixer -c Device sget Mic capture | grep -o '[0-9]*%' | head -1`
*Expect:* matches the first number in step 1. Proves the screen reads hardware, not config.

first time around:
deck@cyberdeck:~ $ amixer -c Device sget Mic capture | grep -o '[0-9]*%' | head -1
52%

second time around:
deck@cyberdeck:~ $ amixer -c Device sget Mic capture | grep -o '[0-9]*%' | head -1
52%

**3.** F1 → `a` (WSPR AUDIO).
*Expect:* entries `c`, `m`, `g`, `d`; footer ends "the levels are set in those screens"; status line shows TX audio, RX gain and either a dBFS figure or `no reading yet`.

first time around
it says tx audio 20% RX gain 52% (deck set 10%) no rea... and then the text is cut off.

i have 

c calibrate transmit a tone, + and - to set
m calibrate receive a meter, + and - to set

g auto-set receive fingds the gain by measuring
d auto-set transmit finds the level below clipping

the bottom bar says some things and the last thing is "the levels are set in those"... and then is cut off

second time around:
menus are clearer

i was able to calibrate tx volume, 20% is good
RX capture gain at 100% gives me about -33 dBFS - I think recommending between -40 and -30 would be a more sensible range, consistent with wsjt-x than -40 to -12 dBFS

### B. The steppers I broke and restored — no transmit

**4.** On WSPR AUDIO press `t` once.
*Expect:* `TX audio` moves up one rung (50 → 60) and a note naming the new level.

I think i messed up this test, i pressed t multiple time and the tx auidio went u pin increments to 100%. id idn't note the increments

**5.** Press `r` once.
*Expect:* `RX gain` moves one rung; note says `set now` if WSPR is running, else `applies when WSPR starts`.

I also messed up this i hit r a few times and it says RX gain 26% (set 25%), I'm not sure how many times I hit it

why do the t and r keys exist? is this just for testing or something? I don't get it.


### C. Recover the receive level

**6.** Press `m`. Use `+`/`-` until the dBFS reading sits between −30 and −20. Esc.
*Expect:* a live meter that moves; Esc returns to WSPR AUDIO, not past it. Report the final gain % and dBFS.

skipping this, i don't get it

### D. WSPR automatic — receive

**7.** Start WSPR. F1 → `a` → `g`.
*Expect:* first "waits for gaps between windows and takes a few minutes", then `calibrating… waiting for a gap between WSPR windows`, then a result with a bracketed dBFS trail. Minutes, not seconds. Paste the final line.

i'm running this and it is slow and annoying, i'm questioning whehter auto set for recieve and transmit audio are relevant here? it seems easy enough to manually set them with the existing funcitonality.

### E. WSPR automatic — transmit

**8.** With WSPR still running, F1 → `a` → `d`.
*Expect:* ~12 brief keyings, progress notes, then `WSPR transmit level N — [trail of watts]`. Paste the final line.

skipping this:

i'm questioning whehter auto set for recieve and transmit audio are relevant here? it seems easy enough to manually set them with the existing funcitonality.  I think i'd rather preserve the manual level setting funcitonality and rip out the automatic functionality which seems overcomplicated and kludgey for what it is worth.

TX 25% and RX 100% seem to be good default settings for this deck and radio as configured.

### F. The rollback test — the one that matters most

**9.** Note the current `TX audio` %. Start `d` again, and press **Esc** after two or three keyings.
*Expect:* `calibration stopped — level put back`, the radio unkeyed, and `TX audio` back at the value you noted — **not** left on the last rung tried. This is the fix for what damaged your receive gain.

skipping: already asked to remove the auto calibrate audio levels for wspr and it's done.

### G. Digimodes

**10.** Stop WSPR. Go to digimodes. F1 → `5`.
*Expect:* DIGIMODE AUDIO, with `c`, `m`, `t`, `g`, `a`, and an `RX gain` read from the codec.

on this screen it says 

TX drive 30% RX gain 52% (set 75%) measured not mea... and then it gets cut off.

I don't understand what RX gain 52% (set 75%) means and I don't like that the line is cut off.

**11.** Press `g`.
*Expect:* gain steps, menu stays open, the label shows the new value, note says it's set on the codec now.

this does move the RX gain but I don't know what it means or is doing

**12.** Press `m`.
*Expect:* header `DIGIMODE CALIBRATE — RECEIVE`; `no meter here` rather than an empty meter bar; `+`/`-` move the gain. Esc returns to the audio menu.

crashes the application

**13.** Press `c`. Press Enter. Adjust with `+`/`-`. Press Enter again. Then Esc.
*Expect:* header `DIGIMODE CALIBRATE — TRANSMIT`, `TX drive` and `measured N W`; Enter raises a carrier your radio's meter reads; `+`/`-` move the drive and the measured figure follows; second Enter drops it; **Esc leaves nothing keyed**. Confirm the carrier is down after Esc.

crashes the application

**14.** Press `t` (auto drive).
*Expect:* ~12 keyings, then `digimode transmit drive N — [trail of watts]`. Paste it.

exits to the main digimodes screen and says could not set 5: no playback control named 'pcm' on card device -level put back


similarlly to the WSPR funcitonality, I think i want this vastly simplfiied down to some manual tx and rx audio adjustment functionality with instructions on what meter to look at, possibly with a 100% duty cycle test tone. I don't think auto setting proceedures are worth the complication and fragility of the programming


**15.** Send a PSK31 message.
*Report:* the radio's power meter reading, and **whether the ALC engages**. Expect watts below step 14's figure — tune is 100% duty, PSK31 isn't. ALC staying out is the pass condition, not the wattage.

### H. Renumbering regression

**16.** On the digimodes F1 menu, press `6`, then reopen and check `7`.
*Expect:* `6` cycles the `^G` log-hotkey line in place; `7` opens the keys list; `5` is Audio levels.

**17.** Look at the digimodes conversation screen.
*Expect:* none of the calibration notes from steps 10–14 appear in the transcript. They belong on the screen's own message line, not in the on-air record.

---

If anything stops dead with no visible message, say so against its number — that pattern was the bug in steps 7 and 8 earlier today, and the fix was to close the menu before writing the reason, so a silent key is a real finding rather than a mystery.