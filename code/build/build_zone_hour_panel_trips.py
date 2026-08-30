# ============================================================
# Script: build_zone_hour_panel_trips.py
# Purpose: Collapse the cleaned Ida-window trip file to
#          pu_zone_id x datetime_hour x platform, producing every
#          weather-free outcome in the CLAUDE.md glossary plus the money
#          columns settled in plan section 2.1. Ratio outcomes are ratios
#          of sums, not means of ratios (Sigma fare / Sigma miles), so a
#          handful of very short trips cannot dominate the cell average.
# Inputs: clean_data/hvfhv_trips_ida_window.parquet
# Outputs: clean_data/zone_hour_panel_trips.parquet
# Deliberate naming note: NOT clean_data/zone_hour_panel.parquet -- that
#          name is reserved by the documented pipeline for the panel WITH
#          the zone-level weather merge (out of scope here). Writing under
#          the canonical name would silently mislead downstream scripts
#          that expect weather columns.
# Author: EK  Date: 2026-08-29
# ============================================================

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = PROJECT_ROOT / "clean_data" / "hvfhv_trips_ida_window.parquet"
OUTPUT_PATH = PROJECT_ROOT / "clean_data" / "zone_hour_panel_trips.parquet"

PLATFORMS = ["Uber", "Lyft", "Via"]


