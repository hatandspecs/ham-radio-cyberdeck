# Deck and rig — design

The screen the deck opens on: what this station calls itself, what the deck
is doing, and the way into everything that is about the deck rather than
about the radio.

One of four application design documents. The others are
[`digimodes_design.md`](digimodes_design.md),
[`qso_log_design.md`](qso_log_design.md) and
[`wspr_design.md`](wspr_design.md). Requirements, hardware and the
cross-cutting architecture are in [`platform_design.md`](platform_design.md).

## 1. What it is for

Three jobs, and the third is the one that justifies the screen existing:

* **Edit the station.** Callsign, name, QTH, locator, rig, antenna and the
  power ceiling, each with the `{call}`-style token a message memory
  substitutes it into.
* **Say what the deck is doing**, in one word, where the operator is looking
  at power-on.
* **Be an area of its own**, a peer of the logger and the digimodes rather
  than a menu hanging off them.

## 2. Why it is an area and not a menu

The deck's settings were once a line on the digimode menu. Reaching them
meant starting on the digimode screen, which made the digimode screen the
deck's home whether or not that was intended — and the deck does three
things now, of which digital modes are one.

So the three are peers on a ring: `settings | log | digimodes`, walked with
`^O` and `^P`, wrapping, every area one keystroke from both others. The
consequences that follow from being a peer rather than a menu:

* **`F1` opens this area's menu**, as it opens the menu for whichever area
  the operator is in.
* **`F2` and `F3`** are this area's two sub-views — Display and System —
  the way they are the tuner and the mode picker on the digimode screen and
  the activities and schemas on the log screen.
* **`Esc` backs out within the area and never leaves it.** There is no "up"
  from an application to go to.

## 3. The deck opens here

Not on the conversation, which is where it used to open.

The reason is what the screen says rather than what it edits. **The startup
notes go to the transcript** — "no connection to fldigi, waiting for it" is
the most important thing the deck can say at power-on — and a deck that
opened somewhere else left that message on a screen nobody was looking at.

So the header carries one word of state, computed without touching the
radio:

| Word | Means |
|---|---|
| `NO MODEM` | fldigi is not answering |
| `TX INHIBITED` | fldigi is up and transmit is not armed |
| `TX ARMED` | fldigi is up and transmit is armed |

Both readings are plain attributes — `connected` is set by the fldigi client
on every call it makes, and the inhibit is the session's own flag. Neither
is a query, which §5 explains is not a detail.

## 4. The station fields

| Field | Token | Notes |
|---|---|---|
| Callsign | `{call}` | |
| Name | `{name}` | |
| QTH | `{qth}` | |
| Locator | `{grid}` | mixed case by convention — `FN10cs`, not `FN10CS` |
| Rig | `{rig}` | goes on every logged contact |
| Antenna | `{ant}` | goes on every logged contact |
| Max power (W) | — | the ceiling, not the power |

**Every row is editable and the cursor lands on all of them.** No headings,
nothing to skip, nothing drawn that cannot be used — a cursor that can sit
on a row where `Enter` does nothing reads as a broken key.

**The tokens are shown here deliberately.** The moment an operator wants to
know that `{qth}` exists is the moment they are looking at what QTH is set
to. A separate list of tokens somewhere else is a list nobody finds.

### `TX_POWER_MAX` is not `TX_POWER`, and only one of them is here

**`TX_POWER_MAX` is the ceiling** the radio's RFPOWER reading is scaled
against. CAT reports power as a fraction between 0 and 1, so without the
ceiling the deck cannot turn a reading into watts at all. On the FTX-1 it
genuinely changes with the configuration — field head on its own battery,
field head on external power, and the Optima are three different maxima —
which is why it is a setting an operator has to be able to type, and why it
is on this screen.

**`TX_POWER` is deliberately NOT on this screen.** It is read from the radio
by `_power_now()`, which falls back to the configured value only when the
radio will not answer. A row for typing it invites setting a number the
radio immediately contradicts. The `{power}` token is unaffected and
substitutes the live reading, so removing the row cost the token nothing.

The distinction matters beyond this screen: WSPR announces its power in dBm
derived from the same reading, and a wrong ceiling there is a wrong figure
in a public database. See [`wspr_design.md`](wspr_design.md) §6.

## 5. Nothing on this screen queries the radio

The live readings — frequency, mode, power, the modem — used to be on here
and are gone.

Each cost a round trip: `_power_now` opens rigctld and asks the radio, the
rest are XML-RPC to fldigi. **The main loop draws five times a second**, so
the screen was making about thirty queries a second while sitting still,
plus six more per keystroke because the key handler rebuilt the row list to
find which rows were editable. On a Pi with CAT over a serial port that
outran the 200 ms poll and the interface fell behind — which presented as
slow scrolling and was in fact the screen being slow the entire time it was
open.

**Nothing on a draw path may call the radio without a cache.** That is a
deck-wide rule, stated here because this screen is where breaking it was
most expensive. The readings are on the digimode status line and the tuning
screen, which are the screens that are about the radio.

## 6. What the menus hold

**`F1` — DECK & RIG**, two lines, because the screen behind it is the
station editor and a menu offering a second list of the same eight settings
was the same information twice.

* **`1` Display** — the five color schemes and the timestamp toggle.
* **`2` System** — pair a Bluetooth keyboard, WiFi, the transmit inhibit,
  clear the transcript, quit.

### The color schemes are the kernel's palette

Five monochrome schemes — Matrix green, Deckard amber, Hal red, Tron cyan,
Ripley white — switched with `F4` from any screen on the deck.

They are not ANSI colors. The deck redefines entries in the **console
palette** through the `PIO_CMAP` ioctl, which is what `setvtrgb(1)` uses and
needs `CAP_SYS_TTY_CONFIG` — granted to the unit as an ambient capability
and nothing else. The palette is a property of the console and not of the
process, so the deck restores it on the way out: without that, whatever owns
tty1 next inherits the scheme.

This is also why the schemes are not a terminal-emulator concern and why a
framework that rendered its own colors would not produce them.

### System holds the things with no better home

Pairing and WiFi are each a screen of their own, reached from here because
they are done rarely and are not about the radio. Pairing a keyboard from
the panel matters for a specific reason: the deck cannot be told anything
when it has no keyboard, so it raises the pairing screen by itself in that
one case. See [`platform_design.md`](platform_design.md) §17.

## 7. What is remembered

The station fields, the color scheme, the timestamp setting and the
menu-changeable settings are written to the state file when they settle —
not on every keystroke, because the card is an SD card.

The settings the MENUS change were once absent from that file while the code
that changed them called `_save_state`: lines-per-contact set to 3 was back
at 1 after a restart, a dupe rule switched to call-only was back to
band+mode. The fix was to put them in the dict that gets written; the lesson
is that calling the save is not the same as being saved.

## 8. Testing

| Property | Tested by |
|---|---|
| the rows, their tokens and their order | `render.settings_screen`, pure, at any width |
| that every row is editable and none is skipped | the key handler against the derived row list |
| the state word | the three conditions, without a radio |
| that the screen makes no radio queries | the absence of the calls, asserted as a property of the source |
| the ring, and `F1`/`F4` from here | `tests/test_area_ring.py`, through a real pty |
| the palette | `tests/test_colors.py`, and a real console by eye |

**The one that cannot be automated** is how the palette looks on the panel.
A desktop terminal renders all of Unicode and any color; the console has
sixteen palette entries and a font with a small glyph set. A scheme that
looks right here can be unreadable there, and the only way to know is to log
into tty1 and look.
