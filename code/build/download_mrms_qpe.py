# ============================================================
# Script: download_mrms_qpe.py
# Purpose: Download hourly NOAA MRMS QPE (0.01 deg, ~1 km), crop each file to
#          the NYC box at download time, and store only the crop.
# Inputs: none (public archives; see sources)
# Outputs: raw_data/weather/mrms/qpe_01h/YYYY/mrms_qpe_01h_YYYYMMDD.parquet
#            long format: valid_time_utc, cell_row, cell_col, precip_mm, product
#          raw_data/weather/mrms/qpe_01h/grid_<product>.json  (grid definition)
#          clean_data/mrms_download_manifest.csv
# Sources (accessed 2026-09-30):
#   2019-01-01 .. 2020-10-13: Iowa State IEM archive, GaugeCorr (MRMS v11)
#     https://mtarchive.geol.iastate.edu/YYYY/MM/DD/mrms/ncep/GaugeCorr_QPE_01H/GaugeCorr_QPE_01H_00.00_YYYYMMDD-HH0000.grib2.gz
#   2020-10-14 .. present: NOAA AWS open data, MultiSensor Pass2 (MRMS v12)
#     https://noaa-mrms-pds.s3.amazonaws.com/CONUS/MultiSensor_QPE_01H_Pass2_00.00/YYYYMMDD/MRMS_MultiSensor_QPE_01H_Pass2_00.00_YYYYMMDD-HH0000.grib2.gz
#   PRODUCT BREAK at 2020-10-14 20Z (recorded in `product`); 19Z is in neither archive.
# Conventions: file time is UTC and is the END of the 1-h accumulation.
#   Values < 0 (-3 = no radar coverage, -999 etc.) are set to NaN.
#   Full CONUS files live only in the OS temp dir and are deleted after cropping.
# Usage: python download_mrms_qpe.py [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--workers N]
# Author: EK  Date: 2026-09-30
# ============================================================

import argparse
import datetime as dt
import json
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pyarrow as pa
import rasterio
from rasterio.windows import from_bounds

sys.path.insert(0, str(Path(__file__).resolve().parent))
import weather_grid_utils as wu

OUT_DIR = wu.WEATHER_DIR / "mrms" / "qpe_01h"
MANIFEST = wu.PROJECT_ROOT / "clean_data" / "mrms_download_manifest.csv"
# Verified 2026-09-30: IEM GaugeCorr last file is 2020-10-14 18Z; AWS Pass2 first file is 2020-10-14 20Z
# (19Z exists in neither archive and is recorded as missing).
BREAK_DATE = dt.date(2020, 10, 14)
BREAK_HOUR = 20
FORCE = False
IEM_URL = ("https://mtarchive.geol.iastate.edu/{y}/{m}/{d}/mrms/ncep/GaugeCorr_QPE_01H/"
           "GaugeCorr_QPE_01H_00.00_{ymd}-{h}0000.grib2.gz")
AWS_URL = ("https://noaa-mrms-pds.s3.amazonaws.com/CONUS/MultiSensor_QPE_01H_Pass2_00.00/{ymd}/"
           "MRMS_MultiSensor_QPE_01H_Pass2_00.00_{ymd}-{h}0000.grib2.gz")
SCHEMA = pa.schema([("valid_time_utc", pa.timestamp("us", tz="UTC")), ("cell_row", pa.int16()),
                    ("cell_col", pa.int16()), ("precip_mm", pa.float32()), ("product", pa.string())])


def source_for(day: dt.date, hour: int):
    if (day, hour) < (BREAK_DATE, BREAK_HOUR):
        return "iem", "GaugeCorr_QPE_01H", IEM_URL
    return "aws", "MultiSensor_QPE_01H_Pass2", AWS_URL


def write_grid_json(product: str, src, window, box) -> None:
    path = OUT_DIR / f"grid_{product}.json"
    if path.exists():
        return
    tr = src.window_transform(window)
    h, w = int(window.height), int(window.width)
    rows, cols = np.meshgrid(np.arange(h), np.arange(w), indexing="ij")
    lon = tr.c + (cols + 0.5) * tr.a
    lat = tr.f + (rows + 0.5) * tr.e
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "product": product, "crs_wkt": src.crs.to_wkt(), "transform": list(tr)[:6],
        "shape": [h, w], "crop_box": box,
        "cell_center_lon": lon.round(5).tolist(), "cell_center_lat": lat.round(5).tolist()}))
    print(f"  grid definition written: {path.name} shape={h}x{w} transform={tr}")


