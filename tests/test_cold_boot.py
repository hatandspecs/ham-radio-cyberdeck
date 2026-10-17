"""Starting up before fldigi does — which is every power-on of the deck.

The terminal's unit is ordered `After=cyberdeck-fldigi.service`, and that
means only that the fldigi process has been spawned. Under Xvfb on a 3A+ it
takes seconds longer to open its XML-RPC port, and the terminal is drawing a
screen well before then. Everything the deck does to the radio at startup used
to sit behind a single `if self.fldigi.connected` in __init__, evaluated once,
with nothing to retry it.

Two faults came out of that, and the second is why it never recovered on its
own:

  * the remembered mode was never sent, so the deck came up in whatever mode
    fldigi itself had saved — CW on a stock configuration;
  * ten seconds later the saver noticed that CW differed from the nothing it
    had recorded at startup, and wrote CW over the remembered mode. Every
    power cycle destroyed the setting again.

Neither is visible from a restart of the terminal alone, because fldigi is
already up by then. That is exactly why this uses a stand-in fldigi whose
moment of arrival the test chooses.
"""
import os
import sys
import json
import time
import shutil
import tempfile
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

from harness import check, equals, report
from fake_fldigi import FakeFldigi, free_port
from test_screen import run

# The deck opens on its own settings screen. One ^O reaches the conversation:
# the ring is settings | log | digimodes and the log is not on it while
# logging is off, which it is in these fixtures.
# **Two backwards hops, not one.** WSPR made the ring four areas --
# settings | log | digimodes | WSPR -- so one `^O` back from the boot
# screen now wraps onto WSPR and every scenario below read the wrong
# screen. Named here so the next area costs one edit per file.
TO_CHAT = "\x0f\x0f"


def conf_pointing_at(tmp, url):
    """The project's own configuration, with fldigi moved to `url`.

    Copied rather than written from scratch: a hand-made minimal config would
    drift from the real one, and the point is to start the deck as it actually
    starts.
    """
    src = os.path.join(_PROJECT, "cyberdeck.conf")
    dst = os.path.join(tmp, "cyberdeck.conf")
    lines = []
    if os.path.exists(src):
        with open(src, encoding="utf-8") as fh:
            lines = [l for l in fh
                     if not l.split("#", 1)[0].strip().upper().startswith("FLDIGI_URL")]
    lines.append(f"\nFLDIGI_URL = {url}\n")
    with open(dst, "w", encoding="utf-8") as fh:
        fh.writelines(lines)
    return dst


def write_state(path, mode, carrier):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"mode": mode, "carrier": carrier, "color": "amber",
                   "timestamps": "yes"}, fh)


def read_state(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


if __name__ == "__main__":
    print("fldigi never answers: the remembered mode must survive untouched")
    tmp = tempfile.mkdtemp(prefix="cyberdeck-cold-")
    try:
        dead = free_port()
        conf = conf_pointing_at(tmp, f"http://127.0.0.1:{dead}/RPC2")
        state = os.path.join(tmp, "state", "cyberdeck.json")
        write_state(state, "RTTY", 1234)

        # settle_s 0.2 so the saver's settle window expires many times over
        # during the run. If it is going to overwrite, it has every chance.
        # ^O to the conversation: the deck opens on DECK & RIG, and what is
        # being read here is the transcript.
        screen = run(keys=[TO_CHAT], state_path=state, conf=conf, settle=3.0,
                     settle_s="0.2")
        body = "\n".join(screen.display)

        after = read_state(state)
        equals("the remembered mode is still RTTY", after.get("mode"), "RTTY")
        equals("the remembered carrier is still 1234", after.get("carrier"), 1234)
        check("and the deck said it was waiting rather than claiming a radio",
              "fldigi" in body.lower(), body[:200])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nfldigi arrives late: the remembered mode must be applied anyway")
    tmp = tempfile.mkdtemp(prefix="cyberdeck-late-")
    fake = None
    try:
        port = free_port()
        conf = conf_pointing_at(tmp, f"http://127.0.0.1:{port}/RPC2")
        state = os.path.join(tmp, "state", "cyberdeck.json")
        write_state(state, "RTTY", 1234)

        # The stand-in comes up a second after the deck does, holding CW the
        # way a freshly started fldigi does. This is the cold boot.
        #
        # `rig_mode` is a DATA mode deliberately. The deck parks the decoder
        # on the `NULL` modem whenever the radio is not in one, so a stand-in
        # answering "USB" would end up holding NULL and this would read as a
        # failed restore -- which is what it did until the two were told
        # apart. What is under test here is the restore, so the radio has to
        # be somewhere the decoder is allowed to run.
        fake = FakeFldigi(modem="CW", carrier=1000, port=port,
                          rig_mode="PKTUSB")
        timer = threading.Timer(1.0, fake.start)
        timer.start()

        screen = run(keys=[TO_CHAT], state_path=state, conf=conf, settle=5.0,
                     settle_s="0.2")
        timer.cancel()
        body = "\n".join(screen.display)

        equals("the deck told the late fldigi to use the remembered mode",
               fake.state.modem, "RTTY")
        equals("and the remembered carrier", fake.state.carrier, 1234)
        check("the panel shows RTTY rather than CW", "RTTY" in body, body[:300])

        after = read_state(state)
        equals("and the state file was not overwritten with CW",
               after.get("mode"), "RTTY")
    finally:
        if fake is not None:
            fake.stop()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nKeys pressed before fldigi exists do not defeat the restore")
    tmp = tempfile.mkdtemp(prefix="cyberdeck-race-")
    fake = None
    try:
        port = free_port()
        conf = conf_pointing_at(tmp, f"http://127.0.0.1:{port}/RPC2")
        state = os.path.join(tmp, "state", "cyberdeck.json")
        write_state(state, "RTTY", 1234)

        # A mode key pressed while fldigi is still starting reaches nothing:
        # set_modem fails silently, the way every call on that client does.
        # So there is no choice to protect, and the remembered mode must still
        # be applied when fldigi appears. An earlier version of the guard
        # below cancelled the restore on the strength of that keystroke and
        # left the deck in fldigi's own mode — the original fault, reached by
        # a different route.
        # A data mode, for the reason given above: the park would otherwise
        # leave the stand-in on NULL and hide what is being tested.
        fake = FakeFldigi(modem="CW", carrier=1000, port=port,
                          rig_mode="PKTUSB")
        timer = threading.Timer(2.5, fake.start)
        timer.start()

        # F3 then 3 picks the third mode in the curated list, pressed while
        # nothing is answering; fldigi appears a moment later. Which mode that
        # is does not matter and is not asserted — what matters is that it is
        # neither the remembered one nor the configured default, because those
        # are the two the startup would have imposed.
        # One write, so both land while nothing is answering. Sent as two
        # keys the per-key wait would push the second past the moment fldigi
        # appears, and the operator's choice would simply come last — which
        # tests nothing, and is how this was first written.
        screen = run(keys=["\x1bOR3"], state_path=state, conf=conf,
                     settle=0.8, settle_s="0.2", after=4.0)
        timer.cancel()

        equals("the remembered mode is applied despite the keystroke",
               fake.state.modem, "RTTY")
        equals("and the remembered carrier with it", fake.state.carrier, 1234)
    finally:
        if fake is not None:
            fake.stop()
        shutil.rmtree(tmp, ignore_errors=True)

    sys.exit(report())
