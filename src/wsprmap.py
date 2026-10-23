"""The world map the WSPR and log screens draw: outline plus spots.

**What this is for is operations awareness, not cartography.** Run WSPR for
half an hour in a field and look at where the dots are: that is roughly where
this antenna is being heard, and roughly where it can hear. A dot a few
pixels off the right coast changes nothing about that answer, so nothing here
trades legibility for precision.

The outline is a **1-bit mask built off the deck** by `tools/make_basemap.py`
and shipped on the card -- 800x480 of coastline, states and provinces in
about six kilobytes. The deck never loads geopandas, never draws a shapefile,
and never needs a network to show a map. It colors the mask from the active
scheme at draw time, which is why the asset is a mask and not a picture.

The projection is Mercator, cut at 90 E -- through Tibet, where no path from
this station crosses -- and clipped north and south to where stations are.
`tools/make_basemap.py` holds the same constants, read from the asset's own
header rather than copied, so the two cannot drift apart.
"""
import math
import os
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
BASEMAP = os.path.join(HERE, "basemap.bin")

# Three views of the same world, cycled with one key. One clip cannot answer
# both questions the map gets asked: "is anyone in Europe hearing me" wants
# North America and Europe filling the panel, and "did I really reach
# Antarctica" wants the globe.
#
#   focus   the continental USA, filling the panel
#   global  the whole world, no Antarctica, 26%
#   wide    the globe including the Antarctic bases, 21%
#
# `focus` clips hard, so a map drawn in it is hiding spots. `SpotMap` counts
# them and the screen says how many rather than letting them vanish.
VIEWS = ("focus", "global", "wide")
DEFAULT_VIEW = "global"


def basemap_path(view=DEFAULT_VIEW):
    """The asset for a view, falling back to the plain one if it is absent."""
    path = os.path.join(HERE, f"basemap_{view}.bin")
    return path if os.path.exists(path) else BASEMAP


def next_view(view, step=1):
    """Cycle the views, tolerating a name that is no longer one."""
    try:
        i = VIEWS.index(view)
    except ValueError:
        return DEFAULT_VIEW
    return VIEWS[(i + step) % len(VIEWS)]

MAGIC = b"CDMAP1"

# Mercator cannot show the poles, and nobody operates from them. Clipped to
# where the stations are: far enough south for the Antarctic bases, far
# enough north for Svalbard.
MERC_LIMIT = 85.0511


def merc_y(lat):
    """Latitude to Mercator Y, in degrees, clamped away from the poles."""
    lat = max(-MERC_LIMIT, min(MERC_LIMIT, float(lat)))
    return math.degrees(math.log(math.tan(math.pi / 4
                                          + math.radians(lat) / 2)))


def plate_y(lat):
    """Equirectangular: latitude straight onto Y.

    No polar inflation at all, which is the point. Mercator makes Greenland
    look like Africa and turns the clipped Antarctic edge into a wall across
    the bottom of the screen -- on a map whose job is "where am I being
    heard", that spends a third of the panel on two places nobody operates
    from. Shapes near the poles stretch sideways instead, which costs
    nothing here because the question is which continent a dot is on.
    """
    return max(-90.0, min(90.0, float(lat)))


def miller_y(lat):
    """Miller cylindrical: Mercator's look with four fifths of its stretch.

    The compromise, for when the polar squash of equirectangular reads as
    wrong rather than as honest.
    """
    lat = max(-89.5, min(89.5, float(lat)))
    return 1.25 * math.degrees(
        math.asinh(math.tan(math.radians(0.8 * lat))))


PROJECTIONS = {"mercator": merc_y, "plate": plate_y, "miller": miller_y}
DEFAULT_PROJECTION = "plate"


