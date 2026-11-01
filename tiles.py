"""WMTS tile download, caching, and extent helpers."""
import io
import os
import threading

import requests
from PIL import Image
import numpy as np

from config import (
    WMTS_BASE, LAYER, STYLE, FORMAT, TILEMATRIXSET, TILE_MATRIX,
    TILE_CACHE_DIR, FOREST_COLORS, TL_X, TL_Y, TILE_SIDE_M, NODATA, log,
)
from classify import nearest_class

_thread_local = threading.local()


def get_session():
    """Return a thread-local requests.Session."""
    sess = getattr(_thread_local, "session", None)
    if sess is None:
        sess = requests.Session()
        _thread_local.session = sess
    return sess


def tile_5514_extent(col, row):
    """Return (xmin, ymin, xmax, ymax) extent of a WMTS tile in EPSG:5514."""
    tx0 = TL_X + col * TILE_SIDE_M
    y_top = TL_Y - row * TILE_SIDE_M
    return tx0, y_top - TILE_SIDE_M, tx0 + TILE_SIDE_M, y_top


def download_tile_with_retries(col, row, max_retries=3):
    """Download (or load from cache) one WMTS tile.

    Returns (rgb_array, col, row) or (None, col, row) on failure.
    Classified age array is cached as .npy for future rebuilds.
    """
    os.makedirs(TILE_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(TILE_CACHE_DIR, f"{col}_{row}.png")
    if os.path.exists(cache_path):
        try:
            arr = np.asarray(Image.open(cache_path).convert("RGB"))
            return arr, col, row
        except Exception:
            os.remove(cache_path)  # corrupt cache file, re-download

    params = {
        "SERVICE": "WMTS", "REQUEST": "GetTile", "VERSION": "1.0.0",
        "LAYER": LAYER, "STYLE": STYLE, "FORMAT": FORMAT,
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


def load_cached_tile(col, row):
    """Load a tile from cache if it exists.

    Returns (age_array, col, row) where age_array is a 256x256 uint8 forest-age
    array (NODATA where no data), or None if not cached.
    """
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
