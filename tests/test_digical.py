"""The digimode calibration screen -- src/cyberdeck.py, src/render.py.

Manual only, deliberately. An automatic version was built and discarded
on 2026-11-27 as "overcomplicated and kludgey for what it is worth": a
receive ladder can only take one reading per six-second gap between WSPR's
114-second capture windows, so it needed minutes to reach an answer a hand
reaches in seconds. These two screens are `render.wspr_cal_screen` with an
`area`, which is what keeps `+` and `-` meaning the same thing in the two
areas. See `docs/wspr_design.md` 6a2.

No curses, no codec, no radio: the deck is built with `__new__` and given
only the attributes these paths touch.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report

import cyberdeck
import render


class Fldigi:
    """Counts tune calls against stops, so a stuck carrier is visible."""

    def __init__(self, answers=True):
        self.answers = answers
        self.tunes = 0
        self.stops = 0

    @property
    def keyed(self):
        return self.tunes > self.stops

    def tune(self):
        if not self.answers:
            return False
        self.tunes += 1
        return True

    def transmitting(self):
        return self.keyed

    def modem_loaded(self):
        return "BPSK31"

    def stop_transmit(self, tries=3):
        if self.tunes > self.stops:
            self.stops += 1
        return True, ""


class Mix:
    """A mixer with coarse raw steps, like the real codec.

    **Steps of 3, on purpose.** `Speaker` on this codec has about 37 raw
    steps, so one step is roughly 2.7% and a percentage target rounds to
    whatever is nearest. A fake that moved in exact percentages would hide
    the bug this models: walking a ladder of percentages from 46% reached
    41% and 49% and nothing between them.
    """

    def __init__(self, v=25, lo=0, hi=100, fail=""):
        self.v = int(v)
        self.lo, self.hi = lo, hi
        self.fail = fail
        self.moves = []

    def read(self):
        return self.v

    def step(self, up):
        if self.fail:
            return self.fail
        self.v = max(self.lo, min(self.hi, self.v + (3 if up else -3)))
        self.moves.append(self.v)
        return ""

    def apply(self, pct):
        # `fail` has to bite here as well as in `step`, or a test for a
        # refused apply quietly asserts nothing.
        if self.fail:
            return self.fail
        self.v = int(pct)
        self.moves.append(int(pct))
        return ""


class Dead:
    def read(self):
        return None

    def apply(self, pct):
        return "amixer failed"


class Session:
    def __init__(self, inhibited=False):
        self.inhibited = inhibited


class Wspr:
    def __init__(self, on):
        self.wspr = on


def deck(kind="tx", drive=25, gain=62, inhibited=False, wspr_running=False,
         mix=None, fl=None, watts=11.5, rig_missing=False):
    d = cyberdeck.Deck.__new__(cyberdeck.Deck)
    d.cfg = {"DIGI_TX_DRIVE": drive, "DIGI_RX_GAIN": gain,
             "DIGI_TX_CONTROL": "PCM", "WSPR_RX_CARD": "Device",
             "TX_POWER_MAX": 20}
    d.session = Session(inhibited)
    d.wspr = Wspr(True) if wspr_running else None
    d.digi_cal = kind
    d.digi_cal_from = ""
    d.digi_cal_message = ""
    d._rx_gain_cache = None
    d._rx_gain_at = 0.0
    d.screen = cyberdeck.DIGICAL
    d.edit = None
    d.menu = ""
    d.notes = []
    d._screen_note = lambda t: (d.notes.append(t),
                                setattr(d, "digi_cal_message", t))
    d._save_state = lambda: None
    d._close_menu = lambda: None
    d._open_menu = lambda m: setattr(d, "menu", m)
    d.fldigi = fl or Fldigi()
    d._mix = mix or Mix(drive if kind == "tx" else gain)
    d._digi_playback_mixer = lambda card=None: d._mix
    d._wspr_capture_mixer = lambda: d._mix
    d._rf_power_set = lambda: (None if rig_missing else 5.0)
    return d


def said(d):
    return " | ".join(str(n) for n in d.notes)


print("the transmit carrier asks the interlocks first")
# `main.tune` was observed to key the radio with fldigi's own rx_only set --
# docs/digimodes_design.md §7 -- so the deck's interlock is the only gate
# in front of it.
fl = Fldigi()
d = deck("tx", inhibited=True, fl=fl)
d._digi_cal_tone()
equals("an inhibited transmitter keys nothing", fl.tunes, 0)
check("and says what arms it", "^B" in said(d), said(d))

fl = Fldigi()
d = deck("tx", fl=fl, rig_missing=True)
d._digi_cal_tone()
equals("no power reading keys nothing", fl.tunes, 0)
check("and names rigctld", "rigctld" in said(d), said(d))

fl = Fldigi(answers=False)
d = deck("tx", fl=fl)
d._digi_cal_tone()
check("a silent fldigi is reported", "not answering" in said(d), said(d))

fl = Fldigi()
d = deck("tx", fl=fl)
d._digi_cal_tone()
equals("Enter starts the carrier", fl.tunes, 1)
d._digi_cal_tone()
equals("and Enter again stops it", fl.stops, 1)
check("leaving nothing keyed", not fl.keyed)

print("\n+ and - move the level and apply it")
# **One mixer step each press, and every value in between reachable.**
# This walked a ladder of percentages, which on a control with ~37 raw
# steps meant `+` and `-` toggled between 41% and 49% from a start of 46%
# and nothing between them could be set: "- and + only toggle the tx drive
# between 41% and 49%. i'd like it to move in units of 1 up or down."
d = deck("tx", drive=46)
d._digi_cal_step(True)
equals("+ moves one step up", d._mix.read(), 49)
equals("and stores what the mixer actually took",
       d.cfg["DIGI_TX_DRIVE"], 49)
d._digi_cal_step(False)
d._digi_cal_step(False)
equals("- walks back down through the values between",
       d._mix.read(), 43)
check("so 46 is reachable again", 43 < 46 < 49)

# amixer clamps at the ends itself, so the extremes hold.
d = deck("tx", drive=100)
d._digi_cal_step(True)
equals("the top holds", d._mix.read(), 100)
d = deck("tx", drive=0)
d._digi_cal_step(False)
equals("and so does the bottom", d._mix.read(), 0)

d = deck("rx", gain=62)
d._digi_cal_step(True)
equals("+ raises the capture gain", d._mix.read(), 65)
equals("and stores that", d.cfg["DIGI_RX_GAIN"], 65)

# Not while WSPR has borrowed the control: it restores what it found when
# the session ends, so a change made now vanishes later with no reason.
mix = Mix(62)
d = deck("rx", gain=62, wspr_running=True, mix=mix)
d._digi_cal_step(True)
equals("the gain is left alone mid-WSPR", mix.moves, [])
check("and says why", "borrowed" in d.digi_cal_message, d.digi_cal_message)

d = deck("tx", drive=46, mix=Mix(46, fail="amixer: no such control"))
d._digi_cal_step(True)
check("a refused step is reported", "drive" in d.digi_cal_message,
      d.digi_cal_message)
equals("and the setting is untouched", d.cfg["DIGI_TX_DRIVE"], 46)

d = deck("rx")
d._wspr_capture_mixer = lambda: Dead()
equals("an unreadable control reads as None", d._rx_gain_now(), None)

print("\nleaving the screen puts the carrier down")
fl = Fldigi()
d = deck("tx", fl=fl)
d._digi_cal_tone()
check("keyed before leaving", fl.keyed)
d._close_digi_cal()
check("Esc out of the screen unkeys", not fl.keyed, (fl.tunes, fl.stops))
equals("and goes back to the digimode screen", d.screen, cyberdeck.CHAT)

fl = Fldigi()
d = deck("tx", fl=fl)
d._digi_cal_tone()
cyberdeck.Deck._handle_digi_cal(d, 27)
check("Esc unkeys through the handler", not fl.keyed)
equals("and closes the screen", d.digi_cal, "")

fl = Fldigi()
d = deck("tx", fl=fl)
d._digi_cal_tone()
cyberdeck.Deck._handle_digi_cal(d, 3)
check("^C drops the carrier", not fl.keyed)
equals("and stays on the screen", d.digi_cal, "tx")

d = deck("tx")
d.digi_cal_from = "digi_audio"
d._close_digi_cal()
equals("Esc goes back to the audio menu", d.menu, "digi_audio")

print("\nits notes stay off the air")
# `_screen_note`'s fallthrough is `session.note`, which is the TRANSCRIPT --
# a record of what went over the air, and a capture gain was never part of
# any conversation.
d = deck("rx")
d.session.notes = []
d.session.note = lambda t: d.session.notes.append(t)
cyberdeck.Deck._screen_note(d, "capture gain 63%")
equals("the note lands on the screen's own line",
       d.digi_cal_message, "capture gain 63%")
equals("and nothing reached the transcript", d.session.notes, [])

print("\nthe screen names its instrument")
# "the meter" left the operator choosing between the radio's power meter,
# its ALC and the deck's own figure: "it's not clear what meter i should be
# looking at. it should specify which meter." The answer is now explicit,
# and it is the RADIO's meter, because that is the only calibrated one.
tx = "\n".join("".join(t for t, _a in ln) for ln in render.wspr_cal_screen(
    66, 20, area="DIGIMODE",
    state={"kind": "tx", "level": 40, "set_watts": 5.0, "keyed": True}))
check("it names the ALC as the thing to find", "ALC" in tx, tx)
check("and the radio's power meter as the confirmation",
      "meter reads" in tx, tx)
check("it shows the reliable number, the setting", "5.0 W" in tx, tx)

rx = "\n".join("".join(t for t, _a in ln) for ln in render.wspr_cal_screen(
    66, 18, area="DIGIMODE", state={"kind": "rx", "level": 62, "dbfs": None}))
check("receive says there is no meter here", "no meter here" in rx, rx)
check("and does not draw an empty bar", "[---" not in rx, rx)

# The WSPR receive screen states the band as a number, not only as a marked
# stretch: a bar says "not there yet" without saying what "there" is.
wr = "\n".join("".join(t for t, _a in ln) for ln in render.wspr_cal_screen(
    66, 18, area="WSPR", state={"kind": "rx", "level": 70, "dbfs": -35.0}))
check("the WSPR receive screen states the target band",
      f"{render.METER_GOOD_LO:.0f}" in wr and f"{render.METER_GOOD_HI:.0f}" in wr,
      wr)
equals("the band floor is the measured one", render.METER_GOOD_LO, -40.0)
equals("and the ceiling is the operator's", render.METER_GOOD_HI, -30.0)

# Only WSPR carries a dBm, because only a WSPR message encodes its power.
wtx = "\n".join("".join(t for t, _a in ln) for ln in render.wspr_cal_screen(
    66, 20, area="WSPR",
    state={"kind": "tx", "level": 18, "set_watts": 5.0, "meter": 0.102,
           "watts": "5.0", "dbm": 37, "dbm_exact": True, "ceiling": 100,
           "keyed": True}))
check("the WSPR transmit screen carries the dBm", "37 dBm" in wtx, wtx)
check("while the digimode screen does not", "dBm" not in tx, tx)

print("\nthe two areas share one screen, so + cannot drift apart")
for area, want in (("WSPR", "WSPR CALIBRATE"), ("DIGIMODE", "DIGIMODE CALIBRATE")):
    head = "".join(t for t, _a in render.wspr_cal_screen(
        66, 18, area=area, state={"kind": "tx", "level": 25})[0])
    check(f"{area} titles its own screen", want in head, head)



print("\nthe screen is wired into the right dispatch")
# **This is the check that was missing when it crashed.** The branch was
# added to the DRAW dispatch instead of the key dispatch, because one is
# spelled `elif self.screen ==` and the other `if self.screen ==`, so a
# search for the neighbouring WSPRCAL line matched the wrong method. A
# `_draw_*` takes no `ch`, so entering the screen raised NameError on its
# first redraw and the deck exited: "crashes the application", reported
# against both digimode calibration entries. Nothing drove the real
# dispatch, so nothing caught it.
import inspect

draw_src = inspect.getsource(cyberdeck.Deck.draw)
handle_src = inspect.getsource(cyberdeck.Deck.handle)

check("the draw dispatch draws the screen",
      "self._draw_digi_cal(h, w)" in draw_src, "missing from draw()")
check("and the key dispatch handles it",
      "self._handle_digi_cal(ch)" in handle_src, "missing from handle()")
check("the draw dispatch calls NO key handler",
      "_handle_digi_cal" not in draw_src,
      "a _handle_* call in draw() cannot work: draw takes no ch")
check("and the key dispatch calls NO draw method",
      "_draw_digi_cal" not in handle_src,
      "a _draw_* call in handle() cannot work: handle takes no h, w")

# The same mistake is possible for any screen, so hold the whole dispatch
# to the rule rather than only this one screen.
import re
for name, src, wrong in (("draw", draw_src, "_handle_"),
                         ("handle", handle_src, "_draw_")):
    bad = sorted(set(re.findall(rf"self\.({wrong}\w+)\(", src)))
    check(f"no {wrong}* calls anywhere in {name}()", not bad, str(bad))

# And the screen has to be in the area map, or `_area()` cannot place it.
equals("DIGICAL belongs to the digimodes area",
       cyberdeck.AREA_OF.get(cyberdeck.DIGICAL), cyberdeck.AREA_DIGI)



print("\nthe digimode menu's KEYS match its labels")
# **The check that was missing.** `test_menus` asserts the labels and
# `test_menu_arrows` drives the real app, but nothing compared the menu's
# advertised keys against the keys the dispatch actually handles. Adding
# "Audio levels" as 5 twice left the dispatch on the old numbering, so 5
# cycled the log hotkey from a line labelled "Audio levels" and 7 did
# nothing. This is static, so it is fast and it runs everywhere.
import re
import decall
import menus as _menus

advertised = {k for k, _l in _menus.digi_menu(decall.PREFILL_SWITCH)["items"]}
body = inspect.getsource(cyberdeck.Deck._handle_menu)
start = body.index('if m in ("digi", "root"):')
end = body.index('if m == "digi_audio":', start)
branch = body[start:end]
handled = set(re.findall(r'key == "(\d)"', branch))
handled |= set(re.findall(r'"(\d)": "', branch))

equals("every advertised key is handled", sorted(advertised - handled), [])
equals("and nothing is handled that is not advertised",
       sorted(handled - advertised), [])
# And specifically: the three that moved.
equals("5 opens the audio menu",
       re.search(r'"5": "(\w+)"', branch).group(1), "digi_audio")
check("6 is the log hotkey", 'if key == "6":' in branch, branch[:200])
check("7 is the keys list",
      re.search(r'if key == "7":\s*\n\s*self\._open_menu\("keys"\)', branch)
      is not None, branch[:400])



print("\nthe WSPR calibration screen, which is the same screen")
# Covered here because it IS this screen -- one `render.wspr_cal_screen`
# with an `area` -- and because both behaviours below were asked for on
# 2026-11-27 against the WSPR side specifically.


class WsprTx:
    """A WSPR transmitter: a level, and a tone that can be running."""

    def __init__(self, level=25, keyed=False, fail=""):
        self.level = level
        self.keyed = keyed
        self.fail = fail
        self.tones = 0
        self.stops = 0

    def test_tone(self, seconds=40.0):
        if self.fail:
            return self.fail
        self.tones += 1
        self.keyed = True
        return ""

    def stop(self):
        self.stops += 1
        self.keyed = False


def wdeck(kind="tx", level=25, inhibited=False, tx=None, gain=None,
          mode_ok=True):
    d = cyberdeck.Deck.__new__(cyberdeck.Deck)
    d.cfg = {"WSPR_TX_LEVEL": level, "WSPR_RX_GAIN": 70}
    d.session = Session(inhibited)
    d.wspr_cal = kind
    d.wspr_tx = tx if tx is not None else WsprTx(level)
    d.wspr_gain = gain
    d.wspr_band = "20m"
    d._rx_gain_at = 0.0
    d.notes = []
    d._wspr_note = d.notes.append
    d._save_state = lambda: None
    d._rig_mode_ok = lambda: mode_ok
    return d


# **Units of 1.** This walked CAL_LEVELS, which jumps 25, 30, 40, so the
# operator could not stop between its rungs: "I'd like gain steps to be in
# units of 1 throughout."
d = wdeck("tx", level=25)
d._wspr_cal_step(True)
equals("+ moves the transmit level by exactly 1",
       d.cfg["WSPR_TX_LEVEL"], 26)
d._wspr_cal_step(False)
d._wspr_cal_step(False)
equals("- moves it back by 1 each time", d.cfg["WSPR_TX_LEVEL"], 24)
equals("and the transmitter follows", d.wspr_tx.level, 24)

d = wdeck("tx", level=100)
d._wspr_cal_step(True)
equals("the top holds", d.cfg["WSPR_TX_LEVEL"], 100)
check("and says so", "end of the range" in said(d), said(d))
d = wdeck("tx", level=1)
d._wspr_cal_step(False)
equals("and the bottom holds", d.cfg["WSPR_TX_LEVEL"], 1)

# The capture side steps the mixer itself, because a percentage cannot
# address ~35 raw steps -- one step is about 3% on this codec.
mix = Mix(70)
d = wdeck("rx", gain=mix)
d._wspr_cal_step(True)
equals("the capture gain moves by one mixer step", mix.read(), 73)
equals("and what the mixer took is what is stored",
       d.cfg["WSPR_RX_GAIN"], 73)

d = wdeck("rx", gain=Mix(70, fail="amixer: no control"))
d._wspr_cal_step(True)
check("a refused step is reported", "no control" in said(d), said(d))

# **Enter toggles.** It used to start a tone that only its own 40-second
# limit or ^C stopped: "i'd like enter to key the tx and enter to unkey
# the tx."
tx = WsprTx(keyed=False)
d = wdeck("tx", tx=tx)
d._wspr_cal_tone()
equals("Enter starts the tone", tx.tones, 1)
check("and says the carrier is up", "tone on" in said(d), said(d))
d._wspr_cal_tone()
equals("Enter again stops it", tx.stops, 1)
check("and says so", "tone off" in said(d), said(d))
equals("nothing was keyed a second time", tx.tones, 1)

# The interlocks still come first when it is NOT already keyed.
tx = WsprTx(keyed=False)
d = wdeck("tx", inhibited=True, tx=tx)
d._wspr_cal_tone()
equals("an inhibited transmitter sends nothing", tx.tones, 0)
check("and names what arms it", "Ctrl-B" in said(d), said(d))

tx = WsprTx(keyed=False)
d = wdeck("tx", tx=tx, mode_ok=False)
d._wspr_cal_tone()
equals("a rig out of a data mode sends nothing", tx.tones, 0)
check("and says why", "data mode" in said(d), said(d))

# **But a keyed transmitter is stopped before any interlock is consulted.**
# Enter must always be able to unkey: refusing to stop because the rig has
# since left a data mode would strand a carrier.
tx = WsprTx(keyed=True)
d = wdeck("tx", inhibited=True, tx=tx, mode_ok=False)
d._wspr_cal_tone()
equals("Enter stops a running tone regardless", tx.stops, 1)



print("\nthe transmit screens show one number and one procedure")
# **No meter and no verdict.** A dB-precise "N dB under the set power" lived
# here for an afternoon, dividing the meter deflection by the set wattage as
# though both were watts -- but the FTX-1's power meter is logarithmic and
# CAT reports the needle's POSITION, so it reported a radio making about 5 W
# as making 10.2. The raw deflection replaced it and then went too: "i'd
# actually get rid of the meter read out entirely. simplify."
#
# What is left is the one trustworthy number, the radio's own `PC` setting,
# and the operator's procedure, which is closable: raise until the ALC
# engages, back off one step, confirm the power. It replaces "keep the ALC
# out of it", which named no target -- the ALC is out of it at every level
# below the knee, including ones 20 dB too quiet.


def txscreen(area="DIGIMODE", keyed=True, set_w=5.0):
    rows = render.wspr_cal_screen(66, 22, area=area, state={
        "kind": "tx", "level": 10, "set_watts": set_w, "keyed": keyed,
        "watts": None, "dbm": 37, "dbm_exact": True, "ceiling": 100})
    return "\n".join("".join(t for t, _a in ln) for ln in rows)


body = txscreen()
check("the radio's setting is shown", "set" in body and "5.0 W" in body, body)
check("no meter reading is shown",
      "meter   0" not in body and "making" not in body, body)
check("no watts are claimed for anything measured",
      "10.2" not in body, body)
check("and no dB verdict", "dB under" not in body and "matched" not in body,
      body)
check("the procedure names the ALC as the thing to find",
      "ALC just engages" in body, body)
check("says to back off one step", "back off one step" in body, body)
check("and to confirm against the power meter",
      "power" in body and "meter reads" in body, body)
check("it does NOT say to keep the ALC out of it",
      "out of it" not in body, body)

# Both areas, same procedure.
for area in ("WSPR", "DIGIMODE"):
    b = txscreen(area=area)
    check(f"{area} carries the same procedure", "ALC just engages" in b, b)

# Nothing reads the radio's power meter any more.
import rigctld_client
check("power_meter is gone from the client",
      not hasattr(rigctld_client.Rigctld, "power_meter"))
check("and meter_watts with it",
      not hasattr(rigctld_client.Rigctld, "meter_watts"))
check("while power_control stays, as the one reliable number",
      hasattr(rigctld_client.Rigctld, "power_control"))

# The transmit preflight asks that reliable number, not the meter.
pre = inspect.getsource(cyberdeck.Deck._digi_tx_preflight)
check("the preflight checks the power SETTING",
      "_rf_power_set" in pre, pre)
check("and not the radio's power METER, which cannot be trusted",
      "power_meter" not in pre and "meter_watts" not in pre, pre)

print("\neach area asserts its own levels on entry")
# **The 74-versus-100 report.** The WSPR audio menu read 74% with WSPR off
# and 100% with it on, because 100% was only applied when a session
# started and 74% was what the digimodes had left on the shared control:
# "those levels should be set to whatever the wspr mode left them at as
# soon as you go to wspr functions screen. likewise for the levels for the
# digimode function screen."


def area_deck(wspr_gain=100, digi_gain=74, digi_drive=46, mix=None,
              play=None):
    d = cyberdeck.Deck.__new__(cyberdeck.Deck)
    d.cfg = {"WSPR_RX_GAIN": wspr_gain, "DIGI_RX_GAIN": digi_gain,
             "DIGI_TX_DRIVE": digi_drive, "WSPR_TX_DRIVE": 32}
    d._rx_gain_at = 0.0
    d._rx_gain_cache = None
    d.notes = []
    d._screen_note = d.notes.append
    d._cap = mix or Mix(0)
    d._play = play or Mix(0)
    d._wspr_capture_mixer = lambda: d._cap
    d._digi_playback_mixer = lambda: d._play
    return d


d = area_deck()
d._apply_area_levels(cyberdeck.AREA_WSPR)
equals("entering WSPR applies WSPR's capture gain", d._cap.read(), 100)
# **And applies WSPR's own playback level.** It was briefly pinned at full
# scale, on the reasoning that WSPR scales its own samples so the mixer
# belonged out of the way. That threw away about 20 dB and left the
# software scale to find all of it: the operator's ALC threshold moved to
# 1%, the minimum the control has, so there was one usable setting and no
# headroom under it. The mixer gives ~1 dB per step over 37 steps, which is
# where the attenuation belongs.
equals("and applies WSPR's own playback drive", d._play.read(), 32)

d = area_deck()
d._apply_area_levels(cyberdeck.AREA_DIGI)
equals("entering the digimodes applies theirs", d._cap.read(), 74)
equals("and their transmit drive too", d._play.read(), 46)

# Going back and forth leaves each area holding its own value, which is
# what "independent" means over one shared control.
d = area_deck()
for area, want in ((cyberdeck.AREA_WSPR, 100), (cyberdeck.AREA_DIGI, 74),
                   (cyberdeck.AREA_WSPR, 100), (cyberdeck.AREA_DIGI, 74)):
    d._apply_area_levels(area)
    equals(f"{area} holds {want}%", d._cap.read(), want)

# An area that is not one of the two touches nothing.
d = area_deck()
d._apply_area_levels(cyberdeck.AREA_LOG)
equals("other areas leave the levels alone", d._cap.moves, [])

# **Each area's transmit drive is its own**, over the one shared mixer.
d = area_deck()
d._apply_area_levels(cyberdeck.AREA_WSPR)
wspr_drive = d._play.read()
d._apply_area_levels(cyberdeck.AREA_DIGI)
digi_drive_now = d._play.read()
d._apply_area_levels(cyberdeck.AREA_WSPR)
equals("WSPR gets its own drive back", d._play.read(), wspr_drive)
check("which is not the digimodes'", wspr_drive != digi_drive_now,
      (wspr_drive, digi_drive_now))

# A mixer that refuses must not stop the operator arriving.
d = area_deck(mix=Mix(0, fail="amixer: no control"))
d._apply_area_levels(cyberdeck.AREA_WSPR)
check("a refused apply is reported", "capture gain" in said(d), said(d))

# And the ring calls it for both areas, which is the path that matters.
ring = inspect.getsource(cyberdeck.Deck._ring)
check("the ring applies them on landing",
      "_apply_area_levels(where)" in ring, "missing from _ring")
check("and _open_wspr does too, for the function-key route",
      "_apply_area_levels(AREA_WSPR)"
      in inspect.getsource(cyberdeck.Deck._open_wspr), "missing")



print("\nthe two areas are symmetric and decoupled")
# "full decoupled symmetry between the UI and workflow for setting wspr
# function audio levels and digimode function audio levels, while the
# levels themselves are saved for each function and restored upon entering
# that function, and decoupled from one another."
import menus as _m

wm = _m.wspr_audio_menu({"tx_level": 25, "rx_gain": 100, "rx_live": 100,
                         "dbfs": -33.0, "running": True})
dm = _m.digi_audio_menu({"tx_drive": 46, "rx_live": 74, "watts": 4.2})
equals("the same keys, in the same order",
       [k for k, _l in wm["items"] if k.strip()],
       [k for k, _l in dm["items"] if k.strip()])
equals("the same footer", wm["footer"], dm["footer"])
for m, who in ((wm, "WSPR"), (dm, "digimode")):
    row = m["items"][0][1]
    check(f"{who} names its transmit level the same way",
          "TX level" in row, row)
    check(f"{who} names its capture gain the same way",
          "RX gain" in row, row)
# The one wording that differs, and why: the deck can measure a dBFS for
# WSPR and cannot for the digimodes, because fldigi holds the stream.
check("only the receive entry differs, over the meter",
      "a meter" in dict(wm["items"])["m"]
      and "no meter" in dict(dm["items"])["m"],
      str([dict(wm["items"])["m"], dict(dm["items"])["m"]]))

# Both calibration screens are one function with one label set.
for kind in ("tx", "rx"):
    rows = {}
    for area in ("WSPR", "DIGIMODE"):
        rows[area] = [("".join(t for t, _a in ln)).strip()
                      for ln in render.wspr_cal_screen(
                          66, 20, area=area,
                          state={"kind": kind, "level": 25, "set_watts": 5.0,
                                 "measured": 4.2, "keyed": kind == "tx",
                                 "dbfs": -33.0 if kind == "rx" else None})]
    label = "TX level" if kind == "tx" else "RX capture gain"
    for area in ("WSPR", "DIGIMODE"):
        check(f"{area} {kind} uses the shared label {label!r}",
              any(label in r for r in rows[area]), str(rows[area][:6]))



print("\nthe WSPR calibration screen takes the codec for itself")
# **The gate inverted on 2026-11-28.** It used to require a running WSPR
# session, on the reasoning that only a session stops fldigi and frees the
# card. But a session is a competitor: its capture window holds the card
# for 114 s of every 120, so the receive probe was refused ~95% of the time
# ("no audio yet, not listening" while the main screen read -31 dBFS from a
# completed window), a transmit tone was cut short at 30 s with PTT left
# asserted, and the window it collided with came out truncated at 46.9 s.
# "is there a way to run these audio calibrations when WSPR isn't running
# instead of when it is? then they don't have to compete"


class Rx2:
    """A receiver whose probe can be stopped, for the handover test."""

    def __init__(self):
        self.started = 0
        self.stopped = 0
        self.busy_capturing = False

    def start_probe(self):
        self.started += 1
        return "/tmp/probe.wav"

    def probe_done(self):
        return ""

    def stop_probe(self):
        self.stopped += 1


class Gain2:
    def __init__(self, fail=""):
        self.fail = fail
        self.levels = []
        self.agc = []

    def silence_agc(self):
        # The calibration screen silences it exactly as a session does, or
        # it measures in a configuration WSPR does not run in.
        self.agc.append("off")
        return ""

    def restore_agc(self):
        self.agc.append("back")
        return ""

    def apply(self, pct):
        if self.fail:
            return self.fail
        self.levels.append(int(pct))
        return ""

    def read(self):
        return self.levels[-1] if self.levels else 70


def caldeck(running=False):
    d = cyberdeck.Deck.__new__(cyberdeck.Deck)
    d.cfg = {"WSPR_RX_GAIN": 100, "WSPR_TX_LEVEL": 10}
    d.wspr = Wspr(True) if running else None
    d.wspr_cal = ""
    d.wspr_cal_dbfs = None
    d.wspr_cal_from = ""
    d.wspr_message = ""
    d._wspr_note_at = 0.0
    d.menu = "wspr_audio"
    d.screen = cyberdeck.WSPR
    d.notes = []
    d._wspr_note = lambda t: (d.notes.append(t),
                              setattr(d, "wspr_message", t))
    d._close_menu = lambda: setattr(d, "menu", "")
    # Esc out of calibration returns to the menu it came from; that path
    # measures the screen, which these fakes do not have.
    d._open_menu = lambda m, remember=True: setattr(d, "menu", m)
    d._wspr_build = lambda: None
    d.wspr_gain = Gain2()
    d.wspr_rx = Rx2()
    d.wspr_tx = WsprTx()
    d.took = []
    d._wspr_take_audio = lambda: d.took.append("take") or True
    d._wspr_give_audio = lambda: d.took.append("give")
    return d


# With a session running it REFUSES, and closes the menu so the reason is
# visible rather than written underneath it.
d = caldeck(running=True)
d._open_wspr_cal("rx")
equals("a running session is refused", d.wspr_cal, "")
check("and the menu is closed first", d.menu == "", d.menu)
check("naming the session as the thing in the way",
      "stop WSPR" in said(d), said(d))
equals("and nothing was taken", d.took, [])

# With WSPR off it takes the card off fldigi and opens.
d = caldeck(running=False)
d._open_wspr_cal("rx")
equals("with WSPR off the screen opens", d.wspr_cal, "rx")
equals("and takes the audio from fldigi", d.took, ["take"])
equals("applying the configured gain", d.wspr_gain.levels, [100])
# **The codec's AGC is silenced here too.** It ships ON, and with it on the
# codec adds its own gain -- so a level set on this screen would be set
# against a configuration WSPR does not run in. It only surfaced when this
# screen stopped requiring a session, because `_wspr_start` had always
# silenced it first: 100% read -19.8 dBFS where it had read -31.
equals("the AGC is silenced, as a session does", d.wspr_gain.agc, ["off"])
equals("the screen is the calibration one", d.screen, cyberdeck.WSPRCAL)

# Leaving gives it back, after the probe is stopped.
d._close_wspr_cal()
equals("leaving gives the audio back", d.took, ["take", "give"])
equals("and puts the AGC back", d.wspr_gain.agc, ["off", "back"])
check("the probe was stopped first", d.wspr_rx.stopped >= 1,
      d.wspr_rx.stopped)
equals("and the transmitter was stopped", d.wspr_tx.stops, 1)
equals("back to the WSPR screen", d.screen, cyberdeck.WSPR)

# The transmit side takes it too: the tone needs the playback device.
d = caldeck(running=False)
d._open_wspr_cal("tx")
equals("transmit takes the audio as well", d.took, ["take"])
equals("and does not touch the capture gain", d.wspr_gain.levels, [])
d._close_wspr_cal()
equals("and gives it back", d.took, ["take", "give"])

# **One place knows the restart rule.** `_wspr_give_audio` carries the
# warning that fldigi started on top of a dying arecord comes up answering
# XML-RPC and deaf, so the screen reuses it rather than spawning its own.
src = inspect.getsource(cyberdeck.Deck._close_wspr_cal)
check("close reuses _wspr_give_audio", "_wspr_give_audio" in src, src)
check("and does not start fldigi itself",
      "cyberdeck-fldigi" not in src, src)

report()
