"""A keyed transmitter that nothing could unkey -- panel report 2026-11-24.

What the operator saw, in order: an over sent on PSK31 that keyed the radio
and put nothing on the air; Ctrl-C pressed a dozen times, each printing
"transmit aborted", none of them stopping the carrier; a band change that
eventually cleared it; the same thing again on the next attempt; and finally
the radio switched off at the front panel.

Four separate defects, each verified in the source and each fixed:

* `unpark_decoder` cleared `_parked_modem` BEFORE the `modem.set_by_name` it
  depended on. `_call` swallows every error, so a failed unpark left fldigi
  on `NULL`, reported the modem's name as though it had worked, and -- with
  the bookkeeping already gone -- never retried. That is the root cause of
  "keyed and sending nothing": `_digi_mode_ok` reads the RADIO's mode, which
  was right, and never asks what modem fldigi has.
* `start_over` called `main.tx` unconditionally. A timed-out `text.add_tx`
  followed by a successful `main.tx` -- plausible, because `_call` builds a
  fresh proxy after a failure -- keys the radio with an empty widget.
* `abort()` sent `main.abort` and never `main.rx`, and returned None.
  `main.abort` ends a transmission in progress; with nothing in progress PTT
  stayed asserted. `receive_now`, written for exactly this, had no callers
  anywhere in `src/`.
* `session.abort()` clears `_tx_started`, and `tx_timed_out()` is False
  while that is None -- so each failed Ctrl-C disarmed TX_TIMEOUT, the only
  backstop that would have intervened.

These are pure checks against a stub that models trx_state and the loaded
modem, because what has to be asserted is that the deck ASKS the radio
rather than assuming, and a live fldigi would only show the happy path.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report

import cyberdeck
import fldigi_client
import session as session_mod


class FakeRadio:
    """Stands in for the XML-RPC proxy, with state fldigi would really keep.

    `keyed` is what PTT is doing and `modem` is what is loaded, so a test can
    build the exact combination the panel hit: keyed, on NULL, and a deck
    that thinks it is receiving.
    """

    def __init__(self, keyed=False, modem="BPSK31", deaf=(), stays_keyed=False):
        self.keyed = keyed
        self.modem = modem
        self.tx_text = ""
        self.calls = []
        # Names that fail, as a timed-out call does: `_call` returns the
        # default and sets connected False.
        self.deaf = set(deaf)
        # A radio that acknowledges every stop and keeps the carrier up.
        self.stays_keyed = stays_keyed

    def names(self):
        return [n for n, _a in self.calls]

    def __call__(self, name, *args, default=None):
        self.calls.append((name, args))
        if name in self.deaf:
            return default
        if name == "main.tx":
            self.keyed = True
        elif name == "main.rx":
            if not self.stays_keyed:
                self.keyed = False
        elif name == "main.abort":
            if not self.stays_keyed:
                self.keyed = False
        elif name == "text.add_tx":
            self.tx_text += args[0]
        elif name == "text.clear_tx":
            self.tx_text = ""
        elif name == "main.get_trx_state":
            return "TX" if self.keyed else "RX"
        elif name == "modem.set_by_name":
            self.modem = args[0]
        elif name == "modem.get_name":
            return self.modem
        elif name == "modem.get_carrier":
            return 1000
        elif name == "modem.get_names":
            return ["NULL", "BPSK31", "RTTY"]
        return default


def client(radio):
    """A Fldigi wired to `radio`, with `_call` doing the bookkeeping that the
    real one does: connected follows whether the call got through."""
    f = fldigi_client.Fldigi.__new__(fldigi_client.Fldigi)
    f._rx_pos = 0
    f._parked_modem = ""
    f._parked_carrier = 0
    f._null_modem = "NULL"
    f.connected = True
    f.last_error = ""
    f.radio = radio

    def _call(name, *args, default=None):
        out = radio(name, *args, default=default)
        f.connected = name not in radio.deaf
        f.last_error = "" if f.connected else "timeout"
        return out

    f._call = _call
    return f


# ---------------------------------------------------------------------------
print("the root cause: an unpark that forgets before it confirms")

# A set_by_name that does not get through must leave the park in place, so
# the next poll tries again -- and must NOT report a modem that is not back.
radio = FakeRadio(modem="NULL", deaf={"modem.set_by_name"})
f = client(radio)
f._parked_modem = "BPSK31"
equals("a failed unpark reports nothing came back", f.unpark_decoder(), "")
check("and stays parked, so the next poll retries", f.decoder_parked,
      f._parked_modem)
equals("fldigi is still on NULL", radio.modem, "NULL")

# The subtler half: the call gets through and fldigi stays on NULL anyway.
# Reading the modem back is the only way to know.
radio = FakeRadio(modem="NULL")
f = client(radio)
f._parked_modem = "BPSK31"
radio.deaf = set()


def _stubborn(name, *args, default=None):
    """Accepts set_by_name and does not act on it."""
    radio.calls.append((name, args))
    if name == "modem.get_name":
        return "NULL"
    if name == "main.get_trx_state":
        return "RX"
    return default


f._call = _stubborn
equals("a modem that did not actually load reports nothing",
       f.unpark_decoder(), "")
check("and the park is kept", f.decoder_parked, f._parked_modem)

# And the working case still works, which is what the park is for.
radio = FakeRadio(modem="NULL")
f = client(radio)
f._parked_modem = "BPSK31"
f._parked_carrier = 1500
equals("a real unpark reports the modem", f.unpark_decoder(), "BPSK31")
check("the park is released", not f.decoder_parked, f._parked_modem)
equals("fldigi is on it", radio.modem, "BPSK31")
check("and the carrier went back with it",
      ("modem.set_carrier", (1500,)) in radio.calls, radio.calls)

print("\nand the deck can tell a NULL modem from the modem it chose")
radio = FakeRadio(modem="NULL")
f = client(radio)
check("NULL is seen for what it is", f.modem_is_null(), radio.modem)
f._parked_modem = "BPSK31"
equals("while modem() still reports the operator's choice", f.modem(),
       "BPSK31")
check("which is exactly why the keying path asks the other question",
      f.modem_is_null(), "modem_is_null must not consult _parked_modem")

radio = FakeRadio(modem="BPSK31")
f = client(radio)
check("a real modem is not NULL", not f.modem_is_null(), radio.modem)


# ---------------------------------------------------------------------------
print("\nnever key the radio with text that did not land")

radio = FakeRadio(deaf={"text.add_tx"})
f = client(radio)
check("start_over reports it did not send", not f.start_over("CQ DE KD3CCO"),
      radio.names())
check("main.tx was never sent", "main.tx" not in radio.names(),
      radio.names())
check("so the radio is not keyed", not radio.keyed, radio.keyed)

print("\nnor with nothing to send at all")
radio = FakeRadio()
f = client(radio)
check("an empty over is refused", not f.start_over(""), radio.names())
equals("nothing was asked of fldigi", radio.names(), [])
check("the radio is not keyed", not radio.keyed, radio.keyed)

print("\nwhile a good over still goes out exactly as before")
radio = FakeRadio()
f = client(radio)
check("it reports success", f.start_over("CQ DE KD3CCO K"), radio.names())
equals("text first, then key", radio.names(), ["text.add_tx", "main.tx"])
check("the radio is keyed", radio.keyed, radio.keyed)
equals("with the text in the widget", radio.tx_text, "CQ DE KD3CCO K")


# ---------------------------------------------------------------------------
print("\nstopping transmit asks the radio rather than assuming")

radio = FakeRadio(keyed=True)
f = client(radio)
stopped, detail = f.stop_transmit()
check("it confirms the stop", stopped, detail)
check("the radio is unkeyed", not radio.keyed, radio.keyed)
# The escalation, in the order that matters: stop the transmission, drop the
# tail so the next over is its own, then command receive whether or not there
# was a transmission to stop -- and only then believe it.
names = radio.names()
for want in ("main.abort", "text.clear_tx", "main.rx", "main.get_trx_state"):
    check(f"{want} went out", want in names, names)
check("the transmitter is stopped before the text is dropped",
      names.index("main.abort") < names.index("text.clear_tx"), names)
check("receive is commanded explicitly — this was the missing call",
      names.index("text.clear_tx") < names.index("main.rx"), names)
check("and the state is read back only after asking for receive",
      names.index("main.rx") < names.index("main.get_trx_state"), names)

print("\na radio that will not unkey is reported, not papered over")
radio = FakeRadio(keyed=True, stays_keyed=True)
f = client(radio)
stopped, detail = f.stop_transmit(tries=2)
check("it does not claim to have stopped", not stopped, detail)
check("the detail says what fldigi reports", "TX" in detail, detail)
equals("it tried twice before giving up", radio.names().count("main.rx"), 2)

print("\nand so is a radio that cannot be reached")
radio = FakeRadio(keyed=True, deaf={"main.abort", "text.clear_tx", "main.rx",
                                    "main.get_trx_state"})
f = client(radio)
stopped, detail = f.stop_transmit(tries=2)
check("it does not claim to have stopped", not stopped, detail)
check("and says fldigi did not answer", "did not answer" in detail, detail)


# ---------------------------------------------------------------------------
print("\nforce_unpark gets a real modem loaded whatever the bookkeeping says")

radio = FakeRadio(modem="NULL")
f = client(radio)
f._parked_modem = "RTTY"
equals("the parked modem comes back", f.force_unpark(), "RTTY")
check("and the park is released", not f.decoder_parked, f._parked_modem)

# The state the panel actually reached: on NULL with nothing parked, because
# the park was forgotten by the old unpark. Nothing in the old code could get
# out of this; the reset has to.
radio = FakeRadio(modem="NULL")
f = client(radio)
equals("with nothing parked, the fallback is used",
       f.force_unpark("BPSK31"), "BPSK31")
equals("and fldigi is on it", radio.modem, "BPSK31")

radio = FakeRadio(modem="NULL")
f = client(radio)
got = f.force_unpark()
check("with no fallback either, the first non-NULL modem is loaded",
      got and got.upper() != "NULL", got)


# ---------------------------------------------------------------------------
print("\nCtrl-C does not drop to receive until the radio says so")


def deck(radio, state=session_mod.TX):
    d = cyberdeck.Deck.__new__(cyberdeck.Deck)
    d.cfg = {"TX_TIMEOUT": 180, "DEFAULT_MODE": "BPSK31"}
    d.fldigi = client(radio)
    d.session = session_mod.Session("KD3CCO", tx_timeout=180)
    d.session.state = state
    if state == session_mod.TX:
        d.session._tx_started = d.session._clock()
    d._tx_echo = ""
    d._tx_seen = False
    d._tx_idle = 0
    d._handed_at = None
    d._drain_warned = 0.0
    d._stuck_polls = 0
    d._stuck_warned = 0.0
    d._settling = False
    d._settle_good = 0
    d._rx_tail = ""
    d.scroll = 0
    d._saved_mode = ""
    d._boot_mode = ""
    return d


def notes(d):
    """Everything the deck said, as one string. `notices` is the session's own
    list of them, which is cheaper to read than filtering the transcript."""
    return " | ".join(d.session.notices)


radio = FakeRadio(keyed=True)
d = deck(radio)
check("a confirmed stop returns True", d._panic_unkey(), notes(d))
equals("the session is in receive", d.session.state, session_mod.RX)
check("the timer is disarmed, because the radio really did stop",
      d.session._tx_started is None, d.session._tx_started)
check("and it says the radio was confirmed",
      "confirmed in receive" in notes(d), notes(d))

print("\nbut a failed Ctrl-C leaves TX_TIMEOUT armed — this is the fix")
radio = FakeRadio(keyed=True, stays_keyed=True)
d = deck(radio)
check("it reports failure", not d._panic_unkey(), notes(d))
check("the operator is told the radio may still be keyed",
      "RADIO MAY STILL BE KEYED" in notes(d), notes(d))
check("the TX timer is STILL ARMED, so the backstop can fire",
      d.session._tx_started is not None,
      "a failed abort must not disarm TX_TIMEOUT")
check("and the reset key is named", "^R" in notes(d), notes(d))


# ---------------------------------------------------------------------------
print("\na carrier up with no over running is noticed and acted on")

# The state that ran until the radio was switched off: fldigi keyed, this
# side in receive, and -- before this -- nothing in the deck watching for it.
radio = FakeRadio(keyed=True)
d = deck(radio, state=session_mod.RX)
for _ in range(cyberdeck.STUCK_TX_POLLS - 1):
    d._watch_stuck_carrier(True)
equals("it waits before acting — trx_state lags a start_over",
       radio.names().count("main.rx"), 0)
d._watch_stuck_carrier(True)
check("then it stops the radio", not radio.keyed, radio.keyed)
check("and says what it found", "keyed with no over running" in notes(d),
      notes(d))

print("\nand a radio that holds the carrier is reported every few seconds")
radio = FakeRadio(keyed=True, stays_keyed=True)
d = deck(radio, state=session_mod.RX)
for _ in range(cyberdeck.STUCK_TX_POLLS):
    d._watch_stuck_carrier(True)
check("it says the radio is still keyed", "RADIO STILL KEYED" in notes(d),
      notes(d))
check("and names the reset", "^R" in notes(d), notes(d))
# Not on every poll: five notices a second would bury the transcript the
# operator needs to read.
before = notes(d).count("RADIO STILL KEYED")
for _ in range(20):
    d._watch_stuck_carrier(True)
equals("but not on every poll", notes(d).count("RADIO STILL KEYED"), before)

print("\na legitimate over is not mistaken for a stuck one")
radio = FakeRadio(keyed=True)
d = deck(radio, state=session_mod.TX)
for _ in range(cyberdeck.STUCK_TX_POLLS * 2):
    d._watch_stuck_carrier(True)
check("an over in progress is left alone", radio.keyed, radio.keyed)
equals("nothing was sent to fldigi", radio.names().count("main.rx"), 0)

print("\nnor is a hand back still draining")
radio = FakeRadio(keyed=True)
d = deck(radio, state=session_mod.RX)
d._handed_at = 1.0
for _ in range(cyberdeck.STUCK_TX_POLLS * 2):
    d._watch_stuck_carrier(True)
check("a drain after Ctrl-Y is left to _watch_drain", radio.keyed,
      radio.keyed)
equals("and nothing was sent", radio.names().count("main.rx"), 0)


# ---------------------------------------------------------------------------
print("\nCtrl-R puts the digimode side back to something knowable")

radio = FakeRadio(keyed=True, modem="NULL")
d = deck(radio, state=session_mod.RX)
d._tx_echo = "half an over"
d._tx_seen = True
d._handed_at = 99.0
d._rx_tail = "old decodes"
check("the reset confirms the radio stopped", d._reset_digimodes(), notes(d))
check("the radio is unkeyed", not radio.keyed, radio.keyed)
check("a real modem is loaded", radio.modem.upper() != "NULL", radio.modem)
equals("the transmit echo is cleared", d._tx_echo, "")
check("the drain watch is cleared", d._handed_at is None, d._handed_at)
check("the decode preview is cleared", d._rx_tail == "", d._rx_tail)
check("the TX timer is disarmed", d.session._tx_started is None,
      d.session._tx_started)
check("and it says what it did", "digimodes reset" in notes(d), notes(d))

print("\nand says so plainly when it cannot stop the radio")
radio = FakeRadio(keyed=True, modem="NULL", stays_keyed=True)
d = deck(radio, state=session_mod.RX)
check("it reports failure", not d._reset_digimodes(), notes(d))
check("naming the one thing left to do",
      "RADIO MAY STILL BE KEYED" in notes(d), notes(d))

sys.exit(report())
