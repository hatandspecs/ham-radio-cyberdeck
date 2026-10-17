"""The panel's touchscreen, read directly from evdev.

Touch was left out of the original design on the assumption that using it
meant running X (platform_design.md section 15.2). It does not. The controller
enumerates as an ordinary input device and a drag is a handful of integers
read from a character device, so the console keeps its premise — no pointer,
nothing to click — while gaining the one gesture that is awkward from a
keyboard during a contact.

What this deliberately is not: a pointer. There is no cursor and nothing
follows the finger. Two gestures exist and no more:

* a vertical **drag** on the transcript scrolls it — a gesture on content,
  not an instruction to a widget;
* a **tap** chooses a row on the pairing screen, which is the one screen that
  has to be usable when no keyboard is paired yet and therefore cannot ask
  for a keypress.

Everywhere else a tap is discarded. Reporting taps as cells rather than acting
on them is what keeps that decision with the screen rather than here.

Hardware, as found on the deck (2026-09-22):

    10-0038 generic ft5x06      FocalTech FT5x06 at i2c address 0x38
    PROP=2                      INPUT_PROP_DIRECT — a touchscreen, not a pad
    ABS_MT_SLOT/POSITION_X/Y    multitouch protocol type B
    /dev/input/event1           crw-rw---- root input, and deck is in input

Coordinates arrive as panel pixels and the character grid divides them
exactly: 800x480 at a 12x24 font is 66x20, so a row is 24 pixels with nothing
left over. No calibration step and no scaling.
"""
import os
import select
import struct

# struct input_event { struct timeval time; __u16 type, code; __s32 value; }
#
# Native 'l' matches the platform's long, which is what makes this correct on
# both the deck and a development machine: the event is 16 bytes on 32-bit
# userland and 24 on 64-bit, and a hardcoded size is wrong on one of them.
_EVENT = "llHHi"
_EVENT_SIZE = struct.calcsize(_EVENT)

EV_KEY, EV_ABS = 0x01, 0x03
BTN_TOUCH = 0x14a               # 330
ABS_MT_POSITION_X = 0x35        # 53
ABS_MT_POSITION_Y = 0x36        # 54
ABS_X = 0x00
ABS_Y = 0x01

_DEVICES = "/proc/bus/input/devices"
_INPUT_PROP_DIRECT = 1          # bit 1 of the PROP bitmap


def find_device(devices_path=_DEVICES):
    """The touchscreen's event device, or None.

    Chosen by capability rather than by name or by a fixed event number: the
    panel's controller is an FT5x06 and an earlier guess at Goodix found
    nothing, while event numbering is not guaranteed stable across boots.
    INPUT_PROP_DIRECT is the property that distinguishes a touchscreen from a
    touchpad, which is exactly the question being asked.
    """
    try:
        with open(devices_path, encoding="utf-8", errors="replace") as fh:
            blocks = fh.read().split("\n\n")
    except OSError:
        return None

    for block in blocks:
        prop = handlers = None
        for line in block.splitlines():
            if line.startswith("B: PROP="):
                prop = line.split("=", 1)[1].strip()
            elif line.startswith("H: Handlers="):
                handlers = line.split("=", 1)[1].split()
        if not prop or not handlers:
            continue
        # The bitmap is printed as space-separated longs, most significant
        # first; the property bits are small enough to live in the last one.
        try:
            bits = int(prop.split()[-1], 16)
        except ValueError:
            continue
        if not bits & (1 << _INPUT_PROP_DIRECT):
            continue
        for handler in handlers:
            if handler.startswith("event"):
                return "/dev/input/" + handler
    return None


# KEY_Q through KEY_Y — codes 16 to 21, the top letter row.
#
# These live in the LAST word of the KEY bitmap whether a kernel long is 32
# or 64 bits, which is what makes testing them portable between the deck's
# 32-bit userland and a 64-bit development machine. Anything that reports the
# whole top row is a keyboard; nothing that merely has buttons does.
_KEY_QWERTY = sum(1 << bit for bit in range(16, 22))


def find_keyboard(devices_path=_DEVICES):
    """True if a device that can actually type is attached.

    The `kbd` handler alone is not the answer, which is what the first version
    of this assumed and got wrong on the deck. The kernel attaches `kbd` to
    anything that can send a key event to a console, and on this hardware that
    includes two devices permanently present and neither of them a keyboard:

        C-Media USB Audio Device   the radio's codec — USB audio exposes HID
                                   consumer controls for volume and mute
        vc4-hdmi                   the HDMI CEC remote input

    So the check was true forever and could never report a keyboard missing.
    The same shape of false positive appears on an ordinary laptop, where
    power buttons, hotkey blocks and even the PC speaker carry `kbd` with an
    empty key bitmap.

    What separates them is what they can type. A keyboard reports the whole
    top letter row; a volume rocker or a CEC remote does not.

    Read from /proc rather than asked of BlueZ on purpose: a USB keyboard is a
    perfectly good answer and BlueZ knows nothing about it, and this has to
    work where BlueZ is not installed at all.
    """
    try:
        with open(devices_path, encoding="utf-8", errors="replace") as fh:
            blocks = fh.read().split("\n\n")
    except OSError:
        return False

    for block in blocks:
        typed = handler = False
        for line in block.splitlines():
            if line.startswith("H: Handlers="):
                handler = "kbd" in line.split("=", 1)[1].split()
            elif line.startswith("B: KEY="):
                words = line.split("=", 1)[1].split()
                try:
                    last = int(words[-1], 16) if words else 0
                except ValueError:
                    last = 0
                typed = (last & _KEY_QWERTY) == _KEY_QWERTY
        # Both: it must be able to type, and to reach the console.
        if typed and handler:
            return True
    return False


