"""Maidenhead locators, and the distance and bearing between two of them.

WSPR reports a grid square and nothing else, so distance is not something the
protocol carries -- it is computed from the two locators, which is what
wsprnet and wspr.rocks do to fill their own km column.

**Validated against real spots**, not against arithmetic alone: the vectors
in `tests/test_grid.py` are rows from this station's own wsprnet records,
where the km and azimuth were computed independently by wsprnet from the same
two grids. Agreement inside a percent on paths from 500 to 6900 km is what
says the field and subsquare arithmetic is right, and that is the part of
this easy to get wrong in a way that looks plausible.

A locator names a RECTANGLE, not a point, so every figure here is from the
center of each rectangle. A 4-character square is about 150 km across in
latitude, so a distance between two 4-character grids is good to a few tens
of kilometers and no better. The decoder reports 4 characters for a type 1
message and 6 for a type 2, so both occur.
"""
import math

EARTH_KM = 6371.0088          # IUGG mean radius

_FIELD = 18                   # A..R
_SQUARE = 10                  # 0..9
_SUB = 24                     # a..x


def valid(locator):
    """Whether this is a locator this module can place."""
    return to_latlon(locator) is not None


def to_latlon(locator):
    """`(lat, lon)` of the locator's CENTER, or None.

    None rather than an exception: a decoder reports what it decoded, and a
    corrupt grid is an ordinary outcome of a weak signal rather than a
    programming error. `<...>` and `0000` both arrive in practice.
    """
    s = str(locator or "").strip()
    if len(s) not in (4, 6, 8):
        return None
    s = s[:6]                 # the 8-character extension adds nothing useful
    try:
        f_lon = ord(s[0].upper()) - 65
        f_lat = ord(s[1].upper()) - 65
        q_lon = int(s[2])
        q_lat = int(s[3])
    except (ValueError, IndexError):
        return None
    if not (0 <= f_lon < _FIELD and 0 <= f_lat < _FIELD):
        return None

    # Degrees per step, narrowing by level. Longitude spans 360 over 18
    # fields and latitude 180, which is the factor of two between them.
    lon = -180.0 + f_lon * 20.0 + q_lon * 2.0
    lat = -90.0 + f_lat * 10.0 + q_lat * 1.0
    lon_span, lat_span = 2.0, 1.0

    if len(s) == 6:
        s_lon = ord(s[4].lower()) - 97
        s_lat = ord(s[5].lower()) - 97
        if not (0 <= s_lon < _SUB and 0 <= s_lat < _SUB):
            return None
        lon += s_lon * (2.0 / _SUB)
        lat += s_lat * (1.0 / _SUB)
        lon_span, lat_span = 2.0 / _SUB, 1.0 / _SUB

    # The center of the rectangle, not its corner. Taking the corner puts a
    # 4-character grid up to 75 km from where it belongs.
    return lat + lat_span / 2.0, lon + lon_span / 2.0


def distance_km(a, b):
    """Great-circle distance between two locators in km, or None.

    Haversine on a sphere. The ellipsoid would change this by a few tenths
    of a percent, which is far inside the error a 4-character grid already
    carries.
    """
    pa, pb = to_latlon(a), to_latlon(b)
    if pa is None or pb is None:
        return None
    lat1, lon1 = math.radians(pa[0]), math.radians(pa[1])
    lat2, lon2 = math.radians(pb[0]), math.radians(pb[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = (math.sin(dlat / 2.0) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2)
    return 2.0 * EARTH_KM * math.asin(min(1.0, math.sqrt(h)))


def azimuth_deg(a, b):
    """Initial great-circle bearing from `a` to `b` in degrees, or None.

    The INITIAL bearing, which is what an antenna is pointed along; it is not
    constant over the path and the reciprocal is not 180 degrees away.
    """
    pa, pb = to_latlon(a), to_latlon(b)
    if pa is None or pb is None:
        return None
    lat1, lon1 = math.radians(pa[0]), math.radians(pa[1])
    lat2, lon2 = math.radians(pb[0]), math.radians(pb[1])
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = (math.cos(lat1) * math.sin(lat2)
         - math.sin(lat1) * math.cos(lat2) * math.cos(dlon))
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
