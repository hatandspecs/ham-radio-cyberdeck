"""Decoding stops when the radio is not in a data mode, and comes back.

fldigi decodes whatever is on its sound card whether or not the radio is in a
mode that could be carrying it. On a Pi 3A+ that DSP is the deck's largest
continuous cost, and in SSB or FM it buys nothing: anything decoded is noise,
and transmit is interlocked off anyway.

Tested against the stand-in fldigi rather than the real one, because what is
being tested is a sequence of XML-RPC calls -- which modem is loaded, when,
and what the carrier is afterwards -- and the stand-in records every call it
is sent. Driving the real fldigi would also change the modem of whatever the
operator had running.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
from fake_fldigi import FakeFldigi
import fldigi_client
import qsolog


def client(modem="BPSK31", carrier=1500):
    fake = FakeFldigi(modem=modem, carrier=carrier).start()
    return fake, fldigi_client.Fldigi(url=fake.url, timeout=2.0)


print("parking stops the decoder and remembers what to come back to")
fake, f = client()
equals("it starts on the operator's modem", f.modem(), "BPSK31")
check("and reports itself unparked", not f.decoder_parked, "")
equals("parking succeeds", f.park_decoder(), True)
equals("fldigi is actually on NULL", fake.state.modem, "NULL")
check("so no decoder is running", fake.state.modem == "NULL", fake.state.modem)
check("and it reports itself parked", f.decoder_parked, "")

print("\nthe modem it REPORTS is still the operator's")
# Every caller wants this answer: the panel shows what the operator chose, the
# mode picker marks it current, and the log records what a contact was made
# on. A screen reading NULL would say the deck had lost its mode.
equals("modem() answers BPSK31", f.modem(), "BPSK31")
equals("and modem_loaded() answers the truth", f.modem_loaded(), "NULL")

print("\nunparking puts the modem and the carrier back")
# The carrier matters: fldigi moves it to the new modem's own sweet spot
# whenever a modem is loaded, so coming back without restoring it would land
# the operator somewhere other than the signal they had tuned onto.
fake.state.carrier = 40
equals("it says which modem came back", f.unpark_decoder(), "BPSK31")
equals("fldigi is on it", fake.state.modem, "BPSK31")
equals("and the carrier is back where it was", fake.state.carrier, 1500)
check("and it reports itself unparked", not f.decoder_parked, "")

print("\nunparking when nothing is parked does nothing")
before = len(fake.state.calls)
equals("it answers with no modem", f.unpark_decoder(), "")
equals("and sent no call", len(fake.state.calls), before)
equals("the modem is untouched", fake.state.modem, "BPSK31")

print("\nparking twice is parking once")
f.park_decoder()
fake.state.carrier = 700
equals("the second park is a no-op that still reports parked",
       f.park_decoder(), True)
equals("so the modem to come back to is the original", f.modem(), "BPSK31")
f.unpark_decoder()
equals("and the carrier restored is the one from before the FIRST park",
       fake.state.carrier, 1500)
fake.stop()

print("\nchoosing a modem while parked records it instead of loading it")
# Applying it would start the decoder the park exists to stop, and the next
# poll would park it again -- so the deck would fight the operator.
fake, f = client(modem="BPSK31")
f.park_decoder()
f.set_modem("RTTY")
equals("fldigi is still on NULL", fake.state.modem, "NULL")
equals("but the choice is what modem() reports", f.modem(), "RTTY")
equals("and it is what comes back", f.unpark_decoder(), "RTTY")
equals("fldigi is on it now", fake.state.modem, "RTTY")
fake.stop()

print("\nwithout a NULL modem nothing is changed")
# A park that cannot be undone cleanly is worse than a decoder left running,
# so an fldigi offering no NULL modem is left alone.
fake, f = client(modem="BPSK31")
original = fake.state._dispatch


def no_null(method, params):
    if method == "modem.get_names":
        return ["CW", "BPSK31", "RTTY"]
    return original(method, params)


fake.state._dispatch = no_null
equals("the park refuses", f.park_decoder(), False)
equals("the modem is untouched", fake.state.modem, "BPSK31")
check("and it does not claim to be parked", not f.decoder_parked, "")
fake.stop()

print("\nparking is refused when the modem cannot be read")
fake, f = client(modem="NULL")
equals("already on NULL is nothing to park", f.park_decoder(), False)
check("and it does not claim to be parked", not f.decoder_parked, "")
fake.stop()

print("\nthe data modes that keep the decoder running")
# The same set the transmit interlock uses, so the two cannot disagree about
# what counts as a data mode -- which is the whole point of one set.
for mode in ("DATA-U", "PKTUSB", "DIGU", "RTTY"):
    check(f"{mode} is a data mode", mode in qsolog.RIG_DATA_MODES, mode)
for mode in ("USB", "LSB", "FM", "CW", "AM"):
    check(f"{mode} is not", mode not in qsolog.RIG_DATA_MODES, mode)


# -- through the real program --------------------------------------------
#
# The two halves above prove the client can park and that the data-mode set is
# the right one. Neither proves the deck ever CALLS it: `_watch_rig_mode` used
# to return early whenever transmit was already inhibited, which is the common
# case, so a decoder left running would never have been stopped. That is a
# dispatch fault and only the real program shows it.

import json
import shutil
import tempfile
import threading

from fake_fldigi import free_port
from test_screen import run

# The deck boots on DECK & RIG, and the note this test reads is written to the
# TRANSCRIPT. `^O` wraps the ring backwards from the boot screen straight to
# the conversation -- the log is not on the ring while logging is off, which
# it is in this fixture.
TO_CHAT = "\x0f"

_PROJECT = os.path.dirname(_HERE)


def conf_pointing_at(tmp, url, extra=""):
    """The project's own configuration, with fldigi moved to `url`.

    Copied rather than written from scratch, for the reason test_cold_boot
    copies it: a hand-made minimal config drifts from the real one, and the
    point is to start the deck the way it actually starts.
    """
    src = os.path.join(_PROJECT, "cyberdeck.conf")
    lines = []
    if os.path.exists(src):
        with open(src, encoding="utf-8") as fh:
            lines = [l for l in fh if not l.split("#", 1)[0].strip()
                     .upper().startswith("FLDIGI_URL")]
    dst = os.path.join(tmp, "cyberdeck.conf")
    with open(dst, "w", encoding="utf-8") as fh:
        fh.writelines(lines)
        fh.write(f"\nFLDIGI_URL = {url}\n{extra}")
    return dst


def modems_set(state):
    """Every modem the deck loaded, in order. From the call log, not the
    final state.

    The deck UNPARKS on its way out -- a deck that quits must not leave the
    operator's fldigi holding a modem they never chose -- so by the time the
    stand-in can be read, the modem is back to the operator's and the park is
    invisible. The call log still has it, and the sequence is the stronger
    assertion anyway: it shows the park AND the restore, in order.
    """
    return [p[0] for m, p in state.calls if m == "modem.set_by_name" and p]


def deck_against(rig_mode, modem="BPSK31", keys=(), settle=4.0):
    """Start the deck against a stand-in fldigi whose radio is in `rig_mode`.

    Returns (screen text, the stand-in's state) with the stand-in stopped, so
    a caller can assert on what the deck asked it to do.
    """
    tmp = tempfile.mkdtemp(prefix="cyberdeck-park-")
    fake = None
    try:
        port = free_port()
        conf = conf_pointing_at(tmp, f"http://127.0.0.1:{port}/RPC2")
        state = os.path.join(tmp, "state", "cyberdeck.json")
        os.makedirs(os.path.dirname(state), exist_ok=True)
        with open(state, "w", encoding="utf-8") as fh:
            json.dump({"mode": modem, "carrier": 1500}, fh)
        fake = FakeFldigi(modem=modem, carrier=1500, port=port,
                          rig_mode=rig_mode).start()
        screen = run(keys=list(keys), state_path=state, conf=conf,
                     settle=settle, settle_s="0.2")
        return "\n".join(screen.display), fake.state
    finally:
        if fake is not None:
            fake.stop()
        shutil.rmtree(tmp, ignore_errors=True)


print("\nthe radio in a data mode leaves the decoder alone")
body, state = deck_against("PKTUSB", keys=[TO_CHAT])
equals("fldigi is left on the operator's modem", state.modem, "BPSK31")
check("NULL was never loaded", "NULL" not in modems_set(state),
      str(modems_set(state)))
check("and nothing was said about it",
      "decoding off" not in body, body[-500:])

print("\nthe radio in SSB parks the decoder by itself")
body, state = deck_against("USB", keys=[TO_CHAT])
loaded = modems_set(state)
check("fldigi was told to load NULL", "NULL" in loaded, str(loaded))
check("and the operator's modem came back on the way out",
      loaded[-1] == "BPSK31", str(loaded))
equals("so the stand-in is left on it", state.modem, "BPSK31")
check("the deck said the rig is not in a data mode",
      "not a data mode" in body, body[-700:])
check("and that decoding went off", "decoding off" in body, body[-700:])
check("and that it comes back by itself",
      "decoding returns with the rig" in body, body[-700:])
# Not the whole phrase: the transcript wraps at 66 columns and "transmit"
# lands on the next line, so a longer substring would fail on the wrap rather
# than on the behavior.
check("while transmit needs Ctrl-I", "Ctrl-I to arm" in body, body[-700:])
check("the panel still shows the radio's mode, not NULL",
      "NULL" not in body, body[-600:])

print("\nand in FM, which is the other way to get it wrong")
body, state = deck_against("FM")
check("fldigi was told to load NULL", "NULL" in modems_set(state),
      str(modems_set(state)))

print("\nno CAT answer at all is not a reason to stop decoding")
# A deck without CAT control reads no mode, and refusing on an absence of
# evidence would take decoding away from every such station -- the same
# reasoning `_rig_mode_ok` already applies to transmit.
body, state = deck_against("")
check("NULL was never loaded", "NULL" not in modems_set(state),
      str(modems_set(state)))
equals("the decoder is left running", state.modem, "BPSK31")




# -- the unpark survives a systemd stop ----------------------------------
#
# **ncurses installs its own SIGTERM handler in `initscr`, and it calls
# `exit(1)` from inside the handler.** So before `_leave_cleanly` existed, a
# `systemctl restart` tore the process down without unwinding: the `finally`
# in `main` never ran, and the decoder stayed parked on `NULL` for whatever
# owned fldigi next. The operator's fldigi was left holding a modem they
# never chose, and nothing on the deck would put it back -- the next start
# reads the modem to decide whether its own restore took.
#
# This is the one case the test above cannot reach, because `test_screen.run`
# ends with Ctrl-Q and that is the clean path that always worked.

import signal


def stop_with_signal(rig_mode, sig, modem="BPSK31", settle=4.0):
    """Start the deck, send it `sig`, and report (exit status, the stand-in).

    Returns the raw wait status so a caller can tell "exited 0" from "killed
    by the signal" -- which is the distinction the whole fix is about.
    """
    import select
    import struct
    import termios
    import fcntl
    tmp = tempfile.mkdtemp(prefix="cyberdeck-stop-")
    fake = None
    try:
        port = free_port()
        conf = conf_pointing_at(tmp, f"http://127.0.0.1:{port}/RPC2")
        state = os.path.join(tmp, "state", "cyberdeck.json")
        os.makedirs(os.path.dirname(state), exist_ok=True)
        with open(state, "w", encoding="utf-8") as fh:
            json.dump({"mode": modem, "carrier": 1500}, fh)
        fake = FakeFldigi(modem=modem, carrier=1500, port=port,
                          rig_mode=rig_mode).start()

        pid, fd = os.forkpty()
        if pid == 0:                      # pragma: no cover - the child execs
            os.environ["TERM"] = "linux"
            os.environ["CYBERDECK_STATE_PATH"] = state
            os.environ["CYBERDECK_STATE_SETTLE_S"] = "0.2"
            os.environ["CYBERDECK_CONF"] = conf
            os.environ["LINES"], os.environ["COLUMNS"] = "20", "66"
            os.chdir(_PROJECT)
            os.execvp(sys.executable,
                      [sys.executable,
                       os.path.join(_PROJECT, "src", "cyberdeck.py")])
        fcntl.ioctl(fd, termios.TIOCSWINSZ,
                    struct.pack("HHHH", 20, 66, 0, 0))

        def drain(seconds):
            end = time.time() + seconds
            while time.time() < end:
                r, _, _ = select.select([fd], [], [], 0.1)
                if r:
                    try:
                        if not os.read(fd, 65536):
                            return
                    except OSError:
                        return

        drain(settle)
        os.kill(pid, sig)
        # Reap with a real deadline and keep draining, so the child is never
        # blocked writing while it shuts down. The first version of this read
        # a stale WNOHANG result from a loop that broke on EOF and reported a
        # process that had already exited as still running.
        deadline, status = time.time() + 12.0, None
        while time.time() < deadline:
            r, _, _ = select.select([fd], [], [], 0.1)
            if r:
                try:
                    os.read(fd, 65536)
                except OSError:
                    pass
            done, st = os.waitpid(pid, os.WNOHANG)
            if done:
                status = st
                break
        try:
            os.close(fd)
        except OSError:
            pass
        if status is None:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        return status, fake.state
    finally:
        if fake is not None:
            fake.stop()
        shutil.rmtree(tmp, ignore_errors=True)


import time  # noqa: E402  - used by the drain loops above

for sig in (signal.SIGTERM, signal.SIGHUP):
    name = signal.Signals(sig).name
    print(f"\n{name} unwinds instead of killing the process")
    status, state = stop_with_signal("USB", sig)
    check(f"{name}: it exited rather than dying by the signal",
          status is not None and not os.WIFSIGNALED(status), repr(status))
    equals(f"{name}: and exited 0, so the journal says SUCCESS",
           os.WEXITSTATUS(status) if status is not None else None, 0)
    loaded = modems_set(state)
    # The park happened (the radio is in USB) and then the shutdown undid it.
    check(f"{name}: the decoder had been parked", "NULL" in loaded,
          str(loaded))
    check(f"{name}: and the operator's modem was put back last",
          loaded[-1] == "BPSK31", str(loaded))
    equals(f"{name}: so fldigi is left on it", state.modem, "BPSK31")

report()
