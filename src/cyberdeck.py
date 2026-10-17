#!/usr/bin/env python3
#
# Copyright (C) 2026 Donald Natale (KD3CCO)
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program. If not, see <https://www.gnu.org/licenses/>.
"""Keyboard-to-keyboard terminal for fldigi.

The only thing on the screen: a status line, the conversation, and what is
being typed. No window manager, no pointer, nothing to click. fldigi does the
modem work invisibly behind an XML-RPC connection (docs/platform_design.md §4).

Run it over SSH for development; on the deck it runs on tty1 against the
framebuffer, where the color schemes use the real palette.
"""

import curses
import datetime
import json
import os
import signal
import sys
import time

import activities
import colors
import config as configmod
import logform
import qsolog
import menus
import render
import touch as touchmod
from fldigi_client import Fldigi
from session import Entry, Session, RX, TX

CHAT, TUNE, PAIR, NOKB, WIFI = "chat", "tune", "pair", "nokb", "wifi"
LOG, FIELDS, ORDER = "log", "fields", "order"
# One logged contact, field by field. The list has one row per contact and a
# contact has up to forty fields, so without this the ones that did not fit
# were unreadable on the panel and correctable only over SSH -- which is no
# use from the bench where the mistakes get made.
ENTRY = "entry"
# What the deck calls logging with no activity in progress. Internally that is
# still an empty `ACTIVITY` writing to the file `LOG_PATH` names -- this is the
# name on the screen, and the row on the activities list that selects it.
#
# It replaced "casual logging", which described the same state and sounded like
# an absence of one. The master log is a place: every contact ever made is in
# it, whatever activity made it.
MASTER_LOG = "master log"
# The deck and the radio: what this station is and what the panel does. A
# screen rather than a menu because the settings are one of three AREAS, and an
# area needs somewhere to land.
SET = "settings"

# Activities on disk, and the question asked before anything is
# destroyed. The confirmation is a screen of its own because deleting a
# log deletes contacts, and a prompt sharing a screen with the thing it
# is about gets answered by reflex.
ACTS, CONFIRM = "activities", "confirm"

# The three areas, and the ring `^B` and `^F` walk. In that order, though in a
# three-ring the order only decides which direction is shorter: every area is
# one step from both others.
#
# Why control characters and not the arrows. `infocmp linux` defines NO
# modified cursor keys, so Alt+Left reaches the framebuffer console as Esc
# followed by KEY_LEFT -- and Esc is load-bearing on every screen here, so it
# would fire first. `xterm-256color` defines only the SHIFT forms, which means
# Shift+Left would work in the laptop rig and be a dead key on the deck: the
# exact fault class `tests/test_console_keys.py` exists to catch. Control
# characters are 7-bit and arrive identically on every terminal.
# WSPR: a fourth area, and the only one that is EXCLUSIVE. While it is
# running the ring does not leave it and fldigi is stopped -- the USB codec
# holds one capture client and that is measured, not assumed. See
# `docs/wspr_design.md` §2.
WSPR = "wspr"
# And its calibration screen, which is part of the WSPR area rather than a
# menu: the levels are set against a meter, which means watching a reading
# while pressing a key, and a menu cannot show a reading that moves.
WSPRCAL = "wsprcal"

AREA_SETTINGS, AREA_LOG, AREA_DIGI = "settings", "logging", "digimodes"
AREA_WSPR = "wspr"
RING = (AREA_SETTINGS, AREA_LOG, AREA_DIGI, AREA_WSPR)
# Ctrl-O and Ctrl-P: adjacent keys, O left of P, so back and forward map onto
# the ring the way they sit under the hand. Both were unbound, which is what
# makes them the cheap answer -- PgUp and PgDn keep the paging and scrolling
# they already do on the transcript, the contact list, the field selector and
# the all-modes list, and Home and End keep the cursor-to-the-ends job they do
# in all three places something is typed.
#
# Ctrl-M was asked for first and cannot be bound: it IS byte 13, carriage
# return, so no terminal can tell it from Enter and the ring would fire instead
# of logging a contact. Ctrl-N was byte 14 and once opened the log.
#
# Ctrl-O is `VDISCARD` in the tty line discipline and can be swallowed by it
# while IEXTEN is set, which is why `tests/test_area_ring.py` drives both keys
# through a real pty rather than calling the handler: the only proof that a
# control character reaches the application is watching it arrive. It does.
RING_BACK, RING_FWD = 15, 16                     # Ctrl-O, Ctrl-P

# Transmit inhibit, on every screen. **Ctrl-B and not Ctrl-I**: Ctrl-I is
# byte 9 and so is Tab, which no terminal can distinguish and the console
# cannot even in principle -- so the interlock sat on the same key as "next
# field". Ctrl-B was unbound.
INHIBIT_KEY = 2

# How long a dropped CAT read may keep reporting the last mode that was read.
# Long enough to cover a handful of consecutive failures at five draws a
# second, short enough that a radio switched off is admitted to quickly. See
# `Deck._rig_mode_held`.
_RIG_MODE_HOLD = 8.0

# Which area each screen belongs to. Anything missing belongs to digimodes,
# which is where the deck starts and where a screen with no better home goes.
AREA_OF = {
    SET: AREA_SETTINGS,
    LOG: AREA_LOG, ACTS: AREA_LOG, ENTRY: AREA_LOG,
    FIELDS: AREA_LOG, ORDER: AREA_LOG,
    CHAT: AREA_DIGI, TUNE: AREA_DIGI,
    WSPR: AREA_WSPR, WSPRCAL: AREA_WSPR,
}

# Screens the ring must not leave. A question has to be answered and a field
# being typed has to be finished or abandoned deliberately; cycling away from
# either would discard it silently.
AREA_LOCKED = (CONFIRM, PAIR, WIFI, NOKB)

# Settings a menu can change, which therefore have to outlive a restart. The
# conf file is where each one STARTS; the state file is what it is now. Keep
# this in step with the menus: a setting that is changeable and not listed here
# silently reverts, which reads as the panel forgetting rather than as a bug.
_REMEMBERED = ("LOG_LINES", "DUPE_CHECK", "CALLBOOK", "OPERATING",
               "MY_PARK", "EXCHANGE_TX",
               # **Every WSPR setting, because not one of them was here.**
               # They are all reached from a WSPR menu or a calibration
               # screen, which is the rule this tuple follows -- and without
               # them a power cycle put the transmit level, the capture
               # gain, the band rotation, the session name, the time-out and
               # the upload toggle back to whatever the conf file said. The
               # audio levels were reported as "not sticking through power
               # cycles"; the rest were silently the same bug.
               "WSPR_TX_LEVEL", "WSPR_RX_GAIN", "WSPR_BANDS",
               "WSPR_TX_PERCENT", "WSPR_TIMEOUT_MIN", "WSPR_UPLOAD",
               "WSPR_LOG_PATH", "WSPR_SESSION", "WSPR_SESSION_START")

# **Deliberately NOT remembered: WSPR_DEVICE, WSPR_RX_CARD, WSPR_RX_CONTROL
# and WSPR_RX_AGC.** They are hardware addresses, not preferences -- none of
# them is reachable from a menu, which is the rule `_REMEMBERED` follows --
# and persisting them is actively harmful. Remembering them once meant a
# state file written when the codec was card 1 kept pointing a new build at
# card 1 after the codec became card 2, which is the opposite of the fix:
# the stale value won over a corrected default and the audio stayed dead.
# These belong in the conf file, where a card that moves is a one-line edit.

# Releasing the post-over receive hold. Not configuration: these describe how
# a decaying transient is told apart from a station answering, which is a
# property of the problem rather than a preference. See
# Deck._settling_after_over.
SETTLE_POLLS = 2        # consecutive good polls before decodes are trusted
SETTLE_QUALITY = 20.0   # 0-100, used only when fldigi's squelch is off

# How many polls fldigi may report "not transmitting" while this side thinks it
# is, before this side is taken to be wrong. trx_state lags a start_over by a
# poll or two, so believing the first disagreement would abort every over at
# the moment it begins.
TX_IDLE_POLLS = 5

# How long the mode and carrier must hold still before they are written to the
# state file. Tuning moves the carrier continuously, and persisting every step
# would write the card hundreds of times per contact for no benefit; waiting
# for it to settle records where the operator actually stopped. Overridable so
# a test can watch a write happen without waiting ten seconds for it.
STATE_SETTLE_S = float(os.environ.get("CYBERDECK_STATE_SETTLE_S", "10"))

# How long after Ctrl-Y the transmitter may still be draining before the
# operator is told, and how often to repeat it. Not a limit: a long over at
# 31 baud takes minutes to go out and that is correct. TX_TIMEOUT is the limit.
DRAIN_NOTICE_S = 20.0



class _Memories(dict):
    """format_map helper: an unknown {token} is left alone rather than
    raising, so a memory with a typo in it still inserts."""

    def __missing__(self, key):
        return "{" + key + "}"


