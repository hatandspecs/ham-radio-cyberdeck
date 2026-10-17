"""Maidenhead locators, distance and bearing — src/grid.py.

**The vectors are real.** Every row in `SPOTS` is a spot from this station's
own wsprnet records on 2026-10-17, where wsprnet computed the km and the
azimuth independently from the same two grid squares. Agreement with an
outside implementation on paths from 500 to 6900 km is what says the field
and subsquare arithmetic is right — and that arithmetic is the part of this
easy to get wrong in a way that still looks plausible.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import grid

# (from, to, km, azimuth) as wsprnet reported them.
SPOTS = (
    ("FN10cs", "JN47kh", 6599, 52),    # Switzerland, the longest of the night
    ("FN10cs", "CN87oh", 3617, 297),
    ("FN10cs", "CN84lx", 3669, 293),
    ("FN10cs", "EN80ee", 498, 264),    # and the shortest
    ("FN10cs", "EM38tv", 1261, 265),
    ("FN10cs", "JN55rs", 6855, 52),
    ("DM45fg", "FN10cs", 3000, 68),
    ("DN70mq", "FN10cs", 2280, 81),
    ("EL29ot", "FN10cs", 1960, 47),
    ("EN63vb", "FN10cs", 741, 107),
    ("EN52et", "FN10cs", 1006, 99),
)

# Four-character grids, where the square is ~150 km across and the center
# convention accounts for the difference. Held to a looser bound ON PURPOSE:
# claiming a kilometer from a grid that names a 150 km box would be false
# precision, and a tight bound here would be a test of wsprnet's rounding.
COARSE = (
    ("EN54", "FN10cs", 1007, 110),
    ("EM73", "FN10cs", 1034, 36),
)

print("distance agrees with wsprnet on six-character grids")
for a, b, km, _az in SPOTS:
    got = grid.distance_km(a, b)
    check(f"{a}->{b} is {km} km", got is not None and abs(got - km) <= 1.0,
          f"got {got}")

print("\nand so does the bearing")
for a, b, _km, az in SPOTS:
    got = grid.azimuth_deg(a, b)
    # Compared the short way round, so 359 and 1 are two degrees apart.
    off = abs((got - az + 180.0) % 360.0 - 180.0) if got is not None else 999
    check(f"{a}->{b} bears {az} degrees", off <= 1.0, f"got {got}")

print("\nfour-character grids are right to the size of the square")
for a, b, km, az in COARSE:
    got = grid.distance_km(a, b)
    check(f"{a}->{b} is about {km} km",
          got is not None and abs(got - km) <= 10.0, f"got {got}")

print("\nthe center of the square is what is used, not its corner")
# Taking the corner puts a four-character grid up to 75 km from where it
# belongs, which is a wrong answer that looks entirely reasonable.
lat, lon = grid.to_latlon("FN10")
check("FN10 centers at 40.5N", abs(lat - 40.5) < 0.01, str(lat))
check("and 77W", abs(lon - (-77.0)) < 0.01, str(lon))
# Which puts FN10cs on State College, at 77.79W -- the station's own grid,
# so this one is checkable against the map rather than against the formula.
check("FN10cs is where the station is",
      abs(grid.to_latlon("FN10cs")[1] - (-77.79)) < 0.02,
      str(grid.to_latlon("FN10cs")))
# The subsquare must land INSIDE its square.
slat, slon = grid.to_latlon("FN10cs")
check("FN10cs is inside FN10", 40.0 < slat < 41.0 and -78.0 < slon < -76.0,
      f"{slat},{slon}")

print("\nthe corners of the world are placed")
# The CENTERS of the corner squares, which sit exactly on 179 degrees and
# 89.5 -- not beyond them. A strict inequality here failed on the boundary
# and the code was right.
lat, lon = grid.to_latlon("AA00")
check("AA00 centers at 89.5S", abs(lat - (-89.5)) < 0.01, str(lat))
check("and 179W", abs(lon - (-179.0)) < 0.01, str(lon))
lat, lon = grid.to_latlon("RR99")
check("RR99 centers at 89.5N", abs(lat - 89.5) < 0.01, str(lat))
check("and 179E", abs(lon - 179.0) < 0.01, str(lon))

print("\na grid that cannot be placed gives None, not an exception")
# A decoder reports what it decoded. A corrupt grid is an ordinary outcome
# of a weak signal, not a programming error -- and both of these arrive.
for bad in ("", None, "0000", "<...>", "ZZ99", "FN", "FN1", "FN10c",
            "FN10c!", "fn10zz", "99AA"):
    equals(f"{bad!r} does not place", grid.to_latlon(bad), None)
    equals(f"{bad!r} has no distance", grid.distance_km("FN10cs", bad), None)
    equals(f"{bad!r} has no bearing", grid.azimuth_deg("FN10cs", bad), None)

print("\ncase does not matter, because decoders disagree about it")
equals("lower and upper agree", grid.to_latlon("fn10CS"),
       grid.to_latlon("FN10cs"))

print("\na station is zero kilometers from itself")
equals("the same grid is no distance", round(grid.distance_km("FN10cs",
                                                             "FN10cs")), 0)

print("\nthe bearing is the INITIAL one, so it is not reciprocal")
# Over a long path the reciprocal is not 180 degrees away, and treating it
# as though it were is how a bearing ends up pointing at the wrong ocean.
out = grid.azimuth_deg("FN10cs", "JN47kh")
back = grid.azimuth_deg("JN47kh", "FN10cs")
check("the two directions differ by more than 180",
      abs(abs(out - back) - 180.0) > 5.0, f"{out} vs {back}")
equals("while the distance is the same both ways",
       round(grid.distance_km("FN10cs", "JN47kh")),
       round(grid.distance_km("JN47kh", "FN10cs")))

print("\nvalid() answers the same question as to_latlon()")
check("a real grid", grid.valid("FN10cs"), "")
check("and a corrupt one", not grid.valid("<...>"), "")

report()
