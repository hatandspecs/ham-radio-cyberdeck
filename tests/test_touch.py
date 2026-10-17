"""The touchscreen, driven from synthetic evdev events.

No hardware is needed and none should be: the protocol is a fixed-size struct
and a handful of codes, so feeding it bytes exercises the same path a finger
does. What cannot be tested here is whether the panel is wired to the driver,
which is why the hardware check in platform_design.md section 16 exists.

The device found on the deck reports multitouch protocol type B — slots and
tracking IDs — but scrolling needs one finger's Y position and nothing else,
so only BTN_TOUCH and ABS_MT_POSITION_Y are consumed. Ignoring the rest is
deliberate: a second finger cannot start a second drag.
"""
import os
import struct
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import touch as touchmod


def ev(etype, code, value):
    return struct.pack(touchmod._EVENT, 0, 0, etype, code, value)


def down():
    return ev(touchmod.EV_KEY, touchmod.BTN_TOUCH, 1)


def up():
    return ev(touchmod.EV_KEY, touchmod.BTN_TOUCH, 0)


def at(y):
    return ev(touchmod.EV_ABS, touchmod.ABS_MT_POSITION_Y, y)


def detached(row_pixels=24):
    """A Touch with no device behind it, for feeding bytes by hand.

    Built through the real constructor with a path that cannot open, rather
    than through __new__ with the fields set here: the hand-built version
    silently lost every field added afterwards, and the first symptom was an
    AttributeError from inside feed() rather than a failing assertion.
    """
    return touchmod.Touch(path="/dev/null/not-a-device", row_pixels=row_pixels)


# A /proc/bus/input/devices as the deck prints it. PROP=2 is
# INPUT_PROP_DIRECT, which is what distinguishes a touchscreen from a
# touchpad — the panel's controller is an FT5x06, and an earlier guess at a
# Goodix part by name found nothing at all.
PROC = """I: Bus=0019 Vendor=0001 Product=0001 Version=0100
N: Name="vc4-hdmi"
H: Handlers=event3
B: PROP=0
B: EV=21

I: Bus=0018 Vendor=0000 Product=0000 Version=0000
N: Name="10-0038 generic ft5x06 (79)"
S: Sysfs=/devices/platform/soc/3f205000.i2c/i2c-11/i2c-10/10-0038/input/input1
H: Handlers=mouse0 event1
B: PROP=2
B: EV=b
B: ABS=2608000 3

I: Bus=0003 Vendor=046d Product=b35b Version=0011
N: Name="Keyboard"
H: Handlers=sysrq kbd event0
B: PROP=0
B: EV=120013
"""


