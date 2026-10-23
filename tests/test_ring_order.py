"""The configurable function ring — `Deck._ring_areas`.

`^O` and `^P` walk a ring the operator defines. Two properties have to hold
whatever is configured, because both are how an operator gets out of trouble:

**Deck & rig is always on the ring.** It carries the station settings and the
system menu, including the way out of a deck configured into a corner. A
configuration that removed it would need an SSH session to undo.

**A bad configuration costs a stop, not a boot.** An unknown area name, a
duplicate, an empty string: none may raise, and none may leave the ring empty.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from harness import check, equals, report
import cyberdeck


def ring(order, log_on=True):
    d = cyberdeck.Deck.__new__(cyberdeck.Deck)
    d.cfg = {"RING_ORDER": order}
    d.log_on = log_on
    return d._ring_areas()


A = cyberdeck

print("the default order, with nothing configured")
equals("is the built-in ring", ring(""), list(A.RING))
check("which holds all five areas", len(A.RING) == 5, A.RING)
check("including the band plan", A.AREA_ALLOC in A.RING, A.RING)

print("\na configured order is honored exactly")
equals("three areas, in the order given",
       ring("wspr,settings,digimodes"),
       [A.AREA_WSPR, A.AREA_SETTINGS, A.AREA_DIGI])
equals("and a different order gives a different ring",
       ring("digimodes,settings,wspr"),
       [A.AREA_DIGI, A.AREA_SETTINGS, A.AREA_WSPR])

print("\ndeck & rig cannot be configured off the ring")
for order in ("wspr", "digimodes,wspr", "alloc,logging", "nonsense"):
    got = ring(order)
    check(f"{order!r}: deck & rig is still there",
          A.RING_FIXED in got, got)
equals("and it leads when the order leaves it out",
       ring("wspr,digimodes")[0], A.RING_FIXED)

print("\nan area the operator left out is simply not a stop")
got = ring("settings,digimodes")
check("wspr is off the ring", A.AREA_WSPR not in got, got)
check("and so is the band plan", A.AREA_ALLOC not in got, got)
equals("two stops, not five", len(got), 2)

print("\nlogging leaves the ring when it is switched off")
check("it is a stop when logging is on",
      A.AREA_LOG in ring("settings,logging,digimodes", log_on=True))
check("and not when it is off",
      A.AREA_LOG not in ring("settings,logging,digimodes", log_on=False))
check("even when the order names it first",
      A.AREA_LOG not in ring("logging,settings", log_on=False))
check("and deck & rig survives that too",
      A.RING_FIXED in ring("logging", log_on=False),
      ring("logging", log_on=False))

print("\na bad configuration costs a stop, never a crash")
for order in ("", "   ", ",,,", "banana", "wspr,banana,digimodes",
              "WSPR", "wspr,wspr,wspr", "settings,", None, 0):
    try:
        got = ring(order)
        ok = isinstance(got, list) and len(got) >= 1
        check(f"{order!r} produces a usable ring", ok, got)
        check(f"{order!r} keeps deck & rig", A.RING_FIXED in got, got)
    except Exception as exc:                       # noqa: BLE001
        check(f"{order!r} does not raise", False, f"{type(exc).__name__}: {exc}")

print("\nan unknown name is ignored rather than refused")
equals("the rest of the order survives it",
       ring("wspr,banana,digimodes"),
       [A.RING_FIXED, A.AREA_WSPR, A.AREA_DIGI])

print("\na duplicate is one stop, not two")
got = ring("wspr,wspr,digimodes")
equals("wspr appears once", got.count(A.AREA_WSPR), 1)

print("\nthe ring is never empty")
for order in ("banana", "", "logging"):
    got = ring(order, log_on=False)
    check(f"{order!r} still leaves somewhere to be", len(got) >= 1, got)

print("\nevery area the ring can hold has a screen to land on")
d = cyberdeck.Deck.__new__(cyberdeck.Deck)
d.cfg, d.log_on = {"RING_ORDER": ""}, True
d.area_screen = {A.AREA_ALLOC: A.ALLOC, A.AREA_SETTINGS: A.SET,
                 A.AREA_LOG: A.LOG, A.AREA_DIGI: A.CHAT, A.AREA_WSPR: A.WSPR}
for area in A.RING_AREAS:
    check(f"{area} has a landing screen", area in d.area_screen,
          sorted(d.area_screen))

print("\nand every landing screen maps back to its area")
for area, screen in d.area_screen.items():
    equals(f"{screen} belongs to {area}", A.AREA_OF.get(screen), area)

print("\nthe tuner is not on the ring")
# It keys the transmitter for minutes at a time. A screen that does that
# should not be one `^O` from everything else, and it belongs to deck & rig.
check("TUNER is not an area", A.TUNER not in A.RING_AREAS, A.RING_AREAS)
equals("it belongs to deck & rig", A.AREA_OF.get(A.TUNER), A.AREA_SETTINGS)

sys.exit(report())
