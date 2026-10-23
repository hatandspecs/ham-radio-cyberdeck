"""Writing pixels straight to the panel's framebuffer.

The maps are 800x480 pictures and the deck draws 66x20 characters, so there
is no way to put one on the screen through curses. This writes to `/dev/fb0`
instead -- the same device the text console is drawn on, which is why taking
the screen and giving it back is the whole problem here rather than an
afterthought.

**No external viewer.** `fim` and `fbi` were the obvious route and were
rejected: handing the framebuffer to another process means handing it the
keyboard too, and getting both back cleanly from a program that did not
expect to share is exactly the class of problem that cost a stuck
transmitter when fldigi was handed a sound card it already held. Writing the
bytes directly keeps the deck in control of its own screen and its own keys,
and the code is shorter than the handshake would have been.

Giving the screen back is one line in the caller: curses redraws the whole
panel on the next frame, because the text console and the framebuffer are
the same memory.

Nothing here is required for the deck to run. A machine with no framebuffer
-- a laptop, a test rig, an SSH session -- gets `available()` false and the
map screens say so rather than failing.
"""
import os
import struct

FB_DEVICE = "/dev/fb0"
SYS_FB = "/sys/class/graphics/fb0"


def _read_sys(name, sysfs=SYS_FB, default=""):
    try:
        with open(os.path.join(sysfs, name), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return default


def geometry(device=FB_DEVICE, sysfs=SYS_FB):
    """`(width, height, bytes_per_pixel)` for the panel, or None.

    Read from sysfs rather than an ioctl, because sysfs is text and an ioctl
    would need the kernel's struct layout for whichever architecture this is
    built on. The panel does not change size at runtime.
    """
    size = _read_sys("virtual_size", sysfs)
    bpp = _read_sys("bits_per_pixel", sysfs)
    if not size or not bpp:
        return None
    try:
        w, h = (int(v) for v in size.split(","))
        depth = int(bpp)
    except ValueError:
        return None
    if depth not in (16, 32):
        return None
    return (w, h, depth // 8)


def available(device=FB_DEVICE, sysfs=SYS_FB):
    """Whether this machine can show a map at all."""
    return bool(geometry(device, sysfs)) and os.path.exists(device)


def pack(rgb, bytes_per_pixel):
    """One pixel, in the framebuffer's own format.

    16-bit is RGB565, which is what the Waveshare panel reports. 32-bit is
    stored little-endian as BGRX, which is what every framebuffer this has
    been seen on uses -- the X byte is padding and is written as zero.
    """
    r, g, b = ((rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF)
    if bytes_per_pixel == 2:
        v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        return struct.pack("<H", v)
    return struct.pack("<BBBB", b, g, r, 0)


class Canvas:
    """An off-screen image, blitted to the panel in one write.

    Built whole and written once rather than poking pixels through the
    device: a partial frame is a visibly torn one, and one `write` of 768 kB
    is faster than 384,000 seeks on a Pi 3A+.
    """

    def __init__(self, width, height, bytes_per_pixel, background=0x000000):
        self.width = width
        self.height = height
        self.bpp = bytes_per_pixel
        self._blank = pack(background, bytes_per_pixel)
        self.buf = bytearray(self._blank * (width * height))

    def point(self, x, y, rgb):
        if 0 <= x < self.width and 0 <= y < self.height:
            off = (y * self.width + x) * self.bpp
            self.buf[off:off + self.bpp] = pack(rgb, self.bpp)

    def points(self, coords, rgb):
        """Many pixels of one color, which is how a map is drawn."""
        px = pack(rgb, self.bpp)
        w, h, bpp, buf = self.width, self.height, self.bpp, self.buf
        for x, y in coords:
            if 0 <= x < w and 0 <= y < h:
                off = (y * w + x) * bpp
                buf[off:off + bpp] = px

    def write(self, device=FB_DEVICE):
        """Put it on the screen. Returns False rather than raising.

        A map that cannot be drawn is a message on the panel, not a traceback
        that takes the deck down mid-session.
        """
        try:
            with open(device, "wb") as fh:
                fh.write(self.buf)
            return True
        except OSError:
            return False


def canvas_for(device=FB_DEVICE, sysfs=SYS_FB, background=0x000000):
    """A canvas matching the panel, or None where there is no framebuffer."""
    geo = geometry(device, sysfs)
    if not geo:
        return None
    return Canvas(geo[0], geo[1], geo[2], background)
