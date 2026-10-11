#!/usr/bin/env python3
"""Keyboard-to-keyboard terminal for fldigi.

The only thing on the screen: a status line, the conversation, and what is
being typed. No window manager, no pointer, nothing to click. fldigi does the
modem work invisibly behind an XML-RPC connection (docs/design_doc.md §4).

Run it over SSH for development; on the deck it runs on tty1 against the
framebuffer, where the color schemes use the real palette.
"""

import curses
import datetime
import json
import os
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
        self.screen = CHAT
        # Logging. Off means absent: no file is opened, no form is built and
        # Ctrl-N falls through to the unhandled-key branch, exactly as an
        # unused key does (docs/qso_log_design.md §1).
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
        # over. Cleared with Ctrl-I, or F1 6 i.
        if settings["INHIBIT_ON_START"] == "yes":
            self.session.inhibit(True)
            self.fldigi.receive_only(True)
            self.session.note("transmit INHIBITED at startup — Ctrl-I to enable")

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
            # when the over completes. See docs/design_doc.md §5.5 for why this is
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

        self._set_rig_mode()
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
                self._rig = rigctld_client.Rigctld()
            except Exception:
                return None
        return self._rig

    def _log_freq_mhz(self):
        rig = self._log_rig()
        if rig is None:
            return ""
        try:
            hz = rig.frequency()
        except Exception:
            return ""
        return f"{hz / 1_000_000:.3f}" if hz else ""

    def _log_freq_hz(self):
        """Hertz from whatever is in the form, which may have been corrected."""
        try:
            return int(round(float(self.log_form.value("freq")) * 1_000_000))
        except (TypeError, ValueError, AttributeError):
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
        header = {"count": len(self.log_records),
                  "clock": time.strftime("%H%MZ", time.gmtime())}
        if form is not None:
            form.from_radio(freq=self._log_freq_mhz(), mode=self._log_mode())
            if form.activity.name != "GENERAL":
                header["activity"] = form.activity.name
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
        arrived = self._lookup_collect(form)
        if arrived:
            self.log_message = arrived

        message = self.log_message
        if form is not None and not message:
            note = qsolog.dupe_note(qsolog.find_dupes(
                self.log_records, form.value("call"),
                band=header.get("band", ""), mode=form.value("mode"),
                rule=self.cfg.get("DUPE_CHECK", "band+mode"),
                activity=("" if form.activity.name == "GENERAL"
                          else form.activity.name)))
            if note:
                message = f"** {note}"

        for i, line in enumerate(render.log_screen(
                self.log_records, "", w, h, header=header,
                message=message, form=form)):
            self._put(i, 0, line, w)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

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
        self.picker_sel = 0
        self.picker_message = ""
        self.screen = FIELDS
        self._close_menu()

    def _draw_fields(self, h, w):
        for i, line in enumerate(render.field_select_screen(
                self.picker.rows(), self.picker_sel, w, h,
                title=f"SELECT FIELDS — from {self.picker_from}")):
            self._put(i, 0, line, w)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def _handle_fields(self, ch):
        rows = self.picker.rows()
        if ch == 27:
            self.picker = None
            self.screen = LOG
        elif ch == curses.KEY_UP:
            self.picker_sel = (self.picker_sel - 1) % len(rows)
        elif ch == curses.KEY_DOWN:
            self.picker_sel = (self.picker_sel + 1) % len(rows)
        elif ch in (32, 10, 13, curses.KEY_ENTER) and ch == 32:
            self.picker.toggle(rows[self.picker_sel][0])
        elif ch in (10, 13, curses.KEY_ENTER):
            if not self.picker.entry():
                # An activity with no fields is a form with nothing but a
                # callsign on it. Refusing here is kinder than letting it be
                # saved and discovered mid-contact.
                self.session.note("choose at least one field")
                return True
            self.picker_sel = 0
            self.screen = ORDER
        elif 49 <= ch <= 57:                              # 1-9
            at = ch - 49
            if at < len(rows):
                self.picker_sel = at
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
            self._open_editor(None, "Name for this activity",
                              sink=self._save_activity)
        return True

    def _save_activity(self, name):
        """Write the built activity out, then select it."""
        name = "".join(c for c in (name or "").strip().upper()
                       if c.isalnum() or c in "-_")
        if not name:
            self.session.note("an activity needs a name")
            return
        if name in ("GENERAL",):
            self.session.note("GENERAL is the built-in; pick another name")
            return
        base = activities.get(self.picker_from, self._activity_table())
        text = activities.format_activity(
            name, self.picker.entry(),
            label=f"{name} (from {base.label})",
            sig=base.sig, contest_id=base.contest_id,
            serial=base.serial, serial_start=base.serial_start,
            labels={f: base.label_for(f) for f in self.picker.entry()
                    if base.label_for(f) != activities.ENTRY_FIELDS.get(
                        f, (None, f))[1]})
        try:
            path = activities.save(activities.config_path(), name, text)
        except OSError as exc:
            self.session.note(f"could not save: {exc}")
            return
        self.picker = None
        self.session.note(f"saved {name} to {path}")
        self._set_activity(name)
        self.screen = LOG

    def _lookup_start(self, call):
        """Ask the callbooks about a callsign, off the interface thread.

        Fired when focus leaves the callsign field rather than on every
        keystroke: `W`, `W3`, `W3A` are not callsigns, and asking about them
        sends three useless requests and three partial callsigns to a third
        party.
        """
        if self.cfg.get("CALLBOOK") != "yes":
            return
        call = (call or "").strip().upper()
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
        for key in ("name", "qth", "grid"):
            field = form.field(key)
            if field is not None and info.get(key) and not field.value:
                form.set(key, info[key])
        # Reported whether or not a field took it: the grid reaches the record
        # even on an activity whose form has nowhere to show it.
        return "-- " + ", ".join(f"{k}={v}" for k, v in info.items())

    def _activity_table(self):
        """Every activity, built-in and defined. Never raises at the menu.

        A broken activities.conf must not make the menu unopenable — the
        built-ins are a working set on their own, and the operator finds out
        from a note rather than from a screen that will not come up.
        """
        try:
            return activities.load()
        except Exception as exc:
            self.session.note(f"activities.conf: {exc}")
            return dict(activities.BUILTIN)

    def _has_tqsl(self):
        if self._tqsl is None:
            try:
                import lotw
                self._tqsl = lotw.available()
            except Exception:
                self._tqsl = False
        return self._tqsl

    def _set_activity(self, name, table=None):
        """Switch activity, rebuilding the form because its fields change.

        What this station sends is carried across — own reference, own
        exchange, the standing comment — because those describe the operating
        session rather than the activity, and retyping them after changing
        activity is exactly the kind of thing that makes an operator not
        change activity.
        """
        act = activities.get(name, table or self._activity_table())
        self.cfg["ACTIVITY"] = "" if act.name == "GENERAL" else act.name
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
        self.log_form.advance_serial(self.log_records, act.serial_start)
        self._save_state()
        self.session.note(f"activity: {act.label}")

    def _set_my_park(self, value):
        self.cfg["MY_PARK"] = (value or "").strip().upper()
        if self.log_form is not None:
            self.log_form.set("my_park", self.cfg["MY_PARK"])
        self._save_state()

    def _export_adif(self, lotw=False):
        """Write the whole log beside itself as ADIF, and say where."""
        path = qsolog.log_path(self.cfg.get("LOG_PATH", ""))
        records = qsolog.read(path)
        if not records:
            self.session.note("nothing logged yet")
            return
        out = os.path.splitext(path)[0] + ".adi"
        try:
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(qsolog.adif_export(records))
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as exc:
            self.session.note(f"could not write {out}: {exc}")
            return
        self.session.note(f"{len(records)} contacts to {out}")
        if lotw:
            # Printed, never run. tqsl needs a callsign certificate and blocks
            # rather than failing without one, and a signing key does not
            # belong on a card that travels (qso_log_design.md §11).
            try:
                import lotw as lotwmod
                self.session.note("sign it with: " + lotwmod.quoted_command(
                    out, location=self.cfg.get("LOTW_LOCATION", ""),
                    upload=True))
            except Exception:
                pass

    def _open_log(self):
        if not self.log_on:
            self.session.note("logging is off — switch it on from the menu")
            return
        path = qsolog.log_path(self.cfg.get("LOG_PATH", ""))
        if self.log_form is None:
            table = activities.load()
            act = activities.get(self.cfg.get("ACTIVITY", ""), table)
            self.log_form = logform.LogForm(act)
            if self.cfg.get("MY_PARK"):
                self.log_form.set("my_park", self.cfg["MY_PARK"])
            if self.cfg.get("EXCHANGE_TX"):
                self.log_form.set("exchange_tx", self.cfg["EXCHANGE_TX"])
        self.log_records = qsolog.read(path)
        self.log_form.advance_serial(self.log_records,
                                     self.log_form.activity.serial_start)
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
            my_park=values.get("my_park", ""), activity=form.activity,
            serial_tx=values.get("serial_tx", ""),
            exchange_tx=values.get("exchange_tx", ""),
            my_rig=self.cfg.get("RIG", ""),
            my_antenna=self.cfg.get("ANTENNA", ""),
            tx_power=watts or self.cfg.get("TX_POWER", 0))

        try:
            qsolog.append(qsolog.log_path(self.cfg.get("LOG_PATH", "")), rec)
        except OSError as exc:
            # The one failure that must never be quiet: the contact is gone,
            # and the form is left alone so it can be tried again.
            self.log_message = f"-- NOT LOGGED: {exc}"
            return

        self.log_records.append(rec)
        self._looked_up = ""
        form.commit()
        form.advance_serial(self.log_records, form.activity.serial_start)
        self.log_message = (f"-- logged {rec['call']} {rec.get('band', '')} "
                            f"{rec.get('mode', '')}").rstrip()

    def _handle_log(self, ch):
        form = self.log_form
        if form is None:
            self.screen = CHAT
            return True

        if ch == 27:                                    # Esc
            self.screen = CHAT
        # The function keys are otherwise dead here, and F1 means "menu"
        # everywhere else on the deck. It opens the LOGGING menu rather than
        # the root one, because that is what is being configured from this
        # screen; the root menu is one Esc away from it.
        elif ch == curses.KEY_F1:
            self._open_menu("logging")
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
        elif ch == curses.KEY_LEFT:
            form.left()
        elif ch == curses.KEY_RIGHT:
            form.right()
        elif ch == curses.KEY_HOME:
            form.home()
        elif ch == curses.KEY_END:
            form.end()
        elif ch == curses.KEY_UP:
            form.tab(back=True)
        elif ch == curses.KEY_DOWN:
            form.tab()
        elif 32 <= ch < 127:
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
            "mode": f.modem(),
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
            "rig_mode": f.rig_mode(),
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
        if m == "root":
            return menus.ROOT
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
        if m == "station":
            return menus.station_menu(self.cfg)
        if m == "memories":
            return menus.memories_menu(self.cfg)
        if m == "logging":
            act = (self.log_form.activity.name if self.log_form
                   else self.cfg.get("ACTIVITY", ""))
            park = (self.log_form.value("my_park") if self.log_form
                    else self.cfg.get("MY_PARK", ""))
            return menus.log_menu(
                self.log_on, count=len(self.log_records), park=park,
                lookup=self.cfg.get("CALLBOOK") == "yes",
                has_qrz_key=bool(self.cfg.get("QRZ_API_KEY")),
                operating=self.cfg.get("OPERATING", "auto"),
                dupe=self.cfg.get("DUPE_CHECK", "band+mode"),
                has_tqsl=self._has_tqsl(),
                activity="" if act == "GENERAL" else act)
        if m == "activity":
            table = self._activity_table()
            current = (self.log_form.activity.name if self.log_form
                       else self.cfg.get("ACTIVITY", ""))
            return menus.activity_menu(sorted(table), current,
                                       {n: table[n].label for n in table})
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

        if self.screen == TUNE:
            return self._handle_tune(ch)

        if ch == curses.KEY_F1:
            self._open_menu("root")
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
        elif ch == curses.KEY_F4:
            self._apply_scheme(colors.cycle(self.scheme))
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
        elif ch == 9:                        # Ctrl-I, and Tab: same byte
            self._toggle_inhibit()
        elif ch == 24:                       # Ctrl-X
            self._clear_transcript()
        # Ctrl-N opens the log. Bound only when logging is on: off, this falls
        # through to the unhandled-key branch exactly as any unused key does,
        # which is what "absent when off" means in practice.
        elif ch == 14 and self.log_on:       # Ctrl-N
            self._open_log()
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
        for key, field in (("rx_hold_ms", "RX_HOLD_MS"),
                           ("rx_hold_max_ms", "RX_HOLD_MAX_MS")):
            hold = state.get(key)
            if isinstance(hold, int) and 0 <= hold <= 5000:
                self.cfg[field] = hold
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
            "rx_hold_ms": self.cfg.get("RX_HOLD_MS", 0),
            "rx_hold_max_ms": self.cfg.get("RX_HOLD_MAX_MS", 0),
        }
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

    def _open_menu(self, which):
        self.menu = which
        self.menu_page = 0
        self.menu_sel = self._first_selectable(which)

    def _close_menu(self):
        self.menu = None
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
            self._close_menu() if m in ("root",) else self._open_menu("root")
            if m == "root":
                return True
            return True
        if ch == 17:                                   # Ctrl-Q
            return False
        if ch == curses.KEY_PPAGE and m == "modes_all":
            self.menu_page = max(0, self.menu_page - 1); return True
        if ch == curses.KEY_NPAGE and m == "modes_all":
            self.menu_page += 1; return True

        if m == "root":
            dest = {"1": "mode", "2": "tuning", "3": "radio",
                    "4": "display", "5": "memories", "6": "station",
                    "7": "system", "8": "logging"}.get(key)
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
            scheme = {"1": "matrix", "2": "deckard", "3": "hal",
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
                    self._set_rig_mode()
                self._close_menu()
            return True

        if m == "memories":
            if key.isdigit() and 1 <= int(key) <= 8:
                slot = int(key) + 4
                self._open_editor(f"MEMORY_{slot}", f"F{slot}")
            return True

        if m == "station":
            if key.isdigit() and 1 <= int(key) <= len(menus.STATION_FIELDS):
                field_key, label, _token = menus.STATION_FIELDS[int(key) - 1]
                self._open_editor(field_key, label)
            return True

        if m == "logging":
            if key == "l":
                self.log_on = not self.log_on
                self.cfg["LOGGING"] = "yes" if self.log_on else "no"
                self._save_state()
                self.session.note("logging on — Ctrl-N opens it"
                                  if self.log_on else "logging off")
                if not self.log_on and self.screen == LOG:
                    self.screen = CHAT
            elif key == "v":
                self._open_menu("activity")
            elif key == "n":
                current = (self.log_form.activity.name if self.log_form
                           else self.cfg.get("ACTIVITY", "") or "GENERAL")
                self._copy_activity(current)
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
            return True

        if m == "activity":
            table = self._activity_table()
            names = [n for n in sorted(table) if n != "GENERAL"]
            chosen = ""
            if key == "g":
                chosen = "GENERAL"
            elif key.isdigit() and key != "0" and 0 <= int(key) - 1 < len(names):
                chosen = names[int(key) - 1]
            if chosen:
                self._set_activity(chosen, table)
                self._open_menu("logging")
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

    def _open_editor(self, key, title, secret=False, sink=None):
        """Edit a config field, or — with `sink` — anything else.

        `sink` exists for the WiFi passphrase, which must not take the normal
        path: every other edited field is written into the state file on the
        card, and a passphrase typed here belongs to NetworkManager instead.
        `secret` stops it being drawn, because the deck's screen is a panel
        someone else can be standing behind.
        """
        text = "" if key is None else (self.cfg.get(key, "") or "")
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
                # it. The transcript note says the field, never the value.
                self.edit = None
                self.session.note(f"{e['title']} entered")
                e["sink"](text)
                return True
            self.cfg[e["key"]] = text
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
                self._rig = rigctld_client.Rigctld()
            watts = self._rig.power(max_watts=self.cfg.get("TX_POWER_MAX", 0))
        except Exception:
            # No rigctld, no radio, a hamlib that will not convert: all the
            # same event here, and all fall through to the configuration.
            watts = 0
        if not watts:
            watts = self.cfg.get("TX_POWER", 0) or 0
        return f"{int(watts)} W" if watts else ""

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

    def _set_rig_mode(self):
        """Put the radio into the sideband digital work needs.

        Digital modes are upper sideband on every band, including 40 and 80
        where voice is lower — so this is not something to leave to the
        operator's memory at the moment they change bands. PKTUSB is the
        alternative when the radio's own data mode is wanted; which one is
        right depends on how the FTX-1 is configured to route USB audio.
        """
        want = (self.cfg.get("RIG_MODE") or "").strip()
        if not want:
            return
        current = self.fldigi.rig_mode()
        if current == want:
            return
        available = self.fldigi.rig_modes()
        if available and want not in available:
            self.session.note(f"rig will not take mode {want}; left as {current}")
            return
        self.fldigi.set_rig_mode(want)
        # Say so. Silently changing the radio's mode out from under the
        # operator is how a deck ends up transmitting through the speech
        # processor, or reverts a deliberate choice with no trace.
        self.session.note(f"rig mode {current or '?'} -> {want}")

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
        other half of the behaviour and stays available.
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
        self.session.note(f"mode changed to {self.fldigi.modem()} at {now} Hz")
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


def run():
    try:
        settings = configmod.load()
    except configmod.ConfigError as exc:
        print(f"cyberdeck.conf: {exc}", file=sys.stderr)
        return 1
    curses.wrapper(main, settings)
    return 0


if __name__ == "__main__":
    sys.exit(run())
