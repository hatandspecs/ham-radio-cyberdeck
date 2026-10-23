"""Render the deck's screens to PNG, in each color scheme.

The text comes from the same functions the application draws with, and the
colors are the schemes' own hex values (docs/digimodes_design.md §5.9) rather than a
terminal emulator's approximation of them — so these show what the panel
shows, including the true amber and the cyan-shifted Tron blue that the eight
ANSI colors cannot express.

Cell geometry follows the 12x24 console font on the 800x480 panel: 66x20
characters. Rendered at 2x for legibility in documentation.

    python3 tools/capture_png.py            # all screens, all schemes
"""
import os
import sys

# The application modules live in src/; this tool lives in tools/.
_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT, "src"))
from PIL import Image, ImageDraw, ImageFont

import capture_screens as cap
import colors
import menus
import render

SCALE = 2
CELL_W, CELL_H = 12 * SCALE, 24 * SCALE
COLS, ROWS = 66, 20
PAD = 8 * SCALE
OUT = os.path.join(_PROJECT, "docs", "screens")

FONT_CANDIDATES = [
    "/usr/share/fonts/liberation-mono-fonts/LiberationMono-Bold.ttf",
    "/usr/share/fonts/adwaita-mono-fonts/AdwaitaMono-Bold.ttf",
    "/usr/share/fonts/google-noto-vf/NotoSansMono[wght].ttf",
]


def _font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _rgb(hexstr):
    return tuple(int(hexstr[i:i + 2], 16) for i in (0, 2, 4))


def _draw_map(img, sm, scheme_key, w, h):
    """The basemap and its spots, scaled into `img`.

    `colors.map_colors` is what the deck itself uses, so the outline and the
    spots are the same two colors here as on the panel.
    """
    dim_hex, bright_hex = colors.map_colors(scheme_key)
    outline = ((dim_hex >> 16) & 255, (dim_hex >> 8) & 255, dim_hex & 255)
    spot = ((bright_hex >> 16) & 255, (bright_hex >> 8) & 255,
            bright_hex & 255)
    base = sm.base
    px = img.load()
    sx, sy = w / base.width, h / base.height

    def put(x, y, rgb):
        # One basemap pixel covers more than one image pixel once scaled, so
        # it is drawn as the block it occupies rather than as a point -- a
        # point would leave the coastline as a dotted line with gaps.
        x0, y0 = int(x * sx), int(y * sy)
        for ix in range(x0, min(w, int((x + 1) * sx) + 1)):
            for iy in range(y0, min(h, int((y + 1) * sy) + 1)):
                px[ix, iy] = rgb

    for y in range(base.height):
        row = y * base.width
        for x in range(base.width):
            if base.bits[row + x]:
                put(x, y, outline)
    for x, y, _band, _dirn in sm.pixels():
        put(x, y, spot)
    # The scheme's own bright colour, as the deck draws it. White is not
    # one of the phosphor colours; the `×` is what tells home from a spot.
    for x, y in sm.home_pixels():
        put(x, y, spot)


def draw(lines, scheme_key, path, cols=COLS, rows=ROWS, spotmap=None):
    scheme = colors.SCHEMES[scheme_key]
    bright, dim = _rgb(scheme["bright"]), _rgb(scheme["dim"])
    black = (0, 0, 0)

    w = cols * CELL_W + PAD * 2
    h = rows * CELL_H + PAD * 2
    img = Image.new("RGB", (w, h), black)
    d = ImageDraw.Draw(img)
    font = _font(int(CELL_H * 0.78))

    # The map screens are a framebuffer picture with two curses rows on top
    # of it, so a capture that drew only the rows showed an empty screen --
    # which is what the first version of this did. The picture goes down
    # first, scaled from the basemap's own 800x480 (the panel's exact pixel
    # count) to whatever this image is, and the rows are drawn over it the
    # way curses draws them over the framebuffer.
    if spotmap is not None:
        _draw_map(img, spotmap, scheme_key, w, h)

    # The map screen puts its first row at the top and its second at the
    # BOTTOM, with the picture between -- drawn in order, the key row would
    # sit on the map's first scanlines, which is what the deck did until
    # 2026-10-23. The rows between are left alone rather than filled with
    # blanks, or they would paint over the picture.
    if spotmap is not None and len(lines) > 1:
        placed = [(0, lines[0]), (rows - 1, lines[1])]
    else:
        placed = list(enumerate(lines[:rows]))
    for row, line in placed:
        x = 0
        for text, kind in line:
            for ch in text:
                if x >= cols:
                    break
                px, py = PAD + x * CELL_W, PAD + row * CELL_H
                if spotmap is not None:
                    # Curses owns its cells: a space in a curses row paints
                    # the background, it does not let what is underneath
                    # show through. Without this the dim half of the band
                    # row was drawn over coastlines and could not be read --
                    # which is a fault in the capture, not on the panel.
                    d.rectangle([px, py, px + CELL_W, py + CELL_H],
                                fill=black)
                if kind == "reverse":
                    d.rectangle([px, py, px + CELL_W, py + CELL_H], fill=bright)
                    fg = black
                elif kind in ("dim", "note"):
                    fg = dim
                else:
                    fg = bright
                if ch != " ":
                    d.text((px, py + CELL_H * 0.08), ch, font=font, fill=fg)
                x += 1
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)
    return path