def main() -> None:
    if OUTPUT_PATH.exists():
        print(f"WARNING: {OUTPUT_PATH} already exists -- overwriting per plan Step 4.")

    cols = [
        "pu_zone_id", "datetime_hour", "platform",
        "trip_miles", "trip_time", "wait_time", "speed_mph",
        "base_passenger_fare", "driver_pay", "driver_pay_total",
        "passthrough_total", "passenger_outlay", "platform_margin", "tips",
        "shared_request_flag", "shared_match_flag",
    ]
    print(f"Reading {INPUT_PATH}")
    df = pq.read_table(INPUT_PATH, columns=cols).to_pandas()
    print(f"Loaded {len(df):,} trips x {df.shape[1]} columns")

    df["is_shared_request"] = (df["shared_request_flag"] == "Y").astype(int)
    df["is_shared_match"] = (df["shared_match_flag"] == "Y").astype(int)
    df["is_margin_negative"] = (df["platform_margin"] < 0).astype(int)

    grouped = df.groupby(["pu_zone_id", "datetime_hour", "platform"], observed=True)

    # Sums first -- every ratio below is Sigma(numerator)/Sigma(denominator),
    # not mean(ratio), so a cell of very short trips cannot dominate it.
    agg = grouped.agg(
        n_trips=("trip_miles", "size"),
        sum_fare=("base_passenger_fare", "sum"),
        sum_driver_pay=("driver_pay", "sum"),
        sum_driver_pay_total=("driver_pay_total", "sum"),
        sum_passthrough=("passthrough_total", "sum"),
        sum_outlay=("passenger_outlay", "sum"),
        sum_margin=("platform_margin", "sum"),
        sum_tips=("tips", "sum"),
        sum_miles=("trip_miles", "sum"),
        sum_time_s=("trip_time", "sum"),
        mean_wait_time=("wait_time", "mean"),
        mean_trip_miles=("trip_miles", "mean"),
        mean_trip_time=("trip_time", "mean"),
        n_shared_request=("is_shared_request", "sum"),
        n_shared_match=("is_shared_match", "sum"),
        n_margin_negative=("is_margin_negative", "sum"),
    ).reset_index()

    agg["revenue_passenger"] = agg["sum_fare"]
    agg["revenue_driver"] = agg["sum_driver_pay_total"]
    agg["revenue_driver_ex_tips"] = agg["sum_driver_pay"]
    agg["platform_margin"] = agg["sum_margin"]
    agg["passthrough_total"] = agg["sum_passthrough"]
    agg["passenger_outlay"] = agg["sum_outlay"]
    agg["tips_total"] = agg["sum_tips"]

    agg["fare_per_trip"] = agg["sum_fare"] / agg["n_trips"]
    agg["outlay_per_trip"] = agg["sum_outlay"] / agg["n_trips"]
    agg["fare_per_mile"] = agg["sum_fare"] / agg["sum_miles"]
    agg["fare_per_minute"] = agg["sum_fare"] / (agg["sum_time_s"] / 60.0)
    agg["pay_per_trip"] = agg["sum_driver_pay"] / agg["n_trips"]
    agg["pay_per_mile"] = agg["sum_driver_pay"] / agg["sum_miles"]
    agg["driver_share"] = agg["sum_driver_pay"] / agg["sum_fare"]
    agg["driver_share_incl_tips"] = agg["sum_driver_pay_total"] / agg["sum_fare"]
    agg["mean_speed_mph"] = agg["sum_miles"] / (agg["sum_time_s"] / 3600.0)
    agg["share_shared_request"] = agg["n_shared_request"] / agg["n_trips"]
    agg["share_shared_match"] = agg["n_shared_match"] / agg["n_trips"]
    agg["share_margin_negative"] = agg["n_margin_negative"] / agg["n_trips"]

    keep_cols = [
        "pu_zone_id", "datetime_hour", "platform",
        "n_trips",
        "revenue_passenger", "revenue_driver", "revenue_driver_ex_tips",
        "platform_margin", "passthrough_total", "passenger_outlay", "tips_total",
        "fare_per_trip", "fare_per_mile", "fare_per_minute", "outlay_per_trip",
        "pay_per_trip", "pay_per_mile", "driver_share", "driver_share_incl_tips",
        "mean_wait_time", "mean_trip_miles", "mean_trip_time", "mean_speed_mph",
        "share_shared_request", "share_shared_match", "share_margin_negative",
    ]
    agg = agg[keep_cols]

    # Zero-trip zone-hours: fill explicitly as zeros on the full
    # zone x hour x platform cross-product. A storm hour with no trips is
    # data (volume is a key outcome), not a missing value.
    zones = sorted(agg["pu_zone_id"].unique())
    hours = pd.date_range(agg["datetime_hour"].min(), agg["datetime_hour"].max(), freq="h")
    full_index = pd.MultiIndex.from_product([zones, hours, PLATFORMS],
                                             names=["pu_zone_id", "datetime_hour", "platform"])
    print(f"Full zone x hour x platform grid: {len(full_index):,} rows "
          f"({len(zones)} zones x {len(hours)} hours x {len(PLATFORMS)} platforms)")

    panel = agg.set_index(["pu_zone_id", "datetime_hour", "platform"]).reindex(full_index)
    count_cols = ["n_trips", "revenue_passenger", "revenue_driver", "revenue_driver_ex_tips",
                  "platform_margin", "passthrough_total", "passenger_outlay", "tips_total"]
    panel[count_cols] = panel[count_cols].fillna(0.0)
    # Ratio/mean columns stay NaN on zero-trip cells -- a rate is undefined
    # with no trips, not zero; fillna(0) there would misrepresent price.
    panel = panel.reset_index()

    panel["pu_zone_id"] = panel["pu_zone_id"].astype("int32")
    panel["platform"] = panel["platform"].astype(str)
    panel["n_trips"] = panel["n_trips"].astype("int64")

    print("\ndtypes before write:")
    print(panel.dtypes)

    assert not panel.duplicated(subset=["pu_zone_id", "datetime_hour", "platform"]).any(), \
        "Duplicate (pu_zone_id, datetime_hour, platform) keys -- must fix."
    assert str(panel["datetime_hour"].dt.tz) == "America/New_York", \
        "datetime_hour tz is wrong -- fix before writing."
    assert panel[["pu_zone_id", "datetime_hour", "platform", "n_trips"]].isna().sum().sum() == 0, \
        "NaN in a key column -- must fix."

    panel.to_parquet(OUTPUT_PATH, index=False, engine="pyarrow")

    size_mb = OUTPUT_PATH.stat().st_size / 1e6
    print(f"\nWrote {len(panel):,} rows x {panel.shape[1]} columns to {OUTPUT_PATH} ({size_mb:.1f} MB)")
    print(f"Zones: {panel['pu_zone_id'].nunique()}")
    print(f"Datetime range: {panel['datetime_hour'].min()} to {panel['datetime_hour'].max()}")
    print(f"Total n_trips in panel: {panel['n_trips'].sum():,}")

    # Round-trip check
    reread = pq.read_table(OUTPUT_PATH, columns=["pu_zone_id", "datetime_hour", "platform"]).to_pandas()
    print(f"\nRound-trip check: pu_zone_id dtype={reread['pu_zone_id'].dtype}, "
          f"datetime_hour tz={reread['datetime_hour'].dt.tz}")
    assert str(reread["datetime_hour"].dt.tz) == "America/New_York", "Timezone did not survive round trip."

    print("\nDone.")


if __name__ == "__main__":
    main()
