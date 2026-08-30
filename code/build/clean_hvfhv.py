# ============================================================
# Script: clean_hvfhv.py
# Purpose: Trip-level cleaning of the HVFHV records for the Ida analysis
#          window (pre/during/post + 1-day buffer, from
#          clean_data/ida_event_windows.json). Applies the CLAUDE.md filter
#          set, fills surcharge nulls, and constructs the price/money
#          variables settled in the plan (base_passenger_fare - driver_pay
#          as platform_margin; passthrough_total never deducted from it).
# Inputs: raw_data/hvfhv/fhvhv_tripdata_2021-08.parquet,
#         raw_data/hvfhv/fhvhv_tripdata_2021-09.parquet,
#         clean_data/ida_event_windows.json
# Outputs: clean_data/hvfhv_trips_ida_window.parquet
#          output/sum/filter_attrition.csv
# Deliberate naming deviation from CLAUDE.md: the documented pipeline names
#          this step's output hvfhv_trips_2021.parquet, implying full-year
#          coverage. This file covers only the ~32-day Ida window, so it is
#          named hvfhv_trips_ida_window.parquet instead (see
#          .claude/plans/hvfhv-data-introduction-and-ida-first-pass.md).
# Size note: expected output is ~600 MB-1 GB, above the 500 MB threshold in
#          .claude/rules/data-safeguards.md. The user waived that threshold
#          for this one file on 2026-08-29 (see session log). The waiver
#          does not extend to any other output in this pipeline.
# Author: EK  Date: 2026-08-29
# ============================================================

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HVFHV_DIR = PROJECT_ROOT / "raw_data" / "hvfhv"
WINDOWS_PATH = PROJECT_ROOT / "clean_data" / "ida_event_windows.json"
OUTPUT_PATH = PROJECT_ROOT / "clean_data" / "hvfhv_trips_ida_window.parquet"
ATTRITION_PATH = PROJECT_ROOT / "output" / "sum" / "filter_attrition.csv"

INPUT_FILES = [
    HVFHV_DIR / "fhvhv_tripdata_2021-08.parquet",
    HVFHV_DIR / "fhvhv_tripdata_2021-09.parquet",
]

BATCH_SIZE = 1_000_000

READ_COLS = [
    "hvfhs_license_num", "dispatching_base_num", "request_datetime",
    "pickup_datetime", "dropoff_datetime", "PULocationID", "DOLocationID",
    "trip_miles", "trip_time", "base_passenger_fare", "tolls", "bcf",
    "sales_tax", "congestion_surcharge", "airport_fee", "tips", "driver_pay",
    "shared_request_flag", "shared_match_flag", "access_a_ride_flag",
    "wav_match_flag",
]

# TLC 4-digit codes -- see raw_data/HVFHV_Trip_Data_Data_Dictionary.xlsx.
# HV0002 Juno is listed for completeness; it has zero trips in 2021 (Juno
# ceased operations Nov 2019) and will never appear in the output.
PLATFORM_MAP = {
    "HV0002": "Juno",
    "HV0003": "Uber",
    "HV0004": "Via",
    "HV0005": "Lyft",
}

SURCHARGE_COLS = ["tolls", "bcf", "sales_tax", "congestion_surcharge", "airport_fee", "tips"]

# Row-level filter rules, applied identically to pre/during/post per
# CLAUDE.md ("an asymmetric filter is itself a treatment effect"). Each is
# a (name, boolean-mask-function) pair; the mask is True for rows that PASS.
FILTER_RULES = [
    ("fare_gt_0",        lambda df: df["base_passenger_fare"] > 0),
    ("fare_le_1000",     lambda df: df["base_passenger_fare"] <= 1000),
    ("miles_gt_0",       lambda df: df["trip_miles"] > 0),
    ("miles_le_100",     lambda df: df["trip_miles"] <= 100),
    ("time_gt_60s",      lambda df: df["trip_time"] > 60),
    ("time_le_21600s",   lambda df: df["trip_time"] <= 21600),
    ("pu_zone_le_263",   lambda df: df["PULocationID"] <= 263),
    ("do_zone_le_263",   lambda df: df["DOLocationID"] <= 263),
    # Not in CLAUDE.md's base list -- added per plan Step 3, measured below
    # and kept because it is rare and symmetric across windows (see the
    # printed / written filter_attrition.csv breakdown).
    ("driver_pay_gt_0",  lambda df: df["driver_pay"] > 0),
]


def load_windows():
    with open(WINDOWS_PATH) as f:
        w = json.load(f)
    # JSON bounds carry the -04:00 offset; TLC timestamps are naive local
    # wall clock. Strip the tz label (not convert) so comparisons are against
    # the same naive wall-clock numbers -- correct here because the whole
    # window sits inside EDT with no DST transition (CLAUDE.md).
    bounds = {}
    for name in ("pre", "during", "post"):
        start = pd.Timestamp(w["windows"][name]["start"]).tz_localize(None)
        end = pd.Timestamp(w["windows"][name]["end"]).tz_localize(None)
        bounds[name] = (start, end)
    return bounds


