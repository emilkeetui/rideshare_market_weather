# ============================================================
# Script: download_urma_t2m.py
# Purpose: Download hourly NOAA URMA 2.5 km 2 m temperature for the NYC box.
#          Only the TMP 2 m GRIB message (~6 MB of the ~86 MB file) is fetched
#          via HTTP byte ranges, then cropped; only the crop is stored.
# Inputs: none (NOAA AWS open data)
# Outputs: raw_data/weather/urma/t2m/YYYY/urma_t2m_YYYYMMDD.parquet
#            long format: valid_time_utc, cell_row, cell_col, t2m_c
#          raw_data/weather/urma/t2m/grid_urma2p5.json
#          clean_data/urma_download_manifest.csv
# Source (accessed 2026-09-30):
#   https://noaa-urma-pds.s3.amazonaws.com/urma2p5.YYYYMMDD/urma2p5.tHHz.2dvaranl_ndfd.grb2_wexp
#   The .idx is missing for 2019-2021, so GRIB2 message headers are walked:
#   bytes 8-15 of each message = big-endian uint64 total length; Section 4
#   (template 4.0) gives parameter category/number and surface type/value.
#   TMP 2 m = category 0, number 0, surface type 103, value 2. The fetched
#   message is also asserted via GDAL tags (GRIB_ELEMENT == TMP, 2-HTGL).
# Units: GDAL's GRIB driver returns temperature already converted to deg C
#   (tag GRIB_UNIT [C]); stored as t2m_c (plan said Kelvin -- GDAL converts).
# Timezone: valid_time_utc is UTC analysis time (instantaneous).
# Usage: python download_urma_t2m.py [--start] [--end] [--workers N]
# Author: EK  Date: 2026-09-30
# ============================================================

import argparse
import datetime as dt
import json
import struct
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pyarrow as pa
import rasterio
from pyproj import Transformer
from rasterio.windows import Window

sys.path.insert(0, str(Path(__file__).resolve().parent))
import weather_grid_utils as wu

OUT_DIR = wu.WEATHER_DIR / "urma" / "t2m"
MANIFEST = wu.PROJECT_ROOT / "clean_data" / "urma_download_manifest.csv"
URL = ("https://noaa-urma-pds.s3.amazonaws.com/urma2p5.{ymd}/urma2p5.t{h}z.2dvaranl_ndfd.grb2_wexp")
BUFFER_CELLS = 2
SCHEMA = pa.schema([("valid_time_utc", pa.timestamp("us", tz="UTC")), ("cell_row", pa.int16()),
                    ("cell_col", pa.int16()), ("t2m_c", pa.float32())])
MAX_MESSAGES = 20


def rng(session, url, a, b):
    r = session.get(url, headers={"Range": f"bytes={a}-{b}"}, timeout=60)
    if r.status_code not in (200, 206):
        raise RuntimeError(f"HTTP {r.status_code}")
    return r.content


def is_tmp_2m(head: bytes) -> bool:
    """head = first bytes of a GRIB2 message. Walk sections 1..4 and test template 4.0."""
    pos = 16  # after Section 0
    while pos + 5 <= len(head):
        slen, snum = struct.unpack(">IB", head[pos:pos + 5])
        if snum == 4:
            s = head[pos:pos + slen]
            tmpl = struct.unpack(">H", s[7:9])[0]
            cat, num = s[9], s[10]
            surf = s[22]
            return tmpl == 0 and cat == 0 and num == 0 and surf == 103
        pos += slen
    return False


def find_tmp_message(session, url):
    off = 0
    for _ in range(MAX_MESSAGES):
        head = rng(session, url, off, off + 511)
        if head[:4] != b"GRIB":
            raise RuntimeError(f"no GRIB header at offset {off}")
        n = struct.unpack(">Q", head[8:16])[0]
        if is_tmp_2m(head):
            return off, n
        off += n
    raise RuntimeError("TMP 2 m message not found")


