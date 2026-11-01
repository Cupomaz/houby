"""Flask backend serving the Leaflet frontend and the intersection GeoJSONs.
Triggers /auto-rebuilds the mushroom x forest-age intersection via build.py.
"""
import os
import json
import threading
import time

from flask import Flask, jsonify, send_from_directory, request

import build as build_mod

app = Flask(__name__, static_folder="static", template_folder="static")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")

STALE_SECONDS = 24 * 3600  # rebuild if data older than 24h

_build_thread = None
_build_lock = threading.Lock()


def _data_fresh():
    meta_path = os.path.join(DATA_DIR, "meta.json")
    if not os.path.exists(meta_path):
        return False
    try:
        mtime = os.path.getmtime(meta_path)
        return (time.time() - mtime) < STALE_SECONDS
    except OSError:
        return False


def _ensure_built():
    """Build data in the background if missing or stale."""
    global _build_thread
    if _data_fresh():
        return
    with _build_lock:
        if _build_thread is not None and _build_thread.is_alive():
            return  # already rebuilding
        _build_thread = threading.Thread(target=build_mod.run_build, daemon=True)
        _build_thread.start()


@app.before_request
def _startup_build():
    _ensure_built()


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/meta")
def meta():
    path = os.path.join(DATA_DIR, "meta.json")
    if not os.path.exists(path):
        return jsonify({"error": "data not built yet"}), 404
    with open(path) as f:
        return jsonify(json.load(f))


@app.route("/api/status")
def status():
    with build_mod._status_lock:
        status = dict(build_mod.BUILD_STATUS)
    return jsonify(status)


@app.route("/api/rebuild", methods=["POST"])
def rebuild():
    global _build_thread
    with _build_lock:
        if _build_thread is not None and _build_thread.is_alive():
            return jsonify({"error": "rebuild already running"}), 409
        _build_thread = threading.Thread(target=build_mod.run_build, daemon=True)
        _build_thread.start()
    return jsonify({"status": "rebuild started"})


@app.route("/data/<path:filename>")
def data_file(filename):
    return send_from_directory(DATA_DIR, filename)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
