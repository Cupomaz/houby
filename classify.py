"""Pixel classification and mushroom raster loading."""
import base64
import io
import os

import requests
from PIL import Image
import numpy as np

from config import NODATA, MAX_DIST_SQ, MUSH_COLORS, FOREST_COLORS, CHMI_URL, LOCAL_MUSHROOM_PNG, log


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


def is_blank(arr, fraction=0.85):
    """True if at least `fraction` of pixels are near-white (no data)."""
    near_white = (arr[:, :, 0] > 240) & (arr[:, :, 1] > 240) & (arr[:, :, 2] > 240)
    return near_white.mean() >= fraction


def is_blank_rgb(age_arr):
    """Check if a classified age array is effectively blank (all NODATA)."""
    return (age_arr == NODATA).all()