class Basemap:
    """The world outline: a bit per pixel, plus the projection it was drawn in.

    Nothing here is expensive. The mask is unpacked once into a bytearray of
    0 and 1, which costs 384 KB at 800x480 and makes a lit-pixel test an
    index rather than a bit shift -- the draw loop runs on a Pi 3A+ and will
    touch every pixel.
    """

    def __init__(self, width, height, cut_lon, lat_south, lat_north, bits,
                 projection=DEFAULT_PROJECTION, lon_west=None, lon_east=None):
        self.width = width
        self.height = height
        self.cut_lon = cut_lon
        # The longitude window the outline was drawn in. The world views span
        # a full 360 ending at the cut; the USA view is a slice, which is why
        # this is explicit rather than derived from the cut.
        self.lon_east = cut_lon if lon_east is None else lon_east
        self.lon_west = (cut_lon - 360.0) if lon_west is None else lon_west
        self.lat_south = lat_south
        self.lat_north = lat_north
        self.bits = bits
        self.projection = projection
        # **Read from the asset, never assumed.** The outline was drawn in
        # one projection and the spots are placed in another only if these
        # two disagree, which would put every dot in the wrong place in a way
        # that still looks like a map.
        self._y_of = PROJECTIONS.get(projection, PROJECTIONS[DEFAULT_PROJECTION])
        self._y_top = self._y_of(lat_north)
        self._y_bottom = self._y_of(lat_south)

    def lit(self, x, y):
        if 0 <= x < self.width and 0 <= y < self.height:
            return bool(self.bits[y * self.width + x])
        return False

    def project(self, lat, lon):
        """Latitude and longitude to a pixel, or None when off the map.

        Longitude is rebased into the window the map was drawn in, so a
        station east of the cut appears on the western side where its path
        from here actually runs.
        """
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            return None
        if not (-90.0 <= lat <= 90.0):
            return None
        # Rebase into the window, then scale. A station outside a clipped
        # window lands outside the pixel range and is refused below, which is
        # what `SpotMap.offmap` counts.
        lon = self.lon_east - ((self.lon_east - lon) % 360.0)
        span = self.lon_east - self.lon_west
        x = (lon - self.lon_west) / span * self.width
        yv = self._y_of(lat)
        if yv > self._y_top or yv < self._y_bottom:
            return None
        span = self._y_top - self._y_bottom
        y = (self._y_top - yv) / span * self.height
        xi, yi = int(x), int(y)
        if 0 <= xi < self.width and 0 <= yi < self.height:
            return (xi, yi)
        return None


def load(path=None, view=DEFAULT_VIEW):
    """Read a shipped outline. Raises only if the asset is missing or wrong."""
    if path is None:
        path = basemap_path(view)
    with open(path, "rb") as fh:
        blob = fh.read()
    nl = blob.index(b"\n")
    head = blob[:nl].split()
    if head[0] != MAGIC:
        raise ValueError(f"not a basemap: {head[0]!r}")
    width, height = int(head[1]), int(head[2])
    cut, south, north = float(head[3]), float(head[4]), float(head[5])
    projection = head[6].decode() if len(head) > 6 else DEFAULT_PROJECTION
    lon_w = float(head[7]) if len(head) > 7 else None
    lon_e = float(head[8]) if len(head) > 8 else None
    packed = zlib.decompress(blob[nl + 1:])
    row_bytes = (width + 7) // 8
    bits = bytearray(width * height)
    for y in range(height):
        base = y * row_bytes
        out = y * width
        for x in range(width):
            byte = packed[base + (x >> 3)]
            bits[out + x] = (byte >> (7 - (x & 7))) & 1
    return Basemap(width, height, cut, south, north, bits, projection,
                   lon_w, lon_e)


# How a spot is drawn. One pixel is invisible at arm's length on a 5-inch
# panel, so a spot is five: legible against the outline without turning fifty
# of them into a smear, which is the density a half-hour session produces.
#
# **Two shapes, because the two directions answer different questions.** A
# plus is a station that heard this one; a diagonal cross is a station this
# one heard. Seeing both at once is how "am I deaf?" gets answered -- if the
# pluses reach Europe and the crosses stop at the coast, the receive side is
# the weak half, which is exactly what the October analysis measured at
# +11 dB. One shape for both would hide the thing worth looking for.
HEARD_BY = "heard_by"       # they heard me
HEARD = "heard"             # I heard them

PLUS = ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1))
CROSS = ((0, 0), (-1, -1), (1, 1), (-1, 1), (1, -1))
SPOT_OFFSETS = PLUS         # kept: the single-direction maps use it

SHAPES = {HEARD_BY: PLUS, HEARD: CROSS}


