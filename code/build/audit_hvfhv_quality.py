# ============================================================
# Script: audit_hvfhv_quality.py
# Purpose: Data-quality audit of the NYC TLC HVFHV trip records, 2020-04..2026-07.
#          Per-month DuckDB aggregates (nulls, moments, quantiles, anomalies,
#          duplicates, categorical counts, hourly counts) cached month by month,
#          plus full-period medians/quantiles over all files.
# Inputs: raw_data/hvfhv/fhvhv_tripdata_YYYY-MM.parquet (76 files, read-only)
# Outputs: clean_data/dq/month_YYYY-MM_{num,ts,cat,rules,hourly}.parquet
#          clean_data/dq/hourly_counts.parquet, daily_counts.parquet  (--stage combine)
#          clean_data/dq/fullperiod_quantiles.parquet                 (--stage medians)
#          clean_data/dq/footer_rows.csv                              (--stage footers)
# Usage:   python audit_hvfhv_quality.py --stage months [--months 2021-09 2020-04]
#          python audit_hvfhv_quality.py --stage footers | combine | medians [--method exact|approx]
# Timezone: TLC timestamps are naive local America/New_York wall-clock. No tz
#          conversion is done anywhere in this script.
# Cleaning: NO filters on the raw pass. A parallel "filtered" pass applies the
#          CLAUDE.md cleaning rules (fare in (0,1000], miles in (0,100], time in
#          (60s, 6h], zones not 264/265 / not null, access_a_ride != 'Y'). TLC's own
#          caveat: raw base submissions may contain "unexpected categories or
#          numbers out of expected ranges".
# Dictionary notes: on_scene_datetime is Accessible-Vehicles-only (mostly null);
#          driver_pay is net of commission/surcharges/taxes, excl. tolls and tips.
# Author: EK  Date: 2026-10-02
# ============================================================
import argparse
import time
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "raw_data" / "hvfhv"
DQ = ROOT / "clean_data" / "dq"
START, END = (2020, 4), (2026, 7)

CATS = ["hvfhs_license_num", "dispatching_base_num", "originating_base_num",
        "shared_request_flag", "shared_match_flag", "access_a_ride_flag",
        "wav_request_flag", "wav_match_flag"]
TS_COLS = ["request_datetime", "on_scene_datetime", "pickup_datetime", "dropoff_datetime"]
RAW_NUM = ["trip_miles", "trip_time", "base_passenger_fare", "tolls", "bcf", "sales_tax",
           "congestion_surcharge", "airport_fee", "tips", "driver_pay", "cbd_congestion_fee"]
DERIVED = ["wait_time", "fare_per_mile", "driver_share", "mean_speed_mph", "platform_margin"]
NUM_VARS = RAW_NUM + DERIVED
LOC_COLS = ["PULocationID", "DOLocationID"]
ALL_COLS = ["hvfhs_license_num", "dispatching_base_num", "originating_base_num",
            "request_datetime", "on_scene_datetime", "pickup_datetime", "dropoff_datetime",
            "PULocationID", "DOLocationID", "trip_miles", "trip_time", "base_passenger_fare",
            "tolls", "bcf", "sales_tax", "congestion_surcharge", "airport_fee", "tips",
            "driver_pay", "shared_request_flag", "shared_match_flag", "access_a_ride_flag",
            "wav_request_flag", "wav_match_flag", "cbd_congestion_fee"]
TYPES = {c: "VARCHAR" for c in CATS + CATS[:0]}
TYPES.update({c: "TIMESTAMP" for c in TS_COLS})
TYPES.update({c: "INTEGER" for c in LOC_COLS})
TYPES.update({c: "DOUBLE" for c in RAW_NUM})

# CLAUDE.md filter thresholds, written once and reused for flag + rule counts
OK_SQL = ("base_passenger_fare > 0 AND base_passenger_fare <= 1000 AND trip_miles > 0 AND trip_miles <= 100 "
          "AND trip_time > 60 AND trip_time <= 21600 AND PULocationID NOT IN (264,265) "
          "AND DOLocationID NOT IN (264,265) AND PULocationID IS NOT NULL AND DOLocationID IS NOT NULL "
          "AND COALESCE(access_a_ride_flag,'') <> 'Y'")


def months():
    y, m = START
    while (y, m) <= END:
        yield f"{y}-{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def month_path(mon):
    return RAW / f"fhvhv_tripdata_{mon}.parquet"


