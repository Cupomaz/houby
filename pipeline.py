"""Core build pipeline: mushroom x forest-age intersection GeoJSONs.

Pipeline:
  1. Read mushroom probability PNG (local probability.png if present, else CHMI API).
  2. Classify mushroom pixels to nearest of 5 colors (classes 0-4).
  3. Download WMTS POROSTLCR tiles at matrix 9 (JTSK:epsg:5514) concurrently.
     Blank/white tiles are skipped. Each non-blank tile is classified to nearest
     of 8 age colors and written directly into the mushroom EPSG:4326 grid.
  4. Per forest age: mask = forest==age AND mushroom in {3,4}; polygonize;
     write data/age_<a>.geojson + data/meta.json.

Run directly:  python build.py
Or import run_build() from another process (e.g. Flask).
"""
import json
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
from pyproj import Transformer
from rasterio.transform import Affine
from rasterio.features import shapes
from shapely.geometry import shape, mapping

from config import (
    DATA_DIR, NODATA, MUSH_COLORS, MUSH_HIGH_CLASSES, FOREST_COLORS,
    FOREST_LABELS, MUSH_LABELS, MUSH_WEST, MUSH_SOUTH, MUSH_EAST, MUSH_NORTH,
    TL_X, TL_Y, MATRIX_9_RES, TILE_SIDE_M, VALID_R0, VALID_R1, VALID_C0,
    VALID_C1, BLANK_FRACTION, MAX_DIST_SQ, TILE_MATRIX, log,
)
from classify import nearest_class, fetch_mushroom, is_blank_rgb
from tiles import (
    load_cached_tile, download_tile_with_retries, tile_5514_extent,
)

# ---- rebuild status (shared with Flask) ----
_status_lock = threading.Lock()
BUILD_STATUS = {
    "status": "idle",       # idle | running | done | error
    "started_at": None,
    "finished_at": None,
    "message": "",
    "progress": 0,          # 0-100
    "ages": [],
}


def _set_status(**kwargs):
    with _status_lock:
        BUILD_STATUS.update(kwargs)


def process_tile_from_array(age_arr, col, row, mx, my, mush_high):
    """Write forest ages from a pre-classified tile into the mushroom grid.

    age_arr: 256x256 uint8 forest-age class array (NODATA where no data).
    Returns "blank" if blank, None if no overlap, or (rows, cols, ages).
    """
    if age_arr is None:
        return None
    if is_blank_rgb(age_arr):
        return "blank"

    tx0, yb, tx1, yt = tile_5514_extent(col, row)
    m = (mx >= tx0) & (mx < tx1) & (my >= yb) & (my < yt) & mush_high
    if not m.any():
        return None
    rows, cols = np.nonzero(m)
    px_x = mx[rows, cols]
    px_y = my[rows, cols]
    tc = np.floor((px_x - tx0) / MATRIX_9_RES).astype(int)
    tr = np.floor((yt - px_y) / MATRIX_9_RES).astype(int)
    tc = np.clip(tc, 0, 255)
    tr = np.clip(tr, 0, 255)
    ages = age_arr[tr, tc]
    return rows, cols, ages


def process_tile(col, row, mx, my, mush_high):
    """Download (or load from cache) + classify one tile."""
    cached = load_cached_tile(col, row)
    if cached is not None:
        age_arr, _, _ = cached
        return process_tile_from_array(age_arr, col, row, mx, my, mush_high)

    arr, _, _ = download_tile_with_retries(col, row)
    if arr is None:
        return None
    age_arr = nearest_class(arr, FOREST_COLORS)
    return process_tile_from_array(age_arr, col, row, mx, my, mush_high)


