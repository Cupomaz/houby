"""Build intersection GeoJSONs: mushroom probability (highest/2nd highest) x forest age.

Pipeline:
  1. Read mushroom probability PNG (local probability.png if present, else CHMI API).
  2. Classify mushroom pixels to nearest of 5 colors (classes 0-4).
  3. Download WMTS POROSTLCR tiles at matrix 9 (JTSK:epsg:5514) -- the only level
     the service actually serves -- concurrently. Blank/white tiles are skipped.
     Each non-blank tile is classified to nearest of 8 age colors and written
     directly into the mushroom EPSG:4326 grid (one value per mushroom pixel).
  4. Per forest age: mask = forest==age AND mushroom in {3,4}; polygonize;
     write data/age_<a>.geojson + data/meta.json.

Run directly:  python build.py
Or import run_build() from another process (e.g. Flask) with a status callback.
"""
import base64
import io
import json
import logging
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import requests
from PIL import Image
from pyproj import Transformer
from rasterio.transform import Affine
from rasterio.warp import reproject, Resampling
from rasterio.features import shapes
from shapely.geometry import shape, mapping

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("build")

CHMI_URL = "https://data-provider.chmi.cz/api/data/rizika/houby"
WMTS_BASE = "https://geoportal.lesycr.cz/WMTS_LCR/service.svc/get"
LAYER = "POROSTLCR"
TILEMATRIXSET = "JTSK:epsg:5514"
FORMAT = "image/png"
TILE_MATRIX = 9  # the only level the WMTS actually serves

# Mushroom map bounds EPSG:4326 (from prompt.md)
MUSH_WEST, MUSH_SOUTH = 12.0424913, 48.403695
MUSH_EAST, MUSH_NORTH = 19.1177213, 51.0596505

MUSH_COLORS = {
    0: (0xD9, 0x36, 0x29),
    1: (0xF8, 0x8D, 0x51),
    2: (0xFF, 0xFF, 0xBF),
    3: (0x86, 0xCB, 0x66),  # second highest probability
    4: (0x21, 0x9B, 0x51),  # highest probability
}
MUSH_HIGH_CLASSES = {3, 4}
MUSH_LABELS = {3: "second highest", 4: "highest"}

FOREST_COLORS = {
    0: (0xFF, 0xFF, 0x29),  # 1-20 years
    1: (0xFF, 0x8B, 0x62),  # 21-40 years
    2: (0xB4, 0xFF, 0x00),  # 41-60 years
    3: (0xA4, 0xFF, 0xFF),  # 61-80 years
    4: (0xDE, 0x8B, 0x00),  # 81-100 years
    5: (0x9C, 0x9C, 0x9C),  # 101-120 years
    6: (0xD5, 0x7B, 0xFF),  # 121-140 years
    7: (0x0F, 0xFF, 0x73),  # 141 and more years
}
FOREST_LABELS = {
    0: "1-20 years", 1: "21-40 years", 2: "41-60 years", 3: "61-80 years",
    4: "81-100 years", 5: "101-120 years", 6: "121-140 years",
    7: "141 and more years",
}

NODATA = 255
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
LOCAL_MUSHROOM_PNG = os.path.join(HERE, "probability.png")

# JTSK:epsg:5514 grid (parsed from GetCapabilities)
TL_X, TL_Y = -925000.0, -920000.0
MATRIX_9_RES = 14287.5 * 0.00028  # ~4.0005 m / pixel
TILE_SIDE_M = 256 * MATRIX_9_RES
# Valid data limits for POROSTLCR at matrix 9 (from GetCapabilities)
VALID_R0, VALID_R1 = 11, 300
VALID_C0, VALID_C1 = 19, 483

# A tile is considered blank (no forest data) if this fraction of pixels is near-white
BLANK_FRACTION = 0.85
# Pixels whose nearest-color distance exceeds this are treated as NODATA
MAX_DIST_SQ = 40000

# Tile cache: downloaded WMTS tiles are saved here so rebuilds don't re-download
TILE_CACHE_DIR = os.path.join(DATA_DIR, "cache")

_thread_local = threading.local()

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


def nearest_class(rgb, colors, max_dist_sq=MAX_DIST_SQ):
    """Classify each RGB pixel to the nearest colour index.
    Pixels farther than max_dist_sq from every colour -> NODATA.
    Near-white pixels (likely WMTS background outside forest extent) -> NODATA.
    """
    h, w, _ = rgb.shape
    px = rgb.reshape(-1, 3).astype(np.float32)
    best = np.full(px.shape[0], NODATA, dtype=np.uint8)
    best_dist = np.full(px.shape[0], np.inf, dtype=np.float32)

    # near-white pixels = background / outside data extent -> NODATA
    near_white = (px[:, 0] > 240) & (px[:, 1] > 240) & (px[:, 2] > 240)

    for cls, c in colors.items():
        d = ((px - np.asarray(c, dtype=np.float32)) ** 2).sum(axis=1)
        m = (d < best_dist) & (~near_white)
        best[m] = cls
        best_dist[m] = d[m]

    # reject pixels that don't closely match any colour
    best[best_dist > max_dist_sq] = NODATA
    return best.reshape(h, w)


