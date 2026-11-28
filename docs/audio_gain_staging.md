# Audio gain staging

**Read this before changing any audio level, in either direction.** The deck
and the radio have several gain stages in series, the deck owns only some of
them, and getting the split wrong produces faults that look like something
else entirely: a transmitter that ignores its level control, receive audio
that no amount of gain fixes, an ALC that engages at every setting.

Established on 2026-11-27 on the cyberdeck with an FTX-1. Every number here
was measured or set by the operator, not derived.

## The transmit chain

Four stages between the rendered audio and the antenna. The deck controls
the first two.

| | stage | what sets it | range | value |
|---|---|---|---|---|
| 1 | digital amplitude, applied when the WAV is rendered | `WSPR_TX_LEVEL` | 1–100% of full scale | **15%** |
| 2 | ALSA playback mixer on the codec, control `Speaker` | `WSPR_TX_DRIVE` | raw 0–37, ~1 dB/step, −37 dB to 0 dB | **50%** |
| 3 | the radio's own input gain | `USB MOD GAIN`, menu, mode DATA | 0–100 | **50** |
| 4 | the radio's ALC | nothing — it is the limit, not a control | — | must stay out |

Stage 1 is a percentage of **amplitude**, so 18% is −14.9 dB and 1% is
−40 dB. Stage 2 is roughly linear in **decibels**: 46% measured −20.00 dB
and 100% measured 0.00 dB, so about 1 dB per raw step across 37 steps.

**Stage 2 carries the coarse attenuation and stage 1 is the fine
adjustment.** That split is deliberate: stage 2 has 1 dB resolution over a
37 dB range, while stage 1 has a floor of 1% and no room below it.

### Why that split matters, with the fault that proved it

For one afternoon the deck pinned stage 2 at 100% on the reasoning that WSPR
scales its own samples, so the mixer belonged out of the way. That removed
about 20 dB from stage 2 and left stage 1 to find all of it. The result, from
the operator at the radio:

> at tx level 1% the alc doesn't seem to move, but at 2% it does move

The ALC threshold had moved to **1% — the minimum stage 1 has.** One usable
setting, no headroom under it, and turning the level down did nothing because
there was nowhere down to go. Before that change the operator had been
running 18% with the mixer at 46%, and reported the ALC engaging; the
arithmetic says why:

    stage 1 at 18%   -14.9 dB      stage 1 at  1%   -40.0 dB
    stage 2 at 46%   -20.0 dB      stage 2 at 100%    0.0 dB
                     --------                       --------
                     -34.9 dB total                 -40.0 dB total

The clean point is about **−40 dB total**, so the old 18%/46% setting was
roughly 5 dB into the ALC. The ALC complaints were real and were not a bug
in the deck.

### The settled operating point, measured

With stage 2 at 50% and `USB MOD GAIN` at 50, the operator measured:

| stage 1 | result |
|---|---|
| **10%** | no ALC, no compressor, about 5 W on the radio's meter |
| 11% | ALC engages |

**So 10% is the setting and the threshold is one step above it.** That is
what good gain staging looks like here: the useful point sits mid-scale with
headroom in both directions, and a 1% step is 0.83 dB — fine enough to find
the knee, coarse enough to find it quickly. Compare the pinned-mixer case
above, where the same knee sat between 1% and 2% with nothing below it.

The arithmetic is consistent with the −40 dB estimate:

    stage 1 at 10%   -20.0 dB
    stage 2 at 50%   -18.5 dB   (46% measured -20.00 dB, ~1 dB per step)
                     --------
                     -38.5 dB total

so the clean point on this station is about **−38 to −40 dB** of total
attenuation ahead of the radio, however it is divided between the stages.

## The receive chain

| | stage | what sets it | value |
|---|---|---|---|
| 1 | the radio's output level | `USB OUT LEVEL`, menu, mode DATA | **100**, raised from the default of 50 |
| 2 | ALSA capture mixer on the codec, control `Mic` (its cvolume) | `WSPR_RX_GAIN` / `DIGI_RX_GAIN` | **100%** |
| 3 | the capture device, which must take ONE channel | `WSPR_RX_DEVICE` | `ftx1rx` |