if __name__ == "__main__":
    print("Touchscreen")

    # -- finding the device -------------------------------------------------
    with tempfile.NamedTemporaryFile("w", suffix=".devices", delete=False) as fh:
        fh.write(PROC)
        proc_path = fh.name
    try:
        equals("the touchscreen is found by INPUT_PROP_DIRECT",
               touchmod.find_device(proc_path), "/dev/input/event1")
        equals("a missing file is not an error", touchmod.find_device("/nope"), None)
        with tempfile.NamedTemporaryFile("w", delete=False) as fh2:
            fh2.write("I: Bus=0003\nN: Name=\"Keyboard\"\nH: Handlers=kbd event0\nB: PROP=0\n")
            none_path = fh2.name
        equals("a machine with no touchscreen finds nothing",
               touchmod.find_device(none_path), None)
        os.unlink(none_path)
    finally:
        os.unlink(proc_path)

    # -- a device that cannot be opened is harmless -------------------------
    dead = touchmod.Touch(path="/dev/does-not-exist")
    equals("an unopenable device reports unavailable", dead.available, False)
    equals("and polls as no movement", dead.poll(), 0)
    check("with the reason kept", "does-not-exist" in dead.error, dead.error)

    # -- the drag itself ----------------------------------------------------
    t = detached()
    equals("a drag down of four rows", t.feed(down() + at(100) + at(196)), 4)
    equals("and back up again", t.feed(at(100)), -4)

    t = detached()
    equals("movement with no finger down is ignored", t.feed(at(300)), 0)

    # Lifting and touching somewhere else must not count the gap as a drag.
    t = detached()
    t.feed(down() + at(100))
    equals("a new contact does not jump",
           t.feed(up() + down() + at(400)), 0)
    equals("but then drags normally from there", t.feed(at(448)), 2)

    # Sub-row movement accumulates rather than being discarded, so a slow
    # drag still moves the transcript.
    t = detached()
    t.feed(down() + at(100))
    moved = sum(t.feed(at(100 + step * 8)) for step in range(1, 4))
    equals("three eight-pixel steps make one row", moved, 1)

    # Events arriving split across reads, which is what a non-blocking read
    # of a character device actually does.
    t = detached()
    blob = down() + at(100) + at(148)
    half = len(blob) // 2
    first = t.feed(blob[:half])
    second = t.feed(blob[half:])
    equals("a split event stream still yields the drag", first + second, 2)

    # -- it must not get in the way of a machine that is not the deck -------
    #
    # The application runs on an ordinary laptop against an ordinary fldigi
    # (the runbook's laptop section), and people who are not building a deck
    # should never meet the touchscreen at all. Every way it can be absent has
    # to end in "no movement", not in an exception during startup.
    nowhere = touchmod.Touch(devices_path="/proc/does-not-exist")
    equals("no /proc/bus/input/devices at all — macOS, BSD, a container",
           nowhere.available, False)
    equals("and it polls as nothing", nowhere.poll(), 0)

    unreadable = touchmod.Touch(path="/etc/shadow")
    equals("a device the user may not read is not fatal",
           unreadable.available, False)
    check("and says why rather than failing silently",
          "Permission denied" in unreadable.error or "Errno" in unreadable.error,
          unreadable.error)

    source = open(os.path.join(os.path.dirname(_HERE), "src", "touch.py")).read()
    check("the module imports nothing outside the standard library",
          all(f"import {mod}" not in source
              for mod in ("evdev", "gi", "RPi", "gpiozero", "smbus")), "")
    check("and never grabs the device",
          "EVIOCGRAB" not in source and "ioctl" not in source,
          "a grab would steal touch from the desktop it is running on")

    # -- taps, for the pairing screen ---------------------------------------
    #
    # A tap is the only way to choose anything when no keyboard is paired yet,
    # which is exactly the situation the pairing screen exists for. Everywhere
    # else taps are discarded by the caller, not here.
    t = detached()
    t.feed(down() + ev(touchmod.EV_ABS, touchmod.ABS_MT_POSITION_X, 180)
           + at(240) + up())
    equals("a tap reports the cell it landed on", t.taps(), [(10, 15)])
    equals("and is drained once", t.taps(), [])

    t = detached()
    t.feed(down() + at(100) + at(300) + up())
    equals("a drag is not a tap", t.taps(), [])

    # A finger never lands perfectly still; a few pixels must not turn a tap
    # into a scroll.
    t = detached()
    t.feed(down() + at(240) + at(244) + up())
    equals("a small wobble is still a tap", len(t.taps()), 1)

    # -- is there a keyboard at all -----------------------------------------
    #
    # The deck cannot be told by the operator that it has no keyboard, so it
    # has to notice. The first version of this looked for the kernel's `kbd`
    # handler, which was wrong: on the deck that handler is attached to two
    # devices permanently present and neither is a keyboard — the radio's
    # C-Media audio codec, because USB audio exposes HID volume controls, and
    # the HDMI CEC remote input. The check was true forever.
    #
    # What separates them is what they can type. The blocks below are the real
    # ones from the deck, with the keyboard's KEY bitmap from a laptop.
    def probe(text):
        with tempfile.NamedTemporaryFile("w", delete=False) as fh:
            fh.write(text)
            path = fh.name
        try:
            return touchmod.find_keyboard(path)
        finally:
            os.unlink(path)

    CODEC = """I: Bus=0003 Vendor=0d8c Product=0016 Version=0100
N: Name="C-Media Electronics Inc. USB Audio Device"
H: Handlers=kbd event0 
B: EV=13
B: KEY=e080000000000000 0
"""
    HDMI = """I: Bus=001e Vendor=0000 Product=0000 Version=0001
N: Name="vc4-hdmi"
H: Handlers=kbd event2 
B: EV=100013
B: KEY=fff 0 0 0 0
"""
    PANEL = """I: Bus=0018 Vendor=0000 Product=0000 Version=0000
N: Name="10-0038 generic ft5x06 (79)"
H: Handlers=mouse0 event1 
B: PROP=2
B: EV=b
B: ABS=2608000 3
"""
    KEYBOARD = """I: Bus=0005 Vendor=046d Product=b35b Version=0011
N: Name="Pebble K380s"
H: Handlers=sysrq kbd event4 
B: EV=120013
B: KEY=fffffffffffffffe
"""

    equals("the radio's audio codec is not a keyboard", probe(CODEC), False)
    equals("nor is the HDMI CEC remote", probe(HDMI), False)
    equals("nor is the touch panel", probe(PANEL), False)
    equals("all three together are still not a keyboard",
           probe(CODEC + "\n" + HDMI + "\n" + PANEL), False)
    equals("a real keyboard is found", probe(KEYBOARD), True)
    equals("and is found among the decoys",
           probe(CODEC + "\n" + HDMI + "\n" + PANEL + "\n" + KEYBOARD), True)
    equals("a keyboard with no kbd handler cannot reach the console",
           probe(KEYBOARD.replace("H: Handlers=sysrq kbd event4",
                                  "H: Handlers=event4")), False)
    equals("a malformed bitmap is not a keyboard",
           probe(KEYBOARD.replace("B: KEY=fffffffffffffffe", "B: KEY=zzz")), False)
    equals("and no /proc at all is not an error",
           touchmod.find_keyboard("/nope"), False)

    # -- geometry -----------------------------------------------------------
    # 800x480 at a 12x24 font is 66x20, so a row is 24 pixels with nothing
    # left over: the panel's own coordinates are the character grid.
    equals("480 pixels is exactly 20 rows of 24", 480 // 24, 20)
    t = detached(row_pixels=24)
    equals("a full-height drag is the whole screen",
           t.feed(down() + at(0) + at(480)), 20)

    sys.exit(report())
