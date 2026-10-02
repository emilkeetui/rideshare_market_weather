# ============================================================
# Script: build_od_weather_cells.py
# Purpose: Collapse 2021 HVFHV trips to OD cells (platform x PU zone x DO zone
#          x pickup hour x dropoff hour) carrying origin (pickup-hour) and
#          destination (dropoff-hour) rainfall/temperature, for the binned
#          driver_share regression. Weighted cell means (weights = n_trips)
#          reproduce trip-level OLS exactly because every regressor and FE is
#          constant within a cell.
# Inputs: raw_data/hvfhv/fhvhv_tripdata_2021-MM.parquet (read via DuckDB,
#         streamed, 10 columns only)
#         clean_data/weather_zone_hour.parquet (read only, never rebuilt)
# Outputs: clean_data/od_weather_cells_2021/cells_2021-MM.parquet
#          output/sum/od_cells_filter_attrition_2021.csv
#          output/sum/od_cells_build_log_2021.csv
# CLI: --months 08,09 (default all 12)   --force (rebuild existing month files)
#      --out-dir DIR (default clean_data/od_weather_cells_2021; v2 adds sum_log_fare, sum_log_pay)
# Timezones: TLC timestamps are naive local wall clock (America/New_York, no tz
#          marker). weather_zone_hour.parquet datetime_hour is tz-aware
#          America/New_York; it is converted to naive wall clock by dropping the
#          tz label (NOT a UTC conversion) so it matches TLC wall-clock hours.
# Author: EK  Date: 2026-09-30
# Revision 2026-09-30: DO zone 265 kept (see FILTER_RULES_SQL).
# ============================================================

import argparse
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HVFHV_DIR = PROJECT_ROOT / "raw_data" / "hvfhv"
WEATHER_PATH = PROJECT_ROOT / "clean_data" / "weather_zone_hour.parquet"
OUT_DIR = PROJECT_ROOT / "clean_data" / "od_weather_cells_2021"
ATTRITION_PATH = PROJECT_ROOT / "output" / "sum" / "od_cells_filter_attrition_2021.csv"
BUILD_LOG_PATH = PROJECT_ROOT / "output" / "sum" / "od_cells_build_log_2021.csv"

# TLC 4-digit codes (data dictionary). Copied from clean_hvfhv.py PLATFORM_MAP.
# HV0002 Juno has zero 2021 trips.
PLATFORM_MAP = {"HV0002": "Juno", "HV0003": "Uber", "HV0004": "Via", "HV0005": "Lyft"}

# Filter rules mirror FILTER_RULES in code/build/clean_hvfhv.py (same thresholds),
# in SQL. TLC caveat: raw base submissions contain "unexpected categories or
# numbers out of expected ranges". Each rule's count below is the number of rows
# that FAIL that rule alone (not sequential), as in clean_hvfhv.py.
# Two additions for this panel (CLAUDE.md "Sample cuts"/plan Step 1):
#   not_aar: access_a_ride_flag = 'Y' trips are MTA paratransit, not market-priced.
#   in_month: pickup inside the file's own month so cells are unique across files.
FILTER_RULES_SQL = [
    ("fare_gt_0",      "base_passenger_fare > 0"),
    ("fare_le_1000",   "base_passenger_fare <= 1000"),
    ("miles_gt_0",     "trip_miles > 0"),
    ("miles_le_100",   "trip_miles <= 100"),
    ("time_gt_60s",    "trip_time > 60"),
    ("time_le_21600s", "trip_time <= 21600"),
    ("pu_zone_le_263", "PULocationID <= 263"),
    # User decision 2026-09-30: KEEP DOLocationID = 265 ("Outside of NYC", ~3.8% of
    # trips). They identify origin-rain effects; zone 265 has no destination weather
    # (NaN by construction). Only DO 264 ("Unknown", ~1 trip/month) is dropped.
    ("do_zone_ne_264", "DOLocationID <> 264"),
    ("driver_pay_gt_0", "driver_pay > 0"),
    ("not_aar",        "coalesce(access_a_ride_flag, 'N') <> 'Y'"),
]