def normalized_sql(path, with_hash=True):
    """SELECT normalizing the schema drift: airport_fee NULL-typed (2020-04/10) -> DOUBLE;
    cbd_congestion_fee absent before 2025 -> NULL; large_string -> VARCHAR; LocationIDs -> INTEGER.
    Adds platform, derived variables and the filter flag `ok`."""
    have = {r[0] for r in duckdb.sql(f"DESCRIBE SELECT * FROM read_parquet('{path.as_posix()}')").fetchall()}
    sel = [(f'"{c}"::{TYPES[c]} AS {c}' if c in have else f"NULL::{TYPES[c]} AS {c}") for c in ALL_COLS]
    hash_sql = f", hash({', '.join(ALL_COLS)}) AS row_hash" if with_hash else ""
    return f"""
    SELECT {', '.join(sel)} FROM read_parquet('{path.as_posix()}')
    """, hash_sql


def build_table(con, mon):
    base, hash_sql = normalized_sql(month_path(mon))
    con.execute(f"""
    CREATE OR REPLACE TABLE t AS
    SELECT *,
      CASE hvfhs_license_num WHEN 'HV0002' THEN 'Juno' WHEN 'HV0003' THEN 'Uber'
           WHEN 'HV0004' THEN 'Via' WHEN 'HV0005' THEN 'Lyft' ELSE 'other' END AS platform,
      epoch(pickup_datetime) - epoch(request_datetime) AS wait_time,
      CASE WHEN trip_miles > 0 THEN base_passenger_fare / trip_miles END AS fare_per_mile,
      CASE WHEN base_passenger_fare > 0 THEN driver_pay / base_passenger_fare END AS driver_share,
      CASE WHEN trip_time > 0 THEN trip_miles / (trip_time / 3600.0) END AS mean_speed_mph,
      base_passenger_fare - driver_pay AS platform_margin,
      ({OK_SQL}) AS ok
      {hash_sql}
    FROM ({base})
    """)


def write(df, path):
    tmp = path.with_suffix(".tmp")
    df.to_parquet(tmp, index=False, engine="pyarrow")
    tmp.replace(path)


