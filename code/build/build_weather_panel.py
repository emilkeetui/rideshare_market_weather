# ============================================================
# Script: build_weather_panel.py
# Purpose: Aggregate cropped MRMS rainfall and URMA 2 m temperature grids to
#          NYC taxi zone x hour (area-weighted), in America/New_York time.
# Inputs: raw_data/weather/mrms/qpe_01h/YYYY/*.parquet + grid_<product>.json
#         raw_data/weather/urma/t2m/YYYY/*.parquet + grid_urma2p5.json
#         raw_data/taxi_zones/taxi_zones_shp/taxi_zones/taxi_zones.shp
# Outputs: clean_data/weather_zone_hour.parquet  (or --out)
#          columns: pu_zone_id, datetime_hour, precip_mm, precip_cover_share,
#                   mrms_product, temp_c, temp_cover_share
# Method: AREA WEIGHTING, not centroid sampling. Grid cells are polygons; cell x
#   zone intersections are computed in EPSG:2263 (ft, equal-enough area for NYC);
#   weight = intersection area / zone area. Zone value = sum(w*x) / sum(w) over
#   non-NaN cells; *_cover_share = sum(w) over non-NaN cells (share of zone area
#   with valid data).
# TIMEZONE (the only UTC -> America/New_York conversion in the pipeline):
#   MRMS file time = END of the 1-h accumulation (UTC). Rain in [t-1h, t) is
#     labelled datetime_hour = (t - 1h) in local time, matching the TLC
#     floor-to-hour convention (file 02Z = 21:00 EDT hour on 2021-09-01).
#   URMA is an instantaneous analysis at HH:00 UTC -> datetime_hour = HH:00 local.
#   DST fall-back creates two identical wall-clock hours; tz-aware timestamps
#   stay unique.
# Precip cum/max are left to event-specific scripts (depend on event window).
# Usage: python build_weather_panel.py [--start-year 2019] [--end-year 2026] [--out path]
# Author: EK  Date: 2026-09-30
# ============================================================

import argparse
import glob
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import scipy.sparse as sp
from shapely.geometry import box as shp_box

sys.path.insert(0, str(Path(__file__).resolve().parent))
import weather_grid_utils as wu

ROOT = wu.PROJECT_ROOT
MRMS_DIR = wu.WEATHER_DIR / "mrms" / "qpe_01h"
URMA_DIR = wu.WEATHER_DIR / "urma" / "t2m"
DEFAULT_OUT = ROOT / "clean_data" / "weather_zone_hour.parquet"
NY = "America/New_York"


def load_zones() -> gpd.GeoDataFrame:
    z = gpd.read_file(wu.ZONES_SHP)
    print(f"Zone CRS (shapefile): {z.crs}")
    z = z.to_crs(2263)
    z = z[["LocationID", "geometry"]].dissolve(by="LocationID").reset_index()  # some IDs are multipart
    z["zone_area"] = z.geometry.area
    return z


def build_weights(grid: dict, zones: gpd.GeoDataFrame, label: str):
    """Sparse (n_zones x n_cells) area-weight matrix; cell index = row * ncols + col."""
    tr = grid["transform"]  # a, b, c, d, e, f (affine)
    h, w = grid["shape"]
    polys, idx = [], []
    for r in range(h):
        for c in range(w):
            x0, y0 = tr[2] + c * tr[0], tr[5] + r * tr[4]
            x1, y1 = x0 + tr[0], y0 + tr[4]
            polys.append(shp_box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))
            idx.append(r * w + c)
    cells = gpd.GeoDataFrame({"cell_idx": idx}, geometry=polys, crs=grid["crs_wkt"])
    print(f"[{label}] cell CRS: {cells.crs.to_string()[:40]}..., zone CRS: EPSG:{zones.crs.to_epsg()}")
    cells = cells.to_crs(zones.crs)
    assert cells.crs == zones.crs, "CRS mismatch before overlay"
    ov = gpd.overlay(cells, zones[["LocationID", "zone_area", "geometry"]], how="intersection")
    ov["w"] = ov.geometry.area / ov["zone_area"]
    zone_ids = np.sort(zones["LocationID"].unique())
    zpos = {z: i for i, z in enumerate(zone_ids)}
    W = sp.csr_matrix((ov["w"].values, (ov["LocationID"].map(zpos).values, ov["cell_idx"].values)),
                      shape=(len(zone_ids), h * w))
    ws = np.asarray(W.sum(axis=1)).ravel()
    ncell = np.asarray((W > 0).sum(axis=1)).ravel()
    print(f"[{label}] weight sums per zone: min={ws.min():.4f} median={np.median(ws):.4f} max={ws.max():.4f}; "
          f"cells/zone min={ncell.min()} median={int(np.median(ncell))} max={ncell.max()}")
    assert ws.min() > 0.98 and ws.max() < 1.02, "zone not fully covered by the cropped grid"
    return W, zone_ids


