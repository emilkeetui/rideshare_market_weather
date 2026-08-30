# ============================================================
# Script: build_firm_window_aggregates.py
# Purpose: The three-window (pre/during/post) x firm comparison for D4 --
#          the heavy trip-level collapse, done in Python per the documented
#          language split. R (code/analysis/ida_first_pass.r) reads the
#          output and produces the table/figures. This is CLAUDE.md Design
#          2 (simple before/after) -- a descriptive benchmark, not a causal
#          estimate; the during window is far shorter than 14 days, so
#          every level comparison is per-day, never a raw total.
# Inputs: clean_data/hvfhv_trips_ida_window.parquet
# Outputs: clean_data/firm_window_aggregates.parquet
#          clean_data/firm_day_aggregates.parquet
# Author: EK  Date: 2026-08-29
# ============================================================

from pathlib import Path

import json

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parents[2]
D1_PATH = PROJECT_ROOT / "clean_data" / "hvfhv_trips_ida_window.parquet"
WINDOWS_PATH = PROJECT_ROOT / "clean_data" / "ida_event_windows.json"
WINDOW_OUT_PATH = PROJECT_ROOT / "clean_data" / "firm_window_aggregates.parquet"
DAY_OUT_PATH = PROJECT_ROOT / "clean_data" / "firm_day_aggregates.parquet"


def collapse(df: pd.DataFrame, group_cols: list) -> pd.DataFrame:
    is_neg = (df["platform_margin"] < 0).astype(int)
    is_shared = (df["shared_match_flag"] == "Y").astype(int)

    g = df.assign(is_margin_negative=is_neg, is_shared_match=is_shared).groupby(
        group_cols, observed=True)

    agg = g.agg(
        n_trips=("trip_miles", "size"),
        sum_fare=("base_passenger_fare", "sum"),
        sd_fare=("base_passenger_fare", "std"),
        sum_driver_pay=("driver_pay", "sum"),
        sum_driver_pay_total=("driver_pay_total", "sum"),
        sum_tips=("tips", "sum"),
        sum_passthrough=("passthrough_total", "sum"),
        sum_outlay=("passenger_outlay", "sum"),
        sum_margin=("platform_margin", "sum"),
        sd_margin=("platform_margin", "std"),
        sum_miles=("trip_miles", "sum"),
        sum_time_s=("trip_time", "sum"),
        mean_trip_miles=("trip_miles", "mean"),
        sd_trip_miles=("trip_miles", "std"),
        mean_trip_time=("trip_time", "mean"),
        mean_wait_time=("wait_time", "mean"),
        n_margin_negative=("is_margin_negative", "sum"),
        n_shared_match=("is_shared_match", "sum"),
    ).reset_index()

    agg["revenue_passenger"] = agg["sum_fare"]
    agg["passenger_outlay_total"] = agg["sum_outlay"]
    agg["revenue_driver"] = agg["sum_driver_pay_total"]
    agg["revenue_driver_ex_tips"] = agg["sum_driver_pay"]
    agg["tips_total"] = agg["sum_tips"]
    agg["driver_share"] = agg["revenue_driver_ex_tips"] / agg["revenue_passenger"]
    agg["driver_share_incl_tips"] = agg["revenue_driver"] / agg["revenue_passenger"]

    agg["platform_margin"] = agg["revenue_passenger"] - agg["revenue_driver_ex_tips"]
    agg["margin_rate"] = agg["platform_margin"] / agg["revenue_passenger"]
    agg["passthrough_total"] = agg["sum_passthrough"]
    agg["share_margin_negative"] = agg["n_margin_negative"] / agg["n_trips"]

    agg["fare_per_trip"] = agg["sum_fare"] / agg["n_trips"]
    agg["outlay_per_trip"] = agg["sum_outlay"] / agg["n_trips"]
    agg["fare_per_mile"] = agg["sum_fare"] / agg["sum_miles"]
    agg["fare_per_minute"] = agg["sum_fare"] / (agg["sum_time_s"] / 60.0)
    agg["profit_per_trip"] = agg["platform_margin"] / agg["n_trips"]
    agg["mean_speed_mph"] = agg["sum_miles"] / (agg["sum_time_s"] / 3600.0)
    agg["share_shared_match"] = agg["n_shared_match"] / agg["n_trips"]

    return agg


