"""The world map: outline, projection and spots — src/wsprmap.py.

**The map is for operations awareness, not cartography.** Run WSPR for half an
hour in a field and look at where the dots are. So what is asserted here is
that a spot lands on the right continent, that the two directions stay
distinguishable, and that nothing in the draw path can raise -- not that any
pixel is exact.

The two directions matter most. A station that heard this one is a plus; a
station this one heard is a diagonal cross. Seeing both at once is how "am I
deaf?" gets answered, and one shape for both would hide it.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import wsprmap

BASE = wsprmap.load()
HOME = (40.771, -77.792)          # FN10cs

print("the shipped outline is the one the generator wrote")
# 432 rows, not the panel's 480: the two text rows curses draws over the map
# are 24 pixels each, and the picture is generated to fit BELOW them. They
# used to overlap, and curses won -- which is what made the map on the deck
# look like fragments squeezed into the top of the screen.
equals("800 by 432, the panel below its two text rows",
       (BASE.width, BASE.height),
       (800, 432))
equals("cut at 90 east, through Tibet", BASE.cut_lon, 90.0)
# The default view is `global`: the whole world without the ice. The clip
# that reached Antarctica is counted as off the view, asserted further down
# where the three views are compared.
check("it reaches both hemispheres", BASE.lat_south < 0 < BASE.lat_north,
      (BASE.lat_south, BASE.lat_north))
check("and far enough north for Europe and Alaska",
      BASE.lat_north >= 70, BASE.lat_north)
lit = sum(BASE.bits)
check("it has coastline on it", lit > 5000, lit)
check("but is mostly empty, as an outline should be",
      lit < BASE.width * BASE.height * 0.2, lit)

print("\nthe assets are small enough to ship on the card")
total = 0
for view in wsprmap.VIEWS:
    path = wsprmap.basemap_path(view)
    check(f"{view} exists", os.path.exists(path), path)
    total += os.path.getsize(path)
check("all three together are under 64 kB", total < 64_000, total)

print("\nfamiliar places land where they belong, relative to each other")
home = BASE.project(*HOME)
london = BASE.project(51.5, -0.13)
perth = BASE.project(-31.95, 115.86)
rio = BASE.project(-22.9, -43.2)
check("every one is on the map",
      all(p is not None for p in (home, london, perth, rio)),
      (home, london, perth, rio))
check("London is east of Pennsylvania", london[0] > home[0], (home, london))
check("and north of it", london[1] < home[1], (home, london))
check("Rio is south of Pennsylvania", rio[1] > home[1], (home, rio))
check("Perth is west of Pennsylvania on this projection, because the cut "
      "puts Australia on the near side", perth[0] < home[0], (home, perth))
check("and south of it", perth[1] > home[1], (home, perth))

print("\nthe projection is continuous across the cut")
# Either side of 90 E must be at opposite edges, not adjacent pixels.
west = BASE.project(0, 89.9)
east = BASE.project(0, 90.1)
check("both project", west and east, (west, east))
check("they sit at opposite edges",
      abs(west[0] - east[0]) > BASE.width * 0.9, (west, east))

print("\noff-map coordinates are refused rather than clamped")
# Clamping would pile every polar station onto one row and invent coverage.
for lat, lon, why in ((89.0, 0, "north of the clip"),
                      (-89.0, 0, "south of the clip"),
                      (120.0, 0, "not a latitude"),
                      ("x", 0, "not a number"),
                      (None, None, "nothing at all")):
    equals(f"{why} gives None", BASE.project(lat, lon), None)

print("\nlongitude wraps rather than failing")
for lon in (-540, -180, 0, 180, 540, 719.9):
    p = BASE.project(0, lon)
    check(f"{lon} projects onto the map", p is not None, lon)

print("\na spot is five pixels, because one is invisible at arm's length")
sm = wsprmap.SpotMap(BASE, home=HOME)
check("it adds", sm.add(51.5, -0.13, "20m", wsprmap.HEARD))
equals("five pixels for one spot", len(sm.pixels()), 5)

print("\nevery spot is the same `+`, and only this station is not")
# The deck knows one direction: what it HEARD. Who heard IT is on wsprnet,
# which needs a network the deck is often without, so a heard-by half was
# never in the spot log to draw. The one `×` on the map is home.
sm = wsprmap.SpotMap(BASE, home=HOME)
sm.add(51.5, -0.13, "20m")
px = [(x, y) for x, y, _b, _d in sm.pixels()]
equals("a spot is five pixels", len(px), 5)
x0, y0 = min(p[0] for p in px), min(p[1] for p in px)
equals("in a plus, not a cross", {(x - x0, y - y0) for x, y in px},
       {(1, 0), (0, 1), (1, 1), (2, 1), (1, 2)})
home = set(sm.home_pixels())
check("home is a different shape from a spot", len(home) > 5, len(home))
check("and no spot pixel is shaped like it", home != set(px))

print("\nthe band filter still works, though the map no longer offers it")
# The map screen stopped filtering by band on 2026-10-23: it is scoped to
# one session, and within a session every band answers the same question.
# `pixels` keeps the argument because `bands()` is still what names them.
sm = wsprmap.SpotMap(BASE, home=HOME)
sm.add(51.5, -0.13, "20m")
sm.add(-31.95, 115.86, "40m")
equals("both bands are reported, longest first",
       sm.bands(), ["40m", "20m"])
equals("one direction, because the deck knows one",
       sorted(sm.directions()), [wsprmap.HEARD])
equals("one band selected shows one spot",
       len(sm.pixels(bands=["20m"])), 5)
equals("none selected shows nothing", len(sm.pixels(bands=[])), 0)
equals("unfiltered shows both", len(sm.pixels()), 10)

print("\nshapes are clipped at the edge, never wrapped")
# A spot at the cut is at the cut. Wrapping would draw half a marker on the
# far side of the world.
sm = wsprmap.SpotMap(BASE, home=HOME)
sm.add(0, 90.0 - 0.01, "20m")          # hard against the right edge
px = sm.pixels()
check("some pixels survive", len(px) >= 1, len(px))
check("none wrapped to the other side",
      all(p[0] > BASE.width * 0.5 for p in px), sorted(px)[:4])

print("\na grid square is what both logs actually store")
sm = wsprmap.SpotMap(BASE, home=HOME)
check("a good locator plots", sm.add_grid("IO91wm", "20m"))
check("a bad one is refused rather than raising", not sm.add_grid("nope"))
check("and an empty one too", not sm.add_grid(""))
equals("only the good one is on the map", len(sm.points), 1)

print("\nthe station's own marker reads as a place, not a spot")
sm = wsprmap.SpotMap(BASE, home=HOME)
pix = sm.home_pixels()
check("it is drawn", len(pix) > 5, len(pix))
check("as an open shape, not a blob",
      (len(set(pix)) == len(pix)) and len(pix) <= 24, len(pix))
equals("no home, no marker",
       wsprmap.SpotMap(BASE, home=None).home_pixels(), [])

print("\nreach answers the steering question in numbers")
sm = wsprmap.SpotMap(BASE, home=HOME)
sm.add(51.5, -0.13, "20m", wsprmap.HEARD)       # east
sm.add(51.5, -0.13, "20m", wsprmap.HEARD)
sm.add(37.8, -122.4, "20m", wsprmap.HEARD)      # west
sm.add(-22.9, -43.2, "20m", wsprmap.HEARD)         # south
r = sm.reach()
equals("two to the east", r[wsprmap.HEARD]["E"], 2)
equals("one to the west", r[wsprmap.HEARD]["W"], 1)
equals("and the other direction is counted apart",
       r[wsprmap.HEARD]["S"], 1)
check("a direction with nothing in it is simply absent",
      "N" not in r.get(wsprmap.HEARD, {}), r)

print("\nreach needs a home to measure from")
sm = wsprmap.SpotMap(BASE, home=None)
sm.add(51.5, -0.13, "20m")
equals("without one it counts nothing rather than guessing", sm.reach(), {})

print("\nnothing in the draw path raises on empty or odd input")
sm = wsprmap.SpotMap(BASE, home=HOME)
equals("no spots, no pixels", sm.pixels(), [])
equals("no bands", sm.bands(), [])
equals("no directions", sm.directions(), [])
check("a spot off the map is refused, not plotted",
      not sm.add(89.0, 0.0, "20m"))
equals("and leaves nothing behind", len(sm.points), 0)

print("\nthree views of the same world, cycled with one key")
for view in wsprmap.VIEWS:
    b = wsprmap.load(view=view)
    equals(f"{view}: the panel below its text rows", (b.width, b.height),
           (800, 432))
    check(f"{view}: has coastline", sum(b.bits) > 5000, sum(b.bits))
    equals(f"{view}: drawn in mercator", b.projection, "mercator")

print("\nthe views differ in what they show, which is the point")
focus = wsprmap.load(view="focus")
glob = wsprmap.load(view="global")
check("focus starts north of the tropics", focus.lat_south >= 15,
      focus.lat_south)
check("and is a longitude slice, not the whole world",
      focus.lon_east - focus.lon_west < 180,
      (focus.lon_west, focus.lon_east))
check("covering the continental USA",
      focus.lon_west <= -124 and focus.lon_east >= -67,
      (focus.lon_west, focus.lon_east))
for place, lat, lon in (("Seattle", 47.6, -122.3), ("Miami", 25.8, -80.2),
                        ("Maine", 44.8, -68.8), ("San Diego", 32.7, -117.2)):
    check(f"{place} is on the USA view", focus.project(lat, lon) is not None,
          (lat, lon))
for place, lat, lon in (("London", 51.5, -0.13), ("Perth", -31.9, 115.9)):
    equals(f"{place} is not", focus.project(lat, lon), None)
check("the world views span the full 360",
      abs((glob.lon_east - glob.lon_west) - 360) < 0.01,
      (glob.lon_west, glob.lon_east))
check("global drops the ice", glob.lat_south >= -65, glob.lat_south)
# A third view, `wide`, carried -72 to 78 so that DP0GVN at Neumayer III
# (-70.65) was on the map. It was dropped 2026-10-23: twelve more degrees
# at each pole is too nearly the same picture as `global` to be worth a
# press of the key. A spot below the clip is COUNTED, which is the part
# that has to keep working -- see `offmap` above.
equals("and a station below it is off the view rather than lost",
       glob.project(-70.65, -8.27), None)

print("\nfocus gives the USA far more of the panel")
def us_share(b):
    a, c = b.project(25, -100), b.project(49, -100)
    if a is None or c is None:
        return 0.0
    return abs(a[1] - c[1]) / b.height
check("focus devotes most of the panel to the lower 48",
      us_share(focus) > 0.6, us_share(focus))
check("where global gives it a fraction",
      us_share(glob) < 0.25, us_share(glob))
check("so focus is several times the scale",
      us_share(focus) > us_share(glob) * 3,
      (us_share(focus), us_share(glob)))

print("\nthe cycle wraps, and survives a name that is no longer a view")
equals("focus to global", wsprmap.next_view("focus"), "global")
equals("global wraps to focus", wsprmap.next_view("global"), "focus")
equals("and backwards", wsprmap.next_view("global", -1), "focus")
equals("an unknown view falls back", wsprmap.next_view("banana"),
       wsprmap.DEFAULT_VIEW)

print("\na clipped view counts what it is hiding")
# The focus view drops everything south of the tropics. A map that did that
# silently would answer "where am I being heard" with a lie.
sm = wsprmap.SpotMap(focus, home=HOME)
sm.add(40.0, -105.0, "20m")                # Colorado, on the USA view
sm.add(51.5, -0.13, "20m")                 # London, not
sm.add(-31.95, 115.86, "20m")              # Perth, not
sm.add(-22.9, -43.2, "20m")                # Rio, not
equals("one spot plotted", len(sm.points), 1)
equals("three counted as off the view", sm.offmap, 3)
check("and the summary says so", "3 off this view" in sm.summary(),
      sm.summary())

print("\nthe wide view hides none of the same spots")
sm = wsprmap.SpotMap(glob, home=HOME)
for lat, lon in ((40.0, -105.0), (51.5, -0.13), (-31.95, 115.86),
                 (-22.9, -43.2)):
    sm.add(lat, lon, "20m")
equals("all four plotted", len(sm.points), 4)
equals("nothing off the view", sm.offmap, 0)
check("and the summary is just the count", "off this view" not in sm.summary(),
      sm.summary())

print("\nan empty map says so rather than showing a zero")
equals("no spots yet", wsprmap.SpotMap(glob).summary(), "no spots yet")

sys.exit(report())
