# ============================================================
# Script: weather_grid_utils.py
# Purpose: Shared helpers for the MRMS / URMA gridded-weather downloaders:
#          NYC crop box, retrying HTTP session, day iteration, atomic parquet
#          write, resume check, manifest writing.
# Inputs: raw_data/taxi_zones/taxi_zones_shp/taxi_zones/taxi_zones.shp
# Outputs: raw_data/weather/nyc_crop_box.json (created once)
# Author: EK  Date: 2026-09-30
# ============================================================

import csv
import datetime as dt
import json
import os
from pathlib import Path

import geopandas as gpd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEATHER_DIR = PROJECT_ROOT / "raw_data" / "weather"
ZONES_SHP = PROJECT_ROOT / "raw_data" / "taxi_zones" / "taxi_zones_shp" / "taxi_zones" / "taxi_zones.shp"
CROP_BOX_PATH = WEATHER_DIR / "nyc_crop_box.json"
CROP_PAD_DEG = 0.05
MANIFEST_FIELDS = ["date", "hour", "url", "bytes", "http_status", "nan_cells", "source", "accessed"]


def get_crop_box() -> dict:
    """NYC bbox in EPSG:4326 (lon_min, lat_min, lon_max, lat_max), padded 0.05 deg.
    Computed once from the taxi-zone shapefile and cached so both downloaders
    use the identical box."""
    if CROP_BOX_PATH.exists():
        return json.loads(CROP_BOX_PATH.read_text())
    zones = gpd.read_file(ZONES_SHP)
    print(f"Taxi zone CRS: {zones.crs}")  # expect EPSG:2263
    assert zones.crs is not None and zones.crs.to_epsg() == 2263, "unexpected zone CRS"
    zones = zones.to_crs(4326)
    x0, y0, x1, y1 = zones.total_bounds
    box = {"lon_min": round(x0 - CROP_PAD_DEG, 4), "lat_min": round(y0 - CROP_PAD_DEG, 4),
           "lon_max": round(x1 + CROP_PAD_DEG, 4), "lat_max": round(y1 + CROP_PAD_DEG, 4),
           "crs": "EPSG:4326", "pad_deg": CROP_PAD_DEG}
    WEATHER_DIR.mkdir(parents=True, exist_ok=True)
    CROP_BOX_PATH.write_text(json.dumps(box, indent=1))
    print(f"Wrote {CROP_BOX_PATH}: {box}")
    return box


def make_session(pool: int = 16) -> requests.Session:
    s = requests.Session()
    retry = Retry(total=5, backoff_factor=1.0, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET", "HEAD"))
    ad = HTTPAdapter(max_retries=retry, pool_connections=pool, pool_maxsize=pool)
    s.mount("https://", ad)
    s.mount("http://", ad)
    return s


def iter_days(start: dt.date, end: dt.date):
    d = start
    while d <= end:
        yield d
        d += dt.timedelta(days=1)


def parse_date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def default_end() -> dt.date:
    return dt.date.today() - dt.timedelta(days=1)


def day_is_done(path: Path) -> bool:
    """Resume check: day parquet exists and its footer is readable."""
    if not path.exists():
        return False
    try:
        pq.read_metadata(path)
        return True
    except Exception:
        return False


def write_parquet_atomic(table: pa.Table, path: Path) -> None:
    """Write to <name>.tmp then os.replace, so a killed run never leaves a
    half-written day that resume logic would accept."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    pq.write_table(table, tmp)
    os.replace(tmp, path)


def append_manifest(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)
