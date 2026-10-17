## The conversation screen

```
┌──────────────────────────────────────────────────────────────────┐
│ KD3CCO  14.070.589  BPSK63  1500Hz  S/N 18  IMD -24    RX  2114Z │
│──────────────────────────────────────────────────────────────────│
│ 2109Z RX      KD3CCO de NOCALL  good copy, 599 here in State     │
│               College. rig is an FTX-1 running 20 watts into a   │
│               vertical.                                          │
│ 2111Z KD3CCO  NOCALL de KD3CCO  copy 100 percent. this is a pi   │
│               3a+ running fldigi headless behind a terminal i    │
│               wrote.                                             │
│ 2113Z RX      that is excellent. what modes does it do?          │
│ 2114Z --      mode changed to BPSK63                             │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│──────────────────────────────────────────────────────────────────│
│ NOCALL de KD3CCO  all the fldigi keyboard modes — psk, olivia,   │
│ mfsk, rtty                                               [RX 73] │
│ F1 menu  F2 tune  ^T over  ^Y hand  ^C abort  ^O ^P screen       │
└──────────────────────────────────────────────────────────────────┘
```

## The tuning screen — F2

```
┌──────────────────────────────────────────────────────────────────┐
│ TUNING  14.070.589  BPSK63  1500Hz  S/N 18  IMD -24    RX  2114Z │
│──────────────────────────────────────────────────────────────────│
│  rig      14.070.589  PKTUSB                                     │
│  carrier  1500 Hz        width  63 Hz                            │
│  signal   S/N 18 dB   IMD -24 dB                                 │
│                                                                  │
│  quality  ███████████████████████████░░░░░░░░░░░░░░░░░  62       │
│                                                                  │
│  AFC on   squelch on  (5)  RSID on   TXID on   REV off           │
│                                                                  │
│  decode                                                          │
│           NOCALL DE KD3CCO GOOD COPY ON 80M RTTY                 │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│──────────────────────────────────────────────────────────────────│
│  ← →   carrier ±10 Hz        ↑ ↓   search signal                 │
│  ,  .   VFO ±100 Hz          <  >   VFO ±1 kHz                   │
│  a AFC    s squelch    + - level    r RSID    t TXID    v REV    │
└──────────────────────────────────────────────────────────────────┘
```

## The menu — F1

```
┌──────────────────────────────────────────────────────────────────┐
│ DIGIMODES                                                        │
│                                                                  │
│  1  Mode                                                         │
│  2  Tune Settings                                                │
│▸ 3  Band                                                         │
│  4  Memories                                                     │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│──────────────────────────────────────────────────────────────────│
│ Esc back   ↑↓ move   Enter select   ^O ^P screen                 │
└──────────────────────────────────────────────────────────────────┘
```

## Tune Settings — F1 then 2

```
┌──────────────────────────────────────────────────────────────────┐
│ TUNE SETTINGS                                                    │
│                                                                  │
│  a  AFC         ON                                               │
│  s  Squelch     ON                                               │
│  +  Squelch level up       (15)                                  │
│  -  Squelch level down     (15)                                  │
│  r  RSID        ON    follow others' identifiers                 │
│  t  TXID        off   send one before our overs                  │
│  v  Reverse     off   mark/space sense, for RTTY                 │
│  c  Park carrier at the configured offset                        │
│  [  RX hold least  down   (1000 ms)                              │
│  ]  RX hold least  up     (1000 ms)                              │
│  {  RX hold most   down   (4000 ms)                              │
│  }  RX hold most   up     (4000 ms)                              │
│     On the conversation screen, without coming here:             │
│     Ctrl-A / Ctrl-D carrier ±10 Hz  Ctrl-W / Ctrl-S search       │
│                                                                  │
│                                                                  │
│──────────────────────────────────────────────────────────────────│
│ Esc back   ↑↓ move   Enter select   F2 live tuning               │
└──────────────────────────────────────────────────────────────────┘
```

## The mode picker — F3

```
┌──────────────────────────────────────────────────────────────────┐
│ MODE                                                             │
│                                                                  │
│  a  AUTO (RSID)  off                                             │
│  1  BPSK31                                                       │
│  2  BPSK63  <                                                    │
│  3  QPSK31                                                       │
│  4  RTTY                                                         │
│  5  OLIVIA-8/250                                                 │
│  6  OLIVIA-8/500                                                 │
│  7  MFSK16                                                       │
│  8  THOR22                                                       │
│  9  CONTESTIA                                                    │
│  0  DOMEX8                                                       │
│  h  FELDHELL                                                     │
│  c  CW                                                           │
│  m  more modes ...                                               │
│                                                                  │
│                                                                  │
│──────────────────────────────────────────────────────────────────│
│ Esc back   ↑↓ move   Enter select   < marks the mode in use      │
└──────────────────────────────────────────────────────────────────┘
```

