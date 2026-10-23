#!/usr/bin/env python3
"""Render the world outline the deck's maps draw on, once, off the deck.

**Run this on a laptop, never on the deck.** It needs geopandas, shapely and
matplotlib, and it fetches Natural Earth boundaries over the network. The deck
has none of that: 512 MB, no geopandas, and by assumption no network in the
field.

The output is a **1-bit mask** -- one bit per pixel saying "coastline here" --
not a picture. The deck colors it at draw time from whichever scheme is
active, so one asset serves all five instead of five PNGs that would drift
apart. At 800x480 that is 48,000 bytes before compression.

The projection is the prototype's, and `src/wsprmap.py` reimplements it in
pure arithmetic. **The two must agree exactly or every spot lands in the
wrong place**, which is what `tests/test_wsprmap.py` checks by comparing them
at several hundred points.
"""
import argparse
import os
import sys
import zlib

WIDTH, HEIGHT = 800, 480

# The world is cut at 90 E -- through Tibet and the Bay of Bengal -- so that
# no path from this station crosses the seam and the station sits near the
# middle of its own map. Longitudes east of the cut are shifted by -360.
CUT_LON = 90.0

# Three views, cycled on the deck with one key, all Mercator.
#
# One clip cannot serve both questions the map gets asked. "Is anyone in
# Europe hearing me" wants North America and Europe filling the panel; "did
# I really reach Antarctica" wants the whole globe. So the deck ships all
# three and switches between them, which costs about 30 kB.
#
# `wide` keeps the Antarctic bases -- DP0GVN at Neumayer III, -70.65, was
# decoded on 30 m. `global` drops the ice and gains the mid latitudes.
# `focus` is North America and Europe at the largest scale that still shows
# both, and deliberately clips everything south of the tropics: the screen
# says how many spots fell off rather than pretending they did not exist.
# (lat_south, lat_north, lon_west, lon_east). A longitude window of None
# means the full 360 degrees ending at the cut, which is what the two world
# views use.
#
# `focus` is the continental USA with southern Canada and northern Mexico,
# sized so its Mercator aspect matches the panel's 800x480 -- 68 degrees of
# longitude against 40.8 of Mercator latitude -- because a view stretched to
# fit would put Florida in the wrong shape on the one view where the shape
# is recognisable.
VIEWS = {
    "focus":  (22.0, 53.0, -130.0, -62.0),
    "global": (-60.0, 75.0, None, None),
    "wide":   (-72.0, 78.0, None, None),
}
VIEW_ORDER = ("focus", "global", "wide")

# Clipped to where there are stations, and no further.
#
# **The clip, not the projection, is what gives the mid latitudes room.**
# Measured as a share of panel height for 25-60 N, where this station's
# contacts actually are: Mercator 18.5%, Miller 20.9%, equirectangular
# 22.2% at -78..80, and 23.3% once the clip comes in to -72..78. Mercator
# spends 44% of the screen on Greenland and Antarctica to get there.
#
# -72 keeps the Antarctic bases -- DP0GVN at Neumayer III, -70.65, was
# decoded on 30 m -- and drops the ice nobody transmits from. +78 keeps
# Svalbard and Alaska.
LAT_SOUTH, LAT_NORTH = -72.0, 78.0

NE_COUNTRIES = ("https://naturalearth.s3.amazonaws.com/110m_cultural/"
                "ne_110m_admin_0_countries.zip")
NE_STATES = ("https://naturalearth.s3.amazonaws.com/110m_cultural/"
             "ne_110m_admin_1_states_provinces.zip")