def add_all_platform_rows(agg: pd.DataFrame, group_cols: list) -> pd.DataFrame:
    """Emit an 'All' platform total per remaining group key (e.g. per window)."""
    other_cols = [c for c in group_cols if c != "platform"]
    if not other_cols:
        return agg
    frames = [agg]
    for keys, sub in agg.groupby(other_cols, observed=True):
        keys = keys if isinstance(keys, tuple) else (keys,)
        row = {c: k for c, k in zip(other_cols, keys)}
        row["platform"] = "All"
        row["n_trips"] = sub["n_trips"].sum()
        row["sum_fare"] = sub["sum_fare"].sum()
        row["sum_driver_pay"] = sub["sum_driver_pay"].sum()
        row["sum_driver_pay_total"] = sub["sum_driver_pay_total"].sum()
        row["sum_tips"] = sub["sum_tips"].sum()
        row["sum_passthrough"] = sub["sum_passthrough"].sum()
        row["sum_outlay"] = sub["sum_outlay"].sum()
        row["sum_margin"] = sub["sum_margin"].sum()
        row["sum_miles"] = sub["sum_miles"].sum()
        row["sum_time_s"] = sub["sum_time_s"].sum()
        row["mean_trip_miles"] = np.average(sub["mean_trip_miles"], weights=sub["n_trips"])
        row["mean_trip_time"] = np.average(sub["mean_trip_time"], weights=sub["n_trips"])
        row["mean_wait_time"] = np.average(sub["mean_wait_time"], weights=sub["n_trips"])
        row["n_margin_negative"] = sub["n_margin_negative"].sum()
        row["n_shared_match"] = sub["n_shared_match"].sum()
        row["sd_fare"] = np.nan
        row["sd_margin"] = np.nan
        row["sd_trip_miles"] = np.nan
        frames.append(pd.DataFrame([row]))
    out = pd.concat(frames, ignore_index=True)

    # Recompute derived columns for the new "All" rows.
    out["revenue_passenger"] = out["sum_fare"]
    out["passenger_outlay_total"] = out["sum_outlay"]
    out["revenue_driver"] = out["sum_driver_pay_total"]
    out["revenue_driver_ex_tips"] = out["sum_driver_pay"]
    out["tips_total"] = out["sum_tips"]
    out["driver_share"] = out["revenue_driver_ex_tips"] / out["revenue_passenger"]
    out["driver_share_incl_tips"] = out["revenue_driver"] / out["revenue_passenger"]
    out["platform_margin"] = out["revenue_passenger"] - out["revenue_driver_ex_tips"]
    out["margin_rate"] = out["platform_margin"] / out["revenue_passenger"]
    out["passthrough_total"] = out["sum_passthrough"]
    out["share_margin_negative"] = out["n_margin_negative"] / out["n_trips"]
    out["fare_per_trip"] = out["sum_fare"] / out["n_trips"]
    out["outlay_per_trip"] = out["sum_outlay"] / out["n_trips"]
    out["fare_per_mile"] = out["sum_fare"] / out["sum_miles"]
    out["fare_per_minute"] = out["sum_fare"] / (out["sum_time_s"] / 60.0)
    out["profit_per_trip"] = out["platform_margin"] / out["n_trips"]
    out["mean_speed_mph"] = out["sum_miles"] / (out["sum_time_s"] / 3600.0)
    out["share_shared_match"] = out["n_shared_match"] / out["n_trips"]
    return out