if __name__ == "__main__":
    session = cap.scripted_session()
    chat = cap.compose_chat(session, cap.FIELDS)
    made = []

    for key in colors.ORDER:
        made.append(draw(chat, key, f"{OUT}/conversation-{key}.png"))

    made.append(draw(cap.tuning_screen(), "matrix", f"{OUT}/tuning.png"))
    made.append(draw(menus.render(menus.ROOT, COLS, ROWS, selected=2), "matrix", f"{OUT}/menu.png"))
    made.append(draw(menus.render(menus.mode_menu("BPSK63"), COLS, ROWS),
                     "matrix", f"{OUT}/mode-picker.png"))

    # The two screens that exist for the moment there is no keyboard. Built
    # from the same render functions the deck draws with, and from the device
    # data the real scan produced on the panel — two channels of one keyboard
    # under one name, which is the case the screen has to explain.
    import btpair
    kb_here = btpair.Device("/a", {"Address": "DF:3C:77:61:6C:22",
                                   "Alias": "Pebble K380s",
                                   "Icon": "input-keyboard", "RSSI": -54})
    kb_bonded = btpair.Device("/b", {"Address": "DF:3C:77:61:6C:21",
                                     "Alias": "Pebble K380s",
                                     "Icon": "input-keyboard", "Paired": True})
    made.append(draw(render.no_keyboard_screen([kb_bonded], COLS, ROWS),
                     "matrix", f"{OUT}/no-keyboard.png"))
    made.append(draw(render.pair_screen("scanning", [kb_here, kb_bonded],
                                        COLS, ROWS),
                     "matrix", f"{OUT}/pairing.png"))
    made.append(draw(render.pair_screen("passkey", [], COLS, ROWS,
                                        passkey="482190"),
                     "matrix", f"{OUT}/pairing-passkey.png"))

    # The WiFi screen. Invented networks: the real ones belong to the
    # operator's neighbours and do not belong in a published screenshot.
    made.append(draw(cap.wifi_screen(), "matrix", f"{OUT}/wifi.png"))

    # The log screen's three states, and the menu that reaches it.
    for kind in ("general", "pota", "contest"):
        made.append(draw(cap.log_screen(kind), "matrix",
                         f"{OUT}/log-{kind}.png"))
    made.append(draw(menus.render(
        menus.log_menu(True, count=14, lookup=True, activity_type="POTA",
                       park="US-5678", operating="auto", has_tqsl=True),
        COLS, ROWS, selected=0), "matrix", f"{OUT}/log-menu.png"))
    import activities as _acts
    _t = _acts.load(os.path.join(_PROJECT, "activities.conf.example"))
    made.append(draw(menus.render(
        menus.activity_type_menu(sorted(_t), "PAQP",
                            {n: _t[n].label for n in _t}),
        COLS, ROWS, selected=3), "matrix", f"{OUT}/log-activity.png"))

    names = menus.keyboard_modes([n for _, n in menus.MODE_TIER1] + [
        "BPSK125", "BPSK250", "BPSK500", "QPSK63", "QPSK125", "QPSK250",
        "OLIVIA-4/250", "OLIVIA-16/500", "OLIVIA-32/1K", "MFSK8", "MFSK32",
        "MFSK64", "THOR16", "THOR25", "THOR50x1", "DOMEX4", "DOMEX5",
        "DOMEX11", "DOMEX16", "DOMEX22", "CONTESTIA", "RTTY"])
    menu, *_ = menus.paged_menu("ALL MODES", names, 0, COLS, ROWS)
    made.append(draw(menus.render(menu, COLS, ROWS), "matrix", f"{OUT}/all-modes.png"))

    # The WSPR area. Spots are real ones off the air -- other operators'
    # callsigns and grids are already published on wsprnet, which is the
    # whole point of the mode -- with this station's own grid as the
    # reference for the distance and bearing columns.
    import wsprgrid_fixture as _w          # defined below, kept out of the way
    for name, lines in _w.screens(COLS, ROWS):
        made.append(draw(lines, "matrix", f"{OUT}/{name}.png"))
    for name, lines in _w.log_extras(COLS, ROWS):
        made.append(draw(lines, "matrix", f"{OUT}/{name}.png"))
    # The screens added 2026-10-22. The PNG path is the one that can show a
    # reverse-video key cap, which is how the maps' band digits are drawn and
    # which the ASCII capture in `screens.md` cannot represent.
    for name, lines in _w.new_screens(COLS, ROWS):
        made.append(draw(lines, "matrix", f"{OUT}/{name}.png"))
    # The two maps, picture and all.
    for name, spotmap, lines in _w.maps(COLS, ROWS):
        made.append(draw(lines, "matrix", f"{OUT}/{name}.png",
                         spotmap=spotmap))

    for p in made:
        print(f"  {p}  {os.path.getsize(p) // 1024} KB")
