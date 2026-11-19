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
    VALID_C1, BLANK_FRACTION, MAX_DIST_SQ, TILE_MATRIX, TILE_CACHE_DIR, log,
)
from classify import nearest_class, fetch_mushroom, is_blank_rgb
from tiles import load_cached_tile, download_tile_with_retries

# ---- rebuild status (shared with Flask) ----
_status_lock = threading.Lock()
BUILD_STATUS = {
    "status": "idle",       # idle | running | done | error
    "started_at": None,
    "finished_at": None,
    "message": "",
    "progress": 0,          # 0-100
    "ages": [],
    "cached": 0,            # tiles served from local cache
    "downloading": 0,       # tiles still to download from WMTS
    "ntiles": 0,            # total tiles needed for this run
}


def _set_status(**kwargs):
    with _status_lock:
        BUILD_STATUS.update(kwargs)


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
        log.info("tile cache dir: %s (%d files present)",
                 TILE_CACHE_DIR, len([f for f in os.listdir(TILE_CACHE_DIR)
                                      if f.endswith(".npy")]) if os.path.exists(TILE_CACHE_DIR) else 0)

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
        _set_status(message=f"planning {ntiles} tiles", progress=5,
                    ntiles=ntiles, cached=0, downloading=0)

        # 4. Process tiles that contain high-probability mushrooms.
        #
        # Instead of masking the full mushroom grid once per tile (O(tiles x pixels)),
        # compute each mushroom pixel's WMTS tile once (O(pixels)), group pixels by tile,
        # and only load/download tiles that actually have mushrooms.
        dst = np.full((mh, mw), NODATA, dtype=np.uint8)
        processed = 0
        applied = 0
        blanked = 0
        cached_count = 0
        downloaded_count = 0

        # Snapshot of what is already on disk so each cached-tile load avoids a
        # per-file stat() syscall.
        cache_files = set()
        if os.path.isdir(TILE_CACHE_DIR):
            cache_files = {f for f in os.listdir(TILE_CACHE_DIR) if f.endswith(".npy")}

        # --- Per-pixel tile assignment (computed once for all mushrooms) ---
        TILE_PX = 256  # matrix-9 tile side in pixels
        mx_flat = mx.ravel()
        my_flat = my.ravel()
        high_flat = mush_high.ravel()

        gx = np.floor((mx_flat - TL_X) / MATRIX_9_RES).astype(np.int64)
        gy = np.floor((TL_Y - my_flat) / MATRIX_9_RES).astype(np.int64)

        # Restrict to pixels inside the valid WMTS extent before dividing into
        # per-tile coordinates, keeping full-size arrays short-lived.
        in_extent = (
            high_flat
            & (gx >= VALID_C0 * TILE_PX)
            & (gx <= (VALID_C1 + 1) * TILE_PX - 1)
            & (gy >= VALID_R0 * TILE_PX)
            & (gy <= (VALID_R1 + 1) * TILE_PX - 1)
        )
        pix_idx = np.nonzero(in_extent)[0]
        del in_extent, high_flat

        gx_v = gx[pix_idx]
        gy_v = gy[pix_idx]
        del gx, gy

        tile_c_v = gx_v // TILE_PX
        tc_v = gx_v % TILE_PX
        tile_r_v = gy_v // TILE_PX
        tr_v = gy_v % TILE_PX
        del gx_v, gy_v

        in_tile = (
            (tile_c_v >= VALID_C0) & (tile_c_v <= VALID_C1)
            & (tile_r_v >= VALID_R0) & (tile_r_v <= VALID_R1)
        )
        pix_idx = pix_idx[in_tile]
        tile_c_v = tile_c_v[in_tile]
        tc_v = tc_v[in_tile]
        tile_r_v = tile_r_v[in_tile]
        tr_v = tr_v[in_tile]
        del in_tile

        mush_r_v = (pix_idx // mw).astype(np.int64)
        mush_c_v = (pix_idx % mw).astype(np.int64)

        # --- Group pixels by tile ---
        key = tile_r_v.astype(np.int64) * 4096 + tile_c_v.astype(np.int64)
        _, inverse = np.unique(key, return_inverse=True)
        sort_idx = np.argsort(inverse, kind="stable")
        inverse_sorted = inverse[sort_idx]
        pix_sorted = pix_idx[sort_idx]
        tile_r_sorted = tile_r_v[sort_idx]
        tile_c_sorted = tile_c_v[sort_idx]
        tc_sorted = tc_v[sort_idx]
        tr_sorted = tr_v[sort_idx]
        mush_r_sorted = mush_r_v[sort_idx]
        mush_c_sorted = mush_c_v[sort_idx]

        bounds = np.nonzero(np.diff(inverse_sorted) != 0)[0] + 1
        starts = np.concatenate(([0], bounds))
        ends = np.concatenate((bounds, [len(pix_sorted)]))

        tile_tasks = []  # (col, row, start, end)
        for s, e in zip(starts, ends):
            if s < e:
                tile_tasks.append(
                    (int(tile_c_sorted[s]), int(tile_r_sorted[s]), int(s), int(e))
                )

        log.info(
            "%d of %d planned tiles contain high-probability mushroom pixels",
            len(tile_tasks),
            ntiles,
        )

        def _load_tile_age(c, r):
            """Return (age_array_or_None, was_cached) for one tile."""
            cached = load_cached_tile(c, r, cache_files)
            if cached is not None:
                return cached[0], True
            arr, _, _ = download_tile_with_retries(c, r)
            if arr is None:
                return None, False
            age_arr = nearest_class(arr, FOREST_COLORS)
            return age_arr, False

        def _run_phase(tasks, max_workers, start_processed):
            """Process a batch of tile tasks; return per-phase counters."""
            p = a = b = c = d = 0
            if not tasks:
                return p, a, b, c, d
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futs = {
                    ex.submit(_load_tile_age, cc, rr): (cc, rr, ss, ee)
                    for (cc, rr, ss, ee) in tasks
                }
                for fut in as_completed(futs):
                    cc, rr, ss, ee = futs[fut]
                    age_arr, was_cached = fut.result()
                    p += 1
                    if p % 2000 == 0:
                        _set_status(
                            progress=5 + int(90 * (start_processed + p) / ntiles)
                        )
                    if was_cached:
                        c += 1
                    elif age_arr is not None:
                        d += 1
                    if age_arr is None:
                        continue
                    if is_blank_rgb(age_arr):
                        b += 1
                        continue
                    ages = age_arr[tr_sorted[ss:ee], tc_sorted[ss:ee]]
                    dst[mush_r_sorted[ss:ee], mush_c_sorted[ss:ee]] = ages
                    a += len(ages)
            return p, a, b, c, d

        # Split into cached vs to-download so pools can be sized differently.
        cached_tasks = [t for t in tile_tasks if f"{t[0]}_{t[1]}.npy" in cache_files]
        download_tasks = [t for t in tile_tasks if f"{t[0]}_{t[1]}.npy" not in cache_files]

        # Phase 1: tiles already in cache (fast local reads, more workers).
        max_workers_cache = min(32, (os.cpu_count() or 4) + 4)
        p1, a1, b1, c1, d1 = _run_phase(cached_tasks, max_workers_cache, 0)
        processed = p1

        # Phase 2: tiles to download from WMTS (network-bound, fewer workers).
        p2, a2, b2, c2, d2 = _run_phase(download_tasks, 8, processed)
        processed += p2

        applied = a1 + a2
        blanked = b1 + b2
        cached_count = c1 + c2
        downloaded_count = d1 + d2

        log.info(
            "cached tiles: %d, downloaded: %d, missing/failed: %d, "
            "blank: %d, mushroom px assigned: %d",
            cached_count,
            downloaded_count,
            len(tile_tasks) - cached_count - downloaded_count - blanked,
            blanked,
            applied,
        )
        _set_status(
            message=f"cached {cached_count}, downloaded {downloaded_count} of {ntiles} tiles",
            progress=5,
            ntiles=ntiles,
            cached=cached_count,
            downloading=len(download_tasks),
        )

        # 5. Per forest age: polygonize intersection
        _set_status(message="polygonizing forest ages", progress=95)
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