**`USB OUT LEVEL` is 100, not the shipped 50.** Raised deliberately, and the
deck's capture gain is set relative to it. If it is ever put back to 50 the
receive level drops by about 6 dB and the deck's gain has to be found again.

**Stage 3 is not a level and is easy to miss.** The FTX-1's codec presents a
two-channel capture with audio on the left only: measured ch0 at −16.8 dBFS
against ch1 at −65.7. ALSA's `plughw` converts stereo to mono by
**averaging**, which halves the live channel against the dead one and costs
about 6 dB — and the loss happens after the capture mixer, so no amount of
gain recovers it. `WSPR_RX_DEVICE = ftx1rx` is an `~/.asoundrc` device using
`route_policy copy`, which takes channel 0 instead.

At 100% capture gain the receive level reads about **−33 dBFS**, inside the
−40 to −30 band `render.METER_GOOD_LO/HI` marks.

## One codec, two areas

There is **one** capture mixer and **one** playback mixer on **one** codec.
WSPR and the digimodes cannot both hold them, so each area asserts its own
four values when the operator arrives in it —
`Deck._apply_area_levels`, called from `_ring` and `_open_wspr`:

    WSPR        WSPR_TX_LEVEL  WSPR_TX_DRIVE  WSPR_RX_GAIN
    digimodes                  DIGI_TX_DRIVE  DIGI_RX_GAIN

The digimodes have no stage 1 the deck can reach: fldigi's own output level
is not settable over XML-RPC, so `DIGI_TX_DRIVE` on the shared `Speaker`
control is the deck's only transmit lever there. That is the one asymmetry
between the two areas and it belongs to the hardware, not to a design choice.

## What the radio can and cannot tell you

**`PC;` is reliable.** The radio reports its power setting in real watts —
`PC2005;` is 5 W — and `Rigctld.power_control` reads it. Use this for "what
is it set to".

**The power meter is NOT a wattmeter.** Its face is logarithmic: 0 to 10 in
the first few percent of needle travel, 50 near the middle, 100 at about
three quarters, 150 at full scale. What comes over CAT is the needle's
**position**, and hamlib's `RFPOWER_METER_WATTS` is simply that position
multiplied by 100 — a linear reading of a logarithmic meter. On 2026-11-27 it
reported "10.2 W" for what was almost certainly 5 W, and the operator's own
needle could not tell 5 from 10 at that end of the scale.

So `Rigctld.power_meter` returns the deflection, 0 to 1, and **the deck does
not claim watts it cannot compute**. The figure is good for "did that step do
anything"; the absolute answer belongs to the operator reading the radio's
own meter.

**`ALC` over CAT is unusable on this radio.** It returned 1.00 at every drive
level across one five-point sweep and 0.28, 0.28, 0.00 across another a few
minutes earlier. Read the ALC needle on the radio instead. That is also why
the transmit screens say to set the level by the radio's meters.

**`TX_POWER_MAX` must match the configuration**, because it scales every
normalized CAT power reading. The FTX-1 has three maxima: field on battery
**6 W**, field on an external supply **10 W**, SPA-1 Optima **100 W**. The
software cannot discover which is fitted, so the operator sets it on the deck
& rig screen. With it wrong, the dBm a WSPR beacon encodes and uploads to
wsprnet is wrong too.

## Setting a transmit level, in order

1. Radio in **DATA-U** (reports as `PKTUSB`). Not an FM data mode: in FM the
   carrier comes from PTT and no audio level affects power.
2. `USB MOD GAIN` 50, `USB OUT LEVEL` 100, both under mode DATA. Leave them.
3. `TX_POWER_MAX` on the deck & rig screen matching the configuration.
4. Stage 2 (`*_TX_DRIVE`) at 50%, as the coarse setting.
5. Key the carrier from the calibration screen — `c`, then Enter.
6. Raise stage 1 until the radio's **ALC and compressor needles just start to
   move**, then come back a step. Watch the radio's meters, not the deck's
   number.
7. Confirm the radio's power meter reads what its power control is set to.