def audit_month(mon):
    con = duckdb.connect()
    con.execute("SET preserve_insertion_order=false")
    build_table(con, mon)
    n = con.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    grp = "GROUP BY GROUPING SETS ((platform), ())"
    plat = "COALESCE(platform,'ALL') AS platform"

    # numeric: raw and filtered passes
    parts = []
    for v in NUM_VARS:
        for flt in (0, 1):
            where = "WHERE ok" if flt else ""
            parts.append(f"""SELECT {plat}, '{v}' AS variable, {flt} AS filtered, COUNT(*) AS n_rows,
              COUNT(*) - COUNT({v}) AS n_null, COUNT({v}) AS n_nonnull,
              SUM({v}::DOUBLE) AS sum, SUM({v}::DOUBLE * {v}::DOUBLE) AS sum_sq,
              MIN({v}::DOUBLE) AS min, MAX({v}::DOUBLE) AS max,
              quantile_cont({v}::DOUBLE, 0.5) AS median, quantile_cont({v}::DOUBLE, 0.01) AS p01,
              quantile_cont({v}::DOUBLE, 0.99) AS p99,
              SUM(CASE WHEN isnan({v}::DOUBLE) OR isinf({v}::DOUBLE) THEN 1 ELSE 0 END) AS n_nonfinite
              FROM t {where} {grp}""")
    num = con.execute(" UNION ALL ".join(parts)).df()
    num.insert(0, "month", mon)

    ts = con.execute(" UNION ALL ".join(
        f"""SELECT {plat}, '{c}' AS variable, COUNT(*) AS n_rows, COUNT(*) - COUNT({c}) AS n_null,
            MIN({c}) AS min, MAX({c}) AS max FROM t {grp}""" for c in TS_COLS)).df()
    ts.insert(0, "month", mon)

    cat = con.execute(" UNION ALL ".join(
        f"SELECT '{c}' AS variable, platform, {c} AS value, COUNT(*) AS n FROM t GROUP BY ALL" for c in CATS)).df()
    cat.insert(0, "month", mon)

    y, m = int(mon[:4]), int(mon[5:])
    lo, hi = f"{y}-{m:02d}-01", (f"{y+1}-01-01" if m == 12 else f"{y}-{m+1:02d}-01")
    rules = con.execute(f"""
      SELECT {plat}, COUNT(*) AS n_rows, SUM(ok::INT) AS n_pass_filters,
        COUNT(*) - COUNT(DISTINCT row_hash) AS n_exact_dups,
        SUM((base_passenger_fare <= 0)::INT) AS fare_le0, SUM((base_passenger_fare > 1000)::INT) AS fare_gt1000,
        SUM((trip_miles <= 0)::INT) AS miles_le0, SUM((trip_miles > 100)::INT) AS miles_gt100,
        SUM((trip_time <= 60)::INT) AS time_le60s, SUM((trip_time > 21600)::INT) AS time_gt6h,
        SUM((driver_pay < 0)::INT) AS driver_pay_neg, SUM((tolls < 0)::INT) AS tolls_neg,
        SUM((tips < 0)::INT) AS tips_neg, SUM((bcf < 0)::INT) AS bcf_neg,
        SUM((sales_tax < 0)::INT) AS sales_tax_neg, SUM((congestion_surcharge < 0)::INT) AS congestion_neg,
        SUM((airport_fee < 0)::INT) AS airport_fee_neg,
        SUM((driver_share > 1)::INT) AS driver_share_gt1, SUM((wait_time < 0)::INT) AS wait_neg,
        SUM((request_datetime > pickup_datetime)::INT) AS request_after_pickup,
        SUM((dropoff_datetime <= pickup_datetime)::INT) AS dropoff_le_pickup,
        SUM((pickup_datetime < TIMESTAMP '{lo}' OR pickup_datetime >= TIMESTAMP '{hi}')::INT) AS pickup_outside_month,
        SUM((PULocationID IN (264,265))::INT) AS pu_264_265, SUM((DOLocationID IN (264,265))::INT) AS do_264_265,
        SUM((PULocationID IS NULL)::INT) AS pu_null, SUM((DOLocationID IS NULL)::INT) AS do_null,
        SUM((PULocationID NOT BETWEEN 1 AND 265 OR DOLocationID NOT BETWEEN 1 AND 265)::INT) AS loc_out_of_range,
        SUM((access_a_ride_flag = 'Y')::INT) AS access_a_ride_y
      FROM t {grp}""").df()
    # duplicates for ALL = sum over platforms (license is part of the row hash)
    rules.loc[rules.platform == "ALL", "n_exact_dups"] = rules.loc[rules.platform != "ALL", "n_exact_dups"].sum()
    rules.insert(0, "month", mon)

    hourly = con.execute("""SELECT date_trunc('hour', pickup_datetime) AS datetime_hour, platform,
        COUNT(*) AS n_trips, SUM(ok::INT) AS n_trips_filtered FROM t GROUP BY ALL""").df()

    for name, df in [("num", num), ("ts", ts), ("cat", cat), ("rules", rules), ("hourly", hourly)]:
        write(df, DQ / f"month_{mon}_{name}.parquet")
    con.close()
    return n


def stage_months(sel):
    DQ.mkdir(parents=True, exist_ok=True)
    for mon in sel or months():
        outs = [DQ / f"month_{mon}_{k}.parquet" for k in ("num", "ts", "cat", "rules", "hourly")]
        if all(o.exists() for o in outs):
            print(f"{mon}: cached, skip")
            continue
        t0 = time.time()
        n = audit_month(mon)
        print(f"{mon}: {n:,} rows, {time.time() - t0:.0f}s", flush=True)


def stage_footers():
    rows = []
    for mon in months():
        f = pq.ParquetFile(month_path(mon))
        rows.append({"month": mon, "footer_rows": f.metadata.num_rows, "n_cols": f.metadata.num_columns})
    df = pd.DataFrame(rows)
    df.to_csv(DQ / "footer_rows.csv", index=False)
    print(df.footer_rows.sum(), "total footer rows")


def stage_combine():
    for name in ("hourly",):
        df = pd.concat([pd.read_parquet(DQ / f"month_{m}_{name}.parquet") for m in months()])
        # a trip can sit in a neighbouring file's month; sum duplicates of the same key
        df = df.groupby(["datetime_hour", "platform"], as_index=False)[["n_trips", "n_trips_filtered"]].sum()
        write(df, DQ / "hourly_counts.parquet")
        df["date"] = df.datetime_hour.dt.normalize()
        daily = df.groupby(["date", "platform"], as_index=False)[["n_trips", "n_trips_filtered"]].sum()
        write(daily, DQ / "daily_counts.parquet")
        print(f"hourly {len(df):,} rows, daily {len(daily):,} rows")