class Touch:
    """A vertical drag, in character rows.

    Opened non-blocking and read from the same loop that polls fldigi. Nothing
    here raises: a deck with no touchscreen, or one whose device cannot be
    opened, simply reports no movement forever, and the rest of the terminal
    does not know the difference.
    """

    def __init__(self, path=None, row_pixels=24, col_pixels=12,
                 devices_path=_DEVICES, tap_slop=16):
        self.row_pixels = max(1, int(row_pixels))
        self.col_pixels = max(1, int(col_pixels))
        # How far a finger may travel and still count as a tap rather than a
        # drag. Generous: a finger on glass never lands perfectly still, and
        # a tap that silently becomes a one-row scroll is worse than a scroll
        # that needs a deliberate stroke.
        self.tap_slop = max(0, int(tap_slop))
        self.path = path or find_device(devices_path)
        self.error = ""
        self._fd = None
        self._buf = b""
        self._down = False
        self._last_y = None
        self._last_x = None
        self._remainder = 0     # sub-row movement, so a slow drag still moves
        self._travel = 0        # how far this contact has moved, for tap/drag
        self._taps = []
        self._open()

    @property
    def available(self):
        return self._fd is not None

    def _open(self):
        if not self.path:
            self.error = "no touchscreen found"
            return
        try:
            self._fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as exc:
            self._fd = None
            self.error = f"{self.path}: {exc}"

    def close(self):
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def poll(self):
        """Rows dragged since the last call. Positive means older text.

        Dragging the content downward reveals what came before, the way a
        sheet of paper moves under a finger, so a downward drag returns a
        positive number and the caller scrolls back.
        """
        if self._fd is None:
            return 0
        if not select.select([self._fd], [], [], 0)[0]:
            return 0
        try:
            data = os.read(self._fd, 4096)
        except (BlockingIOError, InterruptedError):
            return 0
        except OSError as exc:
            # The device went away — a panel unplugged, or a driver reloaded.
            # Give up on it rather than raising into the draw loop.
            self.error = f"{self.path}: {exc}"
            self.close()
            return 0
        if not data:
            return 0
        return self.feed(data)

    def feed(self, data):
        """Parse raw evdev bytes and return rows dragged. Separate from poll()
        so the protocol can be tested without a touchscreen."""
        self._buf += data
        rows = 0
        while len(self._buf) >= _EVENT_SIZE:
            chunk, self._buf = self._buf[:_EVENT_SIZE], self._buf[_EVENT_SIZE:]
            _sec, _usec, etype, code, value = struct.unpack(_EVENT, chunk)
            if etype == EV_KEY and code == BTN_TOUCH:
                if not value and self._down and self._travel <= self.tap_slop:
                    # Lifted without travelling: a tap, at the cell the finger
                    # was over. Recorded rather than acted on here, because
                    # what a tap means depends on which screen is showing.
                    if self._last_y is not None:
                        self._taps.append(
                            (self._last_y // self.row_pixels,
                             (self._last_x or 0) // self.col_pixels))
                self._down = bool(value)
                # A new contact starts a new drag. Without this the gap
                # between where one finger lifted and the next touched down
                # would be counted as movement.
                self._last_y = None
                self._last_x = None
                self._remainder = 0
                self._travel = 0
            elif etype == EV_ABS and code in (ABS_MT_POSITION_X, ABS_X):
                self._last_x = value
            elif etype == EV_ABS and code in (ABS_MT_POSITION_Y, ABS_Y):
                if self._down:
                    rows += self._move(value)
        return rows

    def taps(self):
        """Completed taps since the last call, as (row, column) cells."""
        out, self._taps = self._taps, []
        return out

    def _move(self, y):
        if self._last_y is None:
            self._last_y = y
            return 0
        delta = y - self._last_y
        self._last_y = y
        self._travel += abs(delta)
        self._remainder += delta
        rows, self._remainder = divmod(self._remainder, self.row_pixels)
        # divmod floors, which is what keeps a drag reversible: the remainder
        # stays positive and the row count accumulates in the right direction
        # whichever way the finger is moving.
        return rows
