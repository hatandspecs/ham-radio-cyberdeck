---
marp: true
paginate: true
footer: "KD3CCO · github.com/hatandspecs/ham-radio-cyberdeck"
style: |
  /* Plain white, one clear typeface, nothing decorative.
     Assertion-evidence: the headline is a full sentence making a claim and the
     body is the evidence for it. Carried inside this file rather than in a
     separate theme so the deck renders identically in the VS Code preview, in
     `marp` on the command line, and in an exported PDF, with nothing to
     register or configure first. */
  section {
    background: #ffffff;
    color: #111111;
    font-family: "Liberation Sans", Helvetica, Arial, sans-serif;
    font-size: 23px;
    line-height: 1.45;
    padding: 44px 56px 56px;
    /* The built-in theme wins on specificity for these, and its selectors are
       not ones a style block can match, so they are forced. The h1 color is a
       variable the theme exposes; the rest are not. */
    display: flex !important;
    flex-direction: column !important;
    justify-content: flex-start !important;
    --h1-color: #111111;
  }
  /* The assertion. A whole sentence, left aligned, never a category label. */
  section h1 { font-size: 32px; font-weight: 600; line-height: 1.25; margin: 0 0 20px 0; color: #111111 !important; }
  section h2 { font-size: 25px; font-weight: 600; margin: 0 0 12px 0; }
  section p { margin: 0 0 12px 0; }
  section ul { margin: 0 0 12px 0; padding-left: 26px; }
  section li { margin: 0 0 8px 0; }
  section strong { font-weight: 600; }
  section blockquote { margin: 0 0 16px 0; padding: 0 0 0 18px; border-left: 3px solid #cccccc; color: #222222; }
  section a { color: #0b4fa8; text-decoration: none; }
  section code { font-family: "Liberation Mono", Consolas, monospace; font-size: 0.86em; background: #f3f3f3; padding: 1px 5px; }
  section pre { background: #f6f6f6; border-left: 3px solid #cccccc; padding: 12px 16px; font-size: 17px; line-height: 1.45; margin: 0 0 14px 0; }
  section pre code { background: none; padding: 0; font-size: 17px; }
  /* Whatever the source image is, it fits the space that is left. */
  section img { display: block; margin: 0 auto; max-width: 100%; max-height: 430px; width: auto; height: auto; }
  section.evidence h1 { margin-bottom: 14px; }
  section.evidence img { max-height: 440px; }
  /* A slide whose evidence is a tall photograph: the picture is a panel down
     one side, so it is never scaled to a stamp to make it fit. */
  section.panel h1 { margin-bottom: 18px; }
  section.title, section.closing { justify-content: center !important; }
  section.title h1 { font-size: 42px; margin-bottom: 16px; }
  section.title p, section.closing p { font-size: 25px; color: #444444; }
  section .caption { display: block; font-size: 18px; color: #555555; margin-top: 10px; }
  /* Two pieces of evidence side by side, each with its own label. Sized by
     height so a tall photograph and a wide screenshot sit level, and so a
     replacement image of any shape still fits the slide. */
  section .pair { display: flex; gap: 30px; justify-content: center; align-items: flex-end; margin-top: 8px; }
  section .pair figure { margin: 0; text-align: center; }
  section .pair img { max-height: 232px; width: auto; margin: 0 0 6px 0; }
  section .pair figcaption { font-size: 17px; color: #555555; }
  section .trio img { max-height: 182px; }
  /* Two wide screen captures whose own header text has to stay
     readable from the back of a room. */
  section .pair.tall img { max-height: 320px; }
  section footer { font-size: 14px; color: #888888; }
  section::after { font-size: 14px; color: #888888; }
---

<!-- _class: title -->
<!-- _paginate: false -->
<!-- _footer: "" -->

# A ham radio cyberdeck

**KD3CCO**

An HF terminal for \$68 — conversation, logbook, WSPR, and a band sweep

---

<!-- _class: evidence -->

# My desk is 20 by 14 inches, and a laptop does not fit on it

![](img/the-deck-on-the-desk.jpg)

<span class="caption">The whole station: the deck, a Bluetooth keyboard, and the FTX-1 just out of frame.</span>

---

# Every digital-mode program assumes a waterfall, a mouse, and a bunch of cluttered windows

That is the right design for tuning and for contesting.

It is the wrong design for **having a conversation** — which is what RTTY, PSK31 and Olivia were built for, and the part I actually wanted.

Opening a laptop to operate also feels like clocking back in.

---

<!-- _class: evidence -->

# So the screen shows the conversation, and not much else

![](../docs/screens/conversation-matrix.png)

<span class="caption">66 columns by 20 rows. A status line, the conversation, what you are typing, and the keys that do something.</span>

---

<!-- _class: evidence -->

# The first contact on it was RTTY, and it went exactly like any other QSO

![](img/first-rtty-qso-n3qe.jpg)

<span class="caption">N3QE: "FB DON I HAVE YOU AS NUMBER 1." </span>

---

![bg right:38%](img/pi-behind-the-panel.jpg)

<!-- _class: panel -->

# It is a \$25 computer behind a \$43 panel, on standoffs that are also the stand

Raspberry Pi 3A+ · Waveshare 5-inch DSI panel · 66 × 20 characters of text.

It ran like this to begin with — the panel plugs into a ribbon cable, the standoffs hold it up, and nothing in the build is beyond a screwdriver.

---

<!-- _class: evidence -->

# A CRT-inspired case finishes the device

<div class="pair">
<figure><img src="img/shell-openscad-model.png"/><figcaption>drawn in OpenSCAD, around the real panel</figcaption></figure>
<figure><img src="img/shell-stl-render.png"/><figcaption>the shell it exports</figcaption></figure>
</div>

<span class="caption">Parametric, so the panel, the Pi and the standoff heights are numbers at the top of the file rather than measurements baked into a mesh — which matters when the thing you are modeling is already built and cannot change to suit the model.</span>

---

![bg right:36%](img/cased-deck-side-profile.jpg)

<!-- _class: panel -->

# KD3CCP printed the case and it came out great

It does two jobs. It **encloses the electronics** — the Pi, the back of the panel, and the ribbon cable between them, which was the most exposed thing on the bare build. And it is **a stable stand**.


**Twelve days** from the first contacts on this thing to a printed shell around it.

---

<!-- _class: evidence -->

# And it earns its place on the desk beside my radio

![](img/cased-deck-with-ftx1.jpg)

<span class="caption">Calling CQ on 20 m BPSK31. The FTX-1 does the radio; the deck does the conversation.</span>

---
<!-- _class: evidence -->

# I did not write a modem, and that is the whole trick

A PSK31 demodulator that beats fldigi's would be a multi-year project, and I would lose.

![width:1150px](img/modem-chain.png)

**XML-RPC** is one program calling functions inside another over HTTP. fldigi publishes a documented method list and keeps it stable across releases; the deck calls forty of them — `modem.set_by_name`, `main.set_frequency`, `text.add_tx`, `text.get_rx`. That makes it a supported client of fldigi, not a fork of it and not a screen-scrape.

**The loopback interface** is `127.0.0.1`, the machine talking to itself. The calls never reach a network card, nothing is open to the LAN, and there is no port to secure.

All of fldigi's signal processing. None of its interface.

---

<!-- _class: evidence -->

# Every control is one keystroke away

![](../docs/screens/tuning.png)

<span class="caption">F2 tuning: carrier, AFC, squelch, signal search. F3 changes mode. Either key gets you back.</span>

---

<!-- _class: evidence -->

# Without a waterfall to look at, the deck has to hunt for the signal itself

![](img/signal-search-matrix.jpg)

<span class="caption">"search down: carrier 2059 → 1729 Hz." It steps the carrier looking for something above the squelch, because there is no picture to point at.</span>

---

<!-- _class: evidence -->

# It keeps up with an RTTY sprint exchange

![](img/rtty-sprint-exchange-k4zw.jpg)

<span class="caption">Serial number, name, state, sent and confirmed, in about 70 seconds on 80 m.</span>

---

<!-- _class: evidence -->

# Explaining the deck to another operator, using the deck

![](img/explaining-the-deck-on-the-air.jpg)

<span class="caption">BPSK31 on 20 m: "i built this psk machine with a raspberry pi." KC3FL came back with a full station list — rig, beam, verticals, beverage.</span>

---

<!-- _class: evidence -->

# The color schemes are an indulgence, and worth every minute

![](img/color-schemes.png)

<span class="caption">Five schemes, switched from the menu. Amber is the readable one in daylight; matrix is the one people ask about.</span>

---

<!-- _class: evidence -->

# It pairs its own Bluetooth keyboard, with no second computer

![](../docs/screens/pairing-passkey.png)

<span class="caption">Pairing needs a screen and a keyboard that types. The deck has a screen; the keyboard being paired types.</span>

---

<!-- _class: evidence -->

# It joins a WiFi network from the panel, and keeps time without one

![](../docs/screens/wifi.png)

<span class="caption">A \$15 real-time clock means a field session is stamped correctly with the WiFi switched off.</span>

---

<!-- _class: evidence -->

# It has worked real DX — Martinique on 20 m PSK31, 20 watts

![](img/dx-qso-fm4ti-martinique.jpg)

<span class="caption">Also Germany, JO41XW — two operators in mountain villages, four thousand miles apart, typing at each other.</span>

---

<!-- _class: evidence -->

# It grew a logbook, and the logbook changed the shape of the program

![](../docs/screens/log-pota.png)

<span class="caption">A contest exchange is a serial and a section, and `599` is both a valid report and a valid serial — no positional parser can tell them apart. So the operator defines the field list per activity, and that list <em>is</em> the grammar.</span>

---

<!-- _class: evidence -->

# Three applications became peers on a ring, not a menu tree

![width:900px](../docs/screens/log-menu.png)

<span class="caption">`^O` and `^P` move between the digimodes, the log and the deck's own settings. It began as the digimodes alone with the rest hanging off its menu, which made the digimode screen the home by accident rather than by anyone's decision.</span>

---

<!-- _class: evidence -->

# A fourth joined them: WSPR, which has to own the radio

![](../docs/screens/wspr.png)

<span class="caption">The USB codec takes one capture client, measured rather than assumed — so WSPR stops fldigi, takes the card, and gives both back. It is the only area the ring refuses to leave while it runs.</span>

---

<!-- _class: evidence -->

# Five watts reached 43 receivers in one slot, and Belgium on the next band

![](img/wspr-reach.jpg)

<span class="caption">The encoder was validated by having the real `wsprd` decode the deck's own output on the bench. The decoder is a 55 KB binary extracted from a 36 MB package, and it decodes a two-minute slot in 14.5 seconds at 20 MiB on a Pi 3A+.</span>

---

<!-- _class: evidence -->

# The band plan is a stop on the ring, split the way the regulation splits it

![width:900px](../docs/screens/alloc.png)

<span class="caption">General and Extra, each band divided into its CW/data and phone segments. `Space` changes license class. It tunes nothing — the point of a reference is being one key away while operating rather than on a phone in a pocket.</span>

---

<!-- _class: evidence -->

# Which applications are on the ring is now a setting, not a constant

![width:900px](../docs/screens/ringed.png)

<span class="caption">WSPR taken off the ring and the band plan moved to the front. A field weekend and a contest weekend want different rings. Deck & rig cannot be removed, because it holds the system menu, but it can be moved.</span>

---

<!-- _class: evidence -->

# The deck sweeps a band and leaves a tuner memory every 10 kHz

![width:900px](../docs/screens/tuner-running.png)

<span class="caption">Pick segments, press Enter, and the deck walks them keying the radio at each point so the external mAT-30 stores a match. Afterwards, changing frequency recalls a memory instead of running a fresh tune cycle. The segment list is the band plan's, so the sweep never parks outside the license class.</span>

---

<!-- _class: evidence -->

# Both logs draw themselves on a map, scoped to the session being run

<div class="pair tall">
<figure><img src="../docs/screens/wspr-map.png"/><figcaption>WSPR spots, one session</figcaption></figure>
<figure><img src="../docs/screens/log-map.png"/><figcaption>contacts, one activity</figcaption></figure>
</div>

<span class="caption">Written straight to `/dev/fb0`, because handing the framebuffer to `fim` or `fbi` means handing over the keyboard too. Contacts with no grid are counted in the header rather than dropped — "4 with no grid" beats a map that looks like a quiet afternoon.</span>

---

<!-- _class: evidence -->

# The files leave on a phone, over the deck's own WiFi, with no account and no uplink

![width:900px](../docs/screens/export.png)

<span class="caption">One key stands up a web page for five minutes. The request names a position in a list the deck handed the server, never a filename — so there is no path to traverse, and `cyberdeck.secrets` is not on the list. It works on a field hotspot with nothing behind it.</span>

---

# Seven features passed 3,994 tests, and then the panel found eleven faults

**Some were things no test could reach.** The framebuffer and the text console are the same memory, so curses erased the map a frame after it was drawn. An aborted over stayed in fldigi's transmit widget and went out ahead of the next message. The tuner's settle time was a guess about how long a radio takes to change frequency.

**Some were gaps between tested parts.** The tuner crashed the deck on `Enter` because one line said `self.rig` where the rest of the file says `self._log_rig()` — the sweep engine tested against a fake radio, the screen tested on its own, and nothing calling the method between them. **If a key starts something, a test should press the key.**

**The rest were the specification being wrong**, which only showed up in use: a map of everything instead of a map of tonight, a filter for data the deck does not have, a session list reachable from a key but not from the menu. Most of the repair was removing things.

---
<!-- _class: evidence -->

# AI helps with faster code and better documentation practices

![width:940px](img/doc-first-cycle.svg)

Hobby time arrives as confetti: twenty minutes before dinner, an hour on a Sunday. What decides whether a project happens is how much progress fits inside one fragment — a text terminal for HF with 3,994 tests behind it was never going to happen otherwise.

**Then turn it against your own design.** Write down how it should work, ask for an analysis of the alternatives, and ask the question worth more than any of them: *does this design imply there are tools, techniques or facts I am not accounting for?*

---

<!-- _class: evidence -->

# Code, documentation, slides and the blog in one window, where the assistant can see all of it

![width:810px](img/vscode-workspace.png)

<span class="caption">Documentation is markdown in the repository, beside the code. Everything advances in the same sitting, so nothing drifts. The blog is another repository in the same workspace; these slides are markdown in this one.</span>

---

<!-- _class: closing -->

# It started because a laptop did not fit on my desk

**Code, design document, runbook, operating tutorial**
github.com/hatandspecs/ham-radio-cyberdeck

**Write-up, with photographs and the things that went wrong**
hatandspecs.github.io/hamradio/articles/keyboard-to-keyboard-cyberdeck/

It runs on an ordinary laptop too: start fldigi, run one Python file.

**KD3CCO** — questions welcome