def aggregate(files, value_col, W, ncells, zone_ids, shift_hours):
    """Weighted zone means for every hour in `files`. Returns long DataFrame."""
    if not files:
        return pd.DataFrame()
    tbl = pa.concat_tables([pq.read_table(f) for f in files]).to_pandas()
    if tbl.empty:
        return pd.DataFrame()
    tbl["cell_idx"] = tbl["cell_row"].astype("int32") * (ncells[1]) + tbl["cell_col"].astype("int32")
    times = np.sort(tbl["valid_time_utc"].unique())
    tpos = {t: i for i, t in enumerate(times)}
    X = np.full((len(times), ncells[0] * ncells[1]), np.nan, dtype="float64")
    X[tbl["valid_time_utc"].map(tpos).values, tbl["cell_idx"].values] = tbl[value_col].values
    valid = ~np.isnan(X)
    num = W @ np.nan_to_num(X).T  # zones x hours
    den = W @ valid.T.astype("float64")
    with np.errstate(invalid="ignore", divide="ignore"):
        val = np.where(den > 0, num / den, np.nan)
    prod = None
    if "product" in tbl:
        prod = tbl.groupby("valid_time_utc")["product"].first().reindex(times).values
    t_utc = pd.DatetimeIndex(times).tz_localize("UTC") if pd.DatetimeIndex(times).tz is None \
        else pd.DatetimeIndex(times)
    dh = (t_utc - pd.Timedelta(hours=shift_hours)).tz_convert(NY)
    out = pd.DataFrame({"pu_zone_id": np.repeat(zone_ids, len(times)).astype("int32"),
                        "datetime_hour": np.tile(dh, len(zone_ids)),
                        "val": val.ravel(), "cover": den.ravel()})
    if prod is not None:
        out["product"] = np.tile(prod, len(zone_ids))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-year", type=int, default=2019)
    ap.add_argument("--end-year", type=int, default=2026)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = ap.parse_args()
    if a.out.exists():
        print(f"WARNING: {a.out} already exists -- overwriting")

    zones = load_zones()
    mg = {p: json.loads(Path(f).read_text()) for p, f in
          [(Path(f).stem.replace("grid_", ""), f) for f in glob.glob(str(MRMS_DIR / "grid_*.json"))]}
    for p, g in mg.items():
        g.pop("cell_center_lon", None), g.pop("cell_center_lat", None)
    prods = list(mg)
    same = all(mg[p]["transform"] == mg[prods[0]]["transform"] and mg[p]["shape"] == mg[prods[0]]["shape"]
               for p in prods)
    print(f"MRMS products {prods}; grids identical across products: {same}")
    assert same, "MRMS product grids differ -- need per-product weights"
    g_mrms = mg[prods[0]]
    g_urma = json.loads((URMA_DIR / "grid_urma2p5.json").read_text())
    W_m, zone_ids = build_weights(g_mrms, zones, "MRMS")
    W_u, _ = build_weights(g_urma, zones, "URMA")

    # Aggregate year by year (bounded memory), then merge MRMS and URMA once so hours
    # straddling a UTC year boundary cannot create duplicate keys.
    m_parts, u_parts = [], []
    for yr in range(a.start_year, a.end_year + 1):
        mf = sorted(glob.glob(str(MRMS_DIR / str(yr) / "*.parquet")))
        uf = sorted(glob.glob(str(URMA_DIR / str(yr) / "*.parquet")))
        m = aggregate(mf, "precip_mm", W_m, g_mrms["shape"], zone_ids, shift_hours=1)
        u = aggregate(uf, "t2m_c", W_u, g_urma["shape"], zone_ids, shift_hours=0)
        if len(m):
            m_parts.append(m.rename(columns={"val": "precip_mm", "cover": "precip_cover_share",
                                             "product": "mrms_product"}))
        if len(u):
            u_parts.append(u.rename(columns={"val": "temp_c", "cover": "temp_cover_share"}))
        print(f"{yr}: mrms rows={len(m):,} urma rows={len(u):,}", flush=True)
        del m, u
    m = pd.concat(m_parts, ignore_index=True)
    u = pd.concat(u_parts, ignore_index=True)
    del m_parts, u_parts
    df = m.merge(u, on=["pu_zone_id", "datetime_hour"], how="outer")
    del m, u
    df["pu_zone_id"] = df["pu_zone_id"].astype("int32")
    df["mrms_product"] = df["mrms_product"].astype(str).replace("nan", "")
    for c in ["precip_mm", "precip_cover_share", "temp_c", "temp_cover_share"]:
        df[c] = df[c].astype("float32")
    df = df.sort_values(["pu_zone_id", "datetime_hour"]).reset_index(drop=True)
    assert str(df["datetime_hour"].dt.tz) == NY, "datetime_hour tz is wrong"
    assert not df.duplicated(["pu_zone_id", "datetime_hour"]).any(), "duplicate keys"
    print(df.dtypes)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(a.out, index=False, engine="pyarrow")
    res = pd.read_parquet(a.out, engine="pyarrow")
    print(f"Written {len(res):,} rows x {res.shape[1]} columns to {a.out} "
          f"({a.out.stat().st_size/1e6:.0f} MB)")
    print(f"Date range: {res['datetime_hour'].min()} to {res['datetime_hour'].max()}")
    print(f"Zones: {res['pu_zone_id'].nunique()}")


if __name__ == "__main__":
    main()