def render(out_path, width=WIDTH, height=HEIGHT, states=True,
           projection="mercator", lat_south=None, lat_north=None,
           lon_west=None, lon_east=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import geopandas as gpd
    south = LAT_SOUTH if lat_south is None else lat_south
    north = LAT_NORTH if lat_north is None else lat_north
    west = (CUT_LON - 360.0) if lon_west is None else lon_west
    east = CUT_LON if lon_east is None else lon_east
    from shapely.geometry import box, Polygon, LineString, MultiPolygon, \
        MultiLineString

    def merc_y(lat):
        """Whichever projection was asked for. Named `merc_y` throughout
        because that is what the geometry pipeline calls it; the default is
        equirectangular, which is not Mercator at all."""
        lat = np.asarray(lat, dtype=float)
        if projection == "mercator":
            lat = np.clip(lat, -85.0511, 85.0511)
            return np.degrees(np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)))
        if projection == "miller":
            lat = np.clip(lat, -89.5, 89.5)
            return 1.25 * np.degrees(
                np.arcsinh(np.tan(np.radians(0.8 * lat))))
        return np.clip(lat, -90.0, 90.0)        # equirectangular

    def shift_project(geom):
        """Clip at the cut, shift the eastern part, then project Y.

        Geometry is cut and rejoined rather than having its points shifted,
        so a country straddling the seam is drawn as two pieces instead of
        being smeared across the whole map.
        """
        west = geom.intersection(box(-180, -90, CUT_LON, 90))
        east = geom.intersection(box(CUT_LON, -90, 180, 90))
        parts = []
        for g_all, dx in ((west, 0.0), (east, -360.0)):
            if g_all.is_empty:
                continue
            for g in (g_all.geoms if hasattr(g_all, "geoms") else [g_all]):
                if g.geom_type == "Polygon":
                    ext = [(x + dx, merc_y(y)) for x, y in g.exterior.coords]
                    ins = [[(x + dx, merc_y(y)) for x, y in r.coords]
                           for r in g.interiors]
                    parts.append(Polygon(ext, ins))
                elif g.geom_type == "LineString":
                    parts.append(LineString(
                        [(x + dx, merc_y(y)) for x, y in g.coords]))
        if not parts:
            return None
        polys = [p for p in parts if p.geom_type == "Polygon"]
        lines = [p for p in parts if p.geom_type == "LineString"]
        if polys:
            return MultiPolygon(polys) if len(polys) > 1 else polys[0]
        if lines:
            return MultiLineString(lines) if len(lines) > 1 else lines[0]
        return None

    layers = [(NE_COUNTRIES, 0.6)]
    if states:
        # Internal boundaries: US states and Canadian provinces, drawn
        # thinner so they read as subdivisions rather than coastline.
        layers.append((NE_STATES, 0.35))

    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100,
                           facecolor="black")
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
    ax.set_facecolor("black")
    ax.set_xlim([west, east])
    ax.set_ylim([merc_y(south), merc_y(north)])

    for url, lw in layers:
        print(f"  reading {url.rsplit('/', 1)[-1]} ...", file=sys.stderr)
        gdf = gpd.read_file(url)
        gdf["geometry"] = gdf["geometry"].apply(shift_project)
        gdf = gdf.dropna(subset=["geometry"])
        gdf.plot(ax=ax, facecolor="none", edgecolor="white", linewidth=lw,
                 antialiased=False)

    # **geopandas sets `aspect='equal'` on every plot call**, which silently
    # overrides the limits set above and shrinks the world into the middle of
    # the frame with black margins either side. That is not merely ugly: the
    # deck's `wsprmap.project` maps the full pixel width onto 360 degrees, so
    # an outline drawn into part of the width puts every spot in the wrong
    # place relative to the coast it is supposed to sit on.
    #
    # Forced back to `auto`, with the limits re-applied after plotting, so
    # the rendered extent is exactly the one the projection assumes.
    ax.set_aspect("auto")
    ax.set_xlim([west, east])
    ax.set_ylim([merc_y(south), merc_y(north)])
    ax.axis("off")

    fig.canvas.draw()
    buf = np.asarray(fig.canvas.buffer_rgba())[:, :, :3]
    # Any non-black pixel is a line. Antialiasing is off, but matplotlib
    # still lays down a few grey pixels at joins; a low threshold keeps them,
    # which is what makes the coastline continuous at this size.
    mask = (buf.max(axis=2) > 40)
    plt.close(fig)

    h, w = mask.shape
    packed = bytearray()
    for row in mask:
        bits = 0
        n = 0
        for on in row:
            bits = (bits << 1) | (1 if on else 0)
            n += 1
            if n == 8:
                packed.append(bits)
                bits = n = 0
        if n:
            packed.append(bits << (8 - n))

    header = (f"CDMAP1 {w} {h} {CUT_LON} {south} {north} "
              f"{projection} {west} {east}\n").encode()
    with open(out_path, "wb") as fh:
        fh.write(header)
        fh.write(zlib.compress(bytes(packed), 9))
    lit = int(mask.sum())
    print(f"  {w}x{h}, {lit} lit pixels ({100 * lit / (w * h):.1f}%), "
          f"{os.path.getsize(out_path)} bytes", file=sys.stderr)
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--out-dir",
                    default=os.path.join(os.path.dirname(__file__), "..",
                                         "src"),
                    help="where basemap_<view>.bin are written")
    ap.add_argument("--view", choices=VIEW_ORDER,
                    help="just one view; the default is all three")
    ap.add_argument("--width", type=int, default=WIDTH)
    ap.add_argument("--height", type=int, default=HEIGHT)
    ap.add_argument("--no-states", action="store_true")
    ap.add_argument("--projection",
                    default="mercator",
                    choices=("mercator", "plate", "miller"),
                    help="plate (equirectangular, the default) keeps "
                         "Greenland and Antarctica in proportion; mercator "
                         "inflates them")
    a = ap.parse_args()
    # All three by default. They differ only in the latitude clip, so the
    # shapefiles are read once per view here -- a few seconds each, run on a
    # laptop, and never on the deck.
    for view in ([a.view] if a.view else VIEW_ORDER):
        south, north, west, east = VIEWS[view]
        out = os.path.join(os.path.abspath(a.out_dir), f"basemap_{view}.bin")
        print(f"{view}: {south}..{north}", file=sys.stderr)
        render(out, a.width, a.height, states=not a.no_states,
               projection=a.projection, lat_south=south, lat_north=north,
               lon_west=west, lon_east=east)