READ_COLS = ["hvfhs_license_num", "pickup_datetime", "dropoff_datetime", "PULocationID",
             "DOLocationID", "trip_miles", "trip_time", "base_passenger_fare",
             "driver_pay", "access_a_ride_flag"]


def build_weather_lookup() -> pd.DataFrame:
    """Weather keyed on (zone, NAIVE local wall-clock hour), 2021-01-01 to 2022-01-01 06:00."""
    w = pd.read_parquet(WEATHER_PATH, columns=["pu_zone_id", "datetime_hour", "precip_mm", "temp_c"],
                        engine="pyarrow")
    assert str(w["datetime_hour"].dt.tz) == "America/New_York", "weather datetime_hour tz wrong"
    lo = pd.Timestamp("2021-01-01", tz="America/New_York")
    hi = pd.Timestamp("2022-01-01 06:00", tz="America/New_York")
    w = w[(w["datetime_hour"] >= lo) & (w["datetime_hour"] < hi)].copy()
    # Drop tz label -> wall-clock time (not a UTC conversion).
    w["hour_naive"] = w["datetime_hour"].dt.tz_localize(None)
    w = w.drop(columns="datetime_hour")
    # DST fall-back (2021-11-07 01:00): two real hours share one wall-clock label.
    # Average them (expect 263 collapsed keys).
    dup = w.duplicated(["pu_zone_id", "hour_naive"], keep=False)
    n_collapsed = int(w.loc[dup].drop_duplicates(["pu_zone_id", "hour_naive"]).shape[0])
    print(f"Weather lookup: {len(w):,} rows in window; DST fall-back keys collapsed: {n_collapsed} (expect 263)")
    w = (w.groupby(["pu_zone_id", "hour_naive"], as_index=False)
           .agg(precip_mm=("precip_mm", "mean"), temp_c=("temp_c", "mean")))
    assert not w.duplicated(["pu_zone_id", "hour_naive"]).any(), "weather lookup key not unique"
    w["pu_zone_id"] = w["pu_zone_id"].astype("int32")
    print(f"Weather lookup unique (zone, naive hour) keys: {len(w):,}")
    return w


