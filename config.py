"""Shared configuration constants for the houby build pipeline."""
import os
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("build")

# --- External services ---
CHMI_URL = "https://data-provider.chmi.cz/api/data/rizika/houby"
WMTS_BASE = "https://geoportal.lesycr.cz/WMTS_LCR/service.svc/get"
LAYER = "POROSTLCR"
TILEMATRIXSET = "JTSK:epsg:5514"
FORMAT = "image/png"
TILE_MATRIX = 9  # the only level the WMTS actually serves
STYLE = "default"

# --- Mushroom map bounds EPSG:4326 (from prompt.md) ---
MUSH_WEST, MUSH_SOUTH = 12.0424913, 48.403695
MUSH_EAST, MUSH_NORTH = 19.1177213, 51.0596505

# Mushroom probability colours (id -> RGB). 0 is lowest, 4 is highest.
MUSH_COLORS = {
    0: (0xD9, 0x36, 0x29),
    1: (0xF8, 0x8D, 0x51),
    2: (0xFF, 0xFF, 0xBF),
    3: (0x86, 0xCB, 0x66),  # second highest probability
    4: (0x21, 0x9B, 0x51),  # highest probability
}
MUSH_HIGH_CLASSES = {3, 4}
MUSH_LABELS = {3: "second highest", 4: "highest"}

# Forest age colours (id -> RGB) and labels.
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

# --- Filesystem paths ---
NODATA = 255
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
LOCAL_MUSHROOM_PNG = os.path.join(HERE, "probability.png")
TILE_CACHE_DIR = os.path.join(DATA_DIR, "cache")

# --- JTSK:epsg:5514 grid (parsed from GetCapabilities) ---
TL_X, TL_Y = -925000.0, -920000.0
MATRIX_9_RES = 14287.5 * 0.00028  # ~4.0005 m / pixel
TILE_SIDE_M = 256 * MATRIX_9_RES
# Valid data limits for POROSTLCR at matrix 9 (from GetCapabilities)
VALID_R0, VALID_R1 = 11, 300
VALID_C0, VALID_C1 = 19, 483

# --- Classification thresholds ---
# A tile is considered blank (no forest data) if this fraction of pixels is near-white
BLANK_FRACTION = 0.85
# Pixels whose nearest-color distance exceeds this are treated as NODATA
MAX_DIST_SQ = 40000