def fetch_mushroom():
    """Return (PIL Image RGB, timeLabel). Uses local probability.png if present."""
    if os.path.exists(LOCAL_MUSHROOM_PNG):
        log.info("using local mushroom map %s", LOCAL_MUSHROOM_PNG)
        img = Image.open(LOCAL_MUSHROOM_PNG).convert("RGB")
        return img, "local probability.png"
    r = requests.get(CHMI_URL, timeout=60)
    r.raise_for_status()
    data = r.json()
    b64 = data.get("img", "")
    if b64.startswith("data:image/png;base64,"):
        b64 = b64.split(",", 1)[1]
    img = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    return img, data.get("timeLabel")


def get_session():
    sess = getattr(_thread_local, "session", None)
    if sess is None:
        sess = requests.Session()
        _thread_local.session = sess
    return sess


def download_tile_with_retries(col, row, max_retries=3):
    # 1. Check local cache first
    os.makedirs(TILE_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(TILE_CACHE_DIR, f"{col}_{row}.png")
    if os.path.exists(cache_path):
        try:
            arr = np.asarray(Image.open(cache_path).convert("RGB"))
            return arr, col, row
        except Exception:
            os.remove(cache_path)  # corrupt cache file, re-download

    # 2. Download from WMTS
    params = {
        "SERVICE": "WMTS", "REQUEST": "GetTile", "VERSION": "1.0.0",
        "LAYER": LAYER, "STYLE": "default", "FORMAT": FORMAT,
        "TILEMATRIXSET": TILEMATRIXSET, "TILEMATRIX": str(TILE_MATRIX),
        "TILEROW": str(row), "TILECOL": str(col),
    }
    sess = get_session()
    for attempt in range(max_retries):
        try:
            r = sess.get(WMTS_BASE, params=params, timeout=40)
            if r.status_code == 200 and r.content:
                img = Image.open(io.BytesIO(r.content)).convert("RGB")
                arr = np.asarray(img)
                # Classify and save age array to cache for future rebuilds
                age_arr = nearest_class(arr, FOREST_COLORS)
                try:
                    np.save(cache_path.replace(".png", ".npy"), age_arr)
                except Exception:
                    pass
                return arr, col, row
        except Exception:
            pass
    return None, col, row


def tile_5514_extent(col, row):
    tx0 = TL_X + col * TILE_SIDE_M
    y_top = TL_Y - row * TILE_SIDE_M
    return tx0, y_top - TILE_SIDE_M, tx0 + TILE_SIDE_M, y_top


def is_blank(arr, fraction=BLANK_FRACTION):
    near_white = (arr[:, :, 0] > 240) & (arr[:, :, 1] > 240) & (arr[:, :, 2] > 240)
    return near_white.mean() >= fraction


def load_cached_tile(col, row):
    """Load a tile from cache if it exists.
    Returns (age_array, col, row) where age_array is a 256x256 uint8 forest-age array,
    or None if not cached."""
    npy_path = os.path.join(TILE_CACHE_DIR, f"{col}_{row}.npy")
    if os.path.exists(npy_path):
        try:
            arr = np.load(npy_path)
            return arr, col, row
        except Exception:
            os.remove(npy_path)
    # Fallback: raw PNG cache (from older builds). Classify and promote to .npy.
    png_path = os.path.join(TILE_CACHE_DIR, f"{col}_{row}.png")
    if not os.path.exists(png_path):
        return None
    try:
        img = Image.open(png_path).convert("RGB")
        arr = np.asarray(img)
        age_arr = nearest_class(arr, FOREST_COLORS)
        try:
            np.save(npy_path, age_arr)
        except Exception:
            pass
        return age_arr, col, row
    except Exception:
        return None


def process_tile_from_array(age_arr, col, row, mx, my, mush_high):
    """Write forest ages from a pre-classified tile into the mushroom grid.
    age_arr: 256x256 uint8 forest-age class array (NODATA where no data).
    Returns "blank" if blank, None if no overlap, or (rows, cols, ages)."""
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


def is_blank_rgb(age_arr):
    """Check if a classified age array is effectively blank (all NODATA)."""
    return (age_arr == NODATA).all()


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


def main():
    run_build()


if __name__ == "__main__":
    main()