def assign_window(pickup: pd.Series, bounds: dict) -> pd.Series:
    window = pd.Series(np.where(pickup.notna(), "buffer", None), index=pickup.index, dtype=object)
    for name, (start, end) in bounds.items():
        window = window.where(~((pickup >= start) & (pickup < end)), name)
    return window


def main() -> None:
    if OUTPUT_PATH.exists():
        print(f"WARNING: {OUTPUT_PATH} already exists -- overwriting per plan Step 3.")
    ATTRITION_PATH.parent.mkdir(parents=True, exist_ok=True)

    bounds = load_windows()
    read_start = bounds["pre"][0] - pd.Timedelta(days=1)
    read_end = bounds["post"][1] + pd.Timedelta(days=1)
    print(f"Buffered read range (naive local): [{read_start}, {read_end})")

    # Accumulators for the required per-window filter-attrition diagnostic.
    window_totals = {"pre": 0, "during": 0, "post": 0, "buffer": 0}
    rule_fail_counts = {name: {"pre": 0, "during": 0, "post": 0, "buffer": 0}
                        for name, _ in FILTER_RULES}
    surcharge_null_counts = {c: 0 for c in SURCHARGE_COLS}
    n_raw_in_range = 0
    n_kept = 0

    writer = None
    output_schema = None

    for input_path in INPUT_FILES:
        size_mb = input_path.stat().st_size / 1e6
        print(f"\nStreaming {input_path.name} ({size_mb:.0f} MB, "
              f"{len(READ_COLS)} of its columns)")
        pf = pq.ParquetFile(input_path)

        for batch_i, batch in enumerate(pf.iter_batches(batch_size=BATCH_SIZE, columns=READ_COLS)):
            df = batch.to_pandas()
            in_range = (df["pickup_datetime"] >= read_start) & (df["pickup_datetime"] < read_end)
            df = df.loc[in_range].copy()
            if df.empty:
                continue
            n_raw_in_range += len(df)

            df["window"] = assign_window(df["pickup_datetime"], bounds)
            for w in window_totals:
                window_totals[w] += int((df["window"] == w).sum())

            # Filter attrition: for each rule independently, count rows that
            # FAIL that rule alone (not sequential), cross-tabbed by window --
            # matches the measurement style already verified in the plan's
            # ground-truth section 0.6.
            pass_masks = {}
            for name, fn in FILTER_RULES:
                m = fn(df)
                pass_masks[name] = m
                fail = ~m
                for w in window_totals:
                    rule_fail_counts[name][w] += int((fail & (df["window"] == w)).sum())

            keep = pd.Series(True, index=df.index)
            for m in pass_masks.values():
                keep &= m
            kept = df.loc[keep].copy()
            if kept.empty:
                continue

            # Null counts BEFORE fill, on the kept rows -- printed once at
            # the end so the fillna(0) below is documented, not silent.
            for c in SURCHARGE_COLS:
                surcharge_null_counts[c] += int(kept[c].isna().sum())
            kept[SURCHARGE_COLS] = kept[SURCHARGE_COLS].fillna(0.0)

            # --- identifiers / geography ---
            kept["platform"] = kept["hvfhs_license_num"].map(PLATFORM_MAP)
            kept["pu_zone_id"] = kept["PULocationID"].astype("int32")
            kept["do_zone_id"] = kept["DOLocationID"].astype("int32")

            # --- time (already local wall clock, naive; tz_localize is
            # correct here, not a conversion -- no DST transition in-window) ---
            kept["datetime_hour"] = kept["pickup_datetime"].dt.floor("h").dt.tz_localize("America/New_York")
            kept["date"] = kept["pickup_datetime"].dt.date
            kept["wait_time"] = (kept["pickup_datetime"] - kept["request_datetime"]).dt.total_seconds()
            kept["speed_mph"] = kept["trip_miles"] / (kept["trip_time"] / 3600.0)

            # --- price ---
            kept["fare_per_mile"] = kept["base_passenger_fare"] / kept["trip_miles"]
            kept["fare_per_minute"] = kept["base_passenger_fare"] / (kept["trip_time"] / 60.0)

            # --- money, per plan section 2.1: surcharges sit ON TOP of
            # base_passenger_fare and are remitted by the firm, so they are
            # never subtracted from platform_margin. ---
            kept["driver_pay_total"] = kept["driver_pay"] + kept["tips"]
            kept["passthrough_total"] = (
                kept["tolls"] + kept["bcf"] + kept["airport_fee"]
                + kept["congestion_surcharge"] + kept["sales_tax"]
            )
            kept["passenger_outlay"] = (
                kept["base_passenger_fare"] + kept["passthrough_total"] + kept["tips"]
            )
            kept["platform_margin"] = kept["base_passenger_fare"] - kept["driver_pay"]
            kept["driver_share"] = kept["driver_pay"] / kept["base_passenger_fare"]
            kept["driver_share_incl_tips"] = kept["driver_pay_total"] / kept["base_passenger_fare"]

            out_cols = [
                "platform", "dispatching_base_num",
                "request_datetime", "pickup_datetime", "dropoff_datetime",
                "pu_zone_id", "do_zone_id",
                "datetime_hour", "date", "window",
                "trip_miles", "trip_time", "wait_time", "speed_mph",
                "base_passenger_fare", "fare_per_mile", "fare_per_minute",
                "tolls", "bcf", "sales_tax", "congestion_surcharge", "airport_fee", "tips",
                "driver_pay", "driver_pay_total",
                "passthrough_total", "passenger_outlay",
                "platform_margin", "driver_share", "driver_share_incl_tips",
                "shared_request_flag", "shared_match_flag",
                "access_a_ride_flag", "wav_match_flag",
            ]
            out = kept[out_cols]

            table = pa.Table.from_pandas(out, preserve_index=False)
            if writer is None:
                output_schema = table.schema
                writer = pq.ParquetWriter(OUTPUT_PATH, output_schema)
            else:
                table = table.cast(output_schema)
            writer.write_table(table)
            n_kept += len(out)

            print(f"  batch {batch_i}: read {len(df):,} in-range rows, "
                  f"kept {len(out):,} ({len(out)/max(len(df),1):.1%})")

    if writer is not None:
        writer.close()

    print(f"\nTotal raw rows in buffered range: {n_raw_in_range:,}")
    print(f"Total kept rows: {n_kept:,} ({n_kept/max(n_raw_in_range,1):.1%})")
    print(f"Window totals (raw, pre-filter): {window_totals}")

    print("\nSurcharge null counts BEFORE fillna(0), among kept rows:")
    for c, n in surcharge_null_counts.items():
        print(f"  {c}: {n:,}")

    # --- filter attrition table ---
    rows = []
    for name, _ in FILTER_RULES:
        for w in ("pre", "during", "post"):
            n_dropped = rule_fail_counts[name][w]
            n_total = window_totals[w]
            share = n_dropped / n_total if n_total else float("nan")
            rows.append({"rule": name, "window": w, "n_dropped": n_dropped,
                         "n_total_window": n_total, "share_dropped": share})
    attrition = pd.DataFrame(rows)
    attrition.to_csv(ATTRITION_PATH, index=False)
    print(f"\nWrote {ATTRITION_PATH}")
    pivot = attrition.pivot(index="rule", columns="window", values="share_dropped")
    print(pivot.to_string(float_format=lambda x: f"{x:.4%}"))

    max_ratio = 1.0
    for name, _ in FILTER_RULES:
        shares = {w: rule_fail_counts[name][w] / window_totals[w] if window_totals[w] else 0
                  for w in ("pre", "during", "post")}
        nonzero = [v for v in shares.values() if v > 0]
        if nonzero:
            ratio = max(shares.values()) / max(min(nonzero), 1e-9)
            if ratio > max_ratio:
                max_ratio = ratio
            flag = " <-- bites unevenly (>2x across windows)" if ratio > 2 else ""
            print(f"  {name}: pre={shares['pre']:.4%} during={shares['during']:.4%} "
                  f"post={shares['post']:.4%}  ratio={ratio:.2f}x{flag}")

    # --- validate output ---
    size_mb = OUTPUT_PATH.stat().st_size / 1e6
    print(f"\nOutput file size: {size_mb:.0f} MB")

    check = pq.read_table(OUTPUT_PATH, columns=["driver_share", "fare_per_mile", "datetime_hour"]).to_pandas()
    med_share = check["driver_share"].median()
    med_fpm = check["fare_per_mile"].median()
    print(f"Median driver_share: {med_share:.3f} (expect 0.6-0.9)")
    print(f"Median fare_per_mile: {med_fpm:.2f} (expect a few dollars)")
    assert 0.5 < med_share < 0.95, "driver_share median out of expected range -- stop and check fare/pay alignment."
    assert 0.5 < med_fpm < 20, "fare_per_mile median out of expected range -- stop and check units."

    tz = check["datetime_hour"].dt.tz
    print(f"datetime_hour tz: {tz}")
    assert str(tz) == "America/New_York", "datetime_hour is not tz-aware America/New_York -- fix before proceeding."

    platforms = pq.read_table(OUTPUT_PATH, columns=["platform"]).to_pandas()["platform"].value_counts()
    print(f"\nPlatform counts:\n{platforms}")
    assert set(platforms.index) <= {"Uber", "Lyft", "Via"}, "Unexpected platform in output."

    print("\nDone.")


if __name__ == "__main__":
    main()
