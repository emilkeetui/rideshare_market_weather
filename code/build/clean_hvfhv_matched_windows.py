# ============================================================
# Script: clean_hvfhv_matched_windows.py
# Purpose: Trip-level cleaning of HVFHV records for the time-of-day-matched
#          pre/post comparison (D4 rework). Mirrors clean_hvfhv.py's filter
#          rules and constructed columns exactly, but keeps only trips whose
#          pickup_datetime falls inside one of the 28 matched windows from
#          clean_data/ida_event_windows.json (pre_matched_windows /
#          post_matched_windows: same clock-hour span as the `during` storm
#          window, replicated 14x at 2-4 week offsets before and after).
#          This isolates the storm's effect on that specific time-of-day
#          slice instead of conflating it with ordinary daytime demand
#          patterns present in the old full-calendar-day pre/post windows.
#          Deliberately duplicates clean_hvfhv.py's per-batch logic rather
#          than refactoring it into a shared module (plan: minimal-risk,
#          does not touch the already-verified D1 pipeline).
# Inputs: raw_data/hvfhv/fhvhv_tripdata_2021-08.parquet,
#         raw_data/hvfhv/fhvhv_tripdata_2021-09.parquet,
#         clean_data/ida_event_windows.json
# Outputs: clean_data/hvfhv_trips_matched_windows.parquet
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
OUTPUT_PATH = PROJECT_ROOT / "clean_data" / "hvfhv_trips_matched_windows.parquet"

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

# Row-level filter rules -- identical to clean_hvfhv.py, applied uniformly
# across pre_matched/post_matched per CLAUDE.md ("an asymmetric filter is
# itself a treatment effect").
FILTER_RULES = [
    ("fare_gt_0",        lambda df: df["base_passenger_fare"] > 0),
    ("fare_le_1000",     lambda df: df["base_passenger_fare"] <= 1000),
    ("miles_gt_0",       lambda df: df["trip_miles"] > 0),
    ("miles_le_100",     lambda df: df["trip_miles"] <= 100),
    ("time_gt_60s",      lambda df: df["trip_time"] > 60),
    ("time_le_21600s",   lambda df: df["trip_time"] <= 21600),
    ("pu_zone_le_263",   lambda df: df["PULocationID"] <= 263),
    ("do_zone_le_263",   lambda df: df["DOLocationID"] <= 263),
    ("driver_pay_gt_0",  lambda df: df["driver_pay"] > 0),
]


def load_matched_windows():
    """Return (pre_bounds, post_bounds), each a list of (start, end) naive
    local Timestamp tuples. JSON bounds carry the -04:00 offset; TLC
    timestamps are naive local wall clock -- strip the tz label (not
    convert) so comparisons are against the same naive wall-clock numbers,
    correct here because the whole span sits inside EDT with no DST
    transition (CLAUDE.md)."""
    with open(WINDOWS_PATH) as f:
        w = json.load(f)
    pre_bounds = [
        (pd.Timestamp(win["start"]).tz_localize(None),
         pd.Timestamp(win["end"]).tz_localize(None),
         win["offset_days"])
        for win in w["pre_matched_windows"]
    ]
    post_bounds = [
        (pd.Timestamp(win["start"]).tz_localize(None),
         pd.Timestamp(win["end"]).tz_localize(None),
         win["offset_days"])
        for win in w["post_matched_windows"]
    ]
    return pre_bounds, post_bounds


def assign_window(pickup: pd.Series, pre_bounds, post_bounds):
    """Return (window, replicate_offset_days) Series. window is
    'pre_matched'/'post_matched'/None; a row is None (dropped) if it falls
    in none of the 28 matched windows."""
    window = pd.Series(None, index=pickup.index, dtype=object)
    offset = pd.Series(np.nan, index=pickup.index, dtype="float64")
    for start, end, off in pre_bounds:
        m = (pickup >= start) & (pickup < end)
        window = window.where(~m, "pre_matched")
        offset = offset.where(~m, off)
    for start, end, off in post_bounds:
        m = (pickup >= start) & (pickup < end)
        window = window.where(~m, "post_matched")
        offset = offset.where(~m, off)
    return window, offset