def build_month(mm: str, weather: pd.DataFrame, con: duckdb.DuckDBPyConnection, write: bool = True,
                out_dir: Path = OUT_DIR):
    t0 = time.time()
    year, month = 2021, int(mm)
    start = pd.Timestamp(year, month, 1)
    end = pd.Timestamp(year + (month == 12), month % 12 + 1, 1)
    src = HVFHV_DIR / f"fhvhv_tripdata_2021-{mm}.parquet"
    print(f"\n=== {mm}: {src.name} ({src.stat().st_size/1e6:.0f} MB) ; pickups in [{start}, {end}) naive local ===")

    cols = ", ".join(READ_COLS)
    con.execute(f"CREATE OR REPLACE TEMP VIEW raw AS SELECT {cols} FROM read_parquet('{src.as_posix()}')")

    # Attrition: independent fail counts per rule (+ out-of-month), then sequential kept.
    in_month = f"(pickup_datetime >= TIMESTAMP '{start}' AND pickup_datetime < TIMESTAMP '{end}')"
    rules = FILTER_RULES_SQL + [("in_month", in_month)]
    sel = ", ".join([f"sum(CASE WHEN NOT coalesce({sql}, false) THEN 1 ELSE 0 END) AS fail_{n}" for n, sql in rules])
    all_pass = " AND ".join([f"coalesce({sql}, false)" for _, sql in rules])
    row = con.execute(f"SELECT count(*) AS n_raw, {sel}, sum(CASE WHEN {all_pass} THEN 1 ELSE 0 END) AS n_kept FROM raw").fetchdf().iloc[0]
    n_raw, n_kept = int(row["n_raw"]), int(row["n_kept"])
    attr_rows = [{"month": mm, "rule": n, "n_dropped": int(row[f"fail_{n}"]), "n_raw": n_raw,
                  "share_dropped": int(row[f"fail_{n}"]) / n_raw} for n, _ in rules]
    for r in attr_rows:
        print(f"  drop {r['rule']:<16s} {r['n_dropped']:>10,}  ({r['share_dropped']:.4%})")
    print(f"  raw rows {n_raw:,}; filtered trips {n_kept:,}")

    plat_case = "CASE hvfhs_license_num " + " ".join(
        [f"WHEN '{k}' THEN '{v}'" for k, v in PLATFORM_MAP.items()]) + " END"
    # driver_share = driver_pay / base_passenger_fare. Dictionary: driver_pay is
    # "total driver pay, excl. tolls and tips, and net of commission, surcharges,
    # and taxes". Values > 1 (TLC minimum-pay floor on short cheap trips) are NOT trimmed.
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE trips AS
        SELECT {plat_case} AS platform,
               PULocationID::INTEGER AS pu_zone_id, DOLocationID::INTEGER AS do_zone_id,
               date_trunc('hour', pickup_datetime) AS datetime_hour,
               date_trunc('hour', dropoff_datetime) AS do_datetime_hour,
               driver_pay / base_passenger_fare AS driver_share,
               base_passenger_fare AS fare, driver_pay, trip_miles, trip_time,
               ln(base_passenger_fare) AS ln_fare, ln(driver_pay) AS ln_pay,
               ln(trip_miles) AS ln_miles, ln(trip_time) AS ln_time
        FROM raw WHERE {all_pass}
    """)
    med_share = con.execute("SELECT median(driver_share) FROM trips").fetchone()[0]
    assert con.execute("SELECT count(*) FROM trips WHERE platform IS NULL").fetchone()[0] == 0, "unmapped platform"

    con.register("wlookup", weather)
    cells = con.execute("""
        WITH c AS (
          SELECT platform, pu_zone_id, do_zone_id, datetime_hour, do_datetime_hour,
                 count(*)::INTEGER AS n_trips, sum(driver_share) AS sum_driver_share,
                 sum(fare) AS sum_fare, sum(driver_pay) AS sum_driver_pay,
                 sum(trip_miles) AS sum_trip_miles, sum(trip_time)::DOUBLE AS sum_trip_time,
                 -- v2 additions (filters guarantee fare > 0 and driver_pay > 0, so ln() is finite)
                 sum(ln_fare) AS sum_log_fare, sum(ln_pay) AS sum_log_pay,
                 -- v3 additions (filters: trip_miles > 0 and trip_time > 60 s, so ln() is finite)
                 sum(ln_miles) AS sum_log_miles, sum(ln_time) AS sum_log_time
          FROM trips GROUP BY ALL)
        SELECT c.*, wp.precip_mm AS pu_precip_mm, wp.temp_c AS pu_temp_c,
               wd.precip_mm AS do_precip_mm, wd.temp_c AS do_temp_c
        FROM c
        LEFT JOIN wlookup wp ON wp.pu_zone_id = c.pu_zone_id AND wp.hour_naive = c.datetime_hour
        LEFT JOIN wlookup wd ON wd.pu_zone_id = c.do_zone_id AND wd.hour_naive = c.do_datetime_hour
    """).fetchdf()
    con.unregister("wlookup")
    print(f"  cells: {len(cells):,}")
    is265 = cells["do_zone_id"] == 265
    n265_trips, n265_cells = int(cells.loc[is265, "n_trips"].sum()), int(is265.sum())
    print(f"  DO zone 265 (outside NYC, kept): {n265_trips:,} trips, {n265_cells:,} cells")

    # --- checks ---
    assert int(cells["n_trips"].sum()) == n_kept, f"sum(n_trips) {cells['n_trips'].sum():,} != filtered rows {n_kept:,}"
    assert np.isfinite(cells[["sum_log_fare", "sum_log_pay", "sum_log_miles", "sum_log_time"]].to_numpy()).all(), "non-finite log aggregates"
    key = ["platform", "pu_zone_id", "do_zone_id", "datetime_hour", "do_datetime_hour"]
    assert not cells.duplicated(key).any(), "duplicate cell keys"
    # NaN gate: destination weather evaluated on in-NYC destinations only (DO 265 is NaN by construction).
    nyc = cells.loc[~is265]
    nan_share = {c: float((nyc if c.startswith("do_") else cells)[c].isna().mean())
                 for c in ["pu_precip_mm", "pu_temp_c", "do_precip_mm", "do_temp_c"]}
    assert cells.loc[is265, "do_precip_mm"].isna().all(), "DO 265 should have no destination weather"
    print("  weather NaN share (do_* on in-NYC destinations only): " + ", ".join(f"{k}={v:.3%}" for k, v in nan_share.items()))
    # Gate downgraded to a flagged warning (2026-09-30): July 2021 has 12 whole-city hours
    # missing in the upstream MRMS panel (1.2% of cells); not a join bug. Regression drops them.
    nan_flag = max(nan_share.values()) > 0.01
    if nan_flag:
        print(f"  WARNING: weather NaN share > 1% (upstream weather hours missing): {nan_share}")
    assert 0.5 < med_share < 0.95, f"median driver_share {med_share:.3f} out of range"
    print(f"  median trip-level driver_share: {med_share:.3f}")

    # DST spring-forward (2021-03-14 02:00 does not exist): count affected cells.
    sf = pd.Timestamp("2021-03-14 02:00")
    n_sf = int(((cells["datetime_hour"] == sf) | (cells["do_datetime_hour"] == sf)).sum())
    n_ff = int(((cells["datetime_hour"] == pd.Timestamp("2021-11-07 01:00")) |
                (cells["do_datetime_hour"] == pd.Timestamp("2021-11-07 01:00"))).sum())
    print(f"  cells with spring-forward 02:00 hour: {n_sf} ; cells with fall-back 01:00 hour: {n_ff}")

    # Integer FE columns from the naive wall clock BEFORE tz localisation.
    dh, dd = cells["datetime_hour"], cells["do_datetime_hour"]
    cells["pu_hod"] = dh.dt.hour.astype("int8")
    cells["do_hod"] = dd.dt.hour.astype("int8")
    cells["month"] = dh.dt.month.astype("int8")
    cells["dow"] = (dh.dt.dayofweek + 1).astype("int8")  # ISO 1=Mon
    cells["doy"] = dh.dt.dayofyear.astype("int16")
    cells["date"] = dh.dt.date  # pickup date, naive local
    # tz-aware America/New_York. ambiguous=False -> the Nov-7 01:00 hour is labelled
    # EST (second occurrence); nonexistent="shift_forward" for Mar-14 02:00. Never
    # "NaT", which would silently null keys. Only those two hours are affected.
    cells["datetime_hour"] = dh.dt.tz_localize("America/New_York", ambiguous=False, nonexistent="shift_forward")
    cells["do_datetime_hour"] = dd.dt.tz_localize("America/New_York", ambiguous=False, nonexistent="shift_forward")
    assert str(cells["datetime_hour"].dt.tz) == "America/New_York"
    assert str(cells["do_datetime_hour"].dt.tz) == "America/New_York"
    assert cells["datetime_hour"].notna().all() and cells["do_datetime_hour"].notna().all()
    for c in ["pu_zone_id", "do_zone_id"]:
        cells[c] = cells[c].astype("int32")
    cells["platform"] = cells["platform"].astype(str)
    for c in ["pu_precip_mm", "pu_temp_c", "do_precip_mm", "do_temp_c"]:
        cells[c] = cells[c].astype("float32")
    cells["n_trips"] = cells["n_trips"].astype("int32")
    print(cells.dtypes.to_string())

    out = out_dir / f"cells_2021-{mm}.parquet"
    if write:
        cells.to_parquet(out, index=False, engine="pyarrow")
    else:
        print(f"  --no-write: {out.name} left untouched; stats only")
    chk = pd.read_parquet(out, engine="pyarrow", columns=["datetime_hour", "pu_zone_id", "n_trips"])
    assert str(chk["datetime_hour"].dt.tz) == "America/New_York"
    print(f"  Written {len(chk):,} rows x {cells.shape[1]} cols to {out} ({out.stat().st_size/1e6:.0f} MB); "
          f"datetime_hour {chk['datetime_hour'].min()} to {chk['datetime_hour'].max()}; zones {chk['pu_zone_id'].nunique()}")

    # Timezone check: citywide max pu_precip_mm hour (cell-level, any cell).
    peak = cells.loc[cells["pu_precip_mm"].idxmax()]
    hourly = cells.groupby("datetime_hour")["pu_precip_mm"].max()
    print(f"  max pu_precip_mm = {hourly.max():.1f} mm at {hourly.idxmax()}")

    secs = time.time() - t0
    log = {"month": mm, "n_raw": n_raw, "n_filtered": n_kept, "sum_n_trips": int(cells["n_trips"].sum()),
           "n_cells": len(cells), "do265_trips": n265_trips, "do265_cells": n265_cells, "median_driver_share": med_share, "peak_pu_precip_mm": float(hourly.max()),
           "peak_pu_precip_hour": str(hourly.idxmax()), "cells_spring_fwd_hour": n_sf, "cells_fall_back_hour": n_ff,
           "build_seconds": round(secs, 1), **{f"nan_{k}": v for k, v in nan_share.items()},
           "file_mb": round(out.stat().st_size / 1e6, 1)}
    print(f"  build time {secs:.0f}s")
    return attr_rows, log


def upsert_csv(path: Path, new: pd.DataFrame, key_cols):
    if path.exists():
        old = pd.read_csv(path, dtype={"month": str})
        old = old[~old["month"].isin(new["month"].unique())]
        new = pd.concat([old, new], ignore_index=True).sort_values(key_cols)
    new.to_csv(path, index=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", default=",".join(f"{m:02d}" for m in range(1, 13)))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--out-dir", default=None,
                    help="output folder (default clean_data/od_weather_cells_2021); non-default folders also get their own attrition/build-log CSVs")
    ap.add_argument("--no-write", action="store_true",
                    help="recompute stats/log/attrition for months without touching their parquet files")
    args = ap.parse_args()
    months = [m.strip().zfill(2) for m in args.months.split(",")]

    out_dir = Path(args.out_dir).resolve() if args.out_dir else OUT_DIR
    attr_path, log_path = ATTRITION_PATH, BUILD_LOG_PATH
    if out_dir != OUT_DIR.resolve():
        # non-default folder: keep its own CSVs, never touch the v1 attrition/build logs
        attr_path, log_path = out_dir / "od_cells_filter_attrition_2021.csv", out_dir / "od_cells_build_log_2021.csv"
    out_dir.mkdir(parents=True, exist_ok=True)
    todo = []
    for mm in months:
        if args.no_write:
            todo.append(mm)
        elif (out_dir / f"cells_2021-{mm}.parquet").exists() and not args.force:
            print(f"SKIP {mm}: cells file exists (use --force to rebuild)")
        else:
            todo.append(mm)
    if not todo:
        return

    for mm in todo:
        f = out_dir / f"cells_2021-{mm}.parquet"
        if f.exists() and not args.no_write:
            print(f"WARNING: {f} already exists - overwriting (--force)")
    weather = build_weather_lookup()
    con = duckdb.connect()
    con.execute("PRAGMA threads=16")
    for mm in todo:
        a, l = build_month(mm, weather, con, write=not args.no_write, out_dir=out_dir)
        upsert_csv(attr_path, pd.DataFrame(a), ["month", "rule"])  # per month: survives a later failure
        upsert_csv(log_path, pd.DataFrame([l]), ["month"])
    print("\nDone.")


if __name__ == "__main__":
    main()