class SpotMap:
    """The outline with spots on it, ready for whatever draws pixels.

    Band filtering and the time window live here rather than in the caller,
    because both maps -- WSPR and the contact log -- want the same two and
    would otherwise each grow their own.
    """

    def __init__(self, basemap, home=None):
        self.base = basemap
        self.home = home
        self.points = []            # (x, y, band, direction)
        # Spots that fell outside the view. The focus view clips hard, and a
        # map that quietly dropped a third of the night would answer "where
        # am I being heard" with a lie.
        self.offmap = 0
        # Records with no grid at all. Not the same absence as `offmap`: a
        # clipped point is on the map somewhere else, a gridless contact
        # cannot be drawn anywhere. The contact log has these; the WSPR log
        # does not, because a spot without a grid is not a spot.
        self.ungridded = 0

    def add(self, lat, lon, band="", direction=HEARD_BY):
        xy = self.base.project(lat, lon)
        if xy is None:
            self.offmap += 1
            return False
        self.points.append((xy[0], xy[1], band, direction))
        return True

    def add_grid(self, locator, band="", direction=HEARD_BY):
        """A Maidenhead square, which is what both logs actually store."""
        import grid
        if not grid.valid(locator):
            return False
        lat, lon = grid.to_latlon(locator)
        return self.add(lat, lon, band, direction)

    def summary(self):
        """The line under the map: what is on it, and what is not.

        Both kinds of absence are named. A point can be missing because the
        view clips it (`offmap`) or because the record never had a grid to
        plot (`ungridded`), and those are different facts: the first is fixed
        by `v`, the second cannot be fixed from this screen at all.
        """
        n = len(self.points)
        if not n and not self.offmap and not self.ungridded:
            return "no spots yet"
        line = f"{n} spot{'' if n == 1 else 's'}"
        if self.offmap:
            line += f"   {self.offmap} off this view"
        if self.ungridded:
            line += f"   {self.ungridded} with no grid"
        return line

    def directions(self):
        """Which directions are present, so the screen offers only those."""
        seen = []
        for _x, _y, _b, d in self.points:
            if d not in seen:
                seen.append(d)
        return seen

    def reach(self, directions=None, bands=None):
        """Spot counts by compass sector, per direction.

        This is the steering question in numbers rather than pixels: a V
        dipole that is broadside east-west shows it here before the eye finds
        it on the map, and a sector with nothing in it is either a null or a
        place with nobody listening.
        """
        want_d = None if directions is None else set(directions)
        want_b = None if bands is None else set(bands)
        out = {}
        cx = self.base.project(*self.home) if self.home else None
        for x, y, band, d in self.points:
            if want_d is not None and d not in want_d:
                continue
            if want_b is not None and band not in want_b:
                continue
            if cx is None:
                continue
            dx, dy = x - cx[0], cx[1] - y
            ang = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0
            sector = ("N" if ang < 45 or ang >= 315 else
                      "E" if ang < 135 else
                      "S" if ang < 225 else "W")
            out.setdefault(d, {}).setdefault(sector, 0)
            out[d][sector] += 1
        return out

    def bands(self):
        """Bands present, in the order the band keys are shown."""
        seen = []
        for _x, _y, band, _d in self.points:
            if band and band not in seen:
                seen.append(band)
        return seen

    def pixels(self, bands=None, directions=None):
        """Every lit spot pixel, as `(x, y, band, direction)`.

        `bands` and `directions` are the sets switched on; None means all.
        Shapes are clipped at the edges rather than wrapped: a spot near the
        cut is near the cut and must not reappear on the far side.
        """
        want_b = None if bands is None else set(bands)
        want_d = None if directions is None else set(directions)
        out = []
        for x, y, band, d in self.points:
            if want_b is not None and band not in want_b:
                continue
            if want_d is not None and d not in want_d:
                continue
            for dx, dy in SHAPES.get(d, PLUS):
                px, py = x + dx, y + dy
                if 0 <= px < self.base.width and 0 <= py < self.base.height:
                    out.append((px, py, band, d))
        return out

    def home_pixels(self):
        """The station's own marker: a small open square, so it reads as a
        place rather than as the loudest spot on the map."""
        if not self.home:
            return []
        xy = self.base.project(*self.home)
        if xy is None:
            return []
        cx, cy = xy
        # A set, because the four sides share corners and a doubled pixel is
        # a doubled draw -- harmless on a framebuffer, misleading in a count.
        seen = set()
        for d in range(-2, 3):
            for px, py in ((cx + d, cy - 2), (cx + d, cy + 2),
                           (cx - 2, cy + d), (cx + 2, cy + d)):
                if 0 <= px < self.base.width and 0 <= py < self.base.height:
                    seen.add((px, py))
        return sorted(seen)