def main() -> None:
    if OUTPUT_PATH.exists():
        print(f"WARNING: {OUTPUT_PATH} already exists -- overwriting.")

    pre_bounds, post_bounds = load_matched_windows()
    print(f"Loaded {len(pre_bounds)} pre_matched + {len(post_bounds)} post_matched windows "
          f"from {WINDOWS_PATH}")

    # Rough size estimate before writing (plan: ~350-400 MB expected).
    n_days_covered = len(pre_bounds) + len(post_bounds)
    print(f"Matched-window union covers {n_days_covered} x 9h ~= "
          f"{n_days_covered * 9 / 24:.2f} days of trip data out of the raw files' "
          f"~55-day span. Estimated output: well under the 500 MB safeguard threshold "
          f"(see .claude/plans/matched-window-comparison-and-margin-per-trip.md).")

    n_kept = 0
    n_raw_scanned = 0
    window_totals = {"pre_matched": 0, "post_matched": 0}
    rule_fail_counts = {name: {"pre_matched": 0, "post_matched": 0} for name, _ in FILTER_RULES}
    surcharge_null_counts = {c: 0 for c in SURCHARGE_COLS}

    writer = None
    output_schema = None

    for input_path in INPUT_FILES:
        size_mb = input_path.stat().st_size / 1e6
        print(f"\nStreaming {input_path.name} ({size_mb:.0f} MB, "
              f"{len(READ_COLS)} of its columns)")
        pf = pq.ParquetFile(input_path)

        for batch_i, batch in enumerate(pf.iter_batches(batch_size=BATCH_SIZE, columns=READ_COLS)):
            df = batch.to_pandas()
            batch_n = len(df)
            n_raw_scanned += batch_n

            window, offset = assign_window(df["pickup_datetime"], pre_bounds, post_bounds)
            in_matched = window.notna()
            if not in_matched.any():
                continue
            df = df.loc[in_matched].copy()
            df["window"] = window.loc[in_matched]
            df["replicate_offset_days"] = offset.loc[in_matched].astype("int32")

            for w in window_totals:
                window_totals[w] += int((df["window"] == w).sum())

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

            # --- money, identical to clean_hvfhv.py / CLAUDE.md-confirmed
            # definitions: surcharges sit ON TOP of base_passenger_fare and
            # are never subtracted from platform_margin. ---
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
                "datetime_hour", "date", "window", "replicate_offset_days",
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

            print(f"  batch {batch_i}: scanned {batch_n:,} rows, "
                  f"{in_matched.sum():,} in a matched window, kept {len(out):,}")

    if writer is not None:
        writer.close()

    print(f"\nTotal raw rows scanned: {n_raw_scanned:,}")
    print(f"Total kept rows: {n_kept:,}")
    print(f"Window totals (raw, pre-filter): {window_totals}")

    print("\nSurcharge null counts BEFORE fillna(0), among kept rows:")
    for c, n in surcharge_null_counts.items():
        print(f"  {c}: {n:,}")

    print("\nFilter attrition (share dropped, per rule x window):")
    for name, _ in FILTER_RULES:
        shares = {w: rule_fail_counts[name][w] / window_totals[w] if window_totals[w] else 0
                  for w in ("pre_matched", "post_matched")}
        print(f"  {name}: pre_matched={shares['pre_matched']:.4%} "
              f"post_matched={shares['post_matched']:.4%}")

    # --- validate output ---
    size_mb = OUTPUT_PATH.stat().st_size / 1e6
    print(f"\nOutput file size: {size_mb:.1f} MB")
    if size_mb > 500:
        print(f"WARNING: output exceeds the 500 MB safeguard threshold "
              f"(.claude/rules/data-safeguards.md) -- flag to the user before proceeding.")

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

    windows_out = pq.read_table(OUTPUT_PATH, columns=["window"]).to_pandas()["window"].value_counts()
    print(f"\nWindow counts (post-filter):\n{windows_out}")
    assert set(windows_out.index) == {"pre_matched", "post_matched"}, "Unexpected window tag in output."

    print("\nDone.")


if __name__ == "__main__":
    main()