def main() -> None:
    print(f"Reading {D1_PATH}")
    d1 = pq.read_table(D1_PATH).to_pandas()
    d1 = d1[d1["window"].isin(["pre", "during", "post"])].copy()
    print(f"Trips in named windows (excl. buffer): {len(d1):,}")

    # --- window x firm aggregates ---
    window_agg = collapse(d1, ["window", "platform"])
    window_agg = add_all_platform_rows(window_agg, ["window", "platform"])

    # n_days = exact elapsed window duration in days, from the frozen window
    # boundaries -- NOT a count of distinct calendar dates touched. The
    # `during` window is ~9 hours spanning parts of 2 calendar dates; using
    # a date count (2) would understate its trips_per_day by ~5x relative
    # to pre/post's true daily rate. This is what makes per-day comparisons
    # across windows of very different length actually comparable.
    with open(WINDOWS_PATH) as f:
        windows_json = json.load(f)
    n_days = {}
    for w in ("pre", "during", "post"):
        start = pd.Timestamp(windows_json["windows"][w]["start"])
        end = pd.Timestamp(windows_json["windows"][w]["end"])
        n_days[w] = (end - start).total_seconds() / 86400
    print(f"n_days per window (exact elapsed duration from ida_event_windows.json): {n_days}")
    window_agg["n_days"] = window_agg["window"].map(n_days)
    window_agg["trips_per_day"] = window_agg["n_trips"] / window_agg["n_days"]
    window_agg["revenue_passenger_per_day"] = window_agg["revenue_passenger"] / window_agg["n_days"]
    window_agg["platform_margin_per_day"] = window_agg["platform_margin"] / window_agg["n_days"]

    # --- assert the money identities (plan section 2.1 / Step 7) ---
    tol = 1e-6
    check1 = (window_agg["revenue_passenger"] - window_agg["revenue_driver_ex_tips"]
              - window_agg["platform_margin"]).abs()
    check2 = (window_agg["revenue_driver"] - window_agg["revenue_driver_ex_tips"]
              - window_agg["tips_total"]).abs()
    check3 = (window_agg["passenger_outlay_total"] - window_agg["revenue_passenger"]
              - window_agg["passthrough_total"] - window_agg["tips_total"]).abs()
    assert (check1 < tol).all(), "Identity failed: revenue_passenger - revenue_driver_ex_tips != platform_margin"
    assert (check2 < tol).all(), "Identity failed: revenue_driver - revenue_driver_ex_tips != tips_total"
    assert (check3 < tol).all(), "Identity failed: passenger_outlay != revenue_passenger + passthrough_total + tips_total"
    print("Money identities verified (revenue-margin, driver-tips, outlay decomposition).")

    keep_cols = [
        "window", "platform", "n_trips", "n_days", "trips_per_day",
        "revenue_passenger", "revenue_passenger_per_day", "passenger_outlay_total",
        "revenue_driver", "revenue_driver_ex_tips", "tips_total",
        "driver_share", "driver_share_incl_tips",
        "platform_margin", "platform_margin_per_day", "margin_rate",
        "passthrough_total", "share_margin_negative",
        "fare_per_trip", "outlay_per_trip", "fare_per_mile", "fare_per_minute",
        "profit_per_trip", "mean_trip_miles", "sd_trip_miles", "mean_trip_time",
        "mean_speed_mph", "mean_wait_time", "share_shared_match",
        "sd_fare", "sd_margin",
    ]
    window_agg = window_agg[keep_cols].sort_values(["window", "platform"])
    window_agg.to_parquet(WINDOW_OUT_PATH, index=False, engine="pyarrow")
    print(f"\nWrote {len(window_agg)} rows to {WINDOW_OUT_PATH}")
    print(window_agg[["window", "platform", "n_trips", "n_days", "trips_per_day",
                      "profit_per_trip", "driver_share", "share_margin_negative",
                      "fare_per_mile"]].to_string(index=False))

    pre_all = window_agg[(window_agg["window"] == "pre") & (window_agg["platform"] == "All")]
    profit_per_trip_pre = pre_all["profit_per_trip"].iloc[0]
    driver_share_pre = pre_all["driver_share"].iloc[0]
    share_neg_pre = pre_all["share_margin_negative"].iloc[0]
    print(f"\nSanity check (pre window, All platforms): profit_per_trip={profit_per_trip_pre:.2f} "
          f"(expect ~$5.24), driver_share={driver_share_pre:.3f} (expect ~0.79), "
          f"share_margin_negative={share_neg_pre:.2%} (expect ~18%)")
    assert 3 < profit_per_trip_pre < 8, "profit_per_trip out of expected range -- check money columns."
    assert 0.6 < driver_share_pre < 0.9, "driver_share out of expected range."
    assert 0.05 < share_neg_pre < 0.35, "share_margin_negative out of expected range."

    # --- day x firm aggregates (for R to plot daily series) ---
    day_agg = collapse(d1, ["date", "platform"])
    day_agg = add_all_platform_rows(day_agg, ["date", "platform"])
    day_keep_cols = [
        "date", "platform", "n_trips",
        "revenue_passenger", "passenger_outlay_total",
        "revenue_driver", "revenue_driver_ex_tips", "tips_total",
        "driver_share", "driver_share_incl_tips",
        "platform_margin", "margin_rate", "passthrough_total", "share_margin_negative",
        "fare_per_trip", "outlay_per_trip", "fare_per_mile", "fare_per_minute",
        "profit_per_trip", "mean_trip_miles", "mean_trip_time", "mean_speed_mph",
        "mean_wait_time", "share_shared_match",
    ]
    day_agg = day_agg[day_keep_cols].sort_values(["date", "platform"])
    day_agg.to_parquet(DAY_OUT_PATH, index=False, engine="pyarrow")
    print(f"\nWrote {len(day_agg)} rows to {DAY_OUT_PATH}")

    # --- percent-change columns, pre -> during and pre -> post ---
    print("\nPercent change, per-day basis (All platforms):")
    pre_row = window_agg[(window_agg["window"] == "pre") & (window_agg["platform"] == "All")].iloc[0]
    for w in ["during", "post"]:
        row = window_agg[(window_agg["window"] == w) & (window_agg["platform"] == "All")].iloc[0]
        for m in ["trips_per_day", "revenue_passenger_per_day", "fare_per_mile", "platform_margin_per_day"]:
            pct = (row[m] - pre_row[m]) / pre_row[m] * 100
            print(f"  pre -> {w}: {m}: {pct:+.1f}%")

    print("\nDone.")


if __name__ == "__main__":
    main()
