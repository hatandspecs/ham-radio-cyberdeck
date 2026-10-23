"""Writing pixels to the panel's framebuffer — src/fbdraw.py.

There is no framebuffer on a laptop or in a test rig, so everything here runs
against a temporary file standing in for `/dev/fb0` and a fake sysfs. What
that can prove is the part that is actually easy to get wrong: the pixel
format, the clipping, and that a machine with no framebuffer gets a clean no
rather than a traceback.

The last one matters most. A map that cannot be drawn has to be a sentence on
the panel, not an exception that takes the deck down in the field.
"""
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import fbdraw


def fake_sysfs(tmp, size="800,480", bpp="16"):
    d = os.path.join(tmp, "fb0")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "virtual_size"), "w") as fh:
        fh.write(size + "\n")
    with open(os.path.join(d, "bits_per_pixel"), "w") as fh:
        fh.write(bpp + "\n")
    return d


print("a machine with no framebuffer says so, and does not raise")
equals("geometry is None", fbdraw.geometry("/nope", "/nope/sys"), None)
equals("available is False", fbdraw.available("/nope", "/nope/sys"), False)
equals("and there is no canvas to draw on",
       fbdraw.canvas_for("/nope", "/nope/sys"), None)

print("\nthe panel's geometry is read from sysfs")
with tempfile.TemporaryDirectory() as tmp:
    sysfs = fake_sysfs(tmp)
    equals("800x480 at two bytes a pixel",
           fbdraw.geometry(sysfs=sysfs), (800, 480, 2))
    equals("32-bit reads as four bytes",
           fbdraw.geometry(sysfs=fake_sysfs(tmp, bpp="32")), (800, 480, 4))

print("\nan unreadable or unsupported panel is refused rather than guessed")
with tempfile.TemporaryDirectory() as tmp:
    for size, bpp, why in (("", "16", "no size"),
                           ("800,480", "", "no depth"),
                           ("garbage", "16", "size is not numbers"),
                           ("800,480", "8", "8-bit, which pack cannot write"),
                           ("800,480", "24", "24-bit, likewise")):
        s = fake_sysfs(tmp, size, bpp)
        equals(f"{why} gives None", fbdraw.geometry(sysfs=s), None)

print("\nthe pixel format is the panel's, not a convenient one")
# RGB565: red in the top five bits, green in the middle six, blue in the low
# five. Getting this wrong gives a map in the wrong colour, which looks like
# a theme bug rather than a packing bug.
equals("white in 565", fbdraw.pack(0xFFFFFF, 2).hex(), "ffff")
equals("black in 565", fbdraw.pack(0x000000, 2).hex(), "0000")
equals("pure red in 565", fbdraw.pack(0xFF0000, 2).hex(), "00f8")
equals("pure green in 565", fbdraw.pack(0x00FF00, 2).hex(), "e007")
equals("pure blue in 565", fbdraw.pack(0x0000FF, 2).hex(), "1f00")
equals("32-bit is BGRX", fbdraw.pack(0xFF0000, 4).hex(), "0000ff00")
equals("and its padding byte is zero", fbdraw.pack(0xFFFFFF, 4)[3], 0)

print("\na canvas starts blank and is exactly the panel's size")
c = fbdraw.Canvas(800, 480, 2)
equals("the buffer is width x height x bytes", len(c.buf), 800 * 480 * 2)
equals("and starts black", set(bytes(c.buf)), {0})

print("\npixels land where they are put")
c = fbdraw.Canvas(4, 3, 2)
c.point(2, 1, 0xFFFFFF)
off = (1 * 4 + 2) * 2
equals("the right offset is set", c.buf[off:off + 2].hex(), "ffff")
equals("and nothing else is",
       sum(1 for i in range(0, len(c.buf), 2)
           if c.buf[i:i + 2] != b"\x00\x00"), 1)

print("\noff-canvas pixels are dropped, not wrapped")
# Wrapping would draw the edge of a map on the opposite side of the screen.
c = fbdraw.Canvas(4, 3, 2)
for x, y in ((-1, 0), (4, 0), (0, -1), (0, 3), (99, 99), (-99, -99)):
    c.point(x, y, 0xFFFFFF)
equals("the canvas is untouched", set(bytes(c.buf)), {0})

print("\nmany points of one colour, which is how a map is drawn")
c = fbdraw.Canvas(10, 10, 2)
c.points([(1, 1), (2, 2), (3, 3), (-5, 5), (50, 5)], 0x00FF00)
lit = sum(1 for i in range(0, len(c.buf), 2)
          if c.buf[i:i + 2] != b"\x00\x00")
equals("three on the canvas, two dropped", lit, 3)

print("\nwriting to a device that is not there fails cleanly")
c = fbdraw.Canvas(4, 3, 2)
equals("it returns False rather than raising",
       c.write("/nope/fb0"), False)

print("\nand writing to one that is there puts the whole frame down")
with tempfile.TemporaryDirectory() as tmp:
    dev = os.path.join(tmp, "fb0")
    c = fbdraw.Canvas(8, 4, 2)
    c.point(0, 0, 0xFFFFFF)
    check("the write reports success", c.write(dev))
    with open(dev, "rb") as fh:
        blob = fh.read()
    equals("a whole frame was written, not a partial one",
           len(blob), 8 * 4 * 2)
    equals("with the pixel in it", blob[0:2].hex(), "ffff")

print("\na background colour fills the frame")
c = fbdraw.Canvas(4, 2, 2, background=0xFFFFFF)
equals("every pixel is the background",
       set(bytes(c.buf)), set(b"\xff\xff"))

print("\ncanvas_for builds one matching the panel")
with tempfile.TemporaryDirectory() as tmp:
    sysfs = fake_sysfs(tmp, "800,480", "32")
    c = fbdraw.canvas_for(sysfs=sysfs)
    equals("the size comes from sysfs", (c.width, c.height), (800, 480))
    equals("and so does the depth", c.bpp, 4)

sys.exit(report())