def fetch_hour(session, day, hour, box, tmpdir):
    src_name, product, tmpl = source_for(day, hour)
    ymd = day.strftime("%Y%m%d")
    url = tmpl.format(y=f"{day:%Y}", m=f"{day:%m}", d=f"{day:%d}", ymd=ymd, h=f"{hour:02d}")
    row = {"date": day.isoformat(), "hour": hour, "url": url, "bytes": 0, "http_status": 0,
           "nan_cells": "", "source": src_name, "accessed": dt.date.today().isoformat()}
    try:
        r = session.get(url, timeout=60)
    except Exception as e:
        row["http_status"] = f"err:{type(e).__name__}"
        return row, None
    row["http_status"] = r.status_code
    if r.status_code != 200:
        return row, None
    row["bytes"] = len(r.content)
    fpath = Path(tmpdir) / f"{ymd}{hour:02d}_{src_name}.grib2.gz"
    fpath.write_bytes(r.content)
    try:
        with rasterio.open(f"/vsigzip/{fpath.as_posix()}") as src:
            # MRMS grid is EPSG:4326-like with lon in -180..180 (verified 2026-09-30)
            assert src.bounds.left < 0, "MRMS longitudes not in -180..180; convert crop box"
            win = from_bounds(box["lon_min"], box["lat_min"], box["lon_max"], box["lat_max"], src.transform)
            win = win.round_offsets().round_lengths()
            a = src.read(1, window=win).astype("float32")
            write_grid_json(product, src, win, box)
    except Exception as e:
        row["http_status"] = f"decode_err:{type(e).__name__}:{e}"
        return row, None
    finally:
        fpath.unlink(missing_ok=True)
    a[a < 0] = np.nan
    row["nan_cells"] = int(np.isnan(a).sum())
    h, w = a.shape
    rr, cc = np.meshgrid(np.arange(h, dtype="int16"), np.arange(w, dtype="int16"), indexing="ij")
    t = np.datetime64(dt.datetime(day.year, day.month, day.day, hour), "us")
    return row, (t, rr.ravel(), cc.ravel(), a.ravel(), product)


def process_day(session, day, box, workers):
    path = OUT_DIR / f"{day:%Y}" / f"mrms_qpe_01h_{day:%Y%m%d}.parquet"
    if wu.day_is_done(path) and not FORCE:
        return None
    with tempfile.TemporaryDirectory() as tmp:  # OS temp dir, never raw_data/
        with ThreadPoolExecutor(workers) as ex:
            results = list(ex.map(lambda h: fetch_hour(session, day, h, box, tmp), range(24)))
    rows = [r for r, _ in results]
    parts = [p for _, p in results if p is not None]
    if parts:
        tbl = pa.table({
            "valid_time_utc": pa.array(np.concatenate([np.full(len(p[1]), p[0]) for p in parts]),
                                       type=pa.timestamp("us", tz="UTC")),
            "cell_row": np.concatenate([p[1] for p in parts]),
            "cell_col": np.concatenate([p[2] for p in parts]),
            "precip_mm": np.concatenate([p[3] for p in parts]),
            "product": np.concatenate([np.full(len(p[1]), p[4]) for p in parts])}, schema=SCHEMA)
        wu.write_parquet_atomic(tbl, path)
    else:  # whole day missing: still write an empty file so resume skips it; manifest has the 404s
        wu.write_parquet_atomic(SCHEMA.empty_table(), path)
    wu.append_manifest(MANIFEST, rows)
    return sum(r["bytes"] for r in rows), sum(1 for p in parts), 24 - len(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2019-01-01", type=wu.parse_date)
    ap.add_argument("--end", default=wu.default_end(), type=wu.parse_date)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--force", action="store_true", help="rewrite existing day files (atomic replace)")
    a = ap.parse_args()
    global FORCE
    FORCE = a.force
    box = wu.get_crop_box()
    session = wu.make_session()
    days = list(wu.iter_days(a.start, a.end))
    print(f"MRMS: {len(days)} days {a.start}..{a.end}, crop box {box}")
    t0, tot_bytes, done = time.time(), 0, 0
    for day in days:
        workers = a.workers or (4 if day < BREAK_DATE else 8)
        t1 = time.time()
        res = process_day(session, day, box, workers)
        if res is None:
            continue
        done += 1
        tot_bytes += res[0]
        print(f"{day} ok_hours={res[1]} missing={res[2]} MB={res[0]/1e6:.1f} sec={time.time()-t1:.1f}", flush=True)
    print(f"Done: {done} days written, {tot_bytes/1e9:.2f} GB transferred, {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
