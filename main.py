from tile_downloader import WMTSDownloader

if __name__ == "__main__":
    downloader = WMTSDownloader()
    downloader.download_grid(max_rows=511, max_cols=511)