class Deck:
    def __init__(self, stdscr, settings):
        self.scr = stdscr
        self.cfg = settings
        self.scheme = settings["COLOR"]
        # The deck opens on its own settings rather than on the conversation.
        # The conversation was the first screen written and so became the home
        # screen by accident; what an operator wants on power-on is what this
        # station is set to -- callsign, rig, antenna, power ceiling -- before
        # any of it goes on the air. `^P` reaches the log and the conversation
        # from here in one keystroke each.
        self.screen = SET
        # Logging. Off means absent: no file is opened, no form is built, and
        # the log is not a stop on the ring at all -- `^O` and `^P` walk two
        # applications instead of three (docs/qso_log_design.md §1).
        self.log_on = str(settings.get("LOGGING", "no")).lower() == "yes"
        self.log_form = None
        self.log_records = []
        self.log_message = ""
        # Whether tqsl is installed, looked up once: the logging menu asks on
        # every draw and shelling out for that would be absurd.
        self._tqsl = None
        # The activity being built, while it is being built. None except
        # between "copy this one" and "save it".
        self.picker = None
        self.picker_sel = 0
        self.picker_from = ""
        self.picker_message = ""
        # Callsign lookup, created on first use and only when it is on.
        self._callbook = None
        self._looked_up = ""
        self.scroll = 0
        # The file the current activity writes to, stamped with the date it
        # was created and then LEFT ALONE. Re-deriving it would fork a
        # multi-day activity across UTC midnight; see
        # qsolog.activity_log_path.
        # Sessions the operator has deleted from the activities list. The
        # records keep their labels -- see §7f -- so the list has to be told.
        self.cfg.setdefault("FORGOTTEN_SESSIONS", [])
        # -- WSPR. Nothing is built until the area is entered: the engines
        # hold subprocess handles and a scheduler holds a session, and a deck
        # that never opens WSPR should carry none of it.
        self.wspr = None              # wsprsched.Schedule
        self.wspr_rx = None           # wsprrx.Receiver
        self.wspr_tx = None           # wsprtx.Transmitter
        self.wspr_up = None           # wsprnet.Uploader
        self.wspr_spots = []          # newest first, for the screen
        self.wspr_sel = None          # None follows the newest spot
        self.wspr_gain = None         # the capture mixer, built on first use
        self.wspr_dbfs = None         # what the last capture measured
        self._wspr_count_cache = None  # (heard, sent), or None when stale
        self._wspr_count_key = None
        # The power reading, which costs a CAT round trip and so may not be
        # taken on every draw. See `_wspr_power`.
        self._wspr_power_cache = (None, None, False)
        self._wspr_power_at = 0.0
        # Spawned `systemctl` calls waiting to be reaped. Never waited on:
        # a stop that queues behind systemd's own start job takes tens of
        # seconds, and the draw loop cannot be in that queue.
        self._service_jobs = []
        # band -> the mode it was in before WSPR changed it. Only bands
        # actually changed appear, so leaving puts back exactly what was
        # taken and nothing else.
        self._wspr_modes = {}
        self.wspr_cal = ""            # "", "tx" or "rx"
        self.wspr_cal_dbfs = None
        self.wspr_cal_from = ""       # the menu to go back to on Esc
        # The menus an operator walked through to get where they are, so Esc
        # retraces it one step at a time. See `_open_menu`.
        self._menu_stack = []
        self.wspr_message = ""
        self.wspr_band = ""
        self.wspr_fldigi_stopped = False
        self.cfg.setdefault("WSPR_BANDS", "")
        self.cfg.setdefault("WSPR_TX_PERCENT", 20)
        self.cfg.setdefault("WSPR_TIMEOUT_MIN", 60)
        self.cfg.setdefault("WSPR_UPLOAD", "yes")
        self.cfg.setdefault("WSPR_SESSION", "")
        self.cfg.setdefault("WSPR_SESSION_START", "")

        # The session `r` is renaming, as `(name, start)`. Held across the
        # editor, which is what hands the new name back.
        self._renaming = ("", "")
        # The schema `e` is editing in place, so saving replaces it instead
        # of asking whether to -- see `_save_activity`.
        self._editing_type = ""
        self._pending_type_edit = False
        # Rows the ACTIVITIES screen last drew, where the cursor is, and the
        # pending question: {"title", "lines", "action", "back"}.
        self.acts_sel = 0
        self.acts_message = ""
        self.confirm = None
        # Which logged contact the arrows have picked out, as an index into
        # the contacts on screen -- None when the form has the keyboard, which
        # is almost always. Enter means two different things depending on this,
        # so it is drawn: the picked row is reversed and the footer changes.
        # Where each area was left, so arriving back lands where the operator
        # was rather than resetting. This is what makes the ring feel like tabs
        # instead of three buttons.
        self.area_screen = {AREA_SETTINGS: SET, AREA_LOG: LOG,
                            AREA_DIGI: CHAT}
        # The settings screen's own message line, and which row its cursor is
        # on. Row 1, because row 0 is a heading.
        self.set_message = ""
        self.set_sel = 0
        # The radio's readings for the entry form, and when they were taken.
        self._radio_cache = ("", "", "")
        # The last rig mode actually read, per SOURCE, and when. Keyed
        # because there are two: fldigi's own CAT and the rigctld client the
        # log uses. They should agree and a shared slot would make a
        # disagreement into a fight. See `_rig_mode_held`.
        self._rig_mode_last = {}
        self._rig_mode_last_at = {}
        self._radio_at = 0.0
        self.log_sel = None
        # What the callbook had to say, kept apart from `log_message` so that a
        # poll arriving between keystrokes cannot overwrite a duplicate warning
        # or the receipt for the contact just logged.
        self.lookup_message = ""
        # The contact being read field by field, and which field the cursor is
        # on. `entry_rec` is a snapshot: the detail screen is opened from the
        # list and the list is rebuilt on every draw.
        self.entry_rec = None
        self.entry_sel = 0
        self.entry_message = ""
        # Set by `d` or `c` on the activity-type picker: the next number typed
        # names the type to delete, or to copy, rather than the one to select.
        self._pending_type_delete = False
        self._pending_type_copy = False
        # How far back the contact list is scrolled, in rows, counted from
        # the newest. Separate from `scroll`: the two screens are scrolled
        # independently and leaving one scrolled must not move the other.
        self.log_scroll = 0
        # Which menu is open, if any, and where in a paged list. A single
        # value rather than a stack: the tree is two deep by design, and
        # Esc from anywhere returns to the conversation.
        self.menu = None
        self.menu_page = 0
        self.menu_sel = 0
        # When a field is being edited in place:
        #   {"key": "MEMORY_7" | "CALLSIGN", "title": str, "text": str,
        #    "cursor": int}
        self.edit = None
        self._page_keys = {}
        self.status_note = ""
        self._tx_seen = False
        self._tx_echo = ""
        # When the last over finished, for the post-transmit receive hold.
        self._tx_ended = 0.0
        # Whether that hold is currently running, and how many consecutive
        # polls have reported a signal worth releasing it for.
        self._settling = False
        self._settle_good = 0
        # Consecutive polls where fldigi says receive and this side says
        # transmit. See poll().
        self._tx_idle = 0
        # The last state-file write error reported, so a failure that repeats
        # every save does not repeat in the transcript.
        self._state_error = None
        # What the state file last recorded, and when, so that a mode or
        # carrier reached any other way than a menu is still remembered.
        self._saved_mode = None
        self._saved_carrier = None
        # Created on first use by _power_now, and only if a memory asks.
        self._rig = None
        self._saved_at = 0.0
        # The remembered mode and carrier, read from the state file but not
        # yet pushed to fldigi. See _apply_radio_startup().
        self._boot_mode = ""
        self._boot_carrier = 0
        self._startup_done = False
        # So the automatic inhibit says why once rather than on every poll.
        self._rig_mode_warned = False
        self._startup_tries = 0
        # fldigi's transmit state as of the last poll, for the status line and
        # for the stuck-transmit check. Read once per poll rather than again
        # at draw time, so both agree.
        self._fldigi_sending = False
        # When Ctrl-Y was pressed, and when the operator was last told the
        # radio is still keyed despite it. See _watch_drain().
        self._handed_at = None
        self._drain_warned = 0.0
        # The last of what has been decoded, for the tuning screen's preview.
        # Held separately from the transcript because it has to survive the
        # transcript being cleared and has to be cheap to take the tail of.
        self._rx_tail = ""
        # The panel's touchscreen, for scrolling the transcript by drag. Never
        # required: a deck without one, or one whose device cannot be opened,
        # gets an object that reports no movement and nothing else notices.
        self.touch = (touchmod.Touch(path=settings.get("TOUCH_DEVICE") or None,
                                     row_pixels=settings.get("TOUCH_ROW_PIXELS", 24))
                      if settings.get("TOUCH") == "yes" else None)
        # A pairing session, only while the pairing screen is open. The module
        # is imported lazily inside it: it needs BlueZ and PyGObject, neither
        # of which exists on every machine this terminal runs on.
        self.pairing = None
        self.pair_sel = 0
        # WiFi, set up properly by _open_wifi. Named here so the poll and the
        # touch handler can ask about them before the screen has ever opened.
        self._wifi = None
        self.wifi_state = "list"
        self.wifi_radio = ""
        self.wifi_nets = []
        self.wifi_sel = 0
        self.wifi_op = None
        self.wifi_error = ""
        self.wifi_message = ""
        self.wifi_joined = ""
        self.wifi_target = ""
        self.wifi_target_known = False
        self.wifi_target_secured = True
        self._wifi_tick = 0
        self._wifi_refreshed = 0.0
        self._pair_refreshed = 0.0
        self._pair_tick = 0
        # The no-keyboard screen's state: which keyboards are already bonded,
        # whether pairing is even possible here, and the animation counter.
        self._nokb_bonded = []
        self._nokb_can_pair = False
        self._nokb_tick = 0
        self._kb_checked = 0.0
        self.fldigi = Fldigi(url=settings["FLDIGI_URL"])
        self.session = Session(
            callsign=settings["CALLSIGN"],
            scrollback=settings["SCROLLBACK"],
            tx_timeout=settings["TX_TIMEOUT"],
        )
        # Reads the remembered mode and carrier but does not send them; see
        # _apply_radio_startup for why that cannot happen here.
        self._load_state()
        self._saved_at = time.monotonic()

        if self.fldigi.connected:
            self._apply_radio_startup()
        else:
            self.session.note("no connection to fldigi — waiting for it")

        # Powering on into a transmit-capable state is the wrong default for a
        # deck that lives in a bag: a stray Ctrl-T on a radio connected to an
        # unknown antenna is worse than an extra keystroke before the first
        # over. Cleared with Ctrl-B, or F1 6 i.
        if settings["INHIBIT_ON_START"] == "yes":
            self.session.inhibit(True)
            self.fldigi.receive_only(True)
            self.session.note("transmit INHIBITED at startup — Ctrl-B to enable")

        self._wifi_on_start(settings)
        self._pair_if_no_keyboard(settings)

    def _wifi_on_start(self, settings):
        """Switch the WiFi radio back on, every time.

        `nmcli radio wifi off` persists across reboots, and that is what makes
        the toggle on the WiFi screen safe to offer at all. With the radio off
        and the Bluetooth keyboard flat there is no SSH, no keyboard, and a
        radio occupying the only USB port — the deck would be unreachable by
        every route it has. Power-cycling is the recovery, and it is only a
        recovery if WiFi comes back on its own.

        So the toggle is for this session, not for the next one, and a deck
        that is switched off with WiFi off comes back with WiFi on. Setting
        WIFI_ON_START = no removes that and there is no other way back in.

        Fire and forget: no availability check, because that is a subprocess
        of its own and this must not add a second to every start. A machine
        with no nmcli fails the spawn, which Op records and nothing reads.
        """
        if settings.get("WIFI_ON_START", "yes") != "yes":
            return
        try:
            import wifi as wifimod
            wifimod.Op(["radio", "wifi", "on"], label="wifi on at start")
        except Exception:       # pragma: no cover - never worth failing a start
            pass

    def _pair_if_no_keyboard(self, settings):
        """Open the pairing screen when there is no keyboard to open it with.

        The pairing screen is reached from the System menu, which is reached
        with F1 — so on a deck with nothing bonded, the one feature that
        exists to fix that is behind the thing it fixes. Someone has to notice
        the keyboard is missing, and the deck is the only one present.

        Three cheap conditions, in the order that keeps `btpair` unimported on
        machines that will never pair:

        1. a real console. Over SSH the keyboard is the far end's and /proc
           knows nothing about it, so this must not fire on a laptop;
        2. no keyboard-capable input device of any kind, Bluetooth or USB;
        3. only then is pairing asked whether it is possible, which is the
           call that imports PyGObject.
        """
        if settings.get("PAIR_ON_NO_KEYBOARD") != "yes":
            return
        if not colors.on_linux_console():
            return
        if touchmod.find_keyboard():
            return
        self._show_no_keyboard()

    def _show_no_keyboard(self):
        """Say there is no keyboard, and offer the two things that fix it.

        Not the pairing screen directly. Two different problems look the same
        from here — a bonded keyboard switched off or asleep, and no bond at
        all — and the first is far the more common. Jumping into a scan would
        answer the rarer one and bury the answer to the usual one.
        """
        try:
            import btpair
            self._nokb_bonded = btpair.bonded_keyboards()
            self._nokb_can_pair = btpair.available()[0]
        except Exception:
            self._nokb_bonded, self._nokb_can_pair = [], False
        self._nokb_tick = 0
        self.screen = NOKB

    # -- fldigi ------------------------------------------------------------

    def poll(self):
        # fldigi echoes transmitted text back through its RX buffer, so text
        # read while the radio is keyed is our own coming back — recording it
        # would enter every over twice, once from the keyboard and once as
        # though a correspondent had sent it.
        #
        # The buffer is still drained rather than skipped: poll_rx() advances
        # its read position, and leaving the echo in place would deliver the
        # whole over in one lump the moment we returned to receive.
        #
        # fldigi's own TX state decides this, not the session's. Ctrl-Y ends
        # the over immediately but fldigi keeps sending until its buffer
        # drains, and the echo keeps arriving for that whole tail.
        text = self.fldigi.poll_rx()
        sending = self.fldigi.trx_state() != "RX"
        self._fldigi_sending = sending
        # Checked on the poll the deck is already doing rather than on a timer
        # of its own: the radio's mode can change at any moment and the only
        # thing that makes the interlock worth having is noticing promptly.
        self._watch_rig_mode()

        # WSPR, if it is running. Every slot decision and every subprocess
        # is collected here, on the poll the deck is already doing.
        if self.wspr is not None:
            self._wspr_poll()

        # The end of the over is established before anything is done with
        # `text`, because the poll in which trx_state flips to RX still
        # carries the tail of our own echo: fldigi's echo and its TX state do
        # not change over atomically. Deciding delivery first delivered that
        # tail to the transcript as though a correspondent had sent it.
        if sending:
            self._tx_seen = True
        elif self._tx_seen:
            # fldigi has finished draining and dropped back to receive. This
            # is the moment the over is really over: Ctrl-Y only stops adding
            # to the buffer.
            self._tx_seen = False
            self._tx_echo = ""
            self._tx_ended = time.monotonic()
            self._settling = True
            self._settle_good = 0
            self._handed_at = None
            self._drain_warned = 0.0
            self.session.confirm_receive()
            self.session.note("sent")

        # fldigi is the authority on whether the radio is keyed. This side's
        # state is set by the operator's keys, and the two can part company —
        # a start_over() whose XML-RPC call failed leaves the session
        # transmitting and the radio idle, and every later Ctrl-T is then
        # refused with no visible cause. Give fldigi a couple of polls to
        # actually key up before believing it, since trx_state lags the
        # request, then correct this side and say so.
        if self.session.state == TX and not sending and not self._tx_seen:
            self._tx_idle += 1
            if self._tx_idle >= TX_IDLE_POLLS:
                if self.session.resync_to_receive():
                    self.session.note("fldigi is not transmitting — back to receive")
                self._tx_idle = 0
        else:
            self._tx_idle = 0

        self._check_keyboard()
        self._scroll_by_touch()
        self._poll_pair()
        self._poll_wifi()
        self._finish_startup()
        self._persist_settled()
        self._watch_drain(sending)

        holding = self._settling_after_over(sending)

        if text and not sending and not holding:
            self.session.receive(text)
            self._rx_tail = (self._rx_tail + text)[-400:]
            self.scroll = 0
        elif text and sending:
            # Our own transmission, echoed back by fldigi as it goes out.
            # Held here rather than written to the transcript: it is drawn as
            # a transient TX line under the over while sending, and dropped
            # when the over completes. See docs/digimodes_design.md §5.5 for why this is
            # transient rather than permanent.
            self._tx_echo += text
            self.scroll = 0
        # Text arriving while holding falls through to neither branch and is
        # dropped. Discarding it is the point; accumulating it into the echo
        # would carry the transient over into the next over's TX line.

        if self.session.tx_timed_out():
            self.fldigi.abort()
            self.session.abort()
            self.session.note(f"transmit timed out after {self.cfg['TX_TIMEOUT']}s")

    def _quit(self):
        """Ctrl-Q. Returns False to leave the main loop.

        On the deck this is not "quit" in any sense the operator can see.
        The systemd unit is Restart=always, so the process exits, the screen
        goes dark for RestartSec, and the terminal comes back with the radio
        where it was. There is no desktop underneath to return to and no way
        to start it again from the panel, so exiting for good is not a thing
        the deck can offer — which makes an unannounced three-second blank
        screen indistinguishable from a crash. It read as one.

        So it confirms first, and says what is about to happen. Off the deck,
        run from a shell, it simply exits and the message is harmless.
        """
        self.session.note("Ctrl-Q again to restart the terminal, any other key to stay")
        self.draw()
        # The main loop runs getch() on a POLL_MS timeout so that fldigi is
        # polled while nobody is typing. Reading the confirmation with that
        # still set gives the operator a fifth of a second to answer, which is
        # no confirmation at all — it returns -1 and cancels before a finger
        # moves. Block for a few seconds instead, then restore the poll.
        try:
            self.scr.timeout(3000)
            again = self.scr.getch()
        finally:
            self.scr.timeout(self.cfg["POLL_MS"])
        return again != 17

    def _scroll_by_touch(self):
        """A vertical drag on the transcript scrolls it.

        Only on the conversation screen, and only when no menu or editor is
        open: a drag is a gesture on content, and there is no content to drag
        anywhere else. Dragging downward reveals earlier text, which is the
        same direction PgUp goes and the same direction a sheet of paper would
        move under the finger.

        This is the whole of the touch interface by design. A tap does
        nothing, nothing is selectable, and there is no cursor — section 1's
        premise is that the deck has no pointer, and a gesture on content does
        not contradict it the way a touch menu would.
        """
        if self.touch is None:
            return
        if self.screen == NOKB:
            self.touch.poll()
            if self.touch.taps() and self._nokb_can_pair:
                # Any tap, not a particular row. The operator has no keyboard
                # and no cursor; asking them to hit a target would be the
                # wrong thing to insist on, and the only action this screen
                # offers is pairing.
                self._open_pair()
            return
        if self.screen == PAIR and self.pairing is not None:
            # The one screen a tap can act on. It exists to attach a keyboard,
            # so it cannot require one: a tap on a device row starts pairing
            # it, which is the whole touch path through this feature.
            self.touch.poll()
            for row, _col in self.touch.taps():
                self._pair_choose(row - render.PAIR_ROW0)
            return
        if self.screen == WIFI and self.wifi_state == "list":
            self.touch.poll()
            for row, _col in self.touch.taps():
                if row >= render.WIFI_ROW0:
                    self._wifi_join(row - render.WIFI_ROW0)
            return
        if self.menu or self.edit is not None:
            return
        if self.screen == LOG:
            # The same gesture on the same kind of content. A drag on the
            # contact list scrolls it; a tap still means nothing, because
            # nothing on this screen is selectable.
            rows = self.touch.poll()
            self.touch.taps()
            if rows:
                self._log_scroll_by(rows)
            return
        if self.screen == WSPR:
            # And the spot list, which is the third list of the same kind.
            # A drag down reveals older spots, the same direction the arrows
            # and PgDn go and the same direction paper moves under a finger.
            rows = self.touch.poll()
            self.touch.taps()
            if rows:
                self._wspr_move(rows)
            return
        if self.screen != CHAT:
            self.touch.poll()
            self.touch.taps()          # discarded: a tap means nothing here
            return
        rows = self.touch.poll()
        self.touch.taps()
        if rows:
            # Clamped at zero exactly as PgDn is: the transcript cannot be
            # scrolled forward past its own end.
            self.scroll = max(0, self.scroll + rows)

    def _check_keyboard(self):
        """Notice a keyboard going away, and coming back.

        A Bluetooth keyboard that sleeps, runs flat or is switched off leaves
        a deck that cannot be told anything — including that it has a problem.
        The screen is the only thing left, so it says so, rather than the
        operator pressing keys at a terminal that looks perfectly healthy.

        Checked at a human rate. /proc is cheap but not free, and a keyboard
        does not come and go five times a second.
        """
        if self.cfg.get("PAIR_ON_NO_KEYBOARD") != "yes":
            return
        if not colors.on_linux_console():
            return
        if self.screen == PAIR or self.menu or self.edit is not None:
            return
        now = time.monotonic()
        if now - self._kb_checked < 3.0:
            return
        self._kb_checked = now
        present = touchmod.find_keyboard()
        if present and self.screen == NOKB:
            self.screen = CHAT
            self.session.note("keyboard is back")
        elif not present and self.screen == CHAT and self.session.state != TX:
            # Not mid-over: the transcript is what matters while a
            # transmission is going out, and the keyboard being absent does
            # not stop it finishing.
            self._show_no_keyboard()

    # -- pairing a keyboard ------------------------------------------------

    def _open_pair(self):
        """Start a pairing session and show its screen.

        The session holds one D-Bus connection open for its whole life. That
        is the entire point: BlueZ tracks an agent per connection, and the
        first pairing script registered one per subprocess, so the agent was
        gone before the passkey could be delivered.
        """
        import btpair
        ok, why = btpair.available()
        if not ok:
            self.session.note(f"cannot pair here: {why}")
            self._close_menu()
            return
        self.pairing = btpair.Pairing()
        self.pair_sel = 0
        self._pair_refreshed = 0.0
        self._pair_tick = 0
        if not self.pairing.start():
            self.session.note(f"pairing failed to start: {self.pairing.error}")
            self.pairing = None
            self._close_menu()
            return
        self._close_menu()
        self.screen = PAIR

    def _close_pair(self):
        if self.pairing is not None:
            self.pairing.stop()
            self.pairing = None
        self.screen = CHAT

    def _pair_devices(self):
        return self.pairing.devices[:9] if self.pairing else []

    def _pair_choose(self, index):
        devices = self._pair_devices()
        if 0 <= index < len(devices):
            self.pair_sel = index
            self.pairing.pair(devices[index])

    def _draw_pair(self, h, w):
        p = self.pairing
        self._pair_tick += 1
        lines = render.pair_screen(
            p.state if p else "failed",
            self._pair_devices(), w, h,
            passkey=p.passkey if p else "",
            error=p.error if p else "no session",
            selected=self.pair_sel,
            # Divided down so the scanning dots move at a readable rate rather
            # than at the poll rate, which is five times a second.
            tick=self._pair_tick // 3)
        for i, line in enumerate(lines):
            self._put(i, 0, line, w)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def _handle_pair(self, ch):
        p = self.pairing
        if p is None:
            self.screen = CHAT
            return True
        key = chr(ch).lower() if 32 <= ch < 127 else ""
        devices = self._pair_devices()

        if ch == 27 or ch == curses.KEY_F1:            # Esc
            self._close_pair()
        elif ch == curses.KEY_UP and devices:
            self.pair_sel = (self.pair_sel - 1) % len(devices)
        elif ch == curses.KEY_DOWN and devices:
            self.pair_sel = (self.pair_sel + 1) % len(devices)
        elif ch in (10, 13, curses.KEY_ENTER):
            self._pair_choose(self.pair_sel)
        elif key.isdigit() and key != "0":
            self._pair_choose(int(key) - 1)
        elif key == "f" and devices:
            # Forgetting is what makes a second attempt possible: a half-made
            # bond cannot be replaced, only removed and made again.
            if p.forget(devices[self.pair_sel]):
                self.session.note("bond removed")
                p.refresh()
        elif key == "r":
            p.refresh()
        elif ch == 17:                                  # Ctrl-Q
            self._close_pair()
            return self._quit()
        return True

    def _poll_pair(self):
        """Service the pairing session from the main loop."""
        if self.pairing is None or self.screen != PAIR:
            return
        self.pairing.pump()
        # Re-reading the whole device list is a round trip, so it happens at
        # a human rate rather than at the poll rate.
        now = time.monotonic()
        if now - self._pair_refreshed >= 1.0:
            self._pair_refreshed = now
            self.pairing.refresh()

    def _apply_radio_startup(self):
        """Put the radio into its starting mode and carrier, once fldigi answers.

        Every line here used to sit behind `if self.fldigi.connected` in
        __init__, which on a cold boot is false. The UI unit is ordered
        `After=cyberdeck-fldigi.service`, and that means only that the process
        has been spawned: fldigi under Xvfb on a 3A+ takes seconds longer to
        open its XML-RPC port, and the terminal is already drawing a screen.
        So none of it ran, nothing retried it, and fldigi stayed in whatever
        mode fldigi itself had saved — CW on a stock configuration. Restarting
        the terminal alone never showed the fault, because fldigi was up by
        then; only a power cycle did.
        """
        settings, f = self.cfg, self.fldigi
        if settings["DEFAULT_MODE"]:
            f.set_modem(settings["DEFAULT_MODE"])
        f.set_carrier(settings["DEFAULT_CARRIER"])
        # The remembered choice overrides the configured default, which is
        # where a deck with no history starts rather than where this one does.
        if self._boot_mode:
            f.set_modem(self._boot_mode)
        if self._boot_carrier:
            f.set_carrier(self._boot_carrier)

        # Did it take? Each of those is an XML-RPC call that returns a usable
        # value whether or not it succeeded, so a call lost to a busy fldigi
        # is invisible from here — and fldigi is at its busiest in the seconds
        # after it starts, which is exactly when this runs. Marking startup
        # done regardless would leave the deck in the mode fldigi chose, with
        # nothing to try again, which is the fault this whole method exists to
        # fix reappearing one layer up.
        want = self._boot_mode or settings["DEFAULT_MODE"]
        got = f.modem()
        if want and got and got != want and self._startup_tries < 5:
            self._startup_tries += 1
            return                  # not done; the next poll tries again

        self.session.note(f"fldigi {f.version()} — {got} at {f.carrier()} Hz")
        if settings.get("REMEMBER_STATE") == "yes" and (self._boot_mode or self._boot_carrier):
            self.session.note(f"resumed {got} at {f.carrier()} Hz, "
                              f"{colors.SCHEMES[self.scheme]['name']}")
        if want and got and got != want:
            # Five attempts and it still disagrees. Say so rather than showing
            # a mode nobody asked for as though it were a choice.
            self.session.note(f"fldigi stayed in {got}; wanted {want}")

        # Baseline for _persist_settled: what is on screen is what the file
        # already says, so an untouched deck does not rewrite the card at boot.
        self._saved_mode = f.modem()
        self._saved_carrier = f.carrier()
        self._saved_at = time.monotonic()

        self._report_rig_mode()
        if settings["RSID_ON_START"] == "yes" and not f.rsid():
            f.set_rsid(True)
            self.session.note("RSID on — will follow other stations' modes")
        # The inhibit is set on this side whether or not fldigi was reachable.
        # If it was not, the call that told fldigi went nowhere.
        if self.session.inhibited:
            f.receive_only(True)
        self._startup_done = True

    def _finish_startup(self):
        """Run the deferred radio startup the moment fldigi first answers."""
        if self._startup_done or not self.fldigi.connected:
            return
        self._apply_radio_startup()

    def _operator_chose(self):
        """Cancel a startup that has not happened yet.

        The deferred apply exists because fldigi may not be answering when the
        terminal comes up. The gap it opens is that the operator can choose a
        mode or move the carrier inside those seconds, and the startup would
        then fire afterwards and put its own values over the top — restoring a
        remembered setting by overwriting a deliberate one, which is worse
        than the fault it was written to fix.

        Startup state is for an untouched deck. Once someone has touched the
        radio, there is nothing left to restore.

        Only when fldigi is answering, and that condition is the whole of the
        subtlety. A mode key pressed while fldigi is still starting reaches
        nothing — `set_modem` fails silently and returns a usable value like
        every other call on that client — so there was no effective choice to
        protect. Cancelling the restore on the strength of it would leave the
        deck in the mode fldigi itself came up in, which is the fault this was
        all written to fix. Keys pressed into the void do not count.
        """
        if self.fldigi.connected:
            self._startup_done = True

    # ---- WiFi ----------------------------------------------------------
    #
    # Deliberately the same shape as pairing: open a screen, list what is
    # nearby, choose one, prove you may use it. The module underneath is
    # simpler — nmcli rather than D-Bus — but nothing about that reaches here.

    def _open_wifi(self):
        import wifi as wifimod            # not imported on machines that never open this
        self._wifi = wifimod
        self.wifi_sel = 0
        self.wifi_op = None
        self.wifi_nets = []
        self.wifi_error = ""
        self.wifi_message = ""
        self.wifi_joined = ""
        self.wifi_target = ""
        self.wifi_target_known = False
        self.wifi_target_secured = True
        self._wifi_tick = 0
        self._wifi_refreshed = 0.0
        self._close_menu()
        self.screen = WIFI
        if not wifimod.available():
            self.wifi_state = "unavailable"
            self.wifi_error = "nmcli is not installed or NetworkManager is not running"
            return
        self.wifi_state = "list"
        self.wifi_radio = wifimod.radio()
        # Ask before offering. Listing networks needs no authorisation, so
        # without this the screen looks entirely normal and refuses every key
        # on it — which is exactly how this was first met.
        self.wifi_error = wifimod.blocked_reason()
        self._wifi_refresh()

    def _close_wifi(self):
        if self.wifi_op is not None:
            # A join left running would finish into a screen that is gone, and
            # its result would appear as a surprise minutes later.
            self.wifi_op.cancel()
            self.wifi_op = None
        self.screen = CHAT

    def _wifi_refresh(self, rescan=False):
        """Re-read the network list. A rescan is a radio operation and slow."""
        if self._wifi is None or self.wifi_radio == "off":
            self.wifi_nets = []
            return
        self.wifi_nets, err = self._wifi.scan(rescan=rescan)
        # Only an explicit rescan reports its failure. The background refresh
        # runs every five seconds, and a message that reappears on its own is
        # indistinguishable from one the operator caused.
        if rescan and err:
            self.wifi_error = err
        self.wifi_sel = min(self.wifi_sel, max(0, len(self.wifi_nets) - 1))
        self._wifi_refreshed = time.monotonic()

    def _wifi_start(self, op, message, ssid="", was_known=False, secured=True):
        # `was_known` decides what happens to the profile if this fails, and
        # it has to be read before the attempt: nmcli creates the profile on
        # its way to failing, so afterwards every network looks known.
        self.wifi_op = op
        self.wifi_message = message
        self.wifi_state = "working"
        self.wifi_error = ""
        self.wifi_target = ssid
        self.wifi_target_known = was_known
        self.wifi_target_secured = secured

    def _wifi_join(self, index):
        """Join the selected network, asking for a passphrase only if needed."""
        if not (0 <= index < len(self.wifi_nets)):
            return
        net = self.wifi_nets[index]
        self.wifi_sel = index
        if net.known:
            # An existing profile already holds the passphrase. Asking again
            # would be the deck forgetting something it has written down.
            self._wifi_start(self._wifi.connect_saved(net.ssid),
                             f"joining {net.ssid}", net.ssid, True, net.secured)
        elif net.secured:
            self._ask_passphrase(net.ssid)
        else:
            self._wifi_start(self._wifi.connect(net.ssid),
                             f"joining {net.ssid}", net.ssid, False, False)

    def _ask_passphrase(self, ssid):
        """Open the editor for a passphrase: masked, and not written to the
        state file the way every other edited field is."""
        self._open_editor(
            None, f"passphrase for {ssid}", secret=True,
            sink=lambda text, ssid=ssid: self._wifi_start(
                self._wifi.connect(ssid, text), f"joining {ssid}",
                ssid, False, True))

    def _ask_hidden_ssid(self):
        """Join a network by name, for one that does not broadcast it."""
        self._open_editor(None, "network name", sink=self._hidden_named)

    def _hidden_named(self, ssid):
        if not ssid:
            return
        self._ask_passphrase(ssid)

    def _poll_wifi(self):
        if self.screen != WIFI or self._wifi is None:
            return
        if self.wifi_op is not None and self.wifi_op.poll():
            op, self.wifi_op = self.wifi_op, None
            if op.ok:
                self.wifi_state = "joined"
                self.wifi_joined = self._wifi.active_ssid() or op.label
                self.session.note(f"joined {self.wifi_joined}")
            else:
                self.wifi_state = "failed"
                self.wifi_error = op.error or "no reason given"
                # nmcli saves the profile on its way to failing, so a wrong
                # passphrase becomes a saved network — and the next Enter then
                # reuses it without asking, failing identically forever. The
                # only way out was to forget the network by hand first, which
                # is a workaround for this and not a feature. A profile this
                # attempt created is removed again; one that existed before is
                # left alone, because the failure may be range rather than the
                # key and that passphrase is still the operator's.
                if self.wifi_target and not self.wifi_target_known:
                    self._wifi.forget(self.wifi_target)
            self.wifi_radio = self._wifi.radio()
            self._wifi_refresh()
            return
        # The list goes stale while the screen is open — signal moves, and a
        # network joined from elsewhere should show as connected. Re-read at a
        # human rate, never at the poll rate: each one is a subprocess.
        if self.wifi_state == "list" and time.monotonic() - self._wifi_refreshed >= 5.0:
            self.wifi_radio = self._wifi.radio()
            self._wifi_refresh()

    # -- the contact log --------------------------------------------------

    def _log_rig(self):
        """The rigctld client, made on first use and only by the log.

        The deck drives the radio through fldigi and has never held one of
        these; a station that never opens the log should not start a
        connection to find that out.
        """
        if self._rig is None:
            try:
                import rigctld_client
                self._rig = rigctld_client.Rigctld(
                    host=self.cfg.get("RIGCTLD_HOST", "127.0.0.1"),
                    port=self.cfg.get("RIGCTLD_PORT", 4532))
            except Exception:
                return None
        return self._rig

    def _log_freq_mhz(self):
        """The radio's frequency at its own resolution: 7.185.000.

        Grouped the way `render.frequency` groups it on the transcript screen
        and the way the radio's own display reads, rather than rounded to
        three decimals -- the rounding threw away the tens of hertz, which is
        the part that matters inside a 31 Hz-wide signal and the part that
        lets this reading be checked against the radio.
        """
        rig = self._log_rig()
        if rig is None:
            return ""
        try:
            hz = rig.frequency()
        except Exception:
            return ""
        return render.frequency(hz) if hz else ""

    def _log_freq_hz(self):
        """Hertz from whatever is in the form, which may have been corrected.

        Parsed by `qsolog.parse_freq`, which reads the grouped form the field
        now shows as well as the plain megahertz an operator might type.
        """
        try:
            return qsolog.parse_freq(self.log_form.value("freq"))
        except AttributeError:
            return 0

    def _log_mode(self):
        """The ADIF mode, decided the way `qsolog.resolve_mode` decides it.

        The deck can answer one question `tools/qso.py` cannot: whether it is
        passing traffic right now. That is what tells `auto` apart a rig
        sitting in USB for voice from one sitting in USB under fldigi.
        """
        rig_mode = ""
        rig = self._log_rig()
        if rig is not None:
            try:
                rig_mode = rig.mode()[0]
            except Exception:
                rig_mode = ""
        rig_mode = self._rig_mode_held(rig_mode, source="rigctld")
        modem = ""
        try:
            if self.fldigi.connected:
                modem = self.fldigi.modem() or ""
        except Exception:
            modem = ""
        mode, _source = qsolog.resolve_mode(
            self.cfg.get("OPERATING", "auto"), rig_mode=rig_mode,
            fldigi_modem=modem, fldigi_active=self.session.state == TX)
        return mode

    def _draw_log(self, h, w):
        """Contacts already made, and the form for the next one.

        The radio fields are refreshed here rather than on a timer: the draw
        is happening anyway, and `from_radio` skips any field the operator
        has corrected.
        """
        form = self.log_form
        # Only this activity's contacts, scoped by the activity NAME rather
        # than by its type. Each activity has its own file, so the file is
        # normally the whole scope and this does nothing; it earns its keep
        # on a file holding more than one activity -- the log that was in use
        # before activities were named.
        #
        # Scoping by TYPE was wrong in both directions: it hid every contact
        # whose type matched nothing, and it showed contacts from a different
        # session that happened to use the same type. The count follows the
        # list, because a count that disagrees with the screen is worse than
        # no count.
        shown = self._log_shown() if form is not None else self.log_records
        header = {"count": len(shown),
                  # Only matters when there is no activity to name; an
                  # activity's file is named after the activity.
                  "log_name": self._log_name(),
                  "clock": time.strftime("%H%MZ", time.gmtime())}
        if form is not None:
            freq, mode, power = self._radio_now()
            form.from_radio(freq=freq, mode=mode, power=power)
            form.from_station(rig=self.cfg.get("RIG", ""),
                              antenna=self.cfg.get("ANTENNA", ""))
            # The activity is what the operator is doing and goes first; the
            # type is what the fields on screen mean and follows it. With one
            # setting there was only ever one of them to show.
            header["activity"] = self._activity_name()
            if form.activity_type.name != "GENERAL":
                header["activity_type"] = form.activity_type.name
            if form.value("my_park"):
                header["my_park"] = form.value("my_park")
            band = qsolog.band_for(self._log_freq_hz())
            if band:
                header["band"] = band
            header["mode"] = form.value("mode")
            header["freq"] = form.value("freq")

        # Said while the callsign is being typed, not at commit: the point of
        # knowing is to decide whether to work them, and by commit that has
        # been decided. It never blocks the contact — a duplicate is logged
        # deliberately often enough that refusing would be wrong.
        self._lookup_maybe(form)
        arrived = self._lookup_collect(form)
        if arrived:
            self.lookup_message = arrived

        # Precedence, most important last to be overridden: what the operator
        # just did, then the duplicate warning, then the callbook's status.
        # All three used to share one attribute, so whichever was written last
        # won -- and the callbook, which polls, was always last.
        message = self.log_message
        if form is not None and not message:
            note = qsolog.dupe_note(qsolog.find_dupes(
                self.log_records, form.value("call"),
                band=header.get("band", ""), mode=form.value("mode"),
                rule=self.cfg.get("DUPE_CHECK", "band+mode"),
                activity=self._activity_name()))
            if note:
                message = f"** {note}"
            elif self.lookup_message:
                message = self.lookup_message

        # Clamped on the way in: contacts arriving while the list is
        # scrolled back must not leave it pointing past the end.
        self.log_scroll = max(0, min(
            self.log_scroll,
            render.log_scroll_max(shown, h, form, w, self._log_lines())))
        # A selection that no longer has a contact under it is dropped rather
        # than clamped: contacts arrive while the screen is open, and silently
        # moving the selection onto a different contact than the one that was
        # picked is how the wrong one gets edited.
        if self.log_sel is not None and not 0 <= self.log_sel < len(shown):
            self.log_sel = None
        for i, line in enumerate(render.log_screen(
                shown, "", w, h, header=header, scroll=self.log_scroll,
                message=message, form=form, lines=self._log_lines(),
                selected=self.log_sel)):
            self._put(i, 0, line, w)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    # -- the three areas ---------------------------------------------------

    def _area(self):
        """Which area the deck is in now."""
        return AREA_OF.get(self.screen, AREA_DIGI)

    def _ring(self, step):
        """Move to the next area, landing where that area was left.

        Remembers the screen on the way out, so leaving the activities list
        and coming back arrives at the activities list. Menus are closed on
        the way: a menu belongs to the area it was opened from, and carrying
        one across would draw the wrong area's menu over the right area's
        screen.
        """
        here = self._area()
        self.area_screen[here] = self.screen
        self._close_menu()
        # The ring holds the applications that EXIST right now. Logging is off
        # by default and when off it has nothing to show -- no form, no file --
        # so it is not on the ring at all and the ring is two stops instead of
        # three. Switch it on from its menu and it joins.
        #
        # The alternative was tried and was worse: landing on the conversation
        # with the logging menu over it. That put the operator in the digimode
        # application while they were being shown a logging menu, so the ring's
        # idea of where they were no longer matched the screen and the next
        # press skipped the conversation entirely.
        # **WSPR running locks the ring.** Not a screen that refuses to
        # draw: the key says what is in the way, because a ring key that did
        # nothing would read as a broken key rather than as a deliberate
        # refusal. The same shape as the refusal when a schema change meets
        # a part-typed contact.
        if self.wspr_running:
            self._wspr_note("WSPR is running — ^C stops it, or F1 then w")
            self.screen = WSPR
            return
        ring = [a for a in RING if a != AREA_LOG or self.log_on]
        if here not in ring:
            here = AREA_DIGI
        where = ring[(ring.index(here) + step) % len(ring)]
        self.screen = self.area_screen.get(where, CHAT)
        if where == AREA_LOG:
            if self.log_form is None:
                self._open_log()
                return
            if self.screen not in AREA_OF or AREA_OF[self.screen] != AREA_LOG:
                self.screen = LOG
        elif where == AREA_DIGI and self.screen not in (CHAT, TUNE):
            self.screen = CHAT
        elif where == AREA_WSPR:
            # Through `_open_wspr`, not by setting the screen: the engines
            # are built on entering the area, and a screen set directly drew
            # a WSPR area with no scheduler behind it -- so every toggle
            # reported `off` including Decode, which defaults to on.
            self._open_wspr()

    def _settings_rows(self):
        """The station, as `(label, token, value, config key)` per row.

        `token` is the `{call}`-style name a message memory substitutes this
        setting into, shown here for the same reason the old Station menu
        showed it: the moment you want to know that `{qth}` exists is the
        moment you are looking at what QTH is set to.

        Every row is editable and the cursor lands on all of them, so there
        are no headings and nothing to skip.

        The radio's live readings used to be on here too and are gone. They
        cost a round trip each -- `_power_now` opens rigctld and asks the
        radio, the rest are XML-RPC to fldigi -- and the main loop draws five
        times a second, so the screen was making about thirty queries a second
        while sitting still, plus six more per keystroke because the key
        handler rebuilt the list to find which rows were editable. On a Pi
        with CAT over a serial port that outran the 200 ms poll and the
        interface fell behind, which looked like slow scrolling and was the
        screen being slow the whole time it was open. They are all on the
        digimode status line and the tuning screen anyway.
        """
        # TX_POWER is skipped. It is READ FROM THE RADIO -- `_power_now` asks
        # rigctld and falls back to the configured value only when the radio
        # cannot be reached -- so a row for typing it invites an operator to
        # set a number the radio will immediately contradict. The `{power}`
        # token is unaffected and still works in message memories: it
        # substitutes `_power_now()`, not this setting.
        #
        # TX_POWER_MAX stays, and is not the same thing. It is the ceiling the
        # radio's 0..1 RFPOWER reading is scaled against, and on the FTX-1 it
        # genuinely changes with the configuration -- field head on its own
        # battery, field head on external power, and the Optima are three
        # different maxima. Without it the deck cannot turn a CAT reading into
        # watts at all.
        return [(label, token, self.cfg.get(key, "") or "(not set)", key)
                for key, label, token in menus.STATION_FIELDS
                if key != "TX_POWER"]

    def _draw_settings(self, h, w):
        for i, line in enumerate(render.settings_screen(
                self._settings_rows(), w, h, selected=self.set_sel,
                message=self.set_message, state=self._deck_state())):
            self._put(i, 0, line, w)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def _deck_state(self):
        """One word for the settings header: what the deck is doing.

        Both readings are plain attributes, not round trips -- `connected` is
        set by the fldigi client on every call it makes, and the inhibit is
        the session's own flag. This screen is drawn five times a second and
        must stay free of radio queries; see `_settings_rows`.

        Worth being on the boot screen at all because the startup notes go to
        the TRANSCRIPT, which the deck no longer opens on: "no connection to
        fldigi -- waiting for it" is the most important thing the deck can say
        on power-on and it was landing on a screen nobody was looking at.
        """
        if not self.fldigi.connected:
            return "NO MODEM"
        if self.session.inhibited:
            return "TX INHIBITED"
        return "TX ARMED"

    def _handle_settings(self, ch):
        rows = self._settings_rows()
        edits = list(range(len(rows)))
        if ch == curses.KEY_F1:
            self._open_menu("deck")
        elif ch == curses.KEY_F2:
            self._open_menu("display")
        elif ch == curses.KEY_F3:
            self._open_menu("system")
        elif ch in (curses.KEY_UP, curses.KEY_DOWN) and edits:
            # Only the editable rows. The headings and the live readings are
            # drawn but never landed on: a cursor that could sit on the VFO
            # and do nothing on Enter would read as a broken key.
            step = -1 if ch == curses.KEY_UP else 1
            if self.set_sel in edits:
                at = edits[(edits.index(self.set_sel) + step) % len(edits)]
            else:
                at = edits[0] if step > 0 else edits[-1]
            self.set_sel = at
            self.set_message = ""
        elif ch in (10, 13, curses.KEY_ENTER) and self.set_sel in edits:
            label, _token, _value, key = rows[self.set_sel]
            self._open_editor(key, label)
        elif ch == 27:
            # Nothing to back out to. This is the top screen of its own
            # application, and Esc does not cross between applications -- see
            # the note on Esc in `_handle_log`.
            self.set_message = ""
        elif ch == 17:
            return self._quit()
        return True

    def _radio_now(self):
        """`(freq, mode, power)` for the entry form, cached for a second.

        Every one of these costs a round trip: the frequency and the mode go
        to rigctld over CAT, the power goes there too, and fldigi is asked for
        the modem on the way. The main loop draws five times a second, so
        building them on every draw meant about twenty round trips a second
        while the operator was doing nothing but moving a selection.

        On a Pi with CAT over a serial port each one takes tens of
        milliseconds, so one draw could overrun the 200 ms poll, the loop
        never caught up, and keystrokes queued and then arrived in a burst --
        the selection jumping several contacts at once after a freeze. The
        deck-and-rig screen had the same fault for the same reason.

        **Nothing on a draw path may call the radio without a cache.** A
        second of staleness on a frequency readout costs nothing; a draw that
        blocks costs the interface.
        """
        now = time.monotonic()
        if now - getattr(self, "_radio_at", 0.0) < 1.0:
            return self._radio_cache
        self._radio_cache = (self._log_freq_mhz(), self._log_mode(),
                             self._power_watts())
        self._radio_at = now
        return self._radio_cache

    def _log_lines(self):
        """Lines per contact in the list: 1, 2 or 3."""
        try:
            n = int(str(self.cfg.get("LOG_LINES", "1")).strip() or "1")
        except (TypeError, ValueError):
            n = 1
        return max(render.LOG_LINES_MIN, min(n, render.LOG_LINES_MAX))

    def _log_shown(self):
        """The contacts the list is showing, in the order it shows them.

        The same scoping `_draw_log` uses. Selection indexes THIS list, so the
        two cannot be allowed to disagree -- an index into the whole log would
        open a contact from a different activity.
        """
        if self.log_form is None:
            return self.log_records
        name = self._activity_name()
        if not name:
            # The master log is EVERY contact, not the ones belonging to no
            # activity. `for_session` is a precise filter and answers the
            # narrower question; the product decision is here.
            #
            # This was wrong and the symptom was sharp: a contact logged under
            # an activity was invisible from the master log, so it could not
            # be picked, opened or deleted from the one view that is supposed
            # to hold everything -- while the activities list counted it. The
            # semantic is a leftover from a file per activity, where the
            # default file really did hold only the unlabeled contacts.
            return self.log_records
        return qsolog.for_session(self.log_records, name,
                                  self._activity_start())

    def _log_pick(self, step):
        """Move the selection through the contacts. Returns False if there are
        none, so the caller can leave the keystroke to the form."""
        shown = self._log_shown()
        if not shown:
            return False
        if self.log_sel is None:
            # Up from the form picks the newest contact, which is the one the
            # question is almost always about -- "did that last one go in".
            self.log_sel = len(shown) - 1 if step < 0 else 0
        else:
            self.log_sel = max(0, min(self.log_sel + step, len(shown) - 1))
        # Follow the selection with the window, so picking never walks the
        # cursor off the top of a scrolled list.
        h, w = self._screen_size()
        per = render.log_body_rows(h, self.log_form, w, self._log_lines())
        back = len(shown) - 1 - self.log_sel
        if back < self.log_scroll:
            self.log_scroll = back
        elif back >= self.log_scroll + per:
            self.log_scroll = back - per + 1
        self.log_message = ""
        return True

    def _open_entry(self):
        """Open the picked contact for reading and correcting."""
        shown = self._log_shown()
        if self.log_sel is None or not 0 <= self.log_sel < len(shown):
            return False
        self.entry_rec = dict(shown[self.log_sel])
        self.entry_sel = self._entry_next(0, +1)
        self.entry_message = ""
        self.screen = ENTRY
        return True

    def _entry_rows(self):
        kind = self.entry_rec.get("activity_type", "") if self.entry_rec else ""
        act = activities.get(kind, self._activity_table()) if kind else None
        return qsolog.detail_rows(self.entry_rec or {}, act)

    def _entry_next(self, start, step):
        """The next editable row at or after `start`, wrapping.

        The cursor skips what cannot be changed rather than stopping on it. A
        cursor that could sit on `when` and do nothing on Enter would read as
        a broken key.
        """
        rows = self._entry_rows()
        if not rows:
            return 0
        i = max(0, min(int(start), len(rows) - 1))
        for _ in range(len(rows)):
            if rows[i][3]:
                return i
            i = (i + step) % len(rows)
        return 0

    def _draw_entry(self, h, w):
        rows = self._entry_rows()
        rec = self.entry_rec or {}
        shown = self._log_shown()
        position = ""
        if self.log_sel is not None and shown:
            position = f"{self.log_sel + 1} of {len(shown)}"
        for i, line in enumerate(render.entry_screen(
                rows, self.entry_sel, w, h, call=rec.get("call", ""),
                when=rec.get("when", ""), message=self.entry_message,
                position=position)):
            self._put(i, 0, line, w)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def _handle_entry(self, ch):
        rows = self._entry_rows()
        if ch == 27:                                    # Esc
            self.entry_rec = None
            self.entry_message = ""
            self.screen = LOG if self.log_on else CHAT
        elif ch == curses.KEY_UP:
            self.entry_sel = self._entry_next(
                (self.entry_sel - 1) % max(1, len(rows)), -1)
            self.entry_message = ""
        elif ch == curses.KEY_DOWN:
            self.entry_sel = self._entry_next(
                (self.entry_sel + 1) % max(1, len(rows)), +1)
            self.entry_message = ""
        elif ch in (ord("d"), ord("D")):
            self._ask_delete_qso()
        elif ch in (10, 13, curses.KEY_ENTER) and rows:
            name, label, value, editable = rows[
                max(0, min(self.entry_sel, len(rows) - 1))]
            if not editable:
                self.entry_message = f"{label} cannot be changed"
                return True
            self._open_editor(None, label, text=value,
                              sink=lambda v, f=name: self._edit_entry(f, v))
        return True

    def _ask_delete_qso(self):
        """Confirm, then remove this contact from the log.

        Behind a confirmation like the activity and activity-type deletes, and
        for a stronger reason: those throw away a template or a file the
        operator can rebuild, and this throws away a contact that cannot be
        recovered from anything on the deck. Enter does it and every other key
        keeps it, which is the rule the other two already follow.
        """
        rec = self.entry_rec or {}
        when, call = rec.get("when", ""), rec.get("call", "")
        if not when:
            self.entry_message = "this contact has no timestamp to find it by"
            return
        band = rec.get("band", "")
        mode = rec.get("mode", "")
        worked = "  ".join(p for p in (call, band, mode) if p)
        self._ask_confirm(
            "DELETE THIS CONTACT",
            [worked or call or "(no callsign)",
             f"{when[:10]} {when[11:19]}Z" if len(when) >= 19 else when,
             "",
             "It is removed from the log permanently. Nothing on",
             "the deck can put it back.",
             "",
             "An ADIF already exported is not changed."],
            lambda w=when, c=call: self._delete_qso(w, c),
            back=LOG if self.log_on else CHAT,
            footer="Enter delete   any other key keeps it")

    def _delete_qso(self, when, call):
        """Remove one contact. Confirmed before it gets here."""
        try:
            gone = qsolog.remove(self._log_path(), when, call)
        except OSError as exc:
            self._log_note(f"could not write the log: {exc}")
            return
        if gone is None:
            self._log_note("that contact is no longer in the log")
            return
        # The contact screen was showing what has just stopped existing, and
        # the selection indexed a list that is now one shorter. Both go.
        self.entry_rec = None
        self.entry_message = ""
        self.log_sel = None
        self.log_records = qsolog.read(self._log_path())
        self._log_note(f"{gone.get('call', 'that contact')} deleted from the "
                       f"log")

    def _edit_entry(self, field, value):
        """Write one corrected field back to the log file.

        The file is replaced whole and atomically -- see `qsolog.update`. The
        contact is found by its timestamp, so a log that changed underneath
        this screen refuses the edit instead of rewriting the wrong line.
        """
        rec = self.entry_rec or {}
        when, call = rec.get("when", ""), rec.get("call", "")
        if not when:
            self.entry_message = "this contact has no timestamp to find it by"
            return
        # A frequency is SHOWN grouped -- 7.185.000 -- and STORED in hertz. The
        # screen hands back what it showed, so it is read back through the same
        # parser that accepts everything an operator might type, and what
        # reaches the file is hertz. Without this, one edit of the frequency
        # field would leave a dotted string where `band_for` and the ADIF
        # export both expect a number.
        if field in qsolog.HERTZ_FIELDS and str(value or "").strip():
            hz = qsolog.parse_freq(value)
            if not hz:
                self.entry_message = f"{qsolog.field_label(field)}: cannot read that frequency"
                return
            value = str(hz)
        try:
            got = qsolog.update(self._log_path(), when, call, {field: value})
        except OSError as exc:
            self.entry_message = f"could not write the log: {exc}"
            return
        if got is None:
            self.entry_message = "that contact is no longer in the log"
            return
        self.entry_rec = got
        # Re-read rather than patching the list in memory: the file is the
        # record and anything else is a second copy of it that can be wrong.
        self.log_records = qsolog.read(self._log_path())
        label = qsolog.field_label(field)
        self.entry_message = (
            f"{label} cleared" if not str(value).strip()
            else f"{label} is now "
                 f"{qsolog.display_value(field, got.get(field, ''))}")

    # -- building an activity ----------------------------------------------

    def _copy_activity(self, name):
        """Start a new activity from an existing one.

        Copying rather than starting blank, because every activity an operator
        wants is a small change to one that already exists — a state QSO party
        is a contest with a different word for the exchange — and a blank
        field list is a worse starting point than any of them.
        """
        act = activities.get(name, self._activity_table())
        self.picker = activities.FieldPicker(act.entry)
        self.picker_from = act.name
        self._editing_type = ""
        self.picker_sel = 0
        self.picker_message = ""
        self.screen = FIELDS
        self._close_menu()

    def _edit_activity_type(self, name):
        """Change a schema in place, keeping its name.

        The route before this was copy it, change it, then type the same name
        and answer a question about replacing it -- which works, and which
        nothing on screen suggested. `_editing_type` is what makes the save
        skip that question: replacing it is the whole intent, so asking is
        noise.

        A BUILT-IN still asks, because editing one writes a section that
        shadows the name everywhere on the deck and the way back -- delete
        yours and the built-in returns -- is worth stating once. That check
        lives in `_save_activity`, which is where the file is looked at.
        """
        act = activities.get(name, self._activity_table())
        self.picker = activities.FieldPicker(act.entry)
        # `picker_from` is what the saved label claims descent from, and an
        # edit descends from nothing -- it IS that schema. Left empty so the
        # label does not come back as "PAQP (from PAQP)".
        self.picker_from = ""
        self._editing_type = act.name
        self.picker_sel = 0
        self.picker_message = ""
        self.screen = FIELDS
        self._close_menu()

    def _new_activity_type(self):
        """Begin a type with no fields chosen.

        Worth having alongside the copy, because an activity that shares
        nothing with GENERAL or a contest reaches its field list faster from
        empty than by pruning somebody else's. An empty `picker_from` is what
        marks it as built from nothing, and keeps the saved label from
        claiming descent from a type it was never copied from.
        """
        self.picker = activities.FieldPicker(())
        self.picker_from = ""
        self._editing_type = ""
        self.picker_sel = 0
        self.picker_message = ""
        self.screen = FIELDS
        self._close_menu()

    def _draw_fields(self, h, w):
        for i, line in enumerate(render.field_select_screen(
                self.picker.rows(), self.picker_sel, w, h,
                title=("SELECT FIELDS — from " + self.picker_from
                       if self.picker_from else "SELECT FIELDS — new schema"),
                footer=(self.picker_message
                        + "  ·  Space toggle  Enter order"
                        if self.picker_message else ""))):
            self._put(i, 0, line, w)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def _handle_fields(self, ch):
        rows = self.picker.rows()
        if ch == 27:
            self.picker = None
            self.picker_message = ""
            self.screen = LOG if self.log_on else CHAT
        elif ch == curses.KEY_UP:
            self.picker_sel = (self.picker_sel - 1) % len(rows)
        elif ch == curses.KEY_DOWN:
            self.picker_sel = (self.picker_sel + 1) % len(rows)
        # A page at a time. The page follows the cursor, so this is just a
        # bigger step rather than separate state.
        elif ch in (curses.KEY_LEFT, curses.KEY_PPAGE):
            self.picker_sel = max(0, self.picker_sel - render.FIELDS_PER_PAGE)
        elif ch in (curses.KEY_RIGHT, curses.KEY_NPAGE):
            self.picker_sel = min(len(rows) - 1,
                                  self.picker_sel + render.FIELDS_PER_PAGE)
        elif ch in (32, 10, 13, curses.KEY_ENTER) and ch == 32:
            self.picker_message = ""
            self.picker.toggle(rows[self.picker_sel][0])
        elif ch in (10, 13, curses.KEY_ENTER):
            if not self.picker.entry():
                # An activity with no fields is a form with nothing but a
                # callsign on it. Refusing here is kinder than letting it be
                # saved and discovered mid-contact.
                #
                # On the screen, not only in the transcript: a type started
                # from nothing begins with every field off, so this is the
                # first thing Enter does, and a note the operator cannot see
                # reads as a dead key.
                self.picker_message = "choose at least one field"
                self._log_note("choose at least one field")
                return True
            self.picker_sel = 0
            self.screen = ORDER
        else:
            # 1-9 then a-e. Digits alone stopped reaching every field once
            # the list grew past nine, and a row only the arrows can get to
            # is a row most operators never find. The screen prints the key
            # beside each row, so the two cannot drift apart.
            # The key names a row on the CURRENT page, not in the whole list.
            at = activities.pick_index(ch)
            page = self.picker_sel // render.FIELDS_PER_PAGE
            if at >= 0:
                at += page * render.FIELDS_PER_PAGE
            if 0 <= at < len(rows):
                self.picker_sel = at
                self.picker_message = ""
                self.picker.toggle(rows[at][0])
        return True

    def _draw_order(self, h, w):
        for i, line in enumerate(render.field_order_screen(
                self.picker.order(), self.picker_sel, w, h,
                message=self.picker_message)):
            self._put(i, 0, line, w)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def _handle_order(self, ch):
        order = self.picker.order()
        if ch == 27:
            self.screen = FIELDS
        elif ch == curses.KEY_UP:
            self.picker_sel = (self.picker_sel - 1) % max(1, len(order))
        elif ch == curses.KEY_DOWN:
            self.picker_sel = (self.picker_sel + 1) % max(1, len(order))
        elif ch == 48:                                    # 0
            # Row 0 is the callsign and is not in `order`. Typing 0 would
            # otherwise do nothing at all, which reads as a broken key rather
            # than as a row that cannot be moved.
            self.picker_message = "the callsign is always first"
        elif 49 <= ch <= 57:                              # 1-9
            name = order[self.picker_sel][1]
            self.picker.move(name, ch - 48)
            # Follow the row that moved, so a second number keeps working on
            # the same field rather than on whatever slid into its place.
            for i, (_n, f, _l) in enumerate(self.picker.order()):
                if f == name:
                    self.picker_sel = i
                    break
            self.picker_message = ""
        elif ch in (10, 13, curses.KEY_ENTER):
            # "activity TYPE", because that is what is being named. It said
            # "Name for this activity", which is the other thing entirely: an
            # activity is a session with a log file, a type is the template of
            # fields that session uses, and the screen that had just finished
            # choosing and ordering FIELDS was asking for the wrong one.
            # Prefilled with the name when a schema is being EDITED, so the
            # last step of an edit is Enter rather than retyping a name the
            # operator never meant to change. Empty for a copy or a new one,
            # where the name is the decision still to be made.
            self._open_editor(None, "Name for this log schema",
                              text=self._editing_type,
                              sink=self._save_activity)
        return True

    def _save_activity(self, name):
        """Name the built type. Three things can stop the write.

        Two are refusals -- no name, and the one reserved name -- and they
        print on the ORDER screen as well as in the transcript. The transcript
        is covered here, so a note on its own reads as an Enter that did
        nothing, which is how the empty-field refusal used to read.

        The third is a question rather than a refusal. `activities.save`
        replaces a section of the same name on purpose, because saving twice
        under one name is what revising a definition looks like -- but it did
        it silently, so a name that collided destroyed the earlier type with
        no sign of it. Asking keeps the revision path and loses the surprise.
        """
        name = "".join(c for c in (name or "").strip().upper()
                       if c.isalnum() or c in "-_")
        if not name:
            self.picker_message = "a log schema needs a name"
            self._log_note("a log schema needs a name")
            return
        if name in ("GENERAL",):
            self.picker_message = "GENERAL is the built-in — pick another name"
            self._log_note("GENERAL is the built-in; pick another name")
            return
        if name == self._editing_type and name in self._file_types():
            # Editing that very schema in place. Replacing it is the whole
            # intent, so the question that guards an accidental name
            # collision has nothing to guard here.
            self._write_activity(name)
            return
        if name in self._file_types():
            # Their own definition, in the file. Replacing it is the common
            # case and the one worth confirming: it is the only one where
            # something an operator wrote goes away.
            self._ask_confirm(
                "REPLACE LOG SCHEMA",
                [name, "",
                 f"A type named {name} is already in activities.conf.",
                 "Saving replaces it. Contacts already logged are",
                 "not touched."],
                lambda n=name: self._write_activity(n),
                back=ORDER, footer="Enter replace   any other key picks "
                                   "a new name",
                cancel=lambda n=name: self._rename_activity_type(n))
            return
        if activities.is_builtin(name):
            # A built-in with no section yet. Nothing of theirs is lost, but
            # the name stops meaning what it means everywhere else on the
            # deck, so it is still worth a keystroke.
            self._ask_confirm(
                "REPLACE BUILT-IN SCHEMA",
                [name, "",
                 f"{name} is built in. Saving puts your version in",
                 "activities.conf, and it is used from then on.",
                 "",
                 f"Deleting yours later restores the built-in {name}."],
                lambda n=name: self._write_activity(n),
                back=ORDER, footer="Enter replace   any other key picks "
                                   "a new name",
                cancel=lambda n=name: self._rename_activity_type(n))
            return
        self._write_activity(name)

    def _rename_activity_type(self, name):
        """Back from "that name is taken" to the name prompt, prefilled.

        Prefilled rather than empty: the operator is changing one name into
        a near neighbor -- PAQP into PAQP-SSB -- and retyping it is work the
        answer to the question already did.
        """
        self.screen = ORDER
        self._open_editor(None, "Name for this log schema",
                          sink=self._save_activity, text=name)

    def _write_activity(self, name):
        """Write the built type out and select it. Past every check."""
        base = activities.get(self.picker_from, self._activity_table())
        text = activities.format_activity(
            name, self.picker.entry(),
            label=(f"{name} (from {base.label})" if self.picker_from
                   else name),
            sig=base.sig, contest_id=base.contest_id,
            serial=base.serial, serial_start=base.serial_start,
            labels={f: base.label_for(f) for f in self.picker.entry()
                    if base.label_for(f) != activities.ENTRY_FIELDS.get(
                        f, (None, f))[1]})
        try:
            path = activities.save(activities.config_path(), name, text)
        except OSError as exc:
            self.picker_message = f"could not save: {exc}"
            self._log_note(f"could not save: {exc}")
            self.screen = ORDER
            return
        self.picker = None
        self.picker_message = ""
        self._editing_type = ""
        self._log_note(f"saved {name} to {path}")
        # `_set_activity_type` rebuilds the form from the saved definition, so
        # editing the schema an activity is already using takes effect on the
        # next contact without leaving the activity -- which is what makes a
        # schema editable mid-session. Contacts already logged keep what they
        # were given; a field added now is blank on them, because the stored
        # line carries only the fields that had a value.
        self._set_activity_type(name)
        self.screen = LOG if self.log_on else CHAT

    def _callbook_state(self):
        """"off", "on" or "no wifi", for the menu and the status line."""
        import callbook as cb
        return cb.callbook_state(self.cfg.get("CALLBOOK"), self._online())

    def _online(self):
        """Whether there is a default route, cached for a few seconds.

        Asked on every menu draw and every lookup decision. The read is a
        handful of bytes out of /proc, but doing it five times a second for
        the life of the process is still pointless.
        """
        now = time.monotonic()
        if now - getattr(self, "_online_checked", 0.0) > 5.0:
            import callbook as cb
            self._online_cached = cb.online()
            self._online_checked = now
        return getattr(self, "_online_cached", False)

    def _lookup_maybe(self, form):
        """Look the callsign up once it has stopped changing.

        The lookup used to fire from exactly one place: Tab out of the
        callsign field. So the fast path -- type a call, press Enter -- never
        looked anything up, and the feature appeared not to work at all. It
        was working; nothing was asking it.

        Asking on every keystroke is the other wrong answer: `W`, `W3`, `W3A`
        are not callsigns, and sending three partial calls to a third party to
        learn that is worse than waiting. So this waits for the field to go
        quiet, which is what a human does anyway before reaching for the next
        one.
        """
        if form is None or self.screen != LOG:
            return
        call = form.value("call").strip().upper()
        if call != getattr(self, "_call_seen", None):
            self._call_seen = call
            self._call_still = time.monotonic()
            # "W1AW: nothing known" must not outlive the callsign it was about.
            self.lookup_message = ""
            return
        if not call or call == self._looked_up:
            return
        if time.monotonic() - getattr(self, "_call_still", 0.0) < 0.8:
            return
        self._lookup_start(call)

    def _lookup_start(self, call):
        """Ask the callbooks about a callsign, off the interface thread.

        Fired when focus leaves the callsign field rather than on every
        keystroke: `W`, `W3`, `W3A` are not callsigns, and asking about them
        sends three useless requests and three partial callsigns to a third
        party.
        """
        call = (call or "").strip().upper()
        # Done before the CALLBOOK guard and before the callsign is judged
        # valid: whatever is in the name and QTH fields describes the station
        # the callsign used to be, and that is true whether or not a new
        # lookup is going to happen. A cleared callsign leaves no name behind.
        if self.log_form is not None and call != self._looked_up:
            self.log_form.forget_lookup()
        if self.cfg.get("CALLBOOK") != "yes":
            return
        if not self._online():
            return
        if not call or call == self._looked_up or not qsolog.is_callsign(call):
            return
        try:
            import callbook
            if self._callbook is None:
                self._callbook = callbook.Background(
                    cache=callbook.Cache(callbook.cache_path()),
                    providers=callbook.providers_from(self.cfg))
            self._callbook.start(call)
            self._looked_up = call
        except Exception:
            # No network, no credentials, no module: the same event as far as
            # this screen is concerned, and none of them may stop a contact
            # being logged.
            pass

    def _lookup_collect(self, form):
        """Merge any answer that has arrived. Never overwrites what was typed."""
        if self._callbook is None or form is None:
            return ""
        call = form.value("call").strip().upper()
        if not call:
            return ""
        info = self._callbook.take(call)
        if info is None:
            return ""
        if not info:
            return f"-- {call}: nothing known"
        # `not touched` rather than `not value`: an answer for the callsign now
        # on the form has to be able to replace the previous station's name,
        # which is not empty. What it may never replace is a value the
        # operator typed -- that is a correction, and it outranks a callbook.
        for key in logform.LOOKUP:
            field = form.field(key)
            if field is not None and info.get(key) and not field.touched:
                form.set(key, info[key])
        # Nothing to say when it worked. The fields filling in front of the
        # operator is the message, and printing the answer as well cost more
        # than it gave: it sat on the one line this screen has for messages and
        # so hid the duplicate warning, which is the thing on that line worth
        # reading. A dupe is a decision about whether to work the station; a
        # name that has already appeared in the Name field is not news.
        #
        # A lookup that found NOTHING still reports, because that cannot be
        # read off the fields: no name appearing looks the same as no network,
        # a wrong callsign, and a station nobody has heard of.
        return ""

    def _file_types(self):
        """Type names defined in activities.conf, as opposed to in code.

        Only these can be deleted. A built-in with no section in the file has
        nothing to remove, and saying so is better than appearing to delete
        something that comes straight back on the next load.
        """
        try:
            with open(activities.config_path(), encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            return set()
        out = set()
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                out.add(line[1:-1].strip().upper())
        return out

    def _activity_table(self):
        """Every activity, built-in and defined. Never raises at the menu.

        A broken activities.conf must not make the menu unopenable — the
        built-ins are a working set on their own, and the operator finds out
        from a note rather than from a screen that will not come up.
        """
        try:
            return activities.load()
        except Exception as exc:
            self._log_note(f"activities.conf: {exc}")
            return dict(activities.BUILTIN)

    def _has_tqsl(self):
        if self._tqsl is None:
            try:
                import lotw
                self._tqsl = lotw.available()
            except Exception:
                self._tqsl = False
        return self._tqsl

    def _set_activity_type(self, name, table=None):
        """Switch activity TYPE, rebuilding the form because its fields change.

        What this station sends is carried across — own reference, own
        exchange, the standing comment — because those describe the operating
        session rather than the type, and retyping them after changing type is
        exactly the kind of thing that makes an operator not change type.

        The activity itself does not change here, and neither does the log
        file: changing the type is a correction to how this session is being
        logged, not the start of a different session.
        """
        act = activities.get(name, table or self._activity_table())
        self.cfg["ACTIVITY_TYPE"] = "" if act.name == "GENERAL" else act.name
        carried = {}
        if self.log_form is not None:
            carried = {k: self.log_form.value(k)
                       for k in ("my_park", "exchange_tx", "comment")}
        self.log_form = logform.LogForm(act)
        for key, value in carried.items():
            if value:
                self.log_form.set(key, value)
        for key, setting in (("my_park", "MY_PARK"),
                             ("exchange_tx", "EXCHANGE_TX")):
            if not self.log_form.value(key) and self.cfg.get(setting):
                self.log_form.set(key, self.cfg[setting])
        self.log_form.advance_serial(self.log_records, act.serial_start,
                                     activity=self._activity_name())
        self._save_state()
        self._log_note(f"schema: {act.label}")
        self._ask_my_park()

    def _ask_my_park(self):
        """Ask for this station's own reference, once, if the type wants one.

        Typed once for the activity rather than once per contact: it is the
        same park on every line of an activation, and it is already carried
        across a type change for that reason. Asking here is what makes "once"
        true -- it used to be a menu item an operator had to know to go and
        find, so the alternative to typing it per contact was not typing it.

        Only when it is not already known. The park is cleared when a new
        activity is named, so a new activation always asks and a correction to
        an activity already under way never does -- last week's reference
        logged onto today's contacts is worse than a question.
        """
        if self.cfg.get("MY_PARK"):
            return
        if not menus.needs_reference(self.cfg.get("ACTIVITY_TYPE", "")):
            return
        self._open_editor("MY_PARK", "My reference", sink=self._set_my_park)

    # -- WSPR --------------------------------------------------------------
    #
    # The engines are built on entering the area and torn down on leaving it.
    # `wsprsched` decides what each slot does; `wsprrx` and `wsprtx` do it;
    # `wsprlog` records it; `wsprnet` reports it. None of them knows what time
    # it is or where the radio is -- this is where those come from.

    @property
    def wspr_running(self):
        """Whether WSPR has the deck. The ring reads this, so it is cheap."""
        return self.wspr is not None and self.wspr.wspr

    def _wspr_note(self, text):
        """A message for the WSPR screen. Not the transcript.

        Same reasoning as `_log_note`: housekeeping about sessions and bands
        was never part of the on-air conversation, and the WSPR screen draws
        its own message line.
        """
        self.wspr_message = text

    def _wspr_dir(self):
        """Where captures and `wsprd`'s own files go.

        Under the state directory rather than beside the log: these are
        working files, one per slot, and a directory that accumulates 114 KB
        every two minutes does not belong next to the contact log.
        """
        base = os.path.dirname(self._state_path() or "") or "/tmp"
        return os.path.join(base, "wspr")

    def _wspr_bands(self):
        """The bands to hop through, as labels. One means no hopping."""
        import wsprbands
        out = []
        for part in str(self.cfg.get("WSPR_BANDS", "") or "").split(","):
            label = wsprbands.normalise(part)
            if label and label not in out:
                out.append(label)
        return out or [wsprbands.normalise("40m")]

    def _wspr_build(self):
        """Make the engines. Idempotent, so entering the area twice is safe."""
        import wsprnet
        import wsprrx
        import wsprsched
        import wsprtx
        if self.wspr is None:
            self.wspr = wsprsched.Schedule(
                bands=self._wspr_bands(),
                tx_percent=self.cfg.get("WSPR_TX_PERCENT", 20),
                timeout_minutes=self.cfg.get("WSPR_TIMEOUT_MIN", 60),
                # Seeded from the callsign so two decks do not share a
                # transmit schedule and collide in the same slots forever.
                seed=sum(ord(c) for c in self.cfg.get("CALLSIGN", "") or "x"))
        if self.wspr_rx is None:
            self.wspr_rx = wsprrx.Receiver(
                self._wspr_dir(),
                device=self.cfg.get("WSPR_DEVICE") or wsprrx.DEFAULT_DEVICE)
        if self.wspr_tx is None:
            self.wspr_tx = wsprtx.Transmitter(
                self._wspr_dir(), rig=self._log_rig(),
                device=self.cfg.get("WSPR_DEVICE") or wsprtx.DEFAULT_DEVICE)
        # Reapplied on every build, not only on the first: the setting is
        # changed from the menu and the transmitter is not rebuilt for it.
        # The setter drops the rendered audio when the value moves, so the
        # next beacon goes out at the new amplitude.
        self.wspr_tx.level = self.cfg.get("WSPR_TX_LEVEL", 50)
        if self.wspr_gain is None:
            import wsprgain
            self.wspr_gain = wsprgain.Gain(
                card=self.cfg.get("WSPR_RX_CARD", "Device"),
                control=self.cfg.get("WSPR_RX_CONTROL", "Mic"),
                agc=self.cfg.get("WSPR_RX_AGC", "Auto Gain Control"))
        if self.wspr_up is None:
            self.wspr_up = wsprnet.Uploader()

    def _open_wspr(self):
        """Enter the WSPR area. Does NOT start it."""
        self._wspr_build()
        self.screen = WSPR
        if not self.wspr_band:
            self.wspr_band = self._wspr_bands()[0]

    def _wspr_start(self):
        """Take the deck: stop fldigi, start the slot clock.

        **fldigi is stopped, not asked to release the audio.** The USB codec
        reports `Subdevices: 0/1` while fldigi holds it and `arecord` fails
        "Device or resource busy" -- measured on the deck, so this is the only
        arrangement that works rather than a precaution.
        """
        self._wspr_build()
        if self.wspr.wspr:
            return
        if not self.cfg.get("CALLSIGN"):
            self._wspr_note("set a callsign on the deck & rig screen first")
            return
        if not self.cfg.get("LOCATOR"):
            self._wspr_note("set a locator — WSPR sends the grid")
            return
        # A run the operator did not name is still a run, so it gets the
        # default name and a pinned start here rather than writing spots
        # with no session for the danger zone and the export to miss.
        self._wspr_ensure_session()
        # Starting without the codec produced a session that looked live and
        # decoded nothing: the slot clock ran, `arecord` failed every two
        # minutes, and the only sign was a truncated error. WSPR without the
        # codec is not a degraded WSPR, it is none.
        if not self._wspr_take_audio():
            return
        # The capture mixer, now that fldigi is down and nothing else is
        # listening. The previous value is remembered and put back by
        # `_wspr_stop`, which is what makes this WSPR's level rather than a
        # change to the station.
        why = self.wspr_gain.apply(self.cfg.get("WSPR_RX_GAIN", 70))
        if why:
            self._wspr_note(f"capture gain: {why}")
        # And the AGC off, which matters for correctness rather than level:
        # it compresses a constant-envelope signal and corrupts the SNR that
        # gets uploaded to wsprnet as a measurement.
        why = self.wspr_gain.silence_agc()
        if why:
            self._wspr_note(f"AGC: {why}")
        self.wspr.start(time.time())
        self.wspr_spots = []
        self.wspr_sel = None
        self.wspr_dbfs = None
        self._wspr_note(f"WSPR started on {self.wspr_band} — "
                        f"^O ^P are locked until it stops")

    def _wspr_stop(self, why=""):
        """Give the deck back: stop everything, restart fldigi.

        Ordered so the radio is safe first. The transmitter's own `stop`
        unkeys from any state, and it is called before anything else can
        fail.
        """
        if self.wspr_tx is not None:
            self.wspr_tx.stop()
        if self.wspr_rx is not None:
            self.wspr_rx.stop()
        if self.wspr is not None:
            self.wspr.stop()
        # Every band WSPR put into a data mode gets its own mode back.
        self._wspr_release_modes()
        # Before fldigi comes back, so the level it finds is the one it had.
        if self.wspr_gain is not None:
            why = self.wspr_gain.restore()
            if why:
                self._wspr_note(f"could not restore the capture gain: {why}")
            self.wspr_gain.restore_agc()
        self._wspr_give_audio()
        self._wspr_note(f"WSPR stopped{' — ' + why if why else ''}")

    def _fldigi_holds_audio(self):
        """Whether the fldigi service is still up, and so still holding the
        USB codec.

        Asked of systemd rather than of the audio device: opening the device
        to find out would itself have to be released again, and `is-active`
        needs no privilege -- which matters precisely in the case this
        exists for, where `stop` failed for want of one.
        """
        import subprocess
        try:
            # A short timeout: this is asked from the draw path, and
            # `is-active` answers in milliseconds or not at all.
            r = subprocess.run(
                ["systemctl", "is-active", "--quiet", "cyberdeck-fldigi"],
                timeout=3, stdin=subprocess.DEVNULL,
                capture_output=True)
            return r.returncode == 0
        except Exception:
            return False

    def _wspr_take_audio(self):
        """Ask systemd to stop fldigi. **Does not wait for it.**

        This used to stop fldigi and then block until the codec was free,
        polling with `time.sleep` and retrying -- on the keypress path, so
        the draw loop stopped. Right after a reboot, when `cyberdeck-ui`
        has just restarted and systemd is still starting fldigi because of
        the UI's own `Wants=`, a `stop` queues behind that start job: the
        panel froze for 30 to 40 seconds on the first toggle.
        **Nothing on a keypress path may wait on systemd.**

        So the command is spawned and the question "is the codec free" is
        asked again before each capture, which is where the answer actually
        matters. There is room for that: the scheduler skips the slot it is
        already inside, so the first window is up to two minutes away.
        """
        if not self._fldigi_holds_audio():
            return True
        self.wspr_fldigi_stopped = self._service_async(
            "stop", "cyberdeck-fldigi")
        return self.wspr_fldigi_stopped

    def _wspr_give_audio(self):
        """Start fldigi again, if this code is what stopped it. Also async:
        leaving must not block either."""
        if self.wspr_fldigi_stopped:
            self._service_async("start", "cyberdeck-fldigi")
            self.wspr_fldigi_stopped = False

    def _service_async(self, action, unit):
        """Spawn systemctl and return. Reaped by `_service_reap`.

        Returns whether the command was SPAWNED, not whether it worked --
        the same distinction `rigctld_client.set_ptt` draws, and for the
        same reason: the answer arrives later.
        """
        import subprocess
        try:
            proc = subprocess.Popen(
                ["systemctl", action, unit],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, stdin=subprocess.DEVNULL)
        except Exception as exc:
            self._wspr_note(f"systemctl {action} {unit}: {exc}")
            return False
        self._service_jobs.append((proc, action, unit))
        del self._service_jobs[8:]
        return True

    def _service_reap(self):
        """Collect finished systemctl jobs and report the ones that failed.

        Polled from `_wspr_poll`, so a failure is reported a fraction of a
        second after it happens rather than being waited for.
        """
        for job in list(self._service_jobs):
            proc, action, unit = job
            if proc.poll() is None:
                continue
            self._service_jobs.remove(job)
            if proc.returncode == 0:
                continue
            why = ""
            try:
                why = (proc.stderr.read() or "").strip().splitlines()[-1]
            except Exception:
                pass
            if "polkit" in why.lower() or "authoriz" in why.lower() \
                    or "authentication" in why.lower():
                why = ("not authorized — see "
                       "polkit/10-cyberdeck-services.rules")
            self._wspr_note(f"systemctl {action} {unit}: "
                            + (why[:52] if why else
                               f"exit {proc.returncode}"))

    def _wspr_data_mode(self):
        """The mode name to put the radio in for WSPR.

        `PKTUSB` is what hamlib calls the FTX-1's DATA-U and what the radio
        reports when it is in it, so it is also what setting it back
        requires. Configurable because another radio names it differently.
        """
        return str(self.cfg.get("WSPR_MODE", "PKTUSB")).strip().upper()

    def _wspr_claim_mode(self, band):
        """Put this band in a data mode, remembering what it was in.

        **The radio remembers a mode per band**, so a rotation can be three
        bands in DATA-U and one in LSB, and the only symptom is a slot that
        transmits nothing useful. A menu item that reported which bands were
        wrong came first; setting them is better, provided what was there is
        given back -- which is what `_wspr_release_modes` is for.

        Nothing is remembered for a band already in a data mode, so leaving
        WSPR does not set a mode the operator had set themselves.
        """
        rig = self._log_rig()
        if rig is None:
            return
        try:
            found = (rig.mode()[0] or "").upper()
        except Exception:
            return
        if not found:
            # A mode that cannot be read is not a mode known to be wrong,
            # and changing it blind would be a change with nothing to undo.
            return
        if found in qsolog.RIG_DATA_MODES:
            return
        want = self._wspr_data_mode()
        try:
            if not rig.set_mode(want):
                return
        except Exception:
            return
        # Remembered only once the command went, and only the FIRST mode
        # seen on this band: visiting a band twice must not record the mode
        # WSPR itself set as the one to go back to.
        self._wspr_modes.setdefault(band, found)
        self._wspr_note(f"{band} was {found} — set to {want}")

    def _wspr_release_modes(self, only=None):
        """Give every band its own mode back.

        The radio holds one mode at a time, so this has to VISIT each band
        it changed. `only` restores a single band, which is the free case:
        the radio is already tuned there.

        Called on stop and on leaving the area, and the band the operator
        was on is returned to last so the radio is left where they left it.
        """
        if not self._wspr_modes:
            return
        rig = self._log_rig()
        if rig is None:
            self._wspr_modes.clear()
            return
        import wsprbands
        bands = ([only] if only is not None
                 else list(self._wspr_modes.keys()))
        here = self.wspr_band
        done = []
        for band in bands:
            was = self._wspr_modes.get(band)
            if not was:
                continue
            try:
                if band != self.wspr_band:
                    hz = wsprbands.dial_hz(band)
                    if hz:
                        rig.set_frequency(hz)
                        time.sleep(0.25)
                rig.set_mode(was)
                time.sleep(0.1)
                done.append(band)
            except Exception:
                continue
        for band in done:
            self._wspr_modes.pop(band, None)
        # Back to where the operator was, if visiting others moved the radio.
        if only is None and here and bands != [here]:
            hz = wsprbands.dial_hz(here)
            if hz:
                try:
                    rig.set_frequency(hz)
                except Exception:
                    pass
        if done:
            self._wspr_note("mode restored on " + ", ".join(done))

    def _wspr_poll(self):
        """One tick of WSPR. Called from `poll`, so it never blocks."""
        if self.wspr is None:
            return
        now = time.time()
        self._service_reap()
        for action, what in self.wspr.tick(now):
            if action == "stop":
                self._wspr_stop(what)
                return
            if action == "tx_off":
                # Receive keeps running: the timer is about the
                # transmitter. Said loudly, because an operator who comes
                # back to a screen that is still decoding needs to know
                # that it has stopped beaconing.
                self._wspr_note(f"transmit off — {what}. Spots still "
                                f"coming in; F1 then t arms it again")
                continue
            if action == "tune":
                self._wspr_tune(what)
            elif action == "capture":
                self._wspr_capture(what)
            elif action == "transmit":
                self._wspr_transmit(what)
        self._wspr_collect()

    def _wspr_tune(self, band):
        """Put the radio on a band's WSPR dial frequency.

        Through `rigctld_client` and not fldigi: fldigi is stopped, which
        takes its rig control with it. Verified on the deck -- the rigctld
        unit keeps the serial port when fldigi goes down.
        """
        import wsprbands
        hz = wsprbands.dial_hz(band)
        if not hz:
            return
        # The band being LEFT gets its mode back first, while the radio is
        # still on it -- which is the only moment restoring it is free.
        if self.wspr_band and self.wspr_band != band \
                and self.wspr_band in self._wspr_modes:
            self._wspr_release_modes(only=self.wspr_band)
        self.wspr_band = band
        rig = self._log_rig()
        if rig is not None:
            try:
                rig.set_frequency(hz)
            except Exception as exc:
                self._wspr_note(f"could not tune: {exc}")
                return
            # And the band being arrived at is put into a data mode, which
            # is what makes a rotation work without the operator setting
            # each band by hand.
            self._wspr_claim_mode(band)

    def _wspr_capture(self, band):
        """Begin a window, unless fldigi still has the codec.

        **This is where "is the audio free" is answered**, not on the
        keypress that started the session -- see `_wspr_take_audio`. Asking
        here costs one `systemctl is-active` per two minutes and keeps the
        draw loop out of systemd's way entirely. A window skipped because
        the codec was still busy says so and the next slot tries again.
        """
        import datetime as _dt
        import wsprbands
        if self._fldigi_holds_audio():
            self._wspr_note("fldigi still has the audio — skipping this "
                            "window (see docs/wspr_deploy.md §4b)")
            return
        when = _dt.datetime.now(_dt.timezone.utc)
        self.wspr_rx.start_capture(when, band or self.wspr_band,
                                   wsprbands.dial_hz(band
                                                      or self.wspr_band))

    def _wspr_transmit(self, band):
        """Beacon this slot. Refused outside a data mode.

        The interlock is the deck's own: `_rig_mode_ok` reads through
        `_rig_mode_held`, so a dropped CAT read cannot be mistaken for a
        radio that left its data mode.
        """
        if not self._rig_mode_ok():
            # **Named band.** The radio remembers a mode per band, so on a
            # hopping session this fires for one band out of four and "the
            # rig is not in a data mode" does not say which to go and set.
            # `Check hop bands for DATA-U` on the menu answers it for the
            # whole rotation without waiting for the slot to come round.
            self._wspr_note(f"{band or self.wspr_band} is not in a data "
                            f"mode — not transmitting on it")
            return
        if self.session.inhibited:
            self._wspr_note("transmit is inhibited — Ctrl-B to arm")
            return
        watts, dbm, exact = self._wspr_power()
        if dbm is None:
            self._wspr_note("cannot read the power — not transmitting")
            return
        why = self.wspr_tx.beacon(self.cfg.get("CALLSIGN", ""),
                                  str(self.cfg.get("LOCATOR", ""))[:4],
                                  dbm)
        if why:
            self._wspr_note(f"beacon failed: {why}")
            return
        self._wspr_record_tx(band or self.wspr_band, dbm, watts)

    def _wspr_power(self, cache_s=1.5):
        """`(watts, dbm, exact)` for the beacon, or `(None, None, False)`.

        **Cached, because this is on a draw path.** It reads the radio over
        CAT -- a socket round trip with a two-second timeout -- and
        `_draw_wspr` called it on every draw, five times a second. Moving the
        spot selection therefore waited on the radio for every keypress,
        which is the lag an operator reported on the arrows. `_radio_now`
        carries the same warning for the same reason: nothing on a draw path
        may call the radio without a cache.
        """
        now = time.monotonic()
        if self._wspr_power_at and now - self._wspr_power_at < cache_s:
            return self._wspr_power_cache
        got = self._wspr_power_read()
        self._wspr_power_cache = got
        self._wspr_power_at = now
        return got

    def _wspr_power_read(self):
        """The uncached reading. Everything else goes through `_wspr_power`.

        The dBm the message carries is derived from what the radio is
        actually making, snapped to a value WSPR can encode. A ceiling is
        required: without `TX_POWER_MAX` the CAT reading is a fraction and
        cannot be turned into watts at all.
        """
        import wspr as _w
        text = self._power_watts()
        if not text:
            return None, None, False
        try:
            watts = float(text)
            dbm, exact = _w.dbm_for_watts(watts)
        except Exception:
            return None, None, False
        return text, dbm, exact

    def _wspr_record_tx(self, band, dbm, watts):
        import wsprbands
        import wsprlog
        rec = wsprlog.tx_record(
            self._utc_now(), band=band,
            dial_hz=wsprbands.dial_hz(band), my_dbm=dbm, tx_power=watts,
            activity=self.cfg.get("WSPR_SESSION", ""),
            activity_start=self.cfg.get("WSPR_SESSION_START", ""),
            my_call=self.cfg.get("CALLSIGN", ""),
            my_grid=self.cfg.get("LOCATOR", ""),
            my_rig=self.cfg.get("RIG", ""),
            my_antenna=self.cfg.get("ANTENNA", ""))
        try:
            self._wspr_counts_stale()
            wsprlog.append(wsprlog.log_path(self.cfg.get("WSPR_LOG_PATH", "")),
                           rec)
        except OSError as exc:
            self._wspr_note(f"could not write the spot log: {exc}")

    def _wspr_collect(self):
        """Drain the engines. Every event here is the result of a subprocess."""
        import wsprbands
        import wsprlog
        import wsprnet
        for event in self.wspr_rx.tick():
            kind = event[0]
            if kind == "captured":
                path, band = event[1], event[2]
                # The WSJT-X analog: the figure that says whether the
                # capture gain is right. Measured on the file that was just
                # written, so it costs no extra audio handling, and strided
                # so a 114-second window is not walked sample by sample on a
                # 512 MB board.
                import wsprgain
                level = wsprgain.level_of(path)
                self.wspr_dbfs = level[2] if level else None
                if self.wspr.decode:
                    self.wspr_rx.start_decode(path, band,
                                              wsprbands.dial_hz(band))
            elif kind == "spots":
                self._wspr_store(event[1], event[2])
            elif kind == "failed":
                self._wspr_note(f"{event[1]}: {event[2]}")
        for event in self.wspr_tx.tick():
            if event[0] == "failed":
                self._wspr_note(f"transmit: {event[2]}")

    def _wspr_store(self, spots, band):
        """Log the spots, show them, and report them if armed."""
        import wsprbands
        import wsprlog
        import wsprnet
        if not spots:
            return
        path = wsprlog.log_path(self.cfg.get("WSPR_LOG_PATH", ""))
        when = self._utc_now()
        common = dict(when=when, band=band,
                      activity=self.cfg.get("WSPR_SESSION", ""),
                      activity_start=self.cfg.get("WSPR_SESSION_START", ""),
                      my_call=self.cfg.get("CALLSIGN", ""),
                      my_grid=self.cfg.get("LOCATOR", ""),
                      my_rig=self.cfg.get("RIG", ""),
                      my_antenna=self.cfg.get("ANTENNA", ""))
        try:
            wsprlog.append_spots(path, spots, **common)
            self._wspr_counts_stale()
        except OSError as exc:
            self._wspr_note(f"could not write the spot log: {exc}")
        # Newest first, which is the order the screen wants.
        #
        # **Distance and bearing are computed here, not stored.** WSPR
        # carries a grid square and no distance; wsprnet and wspr.rocks fill
        # their own km column the same way, from the two locators. They are
        # left out of the log record deliberately: both are derivable from
        # the two grids that ARE in it, and a log holding a figure beside
        # the data it came from invites the two to disagree.
        import grid
        mine = self.cfg.get("LOCATOR", "")
        for spot in spots:
            theirs = str(spot.get("grid", "") or "")
            self.wspr_spots.insert(0, dict(
                spot, when=when, band=band,
                km=grid.distance_km(mine, theirs),
                az=grid.azimuth_deg(mine, theirs)))
        del self.wspr_spots[200:]
        # Three conditions, all the operator's: running, the toggle on, and
        # a network. None of them is decided here.
        armed = (self.wspr_running
                 and self.cfg.get("WSPR_UPLOAD") == "yes"
                 and self._online())
        if not armed:
            return
        for spot in spots:
            self.wspr_up.submit(wsprnet.spot_params(
                spot, self.cfg.get("CALLSIGN", ""),
                self.cfg.get("LOCATOR", ""),
                wsprbands.dial_hz(band), when[2:10].replace("-", ""),
                when[11:16].replace(":", "")), armed=True)

    def _utc_now(self):
        import datetime as _dt
        return _dt.datetime.now(_dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")

    def _wspr_test_tone(self):
        """A steady tone for setting audio drive. Keys the radio.

        Behind the menu and a confirmation rather than under a key, because
        it transmits. The interlock and the inhibit both apply unchanged --
        this is a transmission like any other -- and it stops by itself,
        which is the property that matters most: a test tone is a
        transmitter left keyed.
        """
        import wsprtx
        # **The menu closes before any refusal is reported.** All three of
        # these wrote to `wspr_message`, which is drawn on the WSPR screen --
        # underneath the menu that was still open. From the operator's side
        # the key did nothing at all: "calibrate transmit audio does
        # nothing". The commonest case is the third, since the inhibit
        # starts on and cannot be lifted until the rig reads DATA-U.
        if self.wspr_running:
            self._close_menu()
            self._wspr_note("stop WSPR first — it owns the audio")
            return
        if not self._rig_mode_ok():
            self._close_menu()
            self._wspr_note("rig is not in a data mode — set DATA-U, "
                            "then calibrate")
            return
        if self.session.inhibited:
            self._close_menu()
            self._wspr_note("transmit is inhibited — Ctrl-B on the WSPR "
                            "screen arms it, once the rig reads DATA-U")
            return
        self._wspr_build()
        secs = int(wsprtx.TEST_TONE_S)
        watts, dbm, exact = self._wspr_power()
        self._ask_confirm(
            "TRANSMIT A TEST TONE",
            [f"{secs} seconds of carrier on {self.wspr_band}.",
             "",
             "Set the radio's drive so its power meter reads what",
             "the deck reports, and watch for the dBm to highlight.",
             "",
             f"Reading now: {watts or '?'} W"
             + (f" = {dbm} dBm{'' if exact else ' (snapped)'}"
                if dbm is not None else ""),
             "",
             "It stops by itself. Ctrl-C stops it sooner."],
            self._wspr_do_test_tone,
            back=WSPR,
            footer="Enter transmit   any other key does not")

    def _wspr_do_test_tone(self):
        why = self.wspr_tx.test_tone()
        self._wspr_note(f"test tone failed: {why}" if why
                        else "test tone transmitting")

    def _wspr_forget_all(self):
        """Take every WSPR session off the list. Destroys nothing."""
        import wsprlog
        path = wsprlog.log_path(self.cfg.get("WSPR_LOG_PATH", ""))
        try:
            records = wsprlog.read(path)
        except OSError as exc:
            self._wspr_note(f"could not read the spot log: {exc}")
            return
        pairs = [[s["name"], s["start"]]
                 for s in wsprlog.sessions_in(records)]
        if not pairs:
            self._wspr_note("the list is already empty")
            self._close_menu()
            return
        self.cfg["WSPR_FORGOTTEN"] = pairs
        self._save_state()
        self._close_menu()
        self._wspr_note(f"{len(pairs)} session"
                        f"{'' if len(pairs) == 1 else 's'} forgotten — "
                        f"every spot is still in the log")

    def _wspr_ask_clear_session(self):
        import wsprlog
        name = self.cfg.get("WSPR_SESSION", "")
        start = self.cfg.get("WSPR_SESSION_START", "")
        if not name:
            self._wspr_note("no session selected")
            self._close_menu()
            return
        path = wsprlog.log_path(self.cfg.get("WSPR_LOG_PATH", ""))
        heard, sent = wsprlog.counts(wsprlog.read(path), name, start)
        if not (heard or sent):
            self._wspr_note(f"{name} has no spots")
            self._close_menu()
            return
        self._ask_confirm(
            "DELETE THIS SESSION'S SPOTS",
            [f"{heard} heard and {sent} sent, from {name[:30]}.",
             "",
             "They are removed from the spot log permanently.",
             "Nothing on the deck can put them back.",
             "",
             "Anything already uploaded to wsprnet is not changed."],
            lambda n=name, t=start: self._wspr_clear_session(n, t),
            back=WSPR,
            footer="Enter delete them   any other key keeps them")

    def _wspr_clear_session(self, name, start):
        import wsprlog
        try:
            self._wspr_counts_stale()
            gone = wsprlog.remove_session(
                wsprlog.log_path(self.cfg.get("WSPR_LOG_PATH", "")),
                name, start)
        except OSError as exc:
            self._wspr_note(f"could not write the spot log: {exc}")
            return
        self.wspr_spots = []
        self.wspr_sel = None
        self._wspr_note(f"{gone} record{'' if gone == 1 else 's'} deleted "
                        f"from {name}")

    def _wspr_ask_clear_all(self):
        import wsprlog
        path = wsprlog.log_path(self.cfg.get("WSPR_LOG_PATH", ""))
        records = wsprlog.read(path)
        heard, sent = wsprlog.counts(records)
        if not records:
            self._wspr_note("the spot log is already empty")
            self._close_menu()
            return
        self._ask_confirm(
            "DELETE EVERY WSPR RECORD",
            [f"All {heard} heard and {sent} sent, across",
             f"{len(wsprlog.sessions_in(records))} session"
             f"{'' if len(wsprlog.sessions_in(records)) == 1 else 's'}.",
             "",
             "The spot log is left empty. Nothing on the deck",
             "can put any of them back.",
             "",
             "The contact log is a different file and is untouched."],
            self._wspr_clear_all,
            back=WSPR,
            footer="Enter empty it   any other key keeps it")

    def _wspr_clear_all(self):
        import wsprlog
        try:
            self._wspr_counts_stale()
            gone = wsprlog.clear(
                wsprlog.log_path(self.cfg.get("WSPR_LOG_PATH", "")))
        except OSError as exc:
            self._wspr_note(f"could not write the spot log: {exc}")
            return
        self.wspr_spots = []
        self.wspr_sel = None
        if self.cfg.get("WSPR_FORGOTTEN"):
            self.cfg["WSPR_FORGOTTEN"] = []
            self._save_state()
        self._wspr_note(f"spot log emptied — {gone} record"
                        f"{'' if gone == 1 else 's'} deleted")

    def _log_note(self, text):
        """A message about logging, shown on the logging screens only.

        NOT `session.note`. That writes into the keyboard-to-keyboard
        transcript, which is a record of what was said on the air, and
        housekeeping about activities, types and log files was never part of
        that conversation -- twenty of these were filling the transcript with
        lines nobody on the other end ever sent. Worse, they were invisible
        where they mattered: the log screen draws `log_message`, not the
        transcript, so a refusal raised here could not be read at the moment it
        was raised and could not be got rid of afterwards.

        The log screen is where the operator ends up, so `log_message` is always
        set. The picker and the activities list get it too when that is where
        the message was raised, because those screens cover the log screen and
        would otherwise show nothing.
        """
        self.log_message = text
        if self.screen in (FIELDS, ORDER):
            self.picker_message = text
        elif self.screen == ACTS:
            self.acts_message = text

    def _set_my_park(self, value):
        self.cfg["MY_PARK"] = (value or "").strip().upper()
        if self.log_form is not None:
            self.log_form.set("my_park", self.cfg["MY_PARK"])
        self._save_state()

    def _export_adif(self, lotw=False, session_only=False):
        """Write an ADIF beside the log, and say where.

        The whole log, or -- with `session_only` -- just the session being
        logged. There is one file either way: an activity is a label on
        records, so a per-activity export is a FILTER, and a filtered one
        cannot contain a stray contact that landed in the wrong file the way
        a per-activity file could.
        """
        path = self._log_path()
        records = qsolog.read(path)
        name = self._activity_name()
        if session_only and name:
            records = qsolog.for_session(records, name,
                                         self._activity_start())
        if not records:
            self._log_note("nothing logged yet" if not session_only
                           else f"nothing logged under {name or MASTER_LOG}")
            return
        out = qsolog.export_path(path)
        if session_only and name:
            # Beside the log, named for the session, so two activations of one
            # park do not overwrite each other's export.
            stem = qsolog.activity_slug(name) or "activity"
            day = (self._activity_start() or "")[:10]
            out = os.path.join(os.path.dirname(out),
                               f"{stem}{'_' + day if day else ''}.adi")
        try:
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(qsolog.adif_export(records))
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as exc:
            self._log_note(f"could not write {out}: {exc}")
            return
        self._log_note(f"{len(records)} contacts to {out}")
        if lotw:
            # Printed, never run. tqsl needs a callsign certificate and blocks
            # rather than failing without one, and a signing key does not
            # belong on a card that travels (qso_log_design.md §11).
            try:
                import lotw as lotwmod
                self._log_note("sign it with: " + lotwmod.quoted_command(
                    out, location=self.cfg.get("LOTW_LOCATION", ""),
                    upload=True))
            except Exception:
                pass

    def _screen_size(self):
        """(height, width), or the panel's own size when curses cannot say.

        The fallback is the deck's real geometry rather than a guess: this is
        called from key handling and from the touch poll, neither of which is
        handed the dimensions the way a draw is.
        """
        try:
            return self.scr.getmaxyx()
        except (AttributeError, curses.error):
            return 20, 66

    def _log_scroll_by(self, rows):
        """Move the contact list, clamped to what there is to show.

        Clamped against the same row count the renderer uses, so the list can
        never be scrolled to an offset that draws nothing -- which reads as a
        hang rather than as the end of the log.
        """
        form = self.log_form
        shown = self._log_shown() if form is not None else self.log_records
        h, w = self._screen_size()
        top = render.log_scroll_max(shown, h, form, w, self._log_lines())
        self.log_scroll = max(0, min(self.log_scroll + int(rows), top))
        return self.log_scroll

    def _activity_name(self):
        """The current activity: the session being logged, or "".

        An ACTIVITY is what the operator is doing -- this park, this contest
        weekend -- and it has a name they chose. An ACTIVITY TYPE is the
        template of fields it uses. Blank means casual logging, which is not
        an event and gets the default log file.
        """
        return str(self.cfg.get("ACTIVITY", "") or "").strip()

    def _log_path(self):
        """The log. There is one, whatever activity is in progress.

        An activity is a LABEL on records and the activity screen is a filter
        over this file -- see `docs/qso_log_design.md` §7f. There used to be a
        file per activity and a duplicated write into this one; what that
        bought was a per-activity export, which a filter gives for free, and
        what it cost was two writes to keep in step and two places to find a
        contact in when correcting one.
        """
        return qsolog.log_path(self.cfg.get("LOG_PATH", ""))

    def _activity_start(self):
        """The session this activity began at, or "" for the master log."""
        return str(self.cfg.get("ACTIVITY_START", "") or "").strip()

    def _forgotten(self):
        """Sessions the operator has deleted from the deck's list.

        A list of `[name, start]` pairs. The records keep their labels, so a
        list derived from the log would show a deleted session again the
        moment it was rebuilt -- this is what it is told to leave out.
        """
        out = []
        for pair in (self.cfg.get("FORGOTTEN_SESSIONS") or []):
            try:
                name, start = pair
            except (TypeError, ValueError):
                continue
            out.append((str(name), str(start)))
        return out

    def _set_activity_session(self, name, start=None):
        """Start a named activity, or resume one.

        `start` is the session key: an ISO timestamp pinned here and written
        onto every contact of the session, so a session is `(name, start)`.
        Passed when resuming one chosen from the list; stamped from the deck's
        clock -- a DS3231 that is right with no network, which is the point at
        a picnic table -- when starting a new one.

        Stamped ONCE and then carried, for the reason the log file's name used
        to be: an activation from 23:50 to 00:30 is one session, and anything
        derived from the contacts' own dates would split it at midnight.

        No file changes. There is one log and this only decides which records
        the screen is filtered to.
        """
        name = str(name or "").strip()
        if name and not qsolog.activity_slug(name):
            self._log_note("that name needs a letter or a digit in it")
            return
        leaving = self._activity_name()
        self.cfg["ACTIVITY"] = name
        if not name:
            self.cfg["ACTIVITY_START"] = ""
        elif start:
            self.cfg["ACTIVITY_START"] = str(start)
        else:
            self.cfg["ACTIVITY_START"] = datetime.datetime.now(
                datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Logging under a name again brings its sessions back -- which is what
        # the forget confirmation has always claimed and, until §7i, was not
        # true: the pair went onto a list nothing ever took it off. Matched on
        # the NAME, not the pair, because the operator types a name and "bring
        # back the park I worked last month" cannot mean one activation of it
        # and not another.
        if name:
            kept = [p for p in self._forgotten() if p[0] != name]
            if len(kept) != len(self.cfg.get("FORGOTTEN_SESSIONS") or []):
                self.cfg["FORGOTTEN_SESSIONS"] = [list(p) for p in kept]
        self._save_state()
        self._switch_log()
        if name != leaving:
            # What describes HOW this session is logged comes back with it --
            # §7i. Only on an actual change of activity, so re-selecting the
            # one already running does not undo a schema the operator has
            # just picked by hand.
            self._follow_activity(name)
        if not name:
            self._log_note(f"{MASTER_LOG} — {len(self.log_records)} contacts")
            return
        shown = len(self._log_shown())
        if shown:
            self._log_note(f"{name} resumed — {shown} contact"
                           f"{'' if shown == 1 else 's'}")
        else:
            self._log_note(f"{name} started")

    def _follow_activity(self, name):
        """Apply the schema and own-reference the session was logged under.

        An activity is a session, and the things that describe how it is being
        logged belong to it -- see §7i. They used to be independent global
        settings, so resuming last weekend's park activation left the operator
        logging it under whatever schema they happened to be using an hour
        before, with the park column gone and no field to type a reference in.

        Two cases keep what is already set rather than changing it:

        * **A session with nothing logged into it.** There is nothing to infer
          from, and guessing would undo the choice just made when the activity
          was named -- which is the choice the picker had only asked for a
          keystroke earlier.
        * **The master log.** It holds every contact under every schema there
          has ever been, so it has none of its own to restore.

        The reference is cleared on the way OUT of an activity either way.
        Keeping it is how contacts made after an activation ended went on
        claiming the park, which is a wrong reference in an exported ADIF and
        worse than a missing one.
        """
        if not name:
            # Leaving for the master log. The schema stays -- there is nothing
            # to restore -- but the reference goes, because this is not an
            # activation any more.
            if self.cfg.get("MY_PARK"):
                self._set_my_park("")
            return
        here = None
        for ses in qsolog.sessions_in(self.log_records, self._forgotten()):
            if ses["name"] == name and ses["start"] == self._activity_start():
                here = ses
                break
        if here is None:
            # A session with no contacts yet: a new activity, or one whose
            # contacts were all deleted. Nothing to follow.
            return
        # The reference FIRST, then the schema. `_set_activity_type` ends by
        # calling `_ask_my_park`, which opens an editor when the schema wants
        # a reference and none is set -- so setting the park afterwards left
        # that editor open over the log screen on every resume of a park
        # activation, asking for something the deck was about to fill in by
        # itself.
        if here["park"] != self.cfg.get("MY_PARK", ""):
            self._set_my_park(here["park"])
        # "" on the newest contact means GENERAL -- `make_record` writes no
        # `activity_type` for it -- so an empty type resolves to the built-in
        # rather than being treated as "unknown, leave it alone".
        want = here["type"] or "GENERAL"
        table = self._activity_table()
        if activities.get(want, table).name != \
                activities.get(self.cfg.get("ACTIVITY_TYPE") or "GENERAL",
                               table).name:
            self._set_activity_type(want, table)

    def _ask_confirm(self, title, lines, action, back=None, footer="",
                     cancel=None):
        """Put a destructive action behind one deliberate keystroke.

        Enter does it; Esc and every other key keep things as they are. The
        default is always to keep: the operator who hit the key by accident
        is the one this exists for.
        """
        destination = back or self.screen
        # The menu has to go, not just be covered. `draw` tests `self.menu`
        # before it tests `self.screen`, and so does the key dispatch -- so a
        # confirmation raised from inside a menu was never drawn AND its Enter
        # went to the menu handler instead of here. The question was invisible
        # and unanswerable, which is exactly how "delete does nothing" looks.
        self._close_menu()
        self.confirm = {"title": title, "lines": list(lines),
                        "action": action, "back": destination,
                        "footer": footer, "cancel": cancel}
        self.screen = CONFIRM

    def _draw_confirm(self, h, w):
        c = self.confirm or {}
        for i, line in enumerate(render.confirm_screen(
                c.get("title", "CONFIRM"), c.get("lines", ()), w, h,
                footer=c.get("footer", ""))):
            self._put(i, 0, line, w)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def _handle_confirm(self, ch):
        c = self.confirm or {}
        self.confirm = None
        self.screen = c.get("back") or CHAT
        action = c.get("action") if ch in (10, 13, curses.KEY_ENTER) \
            else c.get("cancel")
        if callable(action):
            action()
        return True

    def _activity_choices(self):
        """What the activities screen lists: the master log, then the rest.

        The master log is always first and is always there. Internally it is
        still "no activity" -- `ACTIVITY` empty, writing to the file `LOG_PATH`
        names -- and the row exists so that going back to it is a thing you can
        SELECT rather than something that happens to you when an activity is
        deleted. It carries `master=True`, which is what makes the delete
        refuse: there is no file of its own to remove, and every contact ever
        made is in it.
        """
        master = {"name": MASTER_LOG, "date": "", "start": "",
                  "master": True, "contacts": len(self.log_records)}
        rows = [master]
        for s in qsolog.sessions_in(self.log_records, self._forgotten()):
            rows.append({"name": s["name"], "start": s["start"],
                         # The date only: the key is a full timestamp so that
                         # two activations of one park on one day stay apart,
                         # and the time of day is not what tells them apart on
                         # a list the operator is reading.
                         "date": s["start"][:10] or s["last"][:10],
                         # The schema resuming it would apply -- §7i. Carried
                         # through rather than recomputed by the renderer,
                         # because the row and the resume have to agree about
                         # it or the list promises one thing and Enter does
                         # another.
                         "type": s["type"],
                         "contacts": s["contacts"], "master": False})

        # The session in progress, even with nothing logged into it yet. The
        # list is derived from RECORDS, so an activity named a moment ago has
        # no row -- and the header named it while the list did not, with no
        # way to select away from it or remove it. It looked stuck.
        #
        # Added rather than suppressed in the header: naming an activity and
        # then working the first contact into it is the normal order, so the
        # name is right and it is the LIST that was incomplete.
        here = self._activity_name()
        began = self._activity_start()
        if here and not any(r["name"] == here and r["start"] == began
                            for r in rows[1:]):
            # Nothing logged into it yet, so there is no contact to read a
            # schema off: the one in use IS what resuming it would keep.
            rows.insert(1, {"name": here, "start": began,
                            "date": began[:10], "contacts": 0,
                            "type": self.cfg.get("ACTIVITY_TYPE", ""),
                            "master": False})
        return rows

    def _resume_activity_master(self):
        """Back to the master log: no activity, the default file."""
        self._set_activity_session("")

    def _resume_activity(self, index):
        """Resume the activity at `index` in the list the menu showed."""
        rows = self._activity_choices()
        if not 0 <= index < len(rows):
            return
        row = rows[index]
        self._set_activity_session(row["name"], start=row.get("start", ""))

    def _open_activities(self):
        self.acts_sel = 0
        self.acts_message = ""
        self.screen = ACTS

    def _draw_activities(self, h, w):
        rows = self._activity_choices()
        if rows:
            self.acts_sel = max(0, min(self.acts_sel, len(rows) - 1))
        for i, line in enumerate(render.activity_screen(
                rows, self.acts_sel, w, h, current=self._activity_name(),
                message=self.acts_message)):
            self._put(i, 0, line, w)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def _draw_wspr(self, h, w):
        """The WSPR screen. No radio queries: `_radio_now` caches, and the
        power reading here comes through it."""
        import wsprbands
        import wsprlog
        import wsprnet
        import wsprsched
        now = time.time()
        watts, dbm, exact = self._wspr_power()
        sched = self.wspr
        # **Cached.** This read and parsed the whole spot log on every draw,
        # and the draw loop runs on every keypress -- so scrolling the list
        # re-parsed a file that grows all session, which is the lag an
        # operator reported on the arrows. The counts change only when a
        # spot is stored, the session changes, or the log is emptied, and
        # each of those drops the cache.
        heard, sent = self._wspr_counts()
        state = {
            "session": self.cfg.get("WSPR_SESSION", ""),
            "band": self.wspr_band,
            "dial_hz": wsprbands.dial_hz(self.wspr_band),
            "hopping": len(self._wspr_bands()) > 1,
            "hop_count": len(self._wspr_bands()),
            "clock": time.strftime("%H%MZ", time.gmtime()),
            # The slot clock runs off the same arithmetic the scheduler acts
            # on, not a second copy of it: what the operator watches and what
            # fires the capture cannot then disagree.
            "slot_in": (now - wsprsched.slot_start(now)
                        if sched and sched.wspr else None),
            "in_capture": wsprsched.in_capture(now),
            "slot_to_next": wsprsched.seconds_to_next_slot(now),
            "selected": self.wspr_sel,
            "wspr": bool(sched and sched.wspr),
            "decode": bool(sched and sched.decode),
            "transmit": bool(sched and sched.transmit),
            "tx_next": bool(sched and sched.tx_next),
            "next_tx": (sched.will_transmit(now + 120)
                        if sched and sched.wspr else None),
            "watts": watts, "dbm": dbm, "dbm_exact": exact,
            "ceiling": self.cfg.get("TX_POWER_MAX", 0),
            "heard": heard, "sent": sent,
            "upload": wsprnet.upload_state(
                self.cfg.get("WSPR_UPLOAD") == "yes", self._online(),
                self.wspr_running),
            "timeout_left": (sched.timeout_remaining(now)
                             if sched else None),
            "decoding": bool(self.wspr_rx and self.wspr_rx.busy_decoding),
            # The inhibit, which this screen did not show at all: transmit
            # was refused and nothing on screen said why.
            "inhibited": bool(self.session.inhibited),
            "tx_level": self.cfg.get("WSPR_TX_LEVEL", 50),
            "rx_gain": self.cfg.get("WSPR_RX_GAIN", 70),
            "dbfs": self.wspr_dbfs,
            "measuring": bool(self.wspr_rx and self.wspr_rx.busy_capturing),
        }
        # The arrows are advertised: a key that scrolls a list nobody knows
        # scrolls is a key that does not exist. Both forms fit 66 columns,
        # which is the panel.
        if self.wspr_sel is not None:
            # While a spot is selected the footer is about the list, because
            # that is what the keys are doing and because Esc releasing the
            # selection is the thing an operator cannot otherwise discover.
            footer = (" ↑↓ PgUp PgDn Home End move   Esc follow the newest"
                      "   ^B inhibit")
        else:
            # `^B inhibit` is advertised here because the interlock is the
            # one key an operator reaches for under time pressure, and it
            # moved off Tab -- so the key that used to work by accident now
            # has to be taught.
            footer = (" F1 menu F2 session F3 band ↑↓ spots "
                      "^B inhibit ^C stop" if self.wspr_running else
                      " F1 menu F2 session F3 band ↑↓ spots "
                      "^B inhibit ^O ^P")
        for i, line in enumerate(render.wspr_screen(
                self.wspr_spots, w, h, state=state,
                message=self.wspr_message, footer=footer)):
            self._put(i, 0, line, w)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def _wspr_counts(self):
        """`(heard, sent)` for the current session, from cache.

        Invalidated by `_wspr_counts_stale`, which every path that changes
        the log calls. A time-based cache was the alternative and is worse:
        it makes a spot that has just been logged take a second to appear in
        a counter that is sitting right next to it.
        """
        import wsprlog
        key = (self.cfg.get("WSPR_SESSION", ""),
               self.cfg.get("WSPR_SESSION_START", ""))
        if self._wspr_count_cache is not None \
                and self._wspr_count_key == key:
            return self._wspr_count_cache
        heard = sent = 0
        try:
            records = wsprlog.read(
                wsprlog.log_path(self.cfg.get("WSPR_LOG_PATH", "")))
            heard, sent = wsprlog.counts(records, key[0], key[1])
        except Exception:
            pass
        self._wspr_count_cache = (heard, sent)
        self._wspr_count_key = key
        return self._wspr_count_cache

    def _wspr_counts_stale(self):
        """Drop the cached counts. Called by anything that writes the log."""
        self._wspr_count_cache = None

    # -- the calibration screen -------------------------------------------
    #
    # A level set against a meter means watching a reading while pressing a
    # key, which a menu cannot do. `+` and `-` mean the same thing on both
    # halves; what differs is the instrument -- the radio's own power meter
    # for transmit, the deck's dBFS reading for receive.

    CAL_LEVELS = (5, 10, 15, 20, 25, 30, 35, 40, 50, 60, 75, 100)

    def _open_wspr_cal(self, kind):
        """Enter calibration. `kind` is "tx" or "rx"."""
        self._wspr_build()
        self.wspr_cal = kind
        self.wspr_cal_dbfs = None
        # Remembered BEFORE the menu is closed, so Esc out of calibration
        # goes back to the audio menu rather than all the way to the screen.
        self.wspr_cal_from = self.menu or ""
        self._close_menu()
        if kind == "rx":
            # The codec is already WSPR's: the menu refuses to open this
            # with WSPR off, so there is nothing to take here and nothing to
            # give back. One mechanism owns fldigi, which is `_wspr_start`.
            why = self.wspr_gain.apply(self.cfg.get("WSPR_RX_GAIN", 70))
            if why:
                self._wspr_note(f"capture gain: {why}")
        self.screen = WSPRCAL
        self._wspr_note("+ and - set the level" + (
            "; Enter sends a tone" if kind == "tx" else ""))

    def _close_wspr_cal(self):
        """Leave calibration, putting back whatever it took."""
        kind, self.wspr_cal = self.wspr_cal, ""
        if self.wspr_tx is not None:
            self.wspr_tx.stop()           # unkeys from any state
        if self.wspr_rx is not None:
            self.wspr_rx.stop_probe()
        # The gain is NOT restored here: the session still owns the codec
        # and the level the operator just set is the level it should run at.
        # `_wspr_stop` puts it back when the session ends.
        self.screen = WSPR
        back, self.wspr_cal_from = self.wspr_cal_from, ""
        if back:
            self._open_menu(back, remember=False)

    def _wspr_cal_step(self, up):
        """Move the level being calibrated one step."""
        tx = self.wspr_cal == "tx"
        setting = "WSPR_TX_LEVEL" if tx else "WSPR_RX_GAIN"
        order = list(self.CAL_LEVELS)
        now = int(self.cfg.get(setting, 50 if tx else 70))
        if now in order:
            at = order.index(now)
        else:
            at = min(range(len(order)), key=lambda i: abs(order[i] - now))
        at = max(0, min(len(order) - 1, at + (1 if up else -1)))
        nxt = order[at]
        if nxt == now:
            self._wspr_note("at the end of the range")
            return
        self.cfg[setting] = nxt
        self._save_state()
        if tx:
            if self.wspr_tx is not None:
                self.wspr_tx.level = nxt
                # **Re-sent at the new level if a tone is running.** The
                # audio is a rendered file, so changing the level mid-play
                # means playing a new one -- which from the operator's side
                # is what adjusting during the test looks like.
                if self.wspr_tx.keyed:
                    self.wspr_tx.stop()
                    self._wspr_cal_tone()
            self._wspr_note(f"TX audio level {nxt}%")
        else:
            note = f"RX capture gain {nxt}%"
            if self.wspr_gain is not None:
                why = self.wspr_gain.apply(nxt)
                if why:
                    note += f" — {why}"
            self._wspr_note(note)

    def _wspr_cal_tone(self):
        """Send a calibration tone. Longer than the menu's, to adjust under."""
        import wsprtx
        if not self._rig_mode_ok():
            self._wspr_note("rig is not in a data mode — no tone")
            return
        if self.session.inhibited:
            self._wspr_note("transmit is inhibited — Ctrl-B arms it")
            return
        why = self.wspr_tx.test_tone(seconds=wsprtx.CAL_TONE_S)
        if why:
            self._wspr_note(f"tone failed: {why}")

    def _wspr_cal_poll(self):
        """Keep the receive meter moving. Called from the draw loop."""
        if self.wspr_cal != "rx" or self.wspr_rx is None:
            return
        import wsprgain
        path = self.wspr_rx.probe_done()
        if path:
            level = wsprgain.level_of(path)
            self.wspr_cal_dbfs = level[2] if level else None
        if not self.wspr_rx.probing and not self.wspr_rx.busy_capturing:
            self.wspr_rx.start_probe()

    def _draw_wspr_cal(self, h, w):
        """The calibration screen."""
        self._wspr_cal_poll()
        if self.wspr_tx is not None:
            for event in self.wspr_tx.tick():
                if event[0] == "failed":
                    self._wspr_note(f"tone: {event[2]}")
        tx = self.wspr_cal == "tx"
        watts = dbm = exact = None
        fallback = False
        if tx:
            watts, dbm, exact = self._wspr_power()
        state = {
            "kind": "tx" if tx else "rx",
            "band": self.wspr_band,
            "level": self.cfg.get("WSPR_TX_LEVEL", 50) if tx
            else self.cfg.get("WSPR_RX_GAIN", 70),
            "watts": watts, "dbm": dbm, "dbm_exact": exact,
            "ceiling": self.cfg.get("TX_POWER_MAX", 0),
            "power_fallback": fallback,
            "keyed": bool(self.wspr_tx and self.wspr_tx.keyed),
            "listening": bool(self.wspr_rx and self.wspr_rx.probing),
            "dbfs": self.wspr_cal_dbfs,
        }
        footer = ("  + - level  Enter send a tone  ^B inhibit  ^C stop  "
                  "Esc back" if tx else
                  "  + - level   ^B inhibit   Esc back")
        for i, line in enumerate(render.wspr_cal_screen(
                w, h, state=state, message=self.wspr_message,
                footer=footer)):
            self._put(i, 0, line, w)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def _handle_wspr_cal(self, ch):
        key = chr(ch).lower() if 32 <= ch < 127 else ""
        # Both spellings of each: the console has no keypad distinction and
        # `=` is unshifted `+` on a small keyboard.
        if key in ("+", "=") or ch == curses.KEY_RIGHT:
            self._wspr_cal_step(True)
        elif key in ("-", "_") or ch == curses.KEY_LEFT:
            self._wspr_cal_step(False)
        elif ch == curses.KEY_UP:
            self._wspr_cal_step(True)
        elif ch == curses.KEY_DOWN:
            self._wspr_cal_step(False)
        elif ch in (10, 13, curses.KEY_ENTER):
            if self.wspr_cal == "tx":
                self._wspr_cal_tone()
        elif ch == 3:                                   # Ctrl-C
            # Aborting a transmission, which is exactly what Ctrl-C does on
            # the conversation screen.
            if self.wspr_tx is not None:
                self.wspr_tx.stop()
            self._wspr_note("stopped")
        elif ch == 27:                                  # Esc
            self._close_wspr_cal()
        return True

    def _wspr_move(self, by):
        """Move the spot selection. The list is newest first, so down is
        older -- the same direction the eye reads it.

        **Arrowing up off the top releases the selection**, which is how a
        list is left: it clamped at the newest spot instead, so the only way
        out was Esc and an operator arrowing back out of the list found the
        highlight stuck on the first row. Esc still works and the footer
        still says so; this is the gesture people actually try.
        """
        total = len(self.wspr_spots)
        if not total:
            self.wspr_sel = None
            return
        if self.wspr_sel is None:
            # Nothing selected: moving down takes the newest, moving up has
            # nothing above it to reach.
            if by > 0:
                self.wspr_sel = 0
            return
        at = self.wspr_sel + by
        if at < 0:
            self.wspr_sel = None
            self._wspr_note("following the newest spot again")
            return
        self.wspr_sel = min(total - 1, at)

    def _handle_wspr(self, ch):
        if ch == curses.KEY_F1:
            self._open_menu("wspr")
        elif ch == curses.KEY_F2:
            self._open_editor(None, "WSPR session name",
                              text=self.cfg.get("WSPR_SESSION", ""),
                              sink=self._wspr_set_session)
        elif ch == curses.KEY_F3:
            self._open_menu("wspr_band")
        elif ch == 3:                                   # Ctrl-C
            # **Ctrl-C, as in the digimodes.** It aborts an over there --
            # byte 3 reaches `getch` because `curses.raw()` disables ISIG,
            # which is why it is a key here and not a signal. Ctrl-X was
            # used first and was wrong: that key means CLEAR everywhere else
            # on the deck, on the transcript and on the entry form, and
            # making it mean "stop" in one application only is the kind of
            # inconsistency an operator pays for under pressure.
            if self.wspr_running:
                self._wspr_stop("stopped by hand")
            else:
                self._wspr_note("WSPR is not running")
        elif ch in (curses.KEY_UP, curses.KEY_DOWN):
            self._wspr_move(-1 if ch == curses.KEY_UP else 1)
        elif ch in (curses.KEY_PPAGE, curses.KEY_NPAGE):
            self._wspr_move(-8 if ch == curses.KEY_PPAGE else 8)
        elif ch == curses.KEY_HOME:
            self.wspr_sel = 0 if self.wspr_spots else None
        elif ch == curses.KEY_END:
            self.wspr_sel = (len(self.wspr_spots) - 1
                             if self.wspr_spots else None)
        elif ch == 27:                                  # Esc
            # **The selection is released FIRST, whether WSPR is running or
            # not.** Tested in the wrong order, the running check answered
            # every Esc with "^C stops it" and an operator who had scrolled
            # into the list could not get back out of it -- reported in
            # exactly those terms.
            if self.wspr_sel is not None:
                self.wspr_sel = None       # back to following the newest
                self._wspr_note("following the newest spot again")
            elif self.wspr_running:
                self._wspr_note("WSPR is running — ^C stops it")
            else:
                self.screen = WSPR
        return True

    def _wspr_ensure_session(self):
        """Give the session a name if it has none. Returns the name."""
        import wsprlog
        name = str(self.cfg.get("WSPR_SESSION", "") or "").strip()
        if not name:
            name = wsprlog.DEFAULT_SESSION
            self._wspr_counts_stale()
            self.cfg["WSPR_SESSION"] = name
            self.cfg["WSPR_SESSION_START"] = self._utc_now()
            self._save_state()
        elif not self.cfg.get("WSPR_SESSION_START"):
            # A name with no start cannot be told from another run under the
            # same name, which is what the start exists to separate.
            self.cfg["WSPR_SESSION_START"] = self._utc_now()
            self._save_state()
        return name

    def _wspr_set_session(self, name):
        """Name a WSPR session. The start is pinned here, as the log's is."""
        name = str(name or "").strip()
        import wsprlog
        self._wspr_counts_stale()
        # Clearing it means "back to the default run", not "no session":
        # spots keep belonging to something that can be exported and cleared.
        name = name or wsprlog.DEFAULT_SESSION
        self.cfg["WSPR_SESSION"] = name
        self.cfg["WSPR_SESSION_START"] = self._utc_now()
        self._save_state()
        self._wspr_note(f"session {name}")

    def _handle_activities(self, ch):
        rows = self._activity_choices()
        if ch == 27:
            self.screen = LOG if self.log_on else CHAT
        elif ch == curses.KEY_UP and rows:
            self.acts_sel = (self.acts_sel - 1) % len(rows)
        elif ch == curses.KEY_DOWN and rows:
            self.acts_sel = (self.acts_sel + 1) % len(rows)
        elif ch in (10, 13, curses.KEY_ENTER) and rows:
            if rows[self.acts_sel].get("master"):
                self._resume_activity_master()
            else:
                self._resume_activity(self.acts_sel)
            self.screen = LOG if self.log_on else CHAT
        elif ch in (ord("n"), ord("N")):
            self._open_editor(None, "Activity name",
                              sink=self._start_named_activity)
        elif ch in (ord("r"), ord("R")) and rows:
            row = rows[self.acts_sel]
            if row.get("master"):
                self.acts_message = (f"{MASTER_LOG} cannot be renamed — it is "
                                     f"every contact there is")
                return True
            # Prefilled with the name it has: a rename is almost always a
            # correction to one word of it, and retyping the rest is work the
            # screen can do.
            self._renaming = (row["name"], row.get("start", ""))
            self._open_editor(None, "New name", text=row["name"],
                              sink=self._rename_activity)
        elif ch in (ord("d"), ord("D")) and rows:
            row = rows[self.acts_sel]
            if row.get("master"):
                # The master log is every contact there is. An activity row is
                # removed to tidy the list; this is the list's whole subject.
                self.acts_message = (f"{MASTER_LOG} cannot be removed — it is "
                                     f"every contact there is")
                return True
            count = row["contacts"]
            # "Remove", not "delete", and the wording says what actually
            # happens. This used to delete a file and the contacts in it, so
            # "permanently deleted" was true; now the records keep their
            # labels and only the list forgets, so claiming otherwise would be
            # frightening an operator about something harmless -- and would
            # teach them to distrust the one confirmation that IS destructive,
            # which is deleting a single contact.
            self._ask_confirm(
                "REMOVE FROM THE LIST",
                [f"{row['name']}  {row['date'] or ''}".strip(),
                 "",
                 f"Its {count} contact{'' if count == 1 else 's'} stay in the "
                 f"log and keep this",
                 "name, so it can still be exported. Only the list",
                 "forgets it.",
                 "",
                 "Logging under the name again brings it back."],
                lambda name=row["name"], start=row.get("start", ""):
                    self._forget_session(name, start),
                back=ACTS,
                footer="Enter remove   any other key keeps it")
        return True

    def _rename_activity(self, new_name):
        """Rename the session picked on the activities screen.

        No confirmation: it destroys nothing, every contact keeps its
        `activity_start` so the session keeps its identity, and renaming back
        undoes it exactly. What it does get is a count, because an operator
        who renames the wrong row wants to know how many contacts moved.
        """
        name, start = getattr(self, "_renaming", ("", ""))
        self._renaming = ("", "")
        if not name:
            return
        new_name = str(new_name or "").strip()
        if not new_name or not qsolog.activity_slug(new_name):
            self.acts_message = "that name needs a letter or a digit in it"
            return
        if new_name == name:
            self.acts_message = f"{name} kept its name"
            return
        try:
            moved = qsolog.rename_session(self._log_path(), name, start,
                                          new_name)
        except OSError as exc:
            self.acts_message = f"could not write the log: {exc}"
            return
        # The session in progress is renamed with it, or the header would go
        # on naming an activity that no record carries any more.
        if name == self._activity_name() and start == self._activity_start():
            self.cfg["ACTIVITY"] = new_name
        # A forgotten pair under the old name can never match anything again,
        # so it would sit on the list for good; one under the NEW name would
        # hide the session that has just taken it.
        kept = [list(p) for p in self._forgotten()
                if p[0] not in (name, new_name)]
        self.cfg["FORGOTTEN_SESSIONS"] = kept
        self._save_state()
        self._switch_log()
        # ONE message, through `_log_note`, which sets `acts_message` itself
        # when the activities list is the screen. Setting that by hand first
        # and then calling the note simply overwrote it, so the count this
        # exists to report never reached the screen.
        self._log_note(f"{name} is now {new_name} — {moved} contact"
                       f"{'' if moved == 1 else 's'} relabeled")

    def _start_named_activity(self, name):
        """Name a new activity, then ask which type it uses.

        Naming it and dropping straight into the log screen left the type at
        whatever the last activity used, which is wrong more often than right:
        a new activity is usually new because the operating is different. So
        the type picker comes next, and that picker is also where a type can
        be copied or created -- the whole decision in one place.
        """
        self._set_activity_session(name)
        # A new activity is a new activation, so this station's own reference
        # is unknown until it is stated. Carrying the last one over would log
        # last week's park onto today's contacts without saying so, and the
        # type picker that comes next is what asks for the new one.
        if name and self.cfg.get("MY_PARK"):
            self._set_my_park("")
        # The log screen goes underneath first. The picker is a menu drawn over
        # whatever screen is current, and leaving the activities list there
        # means backing out of the picker lands on the list the operator has
        # already finished with.
        self.screen = LOG if self.log_on else CHAT
        if name:
            self._open_menu("activity")

    def _ask_forget_all_sessions(self):
        """Confirm, then empty the deck's list of activities.

        The gentlest of the three: no contact is touched. Every record keeps
        its `activity` and `activity_start`, so each session is still
        exportable by name and logging under one of those names again brings
        it back -- see `_forget_session`.
        """
        sessions = qsolog.sessions_in(self.log_records, self._forgotten())
        if not sessions:
            self._log_note("the list is already empty")
            self._close_menu()
            return
        self._ask_confirm(
            "FORGET ALL ACTIVITIES",
            [f"{len(sessions)} session{'' if len(sessions) == 1 else 's'} "
             f"leave the list.",
             "",
             "No contact is deleted. Every one keeps its activity",
             "label, so it still exports under that name, and",
             "logging under a name again brings it back.",
             "",
             f"The log keeps all {len(self.log_records)} contacts."],
            self._forget_all_sessions,
            back=LOG if self.log_on else CHAT,
            footer="Enter forget them   any other key keeps the list")

    def _forget_all_sessions(self):
        """Put every session on the forgotten list. Confirmed above."""
        pairs = [list(p) for p in self._forgotten()]
        known = {tuple(p) for p in pairs}
        for ses in qsolog.sessions_in(self.log_records, self._forgotten()):
            pair = (str(ses.get("name", "")), str(ses.get("start", "")))
            if pair not in known:
                known.add(pair)
                pairs.append(list(pair))
        self.cfg["FORGOTTEN_SESSIONS"] = pairs
        self._save_state()
        # Whatever was in progress is no longer in the list, so there is
        # nothing to log into: fall back to the master log, and drop the
        # reference with it for the reason `_forget_session` gives.
        if self._activity_name():
            self._set_activity_session("")
            if self.cfg.get("MY_PARK"):
                self._set_my_park("")
        self.acts_sel = 0
        self.acts_message = "the list is empty"
        self._log_note("all activities forgotten — every contact is still in "
                       "the log")

    def _ask_clear_session(self):
        """Confirm, then delete the contacts of the activity on screen.

        Deliberately the activity SHOWING, not one chosen from a list: the
        operator can see on the screen behind the question what it is about
        to empty.
        """
        name = self._activity_name()
        if not name:
            # 51 of 66. The quoted menu line made it 67 and it was cut at
            # `the whole lo`, which reads as a damaged screen.
            self._log_note("no activity selected — use Delete EVERY QSO")
            self._close_menu()
            return
        start = self._activity_start()
        doomed = len(self._log_shown())
        if not doomed:
            self._log_note(f"{name} has no contacts")
            self._close_menu()
            return
        self._ask_confirm(
            "DELETE THIS ACTIVITY'S QSOS",
            [f"{doomed} contact{'' if doomed == 1 else 's'} from {name}.",
             f"Session started {start[:10]} {start[11:19]}Z" if len(start) >= 19
             else "Every contact labeled with that name.",
             "",
             "They are removed from the log permanently. Nothing",
             "on the deck can put them back.",
             "",
             "An ADIF already exported is not changed."],
            lambda n=name, s=start: self._clear_session(n, s),
            back=LOG if self.log_on else CHAT,
            footer="Enter delete them   any other key keeps them")

    def _clear_session(self, name, start):
        """Remove one session's contacts. Confirmed above."""
        try:
            gone = qsolog.remove_session(self._log_path(), name, start)
        except OSError as exc:
            self._log_note(f"could not write the log: {exc}")
            return
        self._after_bulk_delete()
        self._log_note(f"{gone} contact{'' if gone == 1 else 's'} deleted "
                       f"from {name}")

    def _ask_clear_log(self):
        """Confirm, then empty the log. The whole log, every activity."""
        doomed = len(self.log_records)
        if not doomed:
            self._log_note("the log is already empty")
            self._close_menu()
            return
        sessions = qsolog.sessions_in(self.log_records)
        self._ask_confirm(
            "DELETE EVERY QSO",
            [f"All {doomed} contact{'' if doomed == 1 else 's'} in the log,",
             f"across {len(sessions)} "
             f"activit{'y' if len(sessions) == 1 else 'ies'} and the "
             f"unlabeled ones.",
             "",
             "The log is left empty. Nothing on the deck can put",
             "any of them back.",
             "",
             "An ADIF already exported is not changed."],
            self._clear_log,
            back=LOG if self.log_on else CHAT,
            footer="Enter empty the log   any other key keeps it")

    def _clear_log(self):
        """Empty the log. Confirmed above."""
        try:
            gone = qsolog.clear(self._log_path())
        except OSError as exc:
            self._log_note(f"could not write the log: {exc}")
            return
        # The forgotten list is a set of (name, start) pairs to leave OUT of a
        # list derived from the records. With no records there is nothing to
        # leave out, so keeping it would only accumulate dead pairs across
        # rounds of testing -- which is the job this screen exists for.
        if self.cfg.get("FORGOTTEN_SESSIONS"):
            self.cfg["FORGOTTEN_SESSIONS"] = []
            self._save_state()
        self._after_bulk_delete()
        self._log_note(f"log emptied — {gone} contact"
                       f"{'' if gone == 1 else 's'} deleted")

    def _after_bulk_delete(self):
        """Put the screen back in step with a log that just got shorter.

        The contact screen may be showing a record that no longer exists and
        the selection indexes a list that is now shorter or empty, so both go
        -- the same two things one deletion clears, for the same reason.
        """
        self.entry_rec = None
        self.entry_message = ""
        self.log_sel = None
        self.log_scroll = 0
        self._switch_log()

    def _forget_session(self, name, start):
        """Take a session off the deck's list. Changes no records.

        The contacts keep their `activity` and `activity_start`, so the
        session stays identifiable and exportable -- which is what makes
        "delete an activity and still have the contacts" a fact about where
        they are rather than a feature with a mechanism behind it.

        That is why this has to be remembered: a list derived from the log
        would show the session again the moment it was rebuilt. Reversible for
        the same reason, and a session logged into again comes back, because
        logging under a name says more than having dismissed it once did.
        """
        pairs = [list(p) for p in self._forgotten()]
        if [str(name), str(start)] not in pairs:
            pairs.append([str(name), str(start)])
        self.cfg["FORGOTTEN_SESSIONS"] = pairs
        self._save_state()
        self.acts_message = f"{name} removed from the list"
        self._log_note(f"{name} removed from the list — its contacts are "
                       f"still in the log")
        # If that was the session in progress there is nothing to log into any
        # more, so fall back to the master log. The reference goes with it: the
        # activation is over and `my_park` on the next contact would be wrong.
        # The SCHEMA stays -- POTA with no reference of your own is hunting.
        # Matched on the NAME, not on the name and the start together. A
        # session with no contacts has no derived start to compare against, so
        # insisting both match left the header naming an activity that had
        # just been removed from the list.
        if name == self._activity_name():
            self._set_activity_session("")
            if self.cfg.get("MY_PARK"):
                self._set_my_park("")
        self.acts_sel = 0

    def _delete_activity_type(self, name):
        """Remove one activity type from activities.conf."""
        ok, detail = activities.delete(activities.config_path(), name)
        self._log_note(detail)
        if not ok:
            return
        # The form may be built on the type that just went.
        table = self._activity_table()
        if self.log_form is not None and \
                self.log_form.activity_type.name == name.upper() and \
                name.upper() not in table:
            self._set_activity_type("GENERAL", table)

    def _log_name(self):
        """The log file's name, or "" when it is the default.

        Empty for the default so the header can leave it out: a name shown on
        every ordinary deck teaches nothing, and one shown only when it is
        unusual cannot be missed.
        """
        name = os.path.basename(self._log_path())
        return "" if name == "qso.log" else name

    def _switch_log(self):
        """Reopen the log after the file has changed underneath it."""
        path = self._log_path()
        try:
            self.log_records = qsolog.read(path)
        except OSError as exc:
            # A log that cannot be read must not take the screen with it: the
            # name is wrong, and the operator needs to be told and left able
            # to type another.
            self.log_records = []
            self._log_note(f"could not read {os.path.basename(path)}: {exc}")
            return
        self._looked_up = ""
        self.log_scroll = 0
        if self.log_form is not None:
            self.log_form.advance_serial(
                self.log_records, self.log_form.activity_type.serial_start,
                activity=self._activity_name())
        self._log_note(f"{os.path.basename(path)} — "
                          f"{len(self.log_records)} contact"
                          f"{'' if len(self.log_records) == 1 else 's'}")

    def _open_log(self):
        if not self.log_on:
            self.session.note("logging is off — switch it on from the menu")
            return
        path = self._log_path()
        if self.log_form is None:
            table = activities.load()
            act = activities.get(self.cfg.get("ACTIVITY_TYPE", ""), table)
            self.log_form = logform.LogForm(act)
            if self.cfg.get("MY_PARK"):
                self.log_form.set("my_park", self.cfg["MY_PARK"])
            if self.cfg.get("EXCHANGE_TX"):
                self.log_form.set("exchange_tx", self.cfg["EXCHANGE_TX"])
        self.log_records = qsolog.read(path)
        self.log_form.advance_serial(
            self.log_records, self.log_form.activity_type.serial_start,
            activity=self._activity_name())
        self.log_form.focus("call")
        self.log_message = ""
        self.screen = LOG

    def _log_commit(self):
        """Write the contact on the form, then ready it for the next."""
        form = self.log_form
        if form is None or not form.ready():
            self.log_message = "-- a callsign, at least"
            return
        values = form.collect()
        try:
            # The mode matters here even though only a callsign is parsed: it
            # picks the default reports. Passing "" logged 599 against an SSB
            # contact, because an activity whose form has no report fields --
            # a contest -- has nothing to correct the default afterwards.
            parsed = qsolog.parse_entry(values.get("call", ""),
                                        values.get("mode", ""))
        except qsolog.ParseError as exc:
            self.log_message = f"-- {exc}"
            return

        for key in ("rst_s", "rst_r", "name", "qth", "park", "serial_rx",
                    "exchange_rx", "comment"):
            if values.get(key):
                parsed[key] = values[key]

        watts = 0
        rig = self._log_rig()
        if rig is not None:
            try:
                watts = rig.power(max_watts=self.cfg.get("TX_POWER_MAX", 0))
            except Exception:
                watts = 0

        rec = qsolog.make_record(
            parsed, datetime.datetime.now(datetime.timezone.utc),
            freq_hz=self._log_freq_hz(), mode=values.get("mode", ""),
            my_call=self.cfg.get("CALLSIGN", ""),
            my_grid=self.cfg.get("LOCATOR", ""),
            my_park=values.get("my_park", ""), activity_type=form.activity_type,
            activity=self._activity_name(),
            activity_start=self._activity_start(),
            serial_tx=values.get("serial_tx", ""),
            exchange_tx=values.get("exchange_tx", ""),
            my_rig=self.cfg.get("RIG", ""),
            my_antenna=self.cfg.get("ANTENNA", ""),
            tx_power=watts or self.cfg.get("TX_POWER", 0))

        try:
            path = self._log_path()
            # An activity's log lives in a directory of its own that may not
            # exist yet. Created here rather than when the activity is named,
            # so naming one and never working a contact leaves nothing behind.
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            qsolog.append(path, rec)
        except OSError as exc:
            # The one failure that must never be quiet: the contact is gone,
            # and the form is left alone so it can be tried again.
            self.log_message = f"-- NOT LOGGED: {exc}"
            return

        self.log_records.append(rec)
        self._looked_up = ""
        form.commit()
        form.advance_serial(self.log_records,
                            form.activity_type.serial_start,
                            activity=self._activity_name())
        self.log_message = (f"-- logged {rec['call']} {rec.get('band', '')} "
                            f"{rec.get('mode', '')}").rstrip()

    def _handle_log(self, ch):
        form = self.log_form
        if form is None:
            self.screen = CHAT
            return True

        if ch == 27:                                    # Esc
            # Esc backs out WITHIN the logging application and stops at its
            # top screen. It does not cross into another one.
            #
            # It used to go to the conversation, which made sense when the log
            # hung off the digimode screen and stopped making sense the moment
            # the three became peers: there is no "up" from here to go to, and
            # ejecting an operator into a different application for pressing
            # the back key is not backing out of anything. ^O and ^P are how
            # you leave; Esc is how you put down whatever you picked up.
            if self.log_sel is not None:
                self.log_sel = None
                self.log_message = ""
            else:
                self.log_message = ""
        # The function keys are otherwise dead here, and F1 means "menu"
        # everywhere else on the deck. It opens the LOGGING menu rather than
        # the root one, because that is what is being configured from this
        # screen; the root menu is one Esc away from it.
        elif ch == curses.KEY_F1:
            self._open_menu("logging")
        # F2 is the activities list: start one, resume one, delete one. On
        # this screen the function keys were dead and F1 was given the menu;
        # the activity is the thing changed often enough to deserve the next
        # one rather than two keystrokes through a menu.
        elif ch == curses.KEY_F2:
            self._open_activities()
        # F3 is the activity TYPE, pairing with F2's activity the way the
        # digimode screen pairs F2's tuner with F3's mode picker: on every
        # area, F2 and F3 are that area's two main sub-views. It also stops
        # the type picker being two keystrokes down a menu, which is where the
        # whole create-and-copy flow now lives.
        elif ch == curses.KEY_F3:
            self._open_menu("activity")
        elif ch == 9:                                   # Tab
            # Leaving the callsign is the moment it is worth asking about.
            if form.current is not None and form.current.name == "call":
                self._lookup_start(form.value("call"))
            form.tab()
            self.log_message = ""
        elif ch in (curses.KEY_BTAB, 353):              # Shift-Tab
            form.tab(back=True)
            self.log_message = ""
        elif ch in (10, 13, curses.KEY_ENTER):
            # With a contact picked, Enter opens it. Not hidden state: the row
            # is reversed and the footer says "Enter open" rather than
            # "Enter log" exactly when this is true.
            if self.log_sel is not None:
                self._open_entry()
            else:
                self._log_commit()
        # Ctrl-Z is 26 over SSH and KEY_SUSPEND on the panel, because
        # TERM=linux defines kspd=^Z and ncurses consumes the byte. Matching
        # only 26 ships dead on the deck — that happened here once already,
        # with the memory-insert undo.
        elif ch in (26, curses.KEY_SUSPEND):            # Ctrl-Z
            self.log_message = ("" if form.restore()
                                else "-- nothing to put back here")
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            form.backspace()
        elif ch == curses.KEY_DC:
            form.delete()
        elif ch == 21:                                  # Ctrl-U
            form.kill()
        # Ctrl-X means "clear what is on this screen" on the conversation
        # screen too, where it empties the transcript. Here it throws away the
        # staged contact and keeps the park, exchange, comment and frequency,
        # which describe the session rather than the station.
        elif ch == 24:                                  # Ctrl-X
            if form.clear():
                self._looked_up = ""
                self.log_message = "-- entry cleared"
            else:
                self.log_message = "-- nothing staged to clear"
        # Both drop the selection first, for the same reason typing does: the
        # operator has gone back to the form, and leaving a contact picked
        # would leave Enter meaning "open that" while they were filling in a
        # new contact.
        elif ch == curses.KEY_LEFT:
            self.log_sel = None
            form.tab(back=True)
            self.log_message = ""
        elif ch == curses.KEY_RIGHT:
            self.log_sel = None
            form.tab()
            self.log_message = ""
        elif ch == curses.KEY_HOME:
            form.home()
        elif ch == curses.KEY_END:
            form.end()
        # The arrows pick a logged contact; Tab and Shift-Tab move between
        # fields, which is what they already did. The arrows were a second,
        # redundant way to do the same thing, so reading back and correcting
        # what is already logged had no keys at all.
        elif ch == curses.KEY_UP:
            if not self._log_pick(-1):
                form.tab(back=True)
        elif ch == curses.KEY_DOWN:
            if self.log_sel is None:
                form.tab()
            elif self.log_sel >= len(self._log_shown()) - 1:
                # Off the bottom of the list is back into the form, which is
                # where the form IS -- below the contacts. Clamping on the last
                # contact left the only way back a key that means something
                # else (Esc, or typing), on a screen whose whole arrangement
                # says down is towards the entry fields.
                self.log_sel = None
                self.log_message = ""
            else:
                self._log_pick(+1)
        # The list, not the form. The arrows move between fields, so paging
        # is what is left -- and a touchscreen gesture should not be the only
        # way to reach a contact from an hour ago.
        elif ch in (curses.KEY_PPAGE, curses.KEY_NPAGE):
            h, w = self._screen_size()
            page = max(1, render.log_body_rows(
                h, form, w, self._log_lines()) - 1)
            self._log_scroll_by(page if ch == curses.KEY_PPAGE else -page)
        elif 32 <= ch < 127:
            # Typing always goes to the form, and drops the selection on the
            # way. An operator who nudged an arrow and then started a callsign
            # must not lose the first letter of it.
            self.log_sel = None
            # The previous contact's receipt stops applying the moment the next
            # one is being typed. Leaving it up suppressed the duplicate
            # warning on the contact now being entered, which is the one
            # message on this screen that changes what the operator does.
            self.log_message = ""
            form.type(chr(ch))
            # "-- logged W3ABC" is about the contact just finished and goes
            # stale the moment the next one is started. Clearing it here is
            # also what lets the duplicate alert be seen: the alert only
            # fills a message line nobody else is using.
            self.log_message = ""
        return True

    def _draw_wifi(self, h, w):
        self._wifi_tick += 1
        lines = render.wifi_screen(
            self.wifi_state, self.wifi_nets, w, h,
            radio=self.wifi_radio, selected=self.wifi_sel,
            message=self.wifi_message, error=self.wifi_error,
            # Divided down so the working dots move at a readable rate rather
            # than five times a second.
            tick=self._wifi_tick // 3,
            ssid=self.wifi_joined if self.wifi_state == "joined" else self.wifi_target,
            retry=self._wifi_can_retry())
        for i, line in enumerate(lines):
            self._put(i, 0, line, w)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def _wifi_can_retry(self):
        """Retrying means retyping a passphrase, so an open network has
        nothing to retry with and the offer would be a dead key."""
        return bool(self.wifi_state == "failed" and self.wifi_target
                    and self.wifi_target_secured)

    def _handle_wifi(self, ch):
        key = chr(ch).lower() if 32 <= ch < 127 else ""
        nets = self.wifi_nets

        if ch == 27 or ch == curses.KEY_F1:
            if self.wifi_state in ("joined", "failed"):
                self.wifi_state = "list"
                self.wifi_error = ""
            elif self.wifi_state == "working":
                self.wifi_op.cancel() if self.wifi_op else None
                self.wifi_op = None
                self.wifi_state = "list"
            else:
                self._close_wifi()
            return True
        if self.wifi_state in ("working", "unavailable"):
            return True
        if self.wifi_state == "failed":
            if ch in (10, 13, curses.KEY_ENTER) and self._wifi_can_retry():
                # Whatever is saved for it is wrong, or we would not be here.
                # Removing it first means the new passphrase is used rather
                # than the stored one being tried again.
                self._wifi.forget(self.wifi_target)
                self._ask_passphrase(self.wifi_target)
                return True
            self.wifi_state = "list"
            self.wifi_error = ""
            self._wifi_refresh()
            return True
        if self.wifi_state == "joined":
            self.wifi_state = "list"
            self.wifi_error = ""
            return True

        if ch == curses.KEY_UP and nets:
            self.wifi_sel = (self.wifi_sel - 1) % len(nets)
        elif ch == curses.KEY_DOWN and nets:
            self.wifi_sel = (self.wifi_sel + 1) % len(nets)
        elif ch in (10, 13, curses.KEY_ENTER):
            self._wifi_join(self.wifi_sel)
        elif key.isdigit() and key != "0":
            self._wifi_join(int(key) - 1)
        elif key == "r":
            on = self.wifi_radio != "on"
            ok, err = self._wifi.set_radio(on)
            self.wifi_error = "" if ok else err
            self.wifi_radio = self._wifi.radio()
            self.session.note("wifi radio " + ("on" if on else "off"))
            self._wifi_refresh()
        elif key == "s":
            self._wifi_refresh(rescan=True)
        elif key == "n":
            self._ask_hidden_ssid()
        elif key == "f" and nets:
            net = nets[self.wifi_sel]
            if net.known:
                ok, err = self._wifi.forget(net.ssid)
                self.wifi_error = "" if ok else err
                if ok:
                    self.session.note(f"forgot {net.ssid}")
                self._wifi_refresh()
            else:
                self.wifi_error = "nothing saved for that network"
        elif ch == 17:                       # Ctrl-Q still quits
            return False
        return True

    def _persist_settled(self):
        """Write the mode and carrier once they have stopped changing.

        `_save_state` used to run only from menu actions, so the file held
        whatever happened to be true at the last colour change or memory edit
        — a snapshot of an unrelated moment. Tuning with the search and nudge
        keys never triggered it at all, so a deck tuned to 1500 and restarted
        came back on a carrier from an hour earlier, and a mode to match. It
        looked like the restore was broken; it was recording the wrong instant.

        Settling rather than saving on every change is what keeps this off the
        card: the carrier moves continuously while a signal is being hunted,
        and only where it comes to rest is worth remembering.
        """
        if not self.fldigi.connected:
            return
        # Before the remembered state has been restored there is nothing on
        # screen worth recording, and recording it destroys what is on the
        # card. With _saved_mode still None, the first reading after a cold
        # boot always differs, so ten seconds later the mode fldigi happened
        # to start in was written over the mode the operator chose. That is
        # what made "it comes back in CW" permanent rather than merely
        # annoying: every power cycle overwrote the file.
        if not self._startup_done:
            return
        mode, carrier = self.fldigi.modem(), self.fldigi.carrier()
        if not mode or not carrier:
            return
        if (mode, carrier) == (self._saved_mode, self._saved_carrier):
            return
        if time.monotonic() - self._saved_at < STATE_SETTLE_S:
            return
        self._save_state()

    def _watch_drain(self, sending):
        """Say something when the radio is still keyed long after a hand back.

        `Ctrl-Y` does not unkey the radio. It appends fldigi's "receive after
        the buffer" mark, and everything already composed still has to go out
        — at 31 baud a long over legitimately takes minutes. So a slow drain
        is not a fault and must not be aborted on a timer.

        What is a fault is a drain that never ends: the mark was lost to a
        failed call, or fldigi is wedged. The two look identical from here for
        the first minute, so this does not guess. It reports, at widening
        intervals, that the transmitter is still running and says which key
        stops it. TX_TIMEOUT remains the thing that actually intervenes, and
        it now stays armed across the drain rather than being disarmed by the
        hand back.
        """
        if self._handed_at is None:
            return
        if not sending:
            self._handed_at = None
            self._drain_warned = 0.0
            return
        waited = time.monotonic() - self._handed_at
        if waited < DRAIN_NOTICE_S:
            return
        # Every DRAIN_NOTICE_S, not every poll: five notices a second would
        # bury the transcript the operator needs to read.
        if waited - self._drain_warned < DRAIN_NOTICE_S:
            return
        self._drain_warned = waited
        self.session.note(f"still transmitting {int(waited)}s after hand back "
                          f"— Ctrl-C drops the carrier")

    def _settling_after_over(self, sending):
        """True while decodes arriving after an over should be discarded.

        RTTY is the mode that needs this. Baudot has no error detection at
        all — five bits between a start and a stop bit — so any noise that
        fits the frame decodes as a character. When PTT drops the receiver
        unmutes and the AGC recovers, and the modem turns that transient into
        text. It is real audio and fldigi is right to decode it; it is simply
        not anybody's transmission. The tail of our own echo lands in the same
        window.

        A fixed timer is the obvious instrument and the wrong one on its own.
        Long enough to cover the transient on a quiet band is long enough to
        swallow the opening characters of a fast reply in a contest, and a
        timer cannot tell those apart. So the timer is only the floor:

        * below ``RX_HOLD_MS``, always discard — at PTT drop even the quality
          metric is still settling, so there is nothing trustworthy to gate on;
        * after that, discard until the modem reports a real signal on two
          consecutive polls. A decaying transient does not sustain; a
          correspondent answering does;
        * give up at ``RX_HOLD_MAX_MS``, so a band with nothing on it returns
          to normal behavior instead of blanking indefinitely.

        ``RX_HOLD_MAX_MS = 0`` disables the quality gate and leaves exactly the
        fixed ``RX_HOLD_MS`` window, which is what this did before.

        Nothing is cleared. ``poll_rx()`` drains and this discards, so the
        chunk delivered on release holds only what arrived since the last
        poll. Calling ``clear_rx()`` on release would throw away the opening
        of the very reply that ended the hold.
        """
        if not self._settling or sending:
            return False

        elapsed = time.monotonic() - self._tx_ended
        floor = self.cfg.get("RX_HOLD_MS", 0) / 1000.0
        ceiling = self.cfg.get("RX_HOLD_MAX_MS", 0) / 1000.0

        if elapsed < floor:
            return True
        if ceiling <= 0 or elapsed >= ceiling:
            self._settling = False
            return False

        # fldigi's squelch level is the operator's own statement of what
        # counts as a signal here, so it is the right threshold when squelch
        # is on. With squelch off no such statement exists and a constant
        # stands in. Either way the transient has to hold above it rather than
        # merely touch it, which is what the consecutive-poll count is for.
        threshold = (self.fldigi.squelch_level() if self.fldigi.squelch()
                     else SETTLE_QUALITY)
        if self.fldigi.quality() >= threshold:
            self._settle_good += 1
        else:
            self._settle_good = 0
        if self._settle_good >= SETTLE_POLLS:
            self._settling = False
            return False
        return True

    # -- rendering ---------------------------------------------------------

    def status_fields(self):
        f = self.fldigi
        freq = f.frequency()
        # fldigi's state, not the session's. The session says what the
        # operator asked for; only the radio knows whether it is keyed. After
        # Ctrl-Y the session is in RX while the transmitter is still draining,
        # and showing RX there told the operator the radio was silent while it
        # was on the air. DRAIN names that window rather than hiding it.
        keyed = self._fldigi_sending
        if keyed and self.session.state == TX:
            state = "TX"
        elif keyed:
            state = "DRAIN"
        elif self.session.inhibited:
            state = "INH"
        else:
            state = "RX"
        if not f.connected:
            state = "NO MODEM"
        return {
            "call": self.cfg["CALLSIGN"] or "NO CALL",
            # Three decimals is how a frequency is read aloud and written
            # in a log: 14.070, not 14.07.
            "freq": render.frequency(freq),
            # Not `f.modem()` alone. fldigi always has a modem loaded, so the
            # status line said BPSK31 while the radio sat in USB for voice —
            # which is the one reading an operator checks before speaking.
            #
            # The rule, the same one `qsolog.resolve_mode` applies to the log:
            # a radio in a data mode means the modem is what is on the air, so
            # report the modem; a radio in anything else is being used for
            # that, so report the radio. A mode that cannot be read falls back
            # to the modem, because a deck without CAT has nothing else.
            "mode": self._shown_mode(),
            "carrier": f"{f.carrier()}Hz",
            "snr": (f.signal_to_noise() or "").strip(),
            "imd": (f.imd() or "").strip(),
            "state": state,
            "clock": time.strftime("%H%M", time.gmtime()) + "Z",
        }

    def draw(self):
        scr = self.scr
        scr.erase()
        h, w = scr.getmaxyx()
        if h < 8 or w < 30:
            self._put(0, 0, [("terminal too small", "bright")], w)
            scr.refresh()
            return

        if self.edit is not None:
            self._draw_edit(h, w)
        elif self.menu:
            self._draw_menu(h, w)
        elif self.screen == NOKB:
            self._nokb_tick += 1
            for i, line in enumerate(render.no_keyboard_screen(
                    self._nokb_bonded, w, h, tick=self._nokb_tick // 4,
                    can_pair=self._nokb_can_pair)):
                self._put(i, 0, line, w)
            try:
                curses.curs_set(0)
            except curses.error:
                pass
        elif self.screen == PAIR:
            self._draw_pair(h, w)
        elif self.screen == WIFI:
            self._draw_wifi(h, w)
        elif self.screen == LOG:
            self._draw_log(h, w)
        elif self.screen == FIELDS:
            self._draw_fields(h, w)
        elif self.screen == ORDER:
            self._draw_order(h, w)
        elif self.screen == ENTRY:
            self._draw_entry(h, w)
        elif self.screen == SET:
            self._draw_settings(h, w)
        elif self.screen == WSPRCAL:
            self._draw_wspr_cal(h, w)
        elif self.screen == WSPR:
            self._draw_wspr(h, w)
        elif self.screen == ACTS:
            self._draw_activities(h, w)
        elif self.screen == CONFIRM:
            self._draw_confirm(h, w)
        elif self.screen == TUNE:
            self._draw_tune(h, w)
        else:
            self._draw_chat(h, w)
        scr.refresh()

    def _draw_chat(self, h, w):
        compose_h = 2
        body_h = h - 1 - 1 - 1 - compose_h - 1   # status, rule, rule, compose, hints

        self._put(0, 0, render.status_line(self.status_fields(), w), w)
        self._put(1, 0, render.rule(w), w)

        entries = self.session.entries
        if self._tx_seen and self._tx_echo:
            # A transient line showing what fldigi has actually put on the air
            # so far, under the over as typed. Not part of the session: it is
            # gone the moment the over completes.
            entries = list(entries) + [Entry("TX", self._tx_echo)]
        lines = render.transcript_lines(
            entries, w, body_h,
            timestamps=self.cfg["TIMESTAMPS"] == "yes", scroll=self.scroll)
        for i, line in enumerate(lines):
            self._put(2 + i, 0, line, w)

        rule_row = 2 + body_h
        self._put(rule_row, 0, render.rule(w), w)

        clines, (crow, ccol) = render.compose_lines(
            self.session.compose, self.session.buffer_indicator(), w, compose_h,
            cursor=self.session.cursor)
        for i, line in enumerate(clines):
            self._put(rule_row + 1 + i, 0, line, w)

        self._put(h - 1, 0, render.hint_line(w), w)
        try:
            self.scr.move(rule_row + 1 + crow, ccol)
        except curses.error:
            pass

    def _draw_tune(self, h, w):
        f = self.fldigi
        self._put(0, 0, render.status_line(
            {**self.status_fields(), "call": "TUNING"}, w), w)
        self._put(1, 0, render.rule(w), w)

        rows = render.tune_rows({
            "freq": render.frequency(f.frequency()),
            "rig_mode": self._rig_mode_held(f.rig_mode()),
            "carrier": f.carrier(),
            "width": render.mode_bandwidth(f.modem(), f.bandwidth()),
            "snr": f.signal_to_noise(),
            "imd": f.imd(),
            "quality": f.quality(),
            "afc": f.afc(),
            "squelch": f.squelch(),
            "squelch_level": f.squelch_level(),
            "rsid": f.rsid(),
            "txid": f.txid(),
            "reverse": f.reverse(),
            "preview": self._rx_tail,
            "note": self.session.last_note,
        }, w)
        for i, text in enumerate(rows):
            if 2 + i < h - 4:
                self._put(2 + i, 0, [(text[:w - 1], "bright")], w)

        self._put(h - 4, 0, render.rule(w), w)
        for i, hint in enumerate(render.TUNE_HINTS):
            self._put(h - 3 + i, 0, [(hint[:w - 1], "dim")], w)

    def _menu_for(self, which, w, h):
        """The menu structure for a name, for navigation and hit-testing."""
        saved, self.menu = self.menu, which
        try:
            return self._current_menu(w, h)
        finally:
            self.menu = saved

    def _current_menu(self, w, h):
        f, m = self.fldigi, self.menu
        if m in ("digi", "root"):
            return menus.DIGI
        if m == "deck":
            return menus.DECK
        if m == "display":
            return menus.DISPLAY
        if m == "tuning":
            return menus.tuning_menu(f.afc(), f.squelch(), f.squelch_level(),
                                     f.rsid(), f.txid(), f.reverse(),
                                     self.cfg.get("RX_HOLD_MS", 0),
                                     self.cfg.get("RX_HOLD_MAX_MS", 0))
        if m == "radio":
            return menus.band_menu(self._supported_bands())
        if m == "system":
            return menus.SYSTEM
        if m == "memories":
            return menus.memories_menu(self.cfg)
        if m == "wspr":
            import wsprlog
            import wsprnet
            # Through the cache: `_menu_for` runs on every keypress while
            # the menu is open, so a read here is the same lag the draw loop
            # had on the arrows.
            heard, sent = self._wspr_counts()
            bands = self._wspr_bands()
            sched = self.wspr
            return menus.wspr_menu({
                "wspr": bool(sched and sched.wspr),
                "decode": bool(sched and sched.decode),
                "transmit": bool(sched and sched.transmit),
                "tx_next": bool(sched and sched.tx_next),
                "session": self.cfg.get("WSPR_SESSION", ""),
                "band": self.wspr_band or (bands[0] if bands else ""),
                "hopping": len(bands) > 1, "hop_count": len(bands),
                "tx_percent": self.cfg.get("WSPR_TX_PERCENT", 20),
                "timeout_minutes": self.cfg.get("WSPR_TIMEOUT_MIN", 60),
                "tx_level": self.cfg.get("WSPR_TX_LEVEL", 50),
                "rx_gain": self.cfg.get("WSPR_RX_GAIN", 70),
                "dbfs": self.wspr_dbfs,
                "upload": menus and wsprnet.upload_state(
                    self.cfg.get("WSPR_UPLOAD") == "yes", self._online(),
                    self.wspr_running),
                "log_name": os.path.basename(wsprlog.log_path(
                    self.cfg.get("WSPR_LOG_PATH", ""))),
                "heard": heard, "sent": sent,
            })
        if m == "wspr_band":
            return menus.wspr_band_menu(self._wspr_bands(), self.wspr_band)
        if m == "wspr_audio":
            return menus.wspr_audio_menu({
                "tx_level": self.cfg.get("WSPR_TX_LEVEL", 50),
                "rx_gain": self.cfg.get("WSPR_RX_GAIN", 70),
                "dbfs": self.wspr_dbfs})
        if m == "wspr_danger":
            import wsprlog
            try:
                records = wsprlog.read(wsprlog.log_path(
                    self.cfg.get("WSPR_LOG_PATH", "")))
            except Exception:
                records = []
            heard, sent = wsprlog.counts(
                records, self.cfg.get("WSPR_SESSION", ""),
                self.cfg.get("WSPR_SESSION_START", ""))
            all_heard, all_sent = wsprlog.counts(records)
            return menus.wspr_danger_menu(
                session=self.cfg.get("WSPR_SESSION", ""),
                heard=heard, sent=sent, total_heard=all_heard,
                total_sent=all_sent,
                sessions=len(wsprlog.sessions_in(records)))
        if m == "danger":
            return menus.danger_menu(
                activity=self._activity_name(),
                contacts=len(self.log_records),
                session=len(self._log_shown()) if self._activity_name() else 0,
                sessions=len(qsolog.sessions_in(self.log_records,
                                                self._forgotten())))
        if m == "logging":
            act = (self.log_form.activity_type.name if self.log_form
                   else self.cfg.get("ACTIVITY_TYPE", ""))
            park = (self.log_form.value("my_park") if self.log_form
                    else self.cfg.get("MY_PARK", ""))
            return menus.log_menu(
                self.log_on, count=len(self.log_records), park=park,
                lookup=self.cfg.get("CALLBOOK") == "yes",
                has_qrz_key=bool(self.cfg.get("QRZ_API_KEY")),
                operating=self.cfg.get("OPERATING", "auto"),
                dupe=self.cfg.get("DUPE_CHECK", "band+mode"),
                has_tqsl=self._has_tqsl(),
                log_name=os.path.basename(
                    qsolog.log_path(self.cfg.get("LOG_PATH", ""))),
                callbook_state=self._callbook_state(),
                activity=self._activity_name() or MASTER_LOG,
                activity_type="" if act == "GENERAL" else act,
                log_lines=self._log_lines())
        if m == "activity":
            table = self._activity_table()
            current = (self.log_form.activity_type.name if self.log_form
                       else self.cfg.get("ACTIVITY_TYPE", ""))
            return menus.activity_type_menu(
                sorted(table), current, {n: table[n].label for n in table})
        if m == "mode":
            return menus.mode_menu(f.modem(), auto=f.rsid())
        if m == "modes_all":
            menu, self.menu_page, _, self._page_keys = menus.paged_menu(
                "ALL MODES", menus.keyboard_modes(f.modem_names()),
                self.menu_page, w, h)
            return menu
        return menus.ROOT

    def _draw_menu(self, h, w):
        menu = self._current_menu(w, h)
        for i, line in enumerate(menus.render(menu, w, h, self.menu_sel)):
            self._put(i, 0, line, w)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def _put(self, row, col, segments, width):
        x = col
        for text, kind in segments:
            if x >= width:
                break
            chunk = text[:width - x]
            try:
                self.scr.addstr(row, x, chunk, colors.attr(kind))
            except curses.error:
                pass
            x += len(chunk)

    # -- keyboard ----------------------------------------------------------

    def handle(self, ch):
        """Returns False to quit."""
        if ch == -1:
            return True

        # The console can change size after curses has started — a late
        # setfont, or the panel settling at boot. ncurses keeps the size it
        # first saw unless told, so every wrap width stays wrong and text
        # breaks early for the life of the process.
        if ch == curses.KEY_RESIZE:
            try:
                curses.update_lines_cols()
            except (AttributeError, curses.error):
                pass
            self.scr.clearok(True)
            return True

        if self.edit is not None:
            return self._handle_edit(ch)

        # The color scheme, from anywhere. It was bound once, on the fallthrough
        # below the screen handlers, which meant it worked on the conversation
        # and was a dead key on the log, the activities list, the pickers, the
        # tune screen and inside every menu. Changing the scheme is a decision
        # about the light in the room rather than about the screen in front of
        # you, so it belongs to no one screen.
        #
        # Before the menu and screen handlers so they cannot shadow it, and
        # after the editor so it cannot interrupt typing. Inside a menu as
        # well: the settings tree is one of the three places this was asked
        # for, and no menu binds F4. Two screens keep it out -- a confirmation,
        # where a keystroke already means "no", and the no-keyboard notice,
        # where a keystroke arriving IS the answer.
        if ch == curses.KEY_F4 and self.screen not in (CONFIRM, NOKB):
            self._apply_scheme(colors.cycle(self.scheme))
            return True

        # The area ring. After the editor and the modal screens, so a question
        # being answered or a field being typed cannot be cycled away from and
        # silently discarded; before the per-screen handlers, so no screen can
        # shadow it.
        if ch in (RING_BACK, RING_FWD) and self.screen not in AREA_LOCKED:
            self._ring(-1 if ch == RING_BACK else 1)
            return True

        # There is deliberately no key that jumps to the log. `^O` and `^P`
        # reach it the same way they reach everything else, and a second route
        # to one application and not the others is a key to remember for no
        # gain. Ctrl-N used to do it, from the conversation screen only --
        # which also made it a dead key on power-on once the deck started on
        # DECK & RIG instead.

        # **Ctrl-B arms and inhibits transmit from anywhere.** It was on the
        # conversation and the two WSPR screens only, so the answer to "can
        # this deck transmit" depended on which screen the operator happened
        # to be looking at.
        #
        # **It was Ctrl-I and could not stay there.** Ctrl-I IS byte 9, which
        # IS Tab: no terminal distinguishes them, and the console least of
        # all -- `modifyOtherKeys`, which lets xterm tell them apart, does
        # not exist under `TERM=linux`. So Tab toggled the transmitter's
        # interlock, including on a form where Tab means "next field". One
        # key, unbound before this, and byte 9 no longer arms anything.
        if ch == INHIBIT_KEY and not self.menu \
                and self.screen not in (PAIR, WIFI, NOKB, CONFIRM):
            self._toggle_inhibit()
            return True

        if self.menu:
            return self._handle_menu(ch)

        if self.screen == NOKB:
            # Any key at all dismisses it: a keystroke arriving IS the proof
            # that the problem it describes has been solved.
            self.screen = CHAT
            self.session.note("keyboard is working")
            return True

        if self.screen == PAIR:
            return self._handle_pair(ch)

        if self.screen == WIFI:
            return self._handle_wifi(ch)

        if self.screen == LOG:
            return self._handle_log(ch)

        if self.screen == FIELDS:
            return self._handle_fields(ch)

        if self.screen == ORDER:
            return self._handle_order(ch)

        if self.screen == ENTRY:
            return self._handle_entry(ch)

        if self.screen == SET:
            return self._handle_settings(ch)

        # Before every other screen: a question that has to be answered is
        # the only thing a keystroke can mean while it is on screen.
        if self.screen == CONFIRM:
            return self._handle_confirm(ch)

        if self.screen == WSPRCAL:
            return self._handle_wspr_cal(ch)
        if self.screen == WSPR:
            return self._handle_wspr(ch)

        if self.screen == ACTS:
            return self._handle_activities(ch)

        if self.screen == TUNE:
            return self._handle_tune(ch)

        if ch == curses.KEY_F1:
            # The DIGIMODE menu, not a deck-wide one. What the deck and the
            # radio are set to is its own area, one `^B` away, and mixing the
            # two is what made this screen the deck's home by accident.
            self._open_menu("digi")
        elif ch == curses.KEY_F3:
            self._open_menu("mode")
        elif ch == curses.KEY_F2:
            # The preview starts empty on every visit. Carrying the last
            # visit's decodes in means the first thing the screen shows is
            # text from a different frequency, which is worse than showing
            # nothing: the preview exists to confirm that what is being tuned
            # *now* is producing copy.
            self._rx_tail = ""
            self.screen = TUNE
        elif ch == 20:                       # Ctrl-T
            # Not while the previous over is still going out. `Ctrl-Y` has
            # already put fldigi's "receive when drained" mark into the
            # transmit buffer and it cannot be recalled, so a second over
            # queued behind it is split by a mark the operator can no longer
            # see: part of it goes out with the first over, the rest waits for
            # a key-up that may never come. Which half arrives depends on
            # fldigi's own handling of text after the mark, and a terminal
            # should not have an answer that depends on that.
            if self._fldigi_sending and self.session.state == RX:
                self.session.note("still sending the last over — wait for RX, "
                                  "or Ctrl-C to cut it short")
            else:
                text = self.session.start_over()
                if text is not None:
                    self._tx_echo = ""
                    self._handed_at = None
                    self._drain_warned = 0.0
                    self.fldigi.start_over(text)
        elif ch == 25:                       # Ctrl-Y
            if self.session.hand_back():
                self._handed_at = time.monotonic()
                self._drain_warned = 0.0
                if not self.fldigi.hand_back():
                    self.session.note("fldigi did not take the hand back — "
                                      "Ctrl-C to drop the carrier")
        elif ch == 3:                        # Ctrl-C
            # Record how much actually went out before the abort. This is the
            # one case where intent and reality differ and the difference
            # matters, so it is kept rather than dropped with the transient
            # progress line.
            partial = self._tx_echo.strip()
            self.fldigi.abort()
            self.session.abort()
            if partial:
                self.session.note(f"aborted — sent: {partial}")
            self._tx_echo = ""
        elif ch == 12:                       # Ctrl-L
            self.scr.clearok(True)
        elif ch == 24:                       # Ctrl-X
            self._clear_transcript()
        # On the conversation screen the arrows edit the line, as they would
        # in any terminal: left and right move the cursor, up and down recall
        # what was sent before.
        elif ch == curses.KEY_LEFT:
            self.session.move(-1)
        elif ch == curses.KEY_RIGHT:
            self.session.move(1)
        elif ch == curses.KEY_UP:
            self.session.recall(-1)
        elif ch == curses.KEY_DOWN:
            self.session.recall(1)
        elif ch == curses.KEY_HOME:
            self.session.home()
        elif ch == curses.KEY_END:
            self.session.end()

        # Tuning without leaving the transcript, on the WASD cluster under the
        # left hand. NOT on Ctrl+arrows: the Linux console cannot send a
        # modified arrow at all — TERM=linux defines no kUP5 or kLFT5, so
        # ncurses sees a plain KEY_UP whether or not Ctrl is held. That would
        # have worked over SSH from an xterm and silently not on the panel.
        elif ch == 1:                        # Ctrl-A
            self._operator_chose(); self.fldigi.nudge_carrier(-10)
        elif ch == 4:                        # Ctrl-D
            self._operator_chose(); self.fldigi.nudge_carrier(10)
        elif ch == 23:                       # Ctrl-W
            self._search(self.fldigi.search_up, "up")
        elif ch == 19:                       # Ctrl-S
            self._search(self.fldigi.search_down, "down")
        # Ctrl-Z arrives as one of two different values depending on the
        # terminal, and the panel gets the one that is easy to miss.
        # TERM=linux defines kspd=^Z, so ncurses consumes byte 26 and returns
        # KEY_SUSPEND (407) instead; TERM=xterm defines no kspd and the byte
        # comes through as 26. Matching only 26 works over SSH and silently
        # does nothing on the deck — which is how this shipped. kspd is the
        # only such capability in the linux entry, so Ctrl-Z is the only
        # command key affected; kbs=^? is already handled with backspace.
        elif ch in (26, curses.KEY_SUSPEND):  # Ctrl-Z
            if not self.session.undo():
                self.session.note("nothing to undo")
        elif curses.KEY_F5 <= ch <= curses.KEY_F12:
            self._insert_memory(ch - curses.KEY_F0)
        elif ch == curses.KEY_PPAGE:
            self.scroll += 5
        elif ch == curses.KEY_NPAGE:
            self.scroll = max(0, self.scroll - 5)
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            self.session.backspace()
        elif ch in (10, 13):
            self._typed("\n")
        elif 32 <= ch < 127:
            self._typed(chr(ch))
        elif ch == 17:                       # Ctrl-Q
            return self._quit()
        else:
            # Same reasoning as the tuning screen: a key that appears dead is
            # otherwise indistinguishable from one whose handler ran and did
            # nothing visible. Caps Lock cost an hour that way.
            name = curses.keyname(ch).decode(errors="replace") if ch >= 0 else "?"
            print(f"chat: unhandled key {ch} ({name})", file=sys.stderr)
        return True

    # -- remembered state --------------------------------------------------
    #
    # What the operator last chose, restored on the next start so the deck
    # comes back as it was left. Deliberately NOT including the transmit
    # inhibit: that is re-asserted on every power-on regardless, because a
    # deck coming out of a bag able to key a radio attached to an unknown
    # antenna is the thing INHIBIT_ON_START exists to prevent. Convenience
    # does not get to override that.

    def _state_path(self):
        # The environment wins, so a test run can point this somewhere
        # disposable — otherwise each run would inherit the previous one's
        # mode and the configured DEFAULT_MODE would never be exercised.
        # Empty means "do not remember", which is what the tests use.
        override = os.environ.get("CYBERDECK_STATE_PATH")
        if override is not None:
            return os.path.expanduser(override) or None
        if self.cfg.get("REMEMBER_STATE") != "yes":
            return None
        return os.path.expanduser(self.cfg.get("STATE_PATH") or "")

    def _load_state(self):
        """Apply the remembered mode, carrier, color and timestamps."""
        path = self._state_path()
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                state = json.load(fh)
        except (OSError, ValueError):
            return          # absent or corrupt: the configured defaults stand
        if state.get("timestamps") in ("yes", "no"):
            self.cfg["TIMESTAMPS"] = state["timestamps"]
        for slot, text in (state.get("memories") or {}).items():
            if slot.isdigit() and 5 <= int(slot) <= 12:
                # A memory set on the deck wins over cyberdeck.conf's default,
                # which is only a starting point.
                self.cfg[f"MEMORY_{int(slot)}"] = text
        known = {k for k, _l, _t in menus.STATION_FIELDS}
        for field, value in (state.get("station") or {}).items():
            if field in known:
                self.cfg[field] = value
        self.session.callsign = self.cfg.get("CALLSIGN") or "LOCAL"
        # A log chosen on the panel outlives a restart, the same as a mode or
        # a memory. Otherwise a power cut during an activation silently sends
        # the rest of it to the default file.
        chosen = state.get("log_path")
        if isinstance(chosen, str) and chosen:
            self.cfg["LOG_PATH"] = chosen
        # An activity outlives a restart, file and all: a flat battery during
        # an activation must resume it rather than start a second one.
        # The remembered activity wins over the conf INCLUDING when it is
        # empty, which is the whole point: deleting an activity sets it empty
        # and saves, and a restore that skipped empty values let the conf's own
        # `ACTIVITY` put the deleted one back on the header at the next
        # restart. A deck ever configured with an activity in its conf could
        # not get back to the master log and stay there.
        for key, field in (("activity", "ACTIVITY"),
                           ("activity_type", "ACTIVITY_TYPE")):
            value = state.get(key)
            if isinstance(value, str):
                self.cfg[field] = value
        # The session key, which replaced `activity_path`: there is one log
        # now, so what has to survive a restart is which session is in
        # progress rather than which file is open.
        began = state.get("activity_start")
        if isinstance(began, str):
            self.cfg["ACTIVITY_START"] = began
        forgotten = state.get("forgotten_sessions")
        if isinstance(forgotten, list):
            self.cfg["FORGOTTEN_SESSIONS"] = [
                [str(p[0]), str(p[1])] for p in forgotten
                if isinstance(p, (list, tuple)) and len(p) == 2]
        for key, field in (("rx_hold_ms", "RX_HOLD_MS"),
                           ("rx_hold_max_ms", "RX_HOLD_MAX_MS")):
            hold = state.get(key)
            if isinstance(hold, int) and 0 <= hold <= 5000:
                self.cfg[field] = hold
        # Blank is a real value for some of these -- an activation that has
        # ended has no reference -- so an empty string is restored and only a
        # missing key falls back to the conf.
        for key in _REMEMBERED:
            if key not in state:
                continue
            # **Coerced through the schema, not required to be a string.**
            # This accepted `str` only, so every numeric setting in the
            # tuple was written to the state file and then ignored on the
            # way back in -- LOG_LINES, and now the WSPR levels, percent and
            # time-out. JSON round-trips an int as an int, so the test for
            # `str` was a test that those keys would never restore.
            want = configmod.SCHEMA.get(key, (None, str, ""))[1]
            value = state[key]
            if want is str:
                if isinstance(value, str):
                    self.cfg[key] = value
                continue
            try:
                self.cfg[key] = want(value)
            except (TypeError, ValueError):
                pass
        scheme = state.get("color")
        if scheme in colors.SCHEMES:
            self.scheme = scheme
            colors.apply(scheme)
        # Stashed, not applied. On a cold boot fldigi is not answering yet and
        # sending these here would do nothing whatsoever, with no error and no
        # retry — which is exactly what used to happen.
        self._boot_mode = state.get("mode") or ""
        self._boot_carrier = state.get("carrier") or 0

    def _save_state(self):
        """Never raises: failing to remember a preference must not disturb a
        contact in progress."""
        path = self._state_path()
        if not path:
            return
        # What the radio is doing, or — when it cannot be asked — what was
        # remembered about it. Writing a null here instead was a quiet way to
        # forget: every _save_state from a colour change or a memory edit runs
        # whether or not fldigi is answering, so one of those while it was
        # down erased the mode and carrier the operator had chosen.
        if self.fldigi.connected and self._startup_done:
            mode, carrier = self.fldigi.modem(), self.fldigi.carrier()
        else:
            mode = self._saved_mode or self._boot_mode or None
            carrier = self._saved_carrier or self._boot_carrier or None
        state = {
            "color": self.scheme,
            "timestamps": self.cfg["TIMESTAMPS"],
            "mode": mode,
            "carrier": carrier,
            "memories": {str(n): self.cfg.get(f"MEMORY_{n}", "")
                         for n in range(5, 13)},
            "station": {k: self.cfg.get(k, "")
                        for k, _label, _token in menus.STATION_FIELDS},
            "log_path": self.cfg.get("LOG_PATH", ""),
            # The activity and the exact file it is writing to. Both, because
            # re-deriving the file from the name would land on today's date
            # and a contest weekend resumed on Sunday would fork.
            "activity": self.cfg.get("ACTIVITY", ""),
            "activity_type": self.cfg.get("ACTIVITY_TYPE", ""),
            "activity_start": self.cfg.get("ACTIVITY_START", ""),
            "forgotten_sessions": [list(p) for p in self._forgotten()],
            "rx_hold_ms": self.cfg.get("RX_HOLD_MS", 0),
            "rx_hold_max_ms": self.cfg.get("RX_HOLD_MAX_MS", 0),
        }
        # Settings the MENUS change. Every one of them already called
        # `_save_state` and not one of them was in this dict, so the panel
        # wrote a state file that did not contain the thing just changed:
        # lines-per-contact set to 3 was back at 1 after a restart, a dupe rule
        # switched to call-only was back to band+mode, and a reference typed
        # for an activation was gone after a flat battery -- during the
        # activation it was typed for.
        #
        # The rule the rest of this function follows: anything reachable from
        # a menu outlives a restart, because the operator changed it on purpose
        # and the conf file is only where it starts.
        for key in _REMEMBERED:
            state[key] = self.cfg.get(key, "")
        try:
            directory = os.path.dirname(path)
            os.makedirs(directory, exist_ok=True)
            tmp = path + ".new"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(state, fh)
                # os.replace is atomic against a crash only once the data it
                # renames is actually on the card. Without these the rename
                # can land while the contents are still in the page cache, and
                # the deck is switched off by pulling its power — so a mode
                # chosen seconds earlier comes back as whatever was there
                # before, or as an empty file. Both were reported as "the mode
                # is not saved", and neither is visible from a clean restart,
                # where the cache is flushed on the way out.
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
            self._saved_mode = state["mode"]
            self._saved_carrier = state["carrier"]
            self._saved_at = time.monotonic()
            self._state_error = None
            # And the directory, so the rename itself survives the same cut.
            dirfd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        except OSError as exc:
            # Not silent. A state file that cannot be written makes every
            # remembered setting appear to work and then revert at the next
            # start, with the deck restoring whatever was last written
            # successfully — which reads as "it always comes back in CW"
            # rather than as a permissions or disk problem. Reported once per
            # failure so a full card or a root-owned file is visible on the
            # panel instead of being inferred.
            if self._state_error != str(exc):
                self._state_error = str(exc)
                self.session.note(f"cannot save settings: {exc}")

    def _apply_scheme(self, name):
        """Switch color scheme and force the whole screen to be repainted.

        The repaint is not cosmetic. fbcon resolves a glyph's color when it is
        drawn, so redefining a palette entry does NOT recolor anything already
        on screen — and ncurses repaints only cells whose content or pair
        NUMBER changed. Changing scheme changes neither: the text is the same
        and the pair is still pair 3, only its definition moved. So without
        this, a scheme change leaves the old colors up until something else
        happens to rewrite those cells, which is why the status bar kept the
        previous scheme's color and one stale cell sat green in the corner.
        """
        self.scheme = name
        colors.apply(name)
        self.scr.clearok(True)
        self.scr.touchwin()
        # No transcript note: the scheme change is self-evident on screen and
        # a log of it is noise in the middle of a contact.
        self._save_state()

    def _open_menu(self, which, remember=True):
        """Open a menu. `remember` pushes the one being left, so Esc returns.

        **Esc goes back ONE level, to wherever the operator actually came
        from.** `MENU_PARENT` could only express a fixed parent, which is
        wrong for a menu reachable two ways: the WSPR band picker is `F3`
        from the screen and `b` from the menu, and a fixed parent has to be
        wrong for one of them. It sent every sub-menu back to the screen,
        so backing out of a sub-sub-menu left the whole area.

        The stack records the route taken. `MENU_PARENT` stays as the
        fallback for a menu opened with nothing beneath it.
        """
        # Arriving at any menu cancels a pending type delete. Without this,
        # `d` then Esc left the flag set, and the next number typed in the
        # picker deleted that type instead of selecting it -- a destructive
        # action still armed by a keystroke the operator had backed out of.
        self._pending_type_delete = False
        self._pending_type_copy = False
        self._pending_type_edit = False
        if remember and self.menu and self.menu != which:
            self._menu_stack.append(self.menu)
            del self._menu_stack[8:]       # a menu tree this deep is a bug
        self.menu = which
        self.menu_page = 0
        self.menu_sel = self._first_selectable(which)

    def _close_menu(self):
        # LEAVING a menu cancels a pending two-key action, exactly as arriving
        # at one does -- see `_open_menu`. This used to be covered by
        # accident: Esc out of the schema picker went UP to the logging menu,
        # and that call cleared the flags on the way. Once Esc began closing
        # the picker to the log screen (§7i, so Esc can mean "keep the schema
        # I have"), `d` then Esc left the delete ARMED, and the next number
        # pressed in the picker deleted that schema instead of selecting it.
        self._pending_type_delete = False
        self._pending_type_copy = False
        self._pending_type_edit = False
        self.menu = None
        self._menu_stack = []
        try:
            curses.curs_set(1)
        except curses.error:
            pass

    def _first_selectable(self, which):
        h, w = self.scr.getmaxyx()
        menu = self._menu_for(which, w, h)
        opts = menus.selectable(menu)
        return opts[0] if opts else 0

    def _handle_menu(self, ch):
        f, m = self.fldigi, self.menu
        # Case-folded for the same reason as the tuning screen: every
        # single-key shortcut here is a letter or a digit, and none of them
        # should stop working because Caps Lock is on.
        key = chr(ch).lower() if 32 <= ch < 127 else ""

        # Arrow-key navigation. The single-key shortcuts still work — this is
        # an addition, not a replacement — but a menu you can walk with the
        # arrows and confirm with Enter needs no memorised letters, which is
        # what a deck used occasionally rather than daily wants.
        h, w = self.scr.getmaxyx()
        menu = self._menu_for(m, w, h)
        opts = menus.selectable(menu)
        if opts and ch in (curses.KEY_UP, curses.KEY_DOWN):
            if self.menu_sel in opts:
                at = opts.index(self.menu_sel)
            else:
                at = 0
            at = (at + (1 if ch == curses.KEY_DOWN else -1)) % len(opts)
            self.menu_sel = opts[at]
            return True
        if ch in (10, 13, curses.KEY_ENTER) and opts:
            # Enter acts as though the selected row's own key was pressed, so
            # both paths go through one dispatch and cannot drift apart.
            sel = self.menu_sel if self.menu_sel in opts else opts[0]
            key = menu["items"][sel][0]
            ch = ord(key) if len(key) == 1 else ch

        # F2 and F3 reach every screen, so the three views — conversation,
        # tuning, mode — form one flat set the operator can move between in a
        # single keystroke, rather than a tree that has to be climbed back out
        # of. Hunting an unidentified signal means going tune, mode, tune,
        # mode; Esc-then-F3 each time is the wrong shape for that.
        if ch == curses.KEY_F3:
            if m in ("mode", "modes_all"):  # already here: F3 is the way out
                self._close_menu()
                self.screen = CHAT
            else:
                self._open_menu("mode")
            return True
        if ch == curses.KEY_F2:
            self._close_menu()
            self._rx_tail = ""             # a fresh preview, as from the chat screen
            self.screen = TUNE
            return True

        if ch == 27:                                   # Esc
            # Up to this menu's parent, or out to the screen underneath when
            # it has none. The screen underneath belongs to the area the menu
            # was opened from, so backing out never crosses an area boundary
            # -- which it did when every menu's parent was one shared root.
            # The route taken, then the declared parent, then out. One
            # level per press, and the last press closes -- never a jump
            # from a sub-sub-menu straight to the screen.
            if self._menu_stack:
                self._open_menu(self._menu_stack.pop(), remember=False)
                return True
            parent = menus.MENU_PARENT.get(m)
            if parent:
                self._open_menu(parent, remember=False)
            else:
                self._close_menu()
            return True
        if ch == 17:                                   # Ctrl-Q
            return False
        if ch == curses.KEY_PPAGE and m == "modes_all":
            self.menu_page = max(0, self.menu_page - 1); return True
        if ch == curses.KEY_NPAGE and m == "modes_all":
            self.menu_page += 1; return True

        # One handler per area menu. `root` is accepted as the old name for
        # the digimode menu so that anything still asking for it by that name
        # gets the menu it used to get rather than nothing.
        if m in ("digi", "root"):
            dest = {"1": "mode", "2": "tuning", "3": "radio",
                    "4": "memories"}.get(key)
            if dest:
                self._open_menu(dest)
            return True

        if m == "deck":
            dest = {"1": "display", "2": "system"}.get(key)
            if dest:
                self._open_menu(dest)
            return True

        if m == "mode":
            if key == "a":
                on = not f.rsid()
                f.set_rsid(on)
                self.session.note(
                    "AUTO on — will follow other stations' mode identifiers"
                    if on else "AUTO off — mode stays where you put it")
                self._close_menu(); return True
            if key == "m":
                self._open_menu("modes_all"); return True
            for k, name in menus.MODE_TIER1:
                if key == k:
                    self._set_mode(name)
                    return True
            return True

        if m == "modes_all":
            name = self._page_keys.get(key)
            if name:
                self._set_mode(name)
            return True

        if m == "display":
            # The same order the menu prints and F4 walks.
            scheme = {"1": "hal", "2": "deckard", "3": "matrix",
                      "4": "tron", "5": "ripley"}.get(key)
            if scheme:
                self._apply_scheme(scheme)
                self._close_menu()
            elif key == "t":
                self.cfg["TIMESTAMPS"] = "no" if self.cfg["TIMESTAMPS"] == "yes" else "yes"
                self.session.note(f"timestamps {self.cfg['TIMESTAMPS']}")
                self._save_state()
                self._close_menu()
            return True

        if m == "tuning":
            if key == "a":
                f.set_afc(not f.afc())
            elif key == "s":
                f.set_squelch(not f.squelch())
            elif key == "r":
                f.set_rsid(not f.rsid())
            elif key == "t":
                f.set_txid(not f.txid())
            elif key == "v":
                on = not f.reverse()
                f.set_reverse(on)
                self.session.note(f"mark/space reversed {'on' if on else 'off'}")
            elif key == "+":
                f.set_squelch_level(min(100.0, f.squelch_level() + 5))
            elif key == "-":
                f.set_squelch_level(max(0.0, f.squelch_level() - 5))
            elif key in ("[", "]", "{", "}"):
                # The lower bound is always discarded; the upper bound caps
                # how long the quality gate may keep waiting. Kept ordered on
                # every change rather than validated on use, so the pair
                # cannot be left describing an impossible window.
                up = key in ("]", "}")
                which = "RX_HOLD_MS" if key in ("[", "]") else "RX_HOLD_MAX_MS"
                step = 250 if up else -250
                value = max(0, min(5000, self.cfg.get(which, 0) + step))
                self.cfg[which] = value
                if which == "RX_HOLD_MS":
                    most = self.cfg.get("RX_HOLD_MAX_MS", 0)
                    if most and most < value:
                        self.cfg["RX_HOLD_MAX_MS"] = value
                elif value and value < self.cfg.get("RX_HOLD_MS", 0):
                    self.cfg["RX_HOLD_MS"] = value
                self._save_state()
                least = self.cfg.get("RX_HOLD_MS", 0)
                most = self.cfg.get("RX_HOLD_MAX_MS", 0)
                self.session.note(
                    f"RX hold {least} ms"
                    + (f" to {most} ms" if most else " (fixed window)"))
            elif key == "c":
                self._operator_chose()
                f.set_carrier(self.cfg["DEFAULT_CARRIER"])
                self.session.note(f"carrier parked at {self.cfg['DEFAULT_CARRIER']} Hz")
                self._save_state()
                self._close_menu()
            return True

        if m == "radio":
            hz = menus.BAND_FREQUENCIES.get(key)
            if hz:
                label = next(lbl for k, lbl, _d, _h in menus.BANDS if k == key)
                allowed = self._supported_bands()
                if allowed is not None and label not in allowed:
                    self.session.note(f"{label} is not supported by this radio")
                else:
                    self._set_vfo(hz, label=render.frequency(hz))
                    # Reported, not set: a band change is not consent to
                    # change the radio's mode.
                    self._report_rig_mode()
                self._close_menu()
            return True

        if m == "memories":
            if key.isdigit() and 1 <= int(key) <= 8:
                slot = int(key) + 4
                self._open_editor(f"MEMORY_{slot}", f"F{slot}")
            return True

        if m == "wspr":
            if key == "w":
                if self.wspr_running:
                    self._wspr_stop("stopped from the menu")
                else:
                    self._wspr_start()
            elif key == "d":
                self._wspr_build()
                self.wspr.decode = not self.wspr.decode
                self._wspr_note("decoding on" if self.wspr.decode else
                                "decoding off — audio still captured, so "
                                "the level reading is live")
            elif key == "t":
                self._wspr_build()
                # Through the setter, which restarts the time-out when
                # transmit is armed -- see `Schedule.set_transmit`.
                self.wspr.set_transmit(not self.wspr.transmit, time.time())
                if self.wspr.transmit:
                    mins = self.cfg.get("WSPR_TIMEOUT_MIN", 60)
                    self._wspr_note(f"transmit armed — {mins} min ToT"
                                    if mins else "transmit armed")
                else:
                    self._wspr_note("transmit off")
            elif key == "n":
                self._wspr_build()
                self.wspr.arm_tx_next(time.time())
                self._wspr_note("beaconing on the next slot")
            elif key == "e":
                self._close_menu()
                self._open_editor(None, "WSPR session name",
                                  text=self.cfg.get("WSPR_SESSION", ""),
                                  sink=self._wspr_set_session)
                return True
            elif key == "b":
                self._open_menu("wspr_band")
                return True
            elif key == "p":
                # Cycles rather than prompts: it is one of four or five
                # values in practice, and a picker for that is more keys
                # than the thing is worth.
                order = (0, 10, 20, 30, 50, 100)
                now = int(self.cfg.get("WSPR_TX_PERCENT", 20))
                nxt = order[(order.index(now) + 1) % len(order)] \
                    if now in order else 20
                self.cfg["WSPR_TX_PERCENT"] = nxt
                if self.wspr is not None:
                    self.wspr.tx_percent = nxt
                self._save_state()
            elif key == "o":
                order = (0, 15, 30, 60, 120, 240)
                now = int(self.cfg.get("WSPR_TIMEOUT_MIN", 60))
                nxt = order[(order.index(now) + 1) % len(order)] \
                    if now in order else 60
                self.cfg["WSPR_TIMEOUT_MIN"] = nxt
                if self.wspr is not None:
                    self.wspr.timeout_minutes = nxt
                self._save_state()
            elif key == "u":
                on = self.cfg.get("WSPR_UPLOAD") != "yes"
                self.cfg["WSPR_UPLOAD"] = "yes" if on else "no"
                self._save_state()
                self._wspr_note(
                    "spots will be reported to wsprnet while WSPR runs and "
                    "there is a network" if on else "spot upload off")
            elif key == "f":
                self._open_editor("WSPR_LOG_PATH", "Spot log")
            elif key == "a":
                self._open_menu("wspr_audio")
                return True
            elif key == "z":
                self._open_menu("wspr_danger")
            return True

        if m == "wspr_band":
            import wsprbands

            # **Space toggles the highlighted band in and out of the hop
            # rotation; a number or Enter selects that band alone.** The
            # first idiom for this was `+` then a number, which an operator
            # reported as undiscoverable -- "I don't get what +n means" --
            # and they were right: a two-key prefix with no visible state
            # between the keys teaches nobody. Space on the row the arrows
            # are already on is a checkbox, and the menu shows `[*]` for a
            # band that is in.
            #
            # `+` is NOT kept as a synonym. Its meaning would have changed
            # silently -- it took the band from the NEXT key and would now
            # toggle whichever row the cursor is on -- and a learned key
            # that still works while meaning something else is worse than
            # one that is gone.
            if key == " ":
                opts = menus.selectable(self._menu_for(
                    m, *reversed(self.scr.getmaxyx())))
                at = self.menu_sel if self.menu_sel in opts else (
                    opts[0] if opts else 0)
                label = wsprbands.BANDS[at][1] if at < len(
                    wsprbands.BANDS) else ""
                if not label:
                    return True
                bands = self._wspr_bands()
                if label in bands:
                    if len(bands) == 1:
                        self._wspr_note(f"{label} is the only band — "
                                        "something has to be selected")
                        return True
                    bands.remove(label)
                else:
                    bands.append(label)
                picked_set = True
            else:
                label = next((l for k, l, _h in wsprbands.BANDS
                              if k == key), "")
                if not label:
                    return True
                bands = [label]
                picked_set = False
            if label:
                # Kept in band order, not the order they were pressed, so
                # the rotation is predictable from the picker.
                order = [l for _k, l, _h in wsprbands.BANDS]
                bands.sort(key=order.index)
                was = self.wspr_band
                self.cfg["WSPR_BANDS"] = ",".join(bands)
                if self.wspr is not None:
                    self.wspr.bands = bands
                if self.wspr_band not in bands:
                    self.wspr_band = bands[0]
                self._save_state()
                # **Tune, here, on the selection.** It only set the band and
                # waited for the scheduler to tune on the next slot, so
                # picking a band with WSPR stopped moved a label and left
                # the radio where it was -- and the spec asks for the
                # opposite: selecting a band tunes to its WSPR dial.
                #
                # Unselecting the band in use tunes too: it changes which
                # band the deck is on, and a deck that says 40 m while the
                # radio sits on 20 m is the same fault in a second place.
                if not picked_set or self.wspr_band != was:
                    dial = wsprbands.dial_hz(self.wspr_band)
                    self._wspr_tune(self.wspr_band)
                    where = f"{self.wspr_band} — {render.frequency(dial)}"
                else:
                    where = ""
                if picked_set:
                    rot = (f"hop: {', '.join(bands)}" if len(bands) > 1
                           else f"hop off — {bands[0]} only")
                    self._wspr_note(f"{rot}{'   ' + where if where else ''}")
                else:
                    self._wspr_note(where)
            return True

        if m == "wspr_audio":
            if key in ("c", "m"):
                # **Gated on WSPR being on, with a reason.** Both of these
                # open the sound card, and fldigi holds it while WSPR is
                # off -- so with WSPR off they produced a capture-device
                # error from inside a screen that looked ready. A menu item
                # that cannot work is told so before it is entered.
                if not self.wspr_running:
                    self._close_menu()
                    self._wspr_note("WSPR must be on to calibrate audio "
                                    "— F1, then w")
                    return True
                self._open_wspr_cal("tx" if key == "c" else "rx")
                return True
            if key in ("t", "r"):
                # Cycled rather than prompted, as the transmit percent is:
                # both are set by ear against a power meter or a dBFS
                # reading, which is a "try the next one down" operation and
                # not a number anybody knows in advance.
                order = (5, 10, 15, 20, 25, 30, 40, 50, 60, 75, 100)
                setting = ("WSPR_TX_LEVEL" if key == "t"
                           else "WSPR_RX_GAIN")
                now = int(self.cfg.get(setting, 50 if key == "t" else 70))
                nxt = (order[(order.index(now) + 1) % len(order)]
                       if now in order else
                       min(order, key=lambda v: abs(v - now)))
                self.cfg[setting] = nxt
                self._save_state()
                if key == "t":
                    # Straight onto the transmitter, which drops the
                    # rendered audio so the next beacon uses the new level.
                    if self.wspr_tx is not None:
                        self.wspr_tx.level = nxt
                    self._wspr_note(f"TX audio level {nxt}% — "
                                    "send a test tone and read the meter")
                else:
                    note = f"RX capture gain {nxt}%"
                    # Only live while WSPR owns the codec; otherwise fldigi
                    # has it and the deck must not touch a control fldigi is
                    # using. It applies at the next start.
                    if self.wspr_running and self.wspr_gain is not None:
                        why = self.wspr_gain.apply(nxt)
                        note += f" — {why}" if why else " — set now"
                    else:
                        note += " — applies when WSPR starts"
                    self._wspr_note(note)
            return True

        if m == "wspr_danger":
            # Refused while running, which the contact log's danger zone has
            # no need to be: a capture is appending every two minutes, and
            # emptying a file a running decoder is about to write to is a
            # race with no useful outcome.
            if self.wspr_running:
                self._wspr_note("stop WSPR first — it is writing to the log")
                self._close_menu()
                return True
            if key == "a":
                self._wspr_forget_all()
            elif key == "s":
                self._wspr_ask_clear_session()
            elif key == "m":
                self._wspr_ask_clear_all()
            return True

        if m == "danger":
            # Each one asks before it does anything, and the question carries
            # the count -- see `menus.danger_menu`. Nothing is destroyed on
            # this screen; it only raises the question.
            if key == "a":
                self._ask_forget_all_sessions()
            elif key == "s":
                self._ask_clear_session()
            elif key == "m":
                self._ask_clear_log()
            return True

        if m == "logging":
            if key == "l":
                self.log_on = not self.log_on
                self.cfg["LOGGING"] = "yes" if self.log_on else "no"
                self._save_state()
                self._log_note("logging on — ^O ^P reach it"
                               if self.log_on else "logging off")
                if not self.log_on and self.screen == LOG:
                    self.screen = CHAT
            elif key == "e":
                self._close_menu()
                self._open_activities()
            elif key == "v":
                self._open_menu("activity")
            elif key == "f":
                self._open_editor("LOG_PATH", "Log file")
            elif key == "a":
                self._export_adif()
                self._close_menu()
            elif key == "t":
                self._export_adif(lotw=True)
                self._close_menu()
            elif key == "c":
                on = self.cfg.get("CALLBOOK") != "yes"
                self.cfg["CALLBOOK"] = "yes" if on else "no"
                self._save_state()
                self.session.note(
                    "callbook lookup on — every call worked goes to a third "
                    "party" if on else "callbook lookup off")
            elif key == "n":
                self.cfg["LOG_LINES"] = str(self._log_lines() % 3 + 1)
                self._save_state()
            elif key == "x":
                self._export_adif(session_only=True)
                self._close_menu()
            elif key == "d":
                rules = qsolog.DUPE_RULES
                now = self.cfg.get("DUPE_CHECK", "band+mode")
                self.cfg["DUPE_CHECK"] = rules[
                    (rules.index(now) + 1) % len(rules)] if now in rules \
                    else qsolog.DUPE_BAND_MODE
                self._save_state()
            elif key == "m":
                order = ("auto", "digital", "voice")
                now = self.cfg.get("OPERATING", "auto")
                self.cfg["OPERATING"] = order[
                    (order.index(now) + 1) % len(order)] if now in order \
                    else "auto"
                self._save_state()
            elif key == "p":
                self._open_editor("MY_PARK", "My reference",
                                  sink=self._set_my_park)
            elif key == "z":
                self._open_menu("danger")
            return True

        if m == "activity":
            table = self._activity_table()
            names = [n for n in sorted(table) if n != "GENERAL"]
            # `d` then a number deletes that type instead of selecting it.
            # Two keystrokes and then a confirmation, because a type an
            # operator spent a contest getting right is worth more than the
            # single keystroke that would remove it.
            if key == "d":
                self._pending_type_delete = True
                self._pending_type_copy = False
                self._pending_type_edit = False
                self._log_note("press the number of the schema to delete")
                return True
            if key == "c":
                self._pending_type_copy = True
                self._pending_type_delete = False
                self._pending_type_edit = False
                self._log_note("press the number of the schema to copy")
                return True
            if key == "e":
                self._pending_type_edit = True
                self._pending_type_copy = False
                self._pending_type_delete = False
                self._log_note("press the number of the schema to edit")
                return True
            if key == "n":
                self._pending_type_copy = False
                self._pending_type_delete = False
                self._pending_type_edit = False
                self._new_activity_type()
                return True
            chosen = ""
            if key == "g":
                chosen = "GENERAL"
            elif key.isdigit() and key != "0" and 0 <= int(key) - 1 < len(names):
                chosen = names[int(key) - 1]
            if chosen and self._pending_type_edit:
                self._pending_type_edit = False
                self._edit_activity_type(chosen)
                return True
            if chosen and self._pending_type_copy:
                self._pending_type_copy = False
                self._copy_activity(chosen)
                return True
            if chosen and self._pending_type_delete:
                self._pending_type_delete = False
                in_file = chosen in self._file_types()
                if not in_file:
                    self._log_note(f"{chosen} is built in — nothing in "
                                   f"activities.conf to delete")
                    return True
                reset = activities.is_builtin(chosen)
                self._ask_confirm(
                    "RESET LOG SCHEMA" if reset else "DELETE LOG SCHEMA",
                    [chosen, "",
                     (f"Your changes to {chosen} will be removed and the "
                      f"built-in definition restored.") if reset else
                     f"The {chosen} schema will be deleted from activities.conf.",
                     "Contacts already logged are not touched."],
                    lambda n=chosen: self._delete_activity_type(n),
                    back=self.screen)
                return True
            self._pending_type_delete = False
            self._pending_type_copy = False
            self._pending_type_edit = False
            if chosen:
                # Not over a part-typed contact. A schema change rebuilds the
                # form and carries only the sticky fields across, so a typed
                # callsign and reports used to be discarded without a word --
                # §7i. Refused rather than confirmed: there is nothing for the
                # operator to weigh up, only something to finish first.
                busy = self.log_form.typed() if self.log_form else []
                if busy:
                    labels = ", ".join(qsolog.field_label(f) for f in busy[:3])
                    self._log_note(f"{labels} still typed — log the contact, "
                                   f"or ^X to clear it, then change schema")
                    self._close_menu()
                    self.screen = LOG if self.log_on else CHAT
                    return True
                self._set_activity_type(chosen, table)
                # One exit, whichever way the picker was reached. It used to
                # go back to the logging menu when opened from there and to
                # the log screen when opened by naming a new activity, which
                # meant the same keystroke on the same screen landed in two
                # places depending on history the operator could not see.
                # Choosing a type rebuilds the form, and looking at the form
                # is the next thing either way.
                self._close_menu()
                self.screen = LOG if self.log_on else CHAT
            return True

        if m == "system":
            if key == "b":
                self._open_pair()
            elif key == "w":
                self._open_wifi()
            elif key == "i":
                self._toggle_inhibit()
                self._close_menu()
            elif key == "c":
                self._clear_transcript()
                self._close_menu()
            elif key == "q":
                return False
            return True

        return True

    def _set_vfo(self, hz, label=None):
        """Command the radio's VFO and check it actually went there.

        fldigi keeps its own frequency and refreshes it from the rig, so a
        command the radio ignores shows up as the deck's number snapping back
        a moment later — which reads as the deck fighting the radio when it is
        really the radio declining.

        This asks once and reports the result. It deliberately does NOT
        re-assert: a loop that re-sends whenever the readback disagrees cannot
        tell a rejected command from the operator turning the knob, so it
        would fight a deliberate manual tune and never let go. One command,
        one answer, and the truth on screen.
        """
        hz = int(hz)
        self.fldigi.set_frequency(hz)
        time.sleep(0.35)          # let the command reach the rig and read back
        got = int(self.fldigi.frequency() or 0)
        where = label or render.frequency(hz)
        if abs(got - hz) <= 5:
            self.session.note(f"VFO {render.frequency(got)}"
                              + (f"  {self.fldigi.rig_mode()}" if label else ""))
            return True
        self.session.note(f"VFO {where} refused — radio stayed on "
                          f"{render.frequency(got)}")
        return False

    # -- editing a message memory in place --------------------------------

    def _toggle_inhibit(self):
        """Arm or disarm transmit. Does not stop an over already running.

        The inhibit is an interlock against *starting*, not a stop button —
        `Ctrl-C` is the stop. fldigi's own `main.rx_only` is set too but is
        not relied on: it was observed not to inhibit `main.tune` (§9). Since
        the control cannot do what pressing it mid-over looks like it should,
        it says so rather than leaving the operator to infer it from a radio
        that stays keyed.
        """
        # Arming transmit is the half that can be refused. Inhibiting is
        # always allowed: a safety control that can fail to engage is not one.
        if self.session.inhibited and not self._rig_mode_ok():
            mode = (self.fldigi.rig_mode() or "?").strip()
            self.session.note(
                f"transmit stays inhibited — the radio is in {mode}, not a "
                f"data mode. Change it on the radio, then Ctrl-B again.")
            return
        self.session.inhibit(not self.session.inhibited)
        self.fldigi.receive_only(self.session.inhibited)
        if self.session.inhibited and self._fldigi_sending:
            self.session.note("inhibited — this over still finishes; "
                              "Ctrl-C to stop it now")

    def _clear_transcript(self):
        """Empty the transcript and fldigi's receive buffer together.

        The decode preview keeps its own tail, so the tuning screen does not
        go blank just because the conversation was cleared — they answer
        different questions.
        """
        self.session.entries.clear()
        self.fldigi.clear_rx()
        self.scroll = 0
        self.session.note("transcript cleared")

    def _open_editor(self, key, title, secret=False, sink=None, text=None):
        """Edit a config field, or — with `sink` — anything else.

        `sink` exists for the WiFi passphrase, which must not take the normal
        path: every other edited field is written into the state file on the
        card, and a passphrase typed here belongs to NetworkManager instead.
        `secret` stops it being drawn, because the deck's screen is a panel
        someone else can be standing behind.
        """
        # A sink edit has no config key to read, so `text` is how it starts
        # with the value being changed rather than with an empty line -- an
        # activity being renamed should not have to be retyped.
        if text is None:
            text = "" if key is None else (self.cfg.get(key, "") or "")
        # `str`, always. Two settings are declared `int` in `config.SCHEMA` --
        # TX_POWER and TX_POWER_MAX -- so `cfg.get` hands back an int, and
        # `len()` of an int is a TypeError that takes the whole panel down.
        # The Station menu has always been able to reach both, so this has
        # been a crash since those settings existed; it only became easy to
        # hit when the deck-and-rig screen made them two keystrokes away.
        text = "" if text is None else str(text)
        # `reveal` is deliberately not remembered between editors. Showing a
        # passphrase is a decision about the room the deck is in at that
        # moment, and it should have to be made again rather than carried in
        # from the last network joined somewhere else.
        self.edit = {"key": key, "title": title, "text": text,
                     "cursor": len(text), "secret": secret, "sink": sink,
                     "reveal": False}

    def _draw_edit(self, h, w):
        e = self.edit
        self._put(0, 0, [(f" EDIT  {e['title']}".ljust(w), "reverse")], w)
        self._put(1, 0, render.rule(w), w)

        body_h = max(1, h - 5)
        masked = e.get("secret") and not e.get("reveal")
        shown = "•" * len(e["text"]) if masked else e["text"]
        lines, (crow, ccol) = render.compose_lines(
            shown, "", w, body_h, cursor=e["cursor"])
        for i, line in enumerate(lines):
            self._put(2 + i, 0, line, w)

        self._put(h - 3, 0, render.rule(w), w)
        self._put(h - 2, 0, [(render.edit_hint(e.get("secret"),
                                               e.get("reveal"))[:w - 1], "dim")], w)
        # `key` is None for an editor with a sink — a WiFi passphrase or a
        # network name, which belong to NetworkManager rather than to any
        # config field. Calling .startswith on that None raised on the first
        # draw, so the deck crashed the instant the passphrase editor opened
        # and systemd restarted it: from the panel, a pause and then the
        # conversation screen again, which looks nothing like a traceback.
        if (e["key"] or "").startswith("MEMORY_"):
            self._put(h - 1, 0, [(render.EDIT_TOKENS_HINT[:w - 1], "dim")], w)
        try:
            curses.curs_set(1)
            self.scr.move(2 + crow, ccol)
        except curses.error:
            pass

    def _handle_edit(self, ch):
        e = self.edit
        if ch == 27:                                   # Esc: discard
            self.edit = None
        elif ch in (10, 13, curses.KEY_ENTER):         # Enter: store
            text = e["text"].strip()
            if e.get("sink") is not None:
                # Not stored here and never written to the card: the sink owns
                # it. The note says the field, never the value.
                #
                # And it does not go to the transcript. Every sink here belongs
                # to the logger -- naming an activity, naming a type, this
                # station's reference -- so "Activity name entered" was landing
                # in the record of a conversation on the air. The sink itself
                # reports what it did; this only has to say the prompt was
                # answered.
                self.edit = None
                self._log_note(f"{e['title']} entered")
                e["sink"](text)
                return True
            # Back as the type the schema declares. Writing the string "100"
            # into TX_POWER_MAX would leave `rig.power(max_watts=...)` dividing
            # by a string on the next CAT read, which is a failure a long way
            # from the typing that caused it. A value that will not convert is
            # refused here, where the operator can see why.
            # **The schema's own converter, whatever it is.** This tested
            # `want is int` and sent everything else through as a string, so
            # adding the `wattage` type -- which exists because sub-watt
            # power has to be expressible -- would have stored "0.5" as text
            # and left the arithmetic downstream to fail a long way from
            # here. Any converter the schema names is applied.
            want = configmod.SCHEMA.get(e["key"], (None, str, ""))[1]
            if want is str:
                self.cfg[e["key"]] = text
            else:
                try:
                    if not text.strip():
                        self.cfg[e["key"]] = want(0)
                    elif want is int:
                        # Through float, as before: "7.5" into a whole-watt
                        # ceiling truncates rather than being refused, and
                        # `int("7.5")` raises. Tolerance kept deliberately.
                        self.cfg[e["key"]] = int(float(text))
                    else:
                        self.cfg[e["key"]] = want(text)
                except (ValueError, TypeError):
                    self.edit = None
                    self._log_note(f"{e['title']}: {text!r} is not a "
                                   f"{getattr(want, '__name__', 'value')}")
                    return True
            if e["key"] == "LOG_PATH":
                # Reopening rather than only remembering the new name: the
                # contact list, the duplicate check and the next serial are
                # all read from the file, so a switch that did not reload
                # would show one log while writing to another.
                self._switch_log()
            if e["key"] == "CALLSIGN":
                # The transcript attributes our own overs by callsign, so the
                # session has to be told rather than reading it once at start.
                self.session.callsign = text or "LOCAL"
            self._save_state()
            self.session.note(f"{e['title']} "
                              + ("cleared" if not text else "saved"))
            self.edit = None
        elif ch == 18 and e.get("secret"):             # Ctrl-R: show or hide
            e["reveal"] = not e.get("reveal")
        elif ch == 21:                                 # Ctrl-U: clear the line
            e["text"], e["cursor"] = "", 0
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            if e["cursor"] > 0:
                e["text"] = e["text"][:e["cursor"] - 1] + e["text"][e["cursor"]:]
                e["cursor"] -= 1
        elif ch == curses.KEY_DC:                      # Delete: forwards
            e["text"] = e["text"][:e["cursor"]] + e["text"][e["cursor"] + 1:]
        elif ch == curses.KEY_LEFT:
            e["cursor"] = max(0, e["cursor"] - 1)
        elif ch == curses.KEY_RIGHT:
            e["cursor"] = min(len(e["text"]), e["cursor"] + 1)
        elif ch == curses.KEY_HOME:
            e["cursor"] = 0
        elif ch == curses.KEY_END:
            e["cursor"] = len(e["text"])
        elif ch == 17:                                 # Ctrl-Q
            return False
        elif 32 <= ch < 127:
            e["text"] = e["text"][:e["cursor"]] + chr(ch) + e["text"][e["cursor"]:]
            e["cursor"] += 1
        return True

    def _power_watts(self):
        """Transmit power as a bare number for the form: "6", or "".

        The same reading `_power_now` puts in a memory, without the unit --
        the form's label already says W, and the log stores a number.
        """
        text = self._power_now()
        return text.split()[0] if text else ""

    def _power_now(self):
        """Transmit power as a string for a memory: "20 W", or "".

        The radio first, the configuration second, nothing at all third. An
        empty string is deliberate — a memory that says "RUNNING  TO A WIRE"
        is odd, but a memory that states a wattage the radio is not using is
        wrong, and wrong is worse than odd on the air.
        """
        watts = 0
        try:
            # Imported and connected lazily, and only here. The deck has never
            # held a rigctld client — it drives the radio through fldigi — and
            # a memory that nobody has put {power} into should not start one.
            if self._rig is None:
                import rigctld_client
                self._rig = rigctld_client.Rigctld(
                    host=self.cfg.get("RIGCTLD_HOST", "127.0.0.1"),
                    port=self.cfg.get("RIGCTLD_PORT", 4532))
            watts = self._rig.power(max_watts=self.cfg.get("TX_POWER_MAX", 0))
        except Exception:
            # No rigctld, no radio, a hamlib that will not convert: all the
            # same event here, and all fall through to the configuration.
            watts = 0
        if not watts:
            watts = self.cfg.get("TX_POWER", 0) or 0
        if not watts:
            return ""
        # **`int(watts)` truncated half a watt to nothing.** The FTX-1 in its
        # field configuration transmits down to 0.5 W and below, and WSPR
        # encodes those exactly -- 0.5 W is 27 dBm, 0.1 W is 20. Rounding to
        # a whole number turned every sub-watt reading into "0 W", which
        # `dbm_for_watts` refuses, and the screen reported "power unknown"
        # from a radio that was answering perfectly well.
        #
        # Whole watts stay whole, as `rigctld_client._watts` and
        # `config.watts` both do: "5 W" and not "5.0 W".
        # Three decimals, not two: 1 mW is 0 dBm and a real WSPR level, and
        # `round(0.001, 2)` is 0.0 -- which would reintroduce the same bug
        # one decimal place further down.
        number = float(watts)
        shown = int(number) if number == int(number) else round(number, 3)
        return f"{shown} W"

    def _insert_memory(self, slot):
        """Put message memory `slot` in at the cursor.

        The station's own details are substituted rather than written into
        each memory, so changing the callsign does not mean rewriting them.
        """
        raw = (self.cfg.get(f"MEMORY_{slot}") or "").strip()
        if not raw:
            self.session.note(f"F{slot} is empty — set it from F1 5")
            return
        # A memory is stored on one line and may be sent as several. Both
        # places it can be stored are line-based — cyberdeck.conf is KEY =
        # value, and the on-deck editor takes Enter to mean save — so a
        # literal newline cannot be typed into either. `\n` is expanded here,
        # at the moment of insertion, which keeps the stored form single-line
        # everywhere and leaves the editor showing exactly what was typed.
        #
        # Multi-line memories are how PSK31 is actually worked: a station
        # description or a brag file arrives as a formatted block, not as one
        # long line the far end has to unwrap.
        text = raw.replace("\\n", "\n").format_map(_Memories({
            "call": self.cfg.get("CALLSIGN", ""),
            "name": self.cfg.get("NAME", ""),
            "qth": self.cfg.get("QTH", ""),
            "grid": self.cfg.get("LOCATOR", ""),
            # {locator} kept as an alias: memories written before the token
            # was renamed still work rather than inserting a literal brace.
            "locator": self.cfg.get("LOCATOR", ""),
            "rig": self.cfg.get("RIG", ""),
            "ant": self.cfg.get("ANTENNA", ""),
            # {antenna} as an alias for the same reason {locator} is one:
            # whichever an operator reaches for should work.
            "antenna": self.cfg.get("ANTENNA", ""),
            # Read from the radio, not from the configuration. A brag line
            # that says 20 W while the radio sits at 5 is worse than no brag
            # line; the configured value is the fallback for when the radio
            # will not answer.
            "power": self._power_now(),
        }))
        out = self.session.insert(text)
        if out:
            self.fldigi.send_more(out)
        self.scroll = 0

    def _search(self, fn, direction):
        """Run fldigi's signal search and say what happened.

        The search either lands the carrier on a signal or leaves it where it
        was, and the difference is invisible on a screen with no waterfall —
        which reads as a dead key when the band is quiet. Report the move.
        """
        self._operator_chose()
        f = self.fldigi
        before = f.carrier()
        fn()
        time.sleep(0.4)          # fldigi needs a moment to settle on a signal
        after = f.carrier()
        if after != before:
            self.session.note(f"search {direction}: carrier {before} -> {after} Hz")
        else:
            self.session.note(f"search {direction}: nothing found above the "
                              f"squelch; still {after} Hz")

    def _supported_bands(self):
        """Band labels this radio covers, or None for all of them.

        Configured rather than probed. hamlib can report a rig's frequency
        ranges through dump_caps, which would make this automatic — but the
        deck has no reason to trust a range list it has never tested against,
        and a wrong answer here silently hides a band the operator can
        actually use.
        """
        raw = (self.cfg.get("RIG_BANDS") or "").strip()
        if not raw:
            return None
        return {part.strip() for part in raw.split(",") if part.strip()}

    def _rig_mode_held(self, reading, source="fldigi"):
        """A rig mode reading, holding the last good one through a dropped read.

        A CAT read that times out or comes back short returns "", and "" is
        not a mode -- it is the absence of an answer. Treated as an answer it
        said "the radio is not in a data mode we can read", which sent
        `resolve_mode` and `_shown_mode` to the MODEM instead, so the panel
        showed `USB` for a few seconds, then `BPSK31`, then `USB` again. Every
        several seconds, because that is how often a read fails over a serial
        port on a Pi, and visible on the logging screen because the header is
        redrawn from this five times a second.

        So a dropped read reports the last mode that WAS read, for up to
        `_RIG_MODE_HOLD` seconds. Bounded, because a radio switched off stops
        answering permanently and the deck must not keep asserting the mode it
        was in an hour ago -- at that point the absence is the truth and the
        modem fallback is right.
        """
        reading = (reading or "").strip()
        now = time.monotonic()
        if reading:
            self._rig_mode_last[source] = reading
            self._rig_mode_last_at[source] = now
            return reading
        held = self._rig_mode_last.get(source, "")
        if held and now - self._rig_mode_last_at.get(source, 0.0) \
                < _RIG_MODE_HOLD:
            return held
        self._rig_mode_last[source] = ""
        return ""

    def _shown_mode(self):
        """What to put on the status line where the mode goes.

        The modem when the radio is in a data mode or cannot be read; the
        radio's own mode otherwise. Kept beside `_log_mode`, which answers the
        same question for the record with `qsolog.resolve_mode` -- so the
        screen and the log agree about what is happening, which they did not
        when this was `fldigi.modem()` unconditionally.
        """
        modem = (self.fldigi.modem() or "").strip()
        rig_mode = self._rig_mode_held(self.fldigi.rig_mode())
        if not rig_mode:
            return modem
        if rig_mode.upper() in qsolog.RIG_DATA_MODES:
            return modem
        # The radio is in SSB, FM, CW: that is what it is doing, and the modem
        # loaded behind it is not on the air.
        return rig_mode

    def _watch_rig_mode(self):
        """Transmit and decoding both follow the radio's mode by themselves.

        The interlock used to be one-sided: `_toggle_inhibit` refused to ARM
        in a voice mode, but a radio moved OUT of a data mode while transmit
        was already armed stayed armed. So the dangerous order -- arm first,
        change the radio second -- was the one the deck did not cover, and the
        operator's next over would go out as a digital signal into a voice
        mode on a voice frequency.

        **Decoding stops too.** fldigi decodes whatever is on the sound card
        whether or not the radio is in a mode that could be carrying it, and
        on a Pi 3A+ that DSP is the deck's largest continuous cost. In SSB or
        FM it buys nothing: anything decoded is noise, and transmit is
        interlocked off anyway. `fldigi_client.park_decoder` is how, and the
        carrier survives the round trip.

        The two resume differently, on purpose. Decoding comes back by itself
        the moment the radio is in a data mode again -- a running decoder puts
        nothing on the air. Arming transmit stays the operator's act, which is
        what `Ctrl-B` is, and what the message says.
        """
        if not self.fldigi.connected:
            return
        if self._rig_mode_ok():
            self._rig_mode_warned = False
            came_back = self.fldigi.unpark_decoder()
            if came_back:
                self.session.note(f"rig back in a data mode — decoding "
                                  f"{came_back} again")
            return
        # Through the hold, so the message cannot read "rig in  — not a data
        # mode" on the poll where the read came back empty.
        current = self._rig_mode_held(self.fldigi.rig_mode()) or "a voice mode"
        # Parked before the inhibit is considered, not after. This used to
        # return early when transmit was ALREADY inhibited, which is the
        # common case -- so a decoder left running was never stopped.
        parked = self.fldigi.park_decoder()
        was_armed = not self.session.inhibited
        if was_armed:
            # Through the session's own setter, which is the route `Ctrl-B`
            # takes, so the state and the transcript cannot disagree about why
            # transmit is off.
            self.session.inhibit(True)
        if self._rig_mode_warned:
            return
        self._rig_mode_warned = True
        did = []
        if was_armed:
            did.append("transmit off")
        if parked:
            did.append("decoding off")
        # TWO short notes rather than one long one. The panel is 66 columns
        # and the single sentence this replaced ran to about 140, so it
        # wrapped to three transcript lines and the first of them scrolled
        # away under the next thing the deck had to say.
        #
        # The first is said whether or not anything CHANGED. With transmit
        # already inhibited and no `NULL` modem to park onto there is nothing
        # to report having done -- and an earlier version returned here,
        # which left the operator with no notice at all that the radio was
        # somewhere the deck will not transmit from. The mode is the fact
        # worth knowing; what the deck did about it is the detail.
        self.session.note(f"rig in {current} — not a data mode"
                          + (f": {', '.join(did)}" if did else ""))
        if parked and self.session.inhibited:
            self.session.note("decoding returns with the rig; "
                              "Ctrl-B to arm transmit")
        elif parked:
            self.session.note("decoding returns when the rig does")
        elif self.session.inhibited:
            self.session.note("Ctrl-B to arm transmit once the rig is back")

    def _report_rig_mode(self):
        """Say what mode the radio is in. Never change it.

        **The deck does not set the radio's mode.** It used to, at startup and
        on every band change, on the reasoning that digital work is upper
        sideband on every band and that is easy to forget. The reasoning was
        right about the radio and wrong about whose decision it is: a deck
        used purely as a logbook beside a microphone would put the radio into
        a data mode the operator had not asked for, mid-session, and a
        deliberate choice would be reverted with a band change.

        So the mode is the operator's, and the deck's side of the bargain is
        the transmit interlock: it reports what it reads, and it refuses to
        arm transmit while the radio is in a mode digital work cannot use.
        See `_toggle_inhibit` and `_rig_mode_ok`.
        """
        current = (self.fldigi.rig_mode() or "").strip()
        if not current:
            return ""
        if not self._rig_mode_ok():
            self.session.note(f"rig in {current} — not a data mode, "
                              f"transmit stays inhibited")
        return current

    def _rig_mode_ok(self):
        """Whether the radio is in a mode digital transmit can use.

        True when the mode cannot be read at all. Refusing on an absence of
        evidence would take transmit away from every deck without CAT control,
        which is a worse failure than the one being prevented — so this
        refuses only on a positive reading of a mode that will not work.

        Through `_rig_mode_held`, so a dropped CAT read is not mistaken for
        "no CAT at all". Without it a single timed-out read returned True for
        one poll, `_watch_rig_mode` unparked the decoder, and the next poll
        parked it again -- the modem reloaded and the carrier rewritten every
        few seconds, which is the flicker with side effects.
        """
        current = self._rig_mode_held(self.fldigi.rig_mode()).upper()
        if not current:
            return True
        return current in qsolog.RIG_DATA_MODES

    def _set_mode(self, name):
        """Change modem, keeping the carrier where it is.

        fldigi resets the carrier to its sweet spot when the modem changes.
        That is right when starting fresh and wrong for the job this screen
        mostly does: identifying an unknown signal by trying modes against it.
        The operator has already tuned onto the signal, and throwing that away
        on every attempt means re-tuning before each guess — with the added
        trap that a mode which *would* have decoded fails because it is now
        pointed at empty spectrum.

        So the carrier is read before the change and written back after.
        `c` on the Tune Settings page parks it deliberately, which is the
        other half of the behavior and stays available.
        """
        # Not mid-over. Changing the modem while the radio is keyed truncates
        # whatever is going out and leaves the far end with a fragment in one
        # mode and a carrier in another. CW is the case that provokes it: it
        # sends far slower than PSK, so there is a long window in which the
        # over looks finished and is not.
        if self.session.state == TX or self.fldigi.trx_state() != "RX":
            self.session.note("still transmitting — Ctrl-Y first, then change mode")
            return
        self._operator_chose()
        was = self.fldigi.carrier()
        self.fldigi.set_modem(name)
        # Only if it actually moved, and only to somewhere sane: a failed read
        # returns 0, and writing that back would park the modem at DC.
        now = self.fldigi.carrier()
        if was and now != was:
            self.fldigi.set_carrier(was)
            now = self.fldigi.carrier()
        if self.fldigi.decoder_parked:
            # The choice was recorded rather than loaded -- see
            # `fldigi_client.set_modem`. Saying "mode changed" and leaving it
            # at that would promise decoding that is not happening.
            self.session.note(
                f"{self.fldigi.modem()} selected — the rig is not in a data "
                f"mode, so decoding starts when it is")
        else:
            self.session.note(
                f"mode changed to {self.fldigi.modem()} at {now} Hz")
        self._save_state()
        self._close_menu()

    def _typed(self, char):
        out = self.session.type(char)
        if out:
            self.fldigi.send_more(out)
        self.scroll = 0

    def _handle_tune(self, ch):
        f = self.fldigi
        # Case-folded: a command key must not depend on Caps Lock or a held
        # shift. The deck reported "unhandled key 65 (A)" for every letter on
        # this screen until this was fixed, which looked exactly like the
        # bindings being dead.
        key = chr(ch).lower() if 32 <= ch < 127 else ""
        if ch == curses.KEY_F3:
            self._open_menu("mode")
            return True
        if ch in (curses.KEY_F2, 27):
            self.screen = CHAT
        elif ch == curses.KEY_LEFT:
            self._operator_chose(); f.nudge_carrier(-10)
        elif ch == curses.KEY_RIGHT:
            self._operator_chose(); f.nudge_carrier(10)
        elif ch == curses.KEY_UP:
            self._search(f.search_up, "up")
        elif ch == curses.KEY_DOWN:
            self._search(f.search_down, "down")
        elif key == "a":
            f.set_afc(not f.afc())
        elif key == "s":
            f.set_squelch(not f.squelch())
        elif key == "r":
            f.set_rsid(not f.rsid())
        elif key == "t":
            f.set_txid(not f.txid())
        elif key == "v":
            on = not f.reverse()
            f.set_reverse(on)
            self.session.note(f"mark/space reversed {'on' if on else 'off'}")
        elif key == "+" or key == "=":
            # '=' too: it is the unshifted key, and squelch is adjusted often
            # enough that reaching for shift each time is a nuisance.
            f.set_squelch_level(min(100.0, f.squelch_level() + 2))
        elif key == "-":
            f.set_squelch_level(max(0.0, f.squelch_level() - 2))
        elif key == ",":
            self._set_vfo(f.frequency() - 100)
        elif key == ".":
            self._set_vfo(f.frequency() + 100)
        elif key == "<":
            self._set_vfo(f.frequency() - 1000)
        elif key == ">":
            self._set_vfo(f.frequency() + 1000)
        elif ch == 17:
            return False
        else:
            # Anything this screen does not bind is reported rather than
            # silently dropped. A key that appears dead is otherwise
            # indistinguishable from a key whose handler ran and did nothing
            # visible, which cost an hour once.
            name = curses.keyname(ch).decode(errors="replace") if ch >= 0 else "?"
            print(f"tune: unhandled key {ch} ({name})", file=sys.stderr)
        return True


def main(stdscr, settings):
    curses.curs_set(1)
    curses.use_default_colors()
    try:
        curses.start_color()
    except curses.error:
        pass
    colors.apply(settings["COLOR"])
    stdscr.keypad(True)
    stdscr.timeout(settings["POLL_MS"])

    # raw(), not the cbreak() curses.wrapper leaves us in. Under cbreak the
    # terminal still interprets Ctrl-C as SIGINT, so it never reaches getch()
    # and Python unwinds with KeyboardInterrupt — on the one key whose whole
    # job is to stop a transmission. raw() delivers it as byte 3 instead.
    curses.raw()

    # Esc and the arrow keys both begin with the same byte, so ncurses waits
    # ESCDELAY for the rest of a sequence before deciding it was a bare Esc.
    # The default is a full second, which makes Esc feel broken. 100 ms is
    # comfortably longer than the few milliseconds a Bluetooth keyboard needs
    # to deliver the remaining bytes of an arrow key, and short enough that
    # Esc is instant.
    try:
        curses.set_escdelay(100)
    except (AttributeError, curses.error):
        pass

    deck = Deck(stdscr, settings)
    try:
        while True:
            deck.poll()
            deck.draw()
            if not deck.handle(stdscr.getch()):
                break
    finally:
        # Whatever happens — clean exit, crash, or a signal that still gets
        # through — do not leave the radio keyed. This runs before curses
        # tears the screen down, and is allowed to fail silently: an exception
        # here would mask the one that brought us here.
        try:
            deck.fldigi.abort()
        except Exception:
            pass
        # Give fldigi its modem back. The decoder may be parked on `NULL`
        # because the radio is in SSB, and the deck exiting is not a reason to
        # leave the operator's fldigi holding a modem they never chose -- on a
        # laptop they go back to the fldigi window, and on the deck the next
        # start reads the modem to decide whether its restore took.
        try:
            deck.fldigi.unpark_decoder()
        except Exception:
            pass
        # Put the console palette back. The deck redefines entries in the
        # kernel's palette, which is a property of the console and not of this
        # process: without this, whatever owns tty1 next inherits the scheme.
        try:
            colors.restore()
        except Exception:
            pass
        try:
            if deck.touch is not None:
                deck.touch.close()
        except Exception:
            pass
        try:
            curses.noraw()
        except curses.error:
            pass


def _leave_cleanly(signum, _frame):
    """Turn a stop signal into an ordinary exit, so the shutdown code runs.

    **ncurses installs its own SIGTERM and SIGINT handlers in `initscr`, and
    they call `exit(1)` from inside the handler.** So a `systemctl stop` or
    `restart` tore the process down without unwinding: `main`'s `finally`
    never ran, and with it none of

      * `fldigi.abort()` -- a keyed transmitter stayed keyed,
      * `unpark_decoder()` -- fldigi was left holding `NULL` whenever the
        radio happened to be in SSB at the moment of the restart,
      * `colors.restore()` -- the console palette is a property of the
        console, not of this process, so whatever owned tty1 next inherited
        the deck's scheme,
      * `touch.close()`.

    It is also why the journal read `code=exited, status=1/FAILURE` after
    every restart, which looks exactly like a crash and is not one: a plain
    curses program with no deck code in it does the same thing.

    Raising rather than exiting is the whole point: `SystemExit` unwinds the
    stack, the `finally` runs, and the process leaves with 0.

    **Installed BEFORE `curses.wrapper`,** because ncurses only takes a
    signal whose disposition is still the default -- `CatchIfDefault` in its
    own source. Installing it afterwards would be overridden; installing it
    first means ncurses leaves it alone.
    """
    raise SystemExit(0)


def run():
    try:
        settings = configmod.load()
    except configmod.ConfigError as exc:
        print(f"cyberdeck.conf: {exc}", file=sys.stderr)
        return 1
    # Non-fatal configuration problems. stderr goes to the journal rather than
    # to tty1, so these are readable after the panel has taken the screen.
    for note in configmod.NOTES:
        print(f"cyberdeck: {note}", file=sys.stderr)
    # SIGHUP as well as SIGTERM: the unit sets `TTYVHangup=yes`, so stopping
    # it hangs up tty1 and the foreground process group gets a SIGHUP it
    # should treat the same way.
    for sig in (signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(sig, _leave_cleanly)
        except (OSError, ValueError):
            # A platform or a thread that will not take the handler is not a
            # reason to refuse to start; it only means the shutdown is as
            # abrupt as it used to be.
            pass
    curses.wrapper(main, settings)
    return 0


if __name__ == "__main__":
    sys.exit(run())