def stage_medians(method, only):
    """Full-period quantiles over all 76 files. Median cannot be combined from monthly medians."""
    con = duckdb.connect()
    con.execute("SET memory_limit='110GB'")
    selects = []
    for mon in months():
        base, _ = normalized_sql(month_path(mon), with_hash=False)
        selects.append(f"""SELECT CASE hvfhs_license_num WHEN 'HV0002' THEN 'Juno' WHEN 'HV0003' THEN 'Uber'
          WHEN 'HV0004' THEN 'Via' WHEN 'HV0005' THEN 'Lyft' ELSE 'other' END AS platform,
          ({OK_SQL}) AS ok, {', '.join(RAW_NUM)},
          epoch(pickup_datetime) - epoch(request_datetime) AS wait_time,
          CASE WHEN trip_miles > 0 THEN base_passenger_fare / trip_miles END AS fare_per_mile,
          CASE WHEN base_passenger_fare > 0 THEN driver_pay / base_passenger_fare END AS driver_share,
          CASE WHEN trip_time > 0 THEN trip_miles / (trip_time / 3600.0) END AS mean_speed_mph,
          base_passenger_fare - driver_pay AS platform_margin FROM ({base})""")
    con.execute("CREATE VIEW allt AS " + " UNION ALL ".join(selects))
    q = "quantile_cont" if method == "exact" else "approx_quantile"
    vs = only or NUM_VARS
    if method == "approx" and not only:
        # one scan for all variables (approx_quantile is a streaming t-digest; low memory)
        t0 = time.time()
        cols = []
        for v in vs:
            for nm, p in (("median", 0.5), ("p01", 0.01), ("p99", 0.99)):
                cols.append(f"approx_quantile({v}::DOUBLE,{p}) AS {v}__{nm}")
                cols.append(f"approx_quantile({v}::DOUBLE,{p}) FILTER (WHERE ok) AS {v}__{nm}_f")
        w = con.execute(f"SELECT {', '.join(cols)} FROM allt").df().iloc[0]
        rows = [{"variable": v, "median": w[f"{v}__median"], "p01": w[f"{v}__p01"], "p99": w[f"{v}__p99"],
                 "median_f": w[f"{v}__median_f"], "p01_f": w[f"{v}__p01_f"], "p99_f": w[f"{v}__p99_f"],
                 "method": method} for v in vs]
        write(pd.DataFrame(rows), DQ / f"fullperiod_quantiles_{method}.parquet")
        print(f"all variables, one scan: {time.time() - t0:.0f}s", flush=True)
        return
    outf = DQ / f"fullperiod_quantiles_{method}.parquet"
    out = [pd.read_parquet(outf)] if outf.exists() else []  # resume: keep variables already computed
    done = set(out[0].variable) if out else set()
    for v in vs:
        if v in done:
            print(f"{v}: cached, skip", flush=True)
            continue
        t0 = time.time()
        r = con.execute(f"""SELECT {q}({v}::DOUBLE,0.5) AS median, {q}({v}::DOUBLE,0.01) AS p01, {q}({v}::DOUBLE,0.99) AS p99,
            {q}({v}::DOUBLE,0.5) FILTER (WHERE ok) AS median_f, {q}({v}::DOUBLE,0.01) FILTER (WHERE ok) AS p01_f,
            {q}({v}::DOUBLE,0.99) FILTER (WHERE ok) AS p99_f FROM allt""").df()
        r.insert(0, "variable", v)
        r["method"] = method
        out.append(r)
        print(f"{v}: {time.time() - t0:.0f}s  median={r['median'][0]:.4g}", flush=True)
        write(pd.concat(out), DQ / f"fullperiod_quantiles_{method}.parquet")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=["months", "footers", "combine", "medians"])
    ap.add_argument("--months", nargs="*")
    ap.add_argument("--method", default="approx", choices=["exact", "approx"])
    ap.add_argument("--vars", nargs="*")
    a = ap.parse_args()
    DQ.mkdir(parents=True, exist_ok=True)
    {"months": lambda: stage_months(a.months), "footers": stage_footers, "combine": stage_combine,
     "medians": lambda: stage_medians(a.method, a.vars)}[a.stage]()
