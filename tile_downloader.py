import os
from concurrent.futures import ThreadPoolExecutor
import requests
import config

class WMTSDownloader:
    def __init__(self, max_workers=config.MAX_WORKERS, output_dir=config.OUTPUT_DIR):
        self.max_workers = max_workers
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=max_workers, pool_maxsize=max_workers
        )
        self.session.mount("https://", adapter)

    def download_tile(self, row: int, col: int):
        url = (
            f"{config.BASE_URL}?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
            f"&LAYER={config.LAYER}&STYLE=default"
            f"&TILEMATRIXSET={config.TILE_MATRIX_SET}"
            f"&TILEMATRIX={config.TILE_MATRIX}"
            f"&TILEROW={row}&TILECOL={col}&FORMAT=image/png"
        )
        try:
            r = self.session.get(url, timeout=10)
            if r.status_code == 200:
                filepath = os.path.join(self.output_dir, f"{row}x{col}.png")
                with open(filepath, "wb") as f:
                    f.write(r.content)
                print(f"Downloaded tile {row}x{col}")
            else:
                print(f"Tile {row}x{col} unavailable ({r.status_code})")
        except Exception as e:
            print(f"Error downloading {row}x{col}: {e}")

    def download_grid(self, max_rows=511, max_cols=511):
        tasks = [(r, c) for r in range(max_rows) for c in range(max_cols)]
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            executor.map(lambda coords: self.download_tile(*coords), tasks)