## WiFi — F1 then 7 then w

```
┌──────────────────────────────────────────────────────────────────┐
│ WIFI                                                             │
│┌────────────────────────────────────────────────────────────────┐│
││  RADIO ON        r turns it off                                ││
││                                                                ││
││ ▸ 1  ✓ Fieldhouse                                     ████ WPA2││
││   2    Fieldhouse-Guest                               ███· WPA2││
││   3    PARK-WIFI                                      ██··     ││
││   4  · Hamshack                                       ██·· WPA3││
││                                                                ││
││  ✓ connected   · known   WPA2 etc = needs a passphrase         ││
││                                                                ││
││                                                                ││
││                                                                ││
││                                                                ││
││                                                                ││
││                                                                ││
││                                                                ││
││                                                                ││
│└────────────────────────────────────────────────────────────────┘│
│ Esc back  ↑↓ move  Enter join  n name  f forget  s scan  r radio │
└──────────────────────────────────────────────────────────────────┘
```

## The full modem list — F3 then m

```
┌──────────────────────────────────────────────────────────────────┐
│ ALL MODES  page 1/2                                              │
│                                                                  │
│  a CW                             n OLIVIA-4/250                 │
│  b BPSK31                         o OLIVIA-16/500                │
│  c BPSK63                         p OLIVIA-32/1K                 │
│  d BPSK125                        q MFSK16                       │
│  e BPSK250                        r MFSK8                        │
│  f BPSK500                        s MFSK32                       │
│  g QPSK31                         t MFSK64                       │
│  h QPSK63                         u CONTESTIA                    │
│  i QPSK125                        v THOR22                       │
│  j QPSK250                        w THOR16                       │
│  k RTTY                           x THOR25                       │
│  l OLIVIA-8/250                   y THOR50x1                     │
│  m OLIVIA-8/500                   z DOMEX8                       │
│                                                                  │
│                                                                  │
│                                                                  │
│──────────────────────────────────────────────────────────────────│
│ Esc  back      PgUp/PgDn  more                                   │
└──────────────────────────────────────────────────────────────────┘
```
## The WSPR screen — `^O` from the deck & rig screen

The fourth area, and the only one that is exclusive: while it runs, the ring
does not leave it and fldigi is stopped, because the USB codec takes one
capture client.

`KM` and `AZ` are computed from the two grid squares. Neither is stored in
the spot log, because both are derivable from the grids that are.

```
┌──────────────────────────────────────────────────────────────────┐
│ WSPR  general  20 m  14.095.600                    INH off  1748Z│
│──────────────────────────────────────────────────────────────────│
│ UTC     dB  CALL       GRID   dBm  BAND     KM   AZ              │
│ 17:46  -19  KD1SQ      FN67    23  20 m   1139   45              │
│ 17:46  -28  N9JNQ      EN34    23  20 m   1309  293              │
│ 17:46  -13  N4DPH      EM64    23  20 m   1565  258              │
│ 17:46  -17  W9LK       EM26    23  20 m   1203  272              │
│ 17:46  -14  G4HSB      IO94    23  20 m   5648   47              │
│ 17:44  -23  KD1SQ      FN67    23  20 m   1139   45              │
│ 17:44  -15  W9RAG      EN54    23  20 m   1005  298              │
│ 17:44  -29  K0PCG      JN49    23  20 m   6452   50              │
│                                                                  │
│──────────────────────────────────────────────────────────────────│
│ WSPR   DECODE   TX   TX NEXT   HOP                               │
│ max 100 W  5 W   37 dBm  snapped                                 │
│ slot 0:05 [#.............] 1:54 to next: RX                      │
│ TX audio 35%  RX gain 100%  level -37 dBFS                       │
│ heard 455    sent 1    upload on    session 46:42 left   decoding│
│ WSPR started on 20 m — ^O ^P are locked until it stops           │
│ F1 menu F2 session F3 band ↑↓ spots ^B inhibit ^C stop           │
└──────────────────────────────────────────────────────────────────┘
```

## The WSPR menu — F1 from the WSPR screen

Thirteen items, and that is a constraint rather than a count: `menus.render`
goes to two columns above `height - 6` items, and the second column has no
room for the values this menu exists to show.