def run_build():
    """Execute the full build. Updates BUILD_STATUS. Safe to call from a thread."""
    _set_status(status="running", started_at=time.time(), message="starting", progress=0, ages=[])
    try:
        os.makedirs(DATA_DIR, exist_ok=True)

        # 1. Mushroom raster (EPSG:4326)
        mush_img, time_label = fetch_mushroom()
        mw, mh = mush_img.size
        mush_arr = np.asarray(mush_img)
        mush_class = nearest_class(mush_arr, MUSH_COLORS)
        mush_high = np.isin(mush_class, list(MUSH_HIGH_CLASSES))
        log.info("mushroom map %dx%d px; high-prob (class 3/4) px: %d",
                 mw, mh, int(mush_high.sum()))

        xres = (MUSH_EAST - MUSH_WEST) / mw
        yres = (MUSH_NORTH - MUSH_SOUTH) / mh
        mush_transform = Affine(xres, 0, MUSH_WEST, 0, -yres, MUSH_NORTH)

        # 2. Mushroom pixel centers in EPSG:5514
        tr = Transformer.from_crs("EPSG:4326", "EPSG:5514", always_xy=True)
        js, is_ = np.meshgrid(np.arange(mw), np.arange(mh))
        lons = MUSH_WEST + (js + 0.5) * xres
        lats = MUSH_NORTH - (is_ + 0.5) * yres
        mx5514, my5514 = tr.transform(lons.ravel(), lats.ravel())
        mx = mx5514.reshape(mh, mw)
        my = my5514.reshape(mh, mw)

        # 3. Tile set intersecting the mushroom class-3/4 extent, clamped to valid limits
        high_ys, high_xs = np.nonzero(mush_high)
        lons_h = MUSH_WEST + (high_xs + 0.5) * xres
        lats_h = MUSH_NORTH - (high_ys + 0.5) * yres
        tmx_h, tmy_h = tr.transform(lons_h, lats_h)
        minx, maxx = float(tmx_h.min()), float(tmx_h.max())
        miny, maxy = float(tmy_h.min()), float(tmy_h.max())
        c0 = max(VALID_C0, math.floor((minx - TL_X) / TILE_SIDE_M))
        c1 = min(VALID_C1, math.floor((maxx - TL_X) / TILE_SIDE_M))
        r0 = max(VALID_R0, math.floor((TL_Y - maxy) / TILE_SIDE_M))
        r1 = min(VALID_R1, math.floor((TL_Y - miny) / TILE_SIDE_M))
        tiles = [(c, r) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)]
        ntiles = len(tiles)
        log.info("need %d matrix-9 forest tiles (cols[%d,%d] rows[%d,%d])",
                 ntiles, c0, c1, r0, r1)
        _set_status(message=f"downloading {ntiles} tiles", progress=5)

        # 4. Process cached tiles directly, download missing ones concurrently
        dst = np.full((mh, mw), NODATA, dtype=np.uint8)
        done = 0
        applied = 0
        blanked = 0
        cached_count = 0
        to_download = []

        # Process cached tiles first (instant, no network)
        for (c, r) in tiles:
            cached = load_cached_tile(c, r)
            if cached is not None:
                res2 = process_tile_from_array(cached[0], c, r, mx, my, mush_high)
                cached_count += 1
            else:
                to_download.append((c, r))
                res2 = None
            done += 1
            if done % 2000 == 0:
                _set_status(progress=5 + int(90 * done / ntiles))
            if res2 is None:
                continue
            if res2 == "blank":
                blanked += 1
                continue
            rows, cols, ages = res2
            dst[rows, cols] = ages
            applied += len(rows)

        log.info("cached tiles: %d, need to download: %d", cached_count, len(to_download))
        _set_status(message=f"cached {cached_count}, downloading {len(to_download)} tiles", progress=5)

        # Download missing tiles concurrently (fewer workers to avoid overwhelming server)
        if to_download:
            ndown = len(to_download)
            ddone = 0
            with ThreadPoolExecutor(max_workers=8) as ex:
                futs = {ex.submit(process_tile, c, r, mx, my, mush_high): (c, r)
                        for (c, r) in to_download}
                for fut in as_completed(futs):
                    res2 = fut.result()
                    ddone += 1
                    done += 1
                    if res2 is None:
                        if ddone % 500 == 0:
                            log.info("downloaded %d/%d tiles", ddone, ndown)
                        _set_status(progress=5 + int(90 * done / ntiles))
                        continue
                    if res2 == "blank":
                        blanked += 1
                        if ddone % 500 == 0:
                            log.info("downloaded %d/%d tiles (%d blank)", ddone, ndown, blanked)
                        _set_status(progress=5 + int(90 * done / ntiles))
                        continue
                    rows, cols, ages = res2
                    dst[rows, cols] = ages
                    applied += len(rows)
                    if ddone % 500 == 0:
                        log.info("downloaded %d/%d tiles, assigned %d mushroom px (%d blank)",
                                 ddone, ndown, applied, blanked)
                    _set_status(progress=5 + int(90 * done / ntiles))
        log.info("forest age assigned to %d mushroom pixels, %d blank tiles skipped, %d from cache",
                 applied, blanked, cached_count)

        # 5. Per forest age: polygonize intersection
        ages_meta = []
        for a in range(8):
            mask = (dst == a) & mush_high
            inter = np.where(mask, mush_class, 0).astype(np.uint8)
            feats = []
            for geom, val in shapes(inter, transform=mush_transform):
                if val == 0:
                    continue
                g = shape(geom)
                if g.is_empty:
                    continue
                g = g.simplify(tolerance=0.0002, preserve_topology=True)
                if g.is_empty or g.area < 1e-12:
                    continue
                feats.append({
                    "type": "Feature",
                    "geometry": mapping(g),
                    "properties": {
                        "age": a,
                        "ageLabel": FOREST_LABELS[a],
                        "mushClass": int(val),
                        "mushLabel": MUSH_LABELS[int(val)],
                    },
                })
            geojson = {"type": "FeatureCollection", "features": feats}
            with open(os.path.join(DATA_DIR, f"age_{a}.geojson"), "w") as f:
                json.dump(geojson, f)
            ages_meta.append({"id": a, "label": FOREST_LABELS[a], "count": len(feats)})
            log.info("age %d (%s): %d polygons", a, FOREST_LABELS[a], len(feats))

        meta = {
            "timeLabel": time_label,
            "mushBounds": [MUSH_WEST, MUSH_SOUTH, MUSH_EAST, MUSH_NORTH],
            "matrix": TILE_MATRIX,
            "ages": ages_meta,
        }
        with open(os.path.join(DATA_DIR, "meta.json"), "w") as f:
            json.dump(meta, f, indent=2)

        _set_status(status="done", finished_at=time.time(),
                    message="build complete", progress=100, ages=ages_meta)
        log.info("build complete -> %s", DATA_DIR)
    except Exception as exc:
        log.exception("build failed")
        _set_status(status="error", finished_at=time.time(), message=str(exc))