def urma_window(src, box):
    tf = Transformer.from_crs(4326, src.crs, always_xy=True)
    xs, ys = tf.transform([box["lon_min"], box["lon_max"], box["lon_min"], box["lon_max"]],
                          [box["lat_min"], box["lat_min"], box["lat_max"], box["lat_max"]])
    r0, c0 = src.index(min(xs), max(ys))
    r1, c1 = src.index(max(xs), min(ys))
    r0, c0 = max(min(r0, r1) - BUFFER_CELLS, 0), max(min(c0, c1) - BUFFER_CELLS, 0)
    r1, c1 = max(r0, r1) + BUFFER_CELLS, max(c0, c1) + BUFFER_CELLS
    return Window(c0, r0, c1 - c0 + 1, r1 - r0 + 1)


def write_grid_json(src, win, box):
    path = OUT_DIR / "grid_urma2p5.json"
    if path.exists():
        return
    tr = src.window_transform(win)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"product": "urma2p5_t2m", "crs_wkt": src.crs.to_wkt(),
                                "transform": list(tr)[:6], "shape": [int(win.height), int(win.width)],
                                "crop_box": box}))
    print(f"  grid definition written: {path.name} shape={int(win.height)}x{int(win.width)} crs={src.crs.to_proj4()}")


def fetch_hour(session, day, hour, box, tmpdir):
    ymd = day.strftime("%Y%m%d")
    url = URL.format(ymd=ymd, h=f"{hour:02d}")
    row = {"date": day.isoformat(), "hour": hour, "url": url, "bytes": 0, "http_status": 0,
           "nan_cells": "", "source": "aws_urma2p5", "accessed": dt.date.today().isoformat()}
    try:
        h = session.head(url, timeout=60)
        if h.status_code != 200:
            row["http_status"] = h.status_code
            return row, None
        off, n = find_tmp_message(session, url)
        msg = rng(session, url, off, off + n - 1)
    except Exception as e:
        row["http_status"] = f"err:{type(e).__name__}:{e}"
        return row, None
    row["http_status"] = 200
    row["bytes"] = len(msg)
    fpath = Path(tmpdir) / f"{ymd}{hour:02d}.grb2"
    fpath.write_bytes(msg)
    try:
        with rasterio.open(fpath) as src:
            tags = src.tags(1)
            assert tags.get("GRIB_ELEMENT") == "TMP" and tags.get("GRIB_SHORT_NAME") == "2-HTGL", tags
            win = urma_window(src, box)
            a = src.read(1, window=win).astype("float32")
            write_grid_json(src, win, box)
    except Exception as e:
        row["http_status"] = f"decode_err:{type(e).__name__}:{e}"
        return row, None
    finally:
        fpath.unlink(missing_ok=True)
    a[(a < -90) | (a > 70) | ~np.isfinite(a)] = np.nan
    row["nan_cells"] = int(np.isnan(a).sum())
    hh, ww = a.shape
    rr, cc = np.meshgrid(np.arange(hh, dtype="int16"), np.arange(ww, dtype="int16"), indexing="ij")
    t = np.datetime64(dt.datetime(day.year, day.month, day.day, hour), "us")
    return row, (t, rr.ravel(), cc.ravel(), a.ravel())


def process_day(session, day, box, workers):
    path = OUT_DIR / f"{day:%Y}" / f"urma_t2m_{day:%Y%m%d}.parquet"
    if wu.day_is_done(path):
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
            "t2m_c": np.concatenate([p[3] for p in parts])}, schema=SCHEMA)
    else:
        tbl = SCHEMA.empty_table()
    wu.write_parquet_atomic(tbl, path)
    wu.append_manifest(MANIFEST, rows)
    return sum(r["bytes"] for r in rows), len(parts), 24 - len(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2019-01-01", type=wu.parse_date)
    ap.add_argument("--end", default=wu.default_end(), type=wu.parse_date)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    box = wu.get_crop_box()
    session = wu.make_session()
    days = list(wu.iter_days(a.start, a.end))
    print(f"URMA: {len(days)} days {a.start}..{a.end}, crop box {box}")
    t0, tot_bytes, done = time.time(), 0, 0
    for day in days:
        t1 = time.time()
        res = process_day(session, day, box, a.workers)
        if res is None:
            continue
        done += 1
        tot_bytes += res[0]
        print(f"{day} ok_hours={res[1]} missing={res[2]} MB={res[0]/1e6:.1f} sec={time.time()-t1:.1f}", flush=True)
    print(f"Done: {done} days written, {tot_bytes/1e9:.2f} GB transferred, {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