```
┌──────────────────────────────────────────────────────────────────┐
│ WSPR                                                             │
│                                                                  │
│▸ w  WSPR                         on                              │
│  d  Decode                       on                              │
│  t  Transmit                     off                             │
│  n  Transmit next slot           off                             │
│  e  Session                      general                         │
│  b  Band                         20 m                            │
│  p  Transmit percent             20%                             │
│  o  Session ToT                  60 min                          │
│  u  Upload spots                 on                              │
│  f  Spot log                     wspr.log                        │
│  x  Export this session          455 heard, 1 sent               │
│  a  Audio levels                 TX 35%  RX 100%                 │
│  z  Danger zone — clear spots                                    │
│                                                                  │
│                                                                  │
│                                                                  │
│──────────────────────────────────────────────────────────────────│
│ Esc back   ↑↓ move   Enter select   ^O ^P locked while running   │
└──────────────────────────────────────────────────────────────────┘
```

## The band picker — F3, or `b` from the WSPR menu

A number or Enter selects that band alone and tunes to its WSPR dial.
Space toggles the highlighted band in and out of the hop rotation; `[*]`
marks the bands in it and `<` the one in use.

Selecting a band also reads the radio's mode and sets DATA-U if it is
not, remembering what was found — the radio keeps a mode per band.

```
┌──────────────────────────────────────────────────────────────────┐
│ WSPR BAND                                                        │
│                                                                  │
│  1  [ ] 80 m      3.568600 MHz                                   │
│  2  [ ] 40 m      7.038600 MHz                                   │
│  3  [ ] 30 m     10.138700 MHz                                   │
│▸ 4  [*] 20 m     14.095600 MHz <                                 │
│  5  [ ] 17 m     18.104600 MHz                                   │
│  6  [ ] 15 m     21.094600 MHz                                   │
│  7  [ ] 12 m     24.924600 MHz                                   │
│  8  [ ] 10 m     28.124600 MHz                                   │
│  9  [ ] 6 m      50.293000 MHz                                   │
│  0  [ ] 2 m     144.489000 MHz                                   │
│  a  [ ] 70 cm   432.300000 MHz                                   │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│──────────────────────────────────────────────────────────────────│
│ Esc back  Enter use this one  Space hop on/off  [*] in rotation  │
└──────────────────────────────────────────────────────────────────┘
```

## The audio menu — `a` from the WSPR menu

The levels are reported here and changed in the calibration screens, where
there is a meter to watch. Both are refused while WSPR is off, with the
reason given: they open the sound card, and fldigi holds it until WSPR
takes it.

```
┌──────────────────────────────────────────────────────────────────┐
│ WSPR AUDIO                                                       │
│                                                                  │
│        TX audio 35%     RX gain 100%     -37 dBFS                │
│                                                                  │
│▸ c  Calibrate transmit        a tone, + and - to set             │
│  m  Calibrate receive         a meter, + and - to set            │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│──────────────────────────────────────────────────────────────────│
│ Esc back   ↑↓ move   Enter select   the levels are set in those  │
└──────────────────────────────────────────────────────────────────┘
```

## Calibrating transmit — `c` from the audio menu

`+` and `-` step the level while the tone is playing. The instrument is the
radio's own power meter; the dBm is highlighted when the wattage lands
exactly on a value WSPR can encode.

```
┌──────────────────────────────────────────────────────────────────┐
│ WSPR CALIBRATE — TRANSMIT                                   20 m │
│──────────────────────────────────────────────────────────────────│
│                                                                  │
│   TX audio level   35%                                           │
│                                                                  │
│ max 100 W  5 W   37 dBm  snapped                                 │
│                                                                  │
│   transmitting — watch the radio's power meter                   │
│                                                                  │
│   Set the radio's drive so its meter reads what                  │
│   the deck reports; watch the dBm highlight.                     │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│ test tone transmitting                                           │
│  + - level  Enter send a tone  ^B inhibit  ^C stop  Esc back     │
└──────────────────────────────────────────────────────────────────┘
```

## Calibrating receive — `m` from the audio menu

The marked stretch of the meter is roughly what `wsprd` wants. The gain is
the capture mixer, which fldigi shares — safe to set only because WSPR
owns the codec while it runs, and put back when the session ends.

```
┌──────────────────────────────────────────────────────────────────┐
│ WSPR CALIBRATE — RECEIVE                                    20 m │
│──────────────────────────────────────────────────────────────────│
│                                                                  │
│   RX capture gain   100%                                         │
│                                                                  │
│ [############::::::::::::......]  -37.0 dBFS  good               │
│                                                                  │
│   listening                                                      │
│                                                                  │
│   Aim for the marked stretch of the meter.                       │
│   Too loud decodes worse than too quiet.                         │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│                                                                  │
│  + - level   ^B inhibit   Esc back                               │
└──────────────────────────────────────────────────────────────────┘
```

