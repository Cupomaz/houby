# syntax=docker/dockerfile:1
FROM python:3.12-slim

# System dependencies required by rasterio / pyproj / shapely (GDAL, PROJ, GEOS)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libgdal-dev \
        libgeos-dev \
        libproj-dev \
        gdal-bin \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py build.py ./
COPY static ./static
COPY probability.png ./

# Generated data (GeoJSON, tile cache) lives here; map a volume or bind-mount it
# so it persists across container restarts and rebuilds.
ENV DATA_DIR=/app/data
ENV FLASK_HOST=0.0.0.0
ENV FLASK_PORT=5000
ENV FLASK_DEBUG=true

EXPOSE 5000

CMD ["python", "app.py"]
