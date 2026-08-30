# ============================================================
# Script: build_firm_window_aggregates.py
# Purpose: The three-window (pre_matched/during/post_matched) x firm
#          comparison for D4 -- the heavy trip-level collapse, done in
#          Python per the documented language split. R
#          (code/analysis/ida_first_pass.r) reads the output and produces
#          the table/figures. This is CLAUDE.md Design 2 (simple
#          before/after) -- a descriptive benchmark, not a causal estimate.
#          pre_matched/post_matched replace the old full-calendar-day
#          pre/post comparison: they replicate the exact clock-hour span of
#          `during` across 14 days each, 2-4 weeks before/after the storm,
#          so the comparison isolates the storm's effect on that specific
#          time-of-day slice instead of conflating it with ordinary
#          daytime-vs-evening demand patterns. Every level comparison is
#          still per-day, never a raw total, since `during` (9h) is far
#          shorter than the pooled 5.25-day matched sides.
#          firm_day_aggregates.parquet (the figure's data source) is now a
#          DAY-ANCHORED 9-HOUR WINDOW aggregate, not a full calendar day:
#          each row collapses only the same evening/overnight clock-hour
#          span as `during`, anchored to that calendar date, so every panel
#          in the figure compares like time-of-day slices throughout the
#          series (user request 2026-08-29).
# Inputs: clean_data/hvfhv_trips_ida_window.parquet (during window only)
#         clean_data/hvfhv_trips_matched_windows.parquet (pre_matched/post_matched)
#         clean_data/ida_event_windows.json
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
MATCHED_PATH = PROJECT_ROOT / "clean_data" / "hvfhv_trips_matched_windows.parquet"
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
    agg["platform_margin_per_trip"] = agg["platform_margin"] / agg["n_trips"]
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
    out["platform_margin_per_trip"] = out["platform_margin"] / out["n_trips"]
    out["mean_speed_mph"] = out["sum_miles"] / (out["sum_time_s"] / 3600.0)
    out["share_shared_match"] = out["n_shared_match"] / out["n_trips"]
    return out


def main() -> None:
    print(f"Reading {D1_PATH}")
    d1_all = pq.read_table(D1_PATH).to_pandas()
    print(f"Total rows in D1 (all tags incl. buffer): {len(d1_all):,}")
    d1_full = d1_all[d1_all["window"].isin(["pre", "during", "post"])].copy()
    print(f"Trips in named windows (excl. buffer): {len(d1_full):,}")

    d1_during = d1_full[d1_full["window"] == "during"].copy()
    print(f"Trips in `during` window: {len(d1_during):,}")

    print(f"Reading {MATCHED_PATH}")
    matched = pq.read_table(MATCHED_PATH).to_pandas()
    matched = matched.drop(columns=["replicate_offset_days"])
    print(f"Trips in pre_matched/post_matched windows: {len(matched):,}")

    # Concatenate on the shared out_cols schema (both cleaning scripts emit
    # identical column sets aside from the matched file's diagnostic-only
    # replicate_offset_days, dropped above). This combined frame feeds only
    # the window x firm aggregates -- day_agg below stays sourced from
    # d1_full (D1's own pre/during/post, unchanged date range), per the plan.
    window_source = pd.concat([d1_during, matched], ignore_index=True)
    print(f"Combined trips across during/pre_matched/post_matched: {len(window_source):,}")

    # --- window x firm aggregates ---
    window_agg = collapse(window_source, ["window", "platform"])
    window_agg = add_all_platform_rows(window_agg, ["window", "platform"])

    # n_days = exact elapsed window duration in days, from the frozen window
    # boundaries -- NOT a count of distinct calendar dates touched. The
    # `during` window is ~9 hours spanning parts of 2 calendar dates; using
    # a date count (2) would understate its trips_per_day by ~5x relative
    # to pre_matched/post_matched's true daily rate. This is what makes
    # per-day comparisons across windows of very different length actually
    # comparable. pre_matched/post_matched each pool 14 replicate windows of
    # the same length as `during`, so their n_days is 14x during's n_days
    # (5.25 days), read from the matched_window_params in the JSON rather
    # than hardcoded.
    with open(WINDOWS_PATH) as f:
        windows_json = json.load(f)
    during_start = pd.Timestamp(windows_json["windows"]["during"]["start"])
    during_end = pd.Timestamp(windows_json["windows"]["during"]["end"])
    during_n_days = (during_end - during_start).total_seconds() / 86400
    n_replicates = windows_json["matched_window_params"]["n_replicates"]
    n_days = {
        "during": during_n_days,
        "pre_matched": during_n_days * n_replicates,
        "post_matched": during_n_days * n_replicates,
    }
    print(f"n_days per window (during's exact elapsed duration x {n_replicates} "
          f"replicates for the matched sides): {n_days}")
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
        "platform_margin_per_trip", "mean_trip_miles", "sd_trip_miles", "mean_trip_time",
        "mean_speed_mph", "mean_wait_time", "share_shared_match",
        "sd_fare", "sd_margin",
    ]
    window_agg = window_agg[keep_cols].sort_values(["window", "platform"])
    window_agg.to_parquet(WINDOW_OUT_PATH, index=False, engine="pyarrow")
    print(f"\nWrote {len(window_agg)} rows to {WINDOW_OUT_PATH}")
    print(window_agg[["window", "platform", "n_trips", "n_days", "trips_per_day",
                      "platform_margin_per_trip", "driver_share", "share_margin_negative",
                      "fare_per_mile"]].to_string(index=False))

    # Sanity check keyed off pre_matched (evening/overnight-only population,
    # not the old full-day `pre`) -- print actual values without hard-failing
    # outside the old full-day figures, since a different typical fare/
    # driver-share for this time-of-day slice is a real result, not a bug.
    # The asserts below are kept as a wide sanity net only (still flag a
    # wildly implausible number), per the plan.
    pre_all = window_agg[(window_agg["window"] == "pre_matched") & (window_agg["platform"] == "All")]
    margin_per_trip_pre = pre_all["platform_margin_per_trip"].iloc[0]
    driver_share_pre = pre_all["driver_share"].iloc[0]
    share_neg_pre = pre_all["share_margin_negative"].iloc[0]
    print(f"\nSanity check (pre_matched window, All platforms): "
          f"platform_margin_per_trip={margin_per_trip_pre:.2f} (old full-day pre was ~$5.24; "
          f"this is an evening/overnight-only population, may differ), "
          f"driver_share={driver_share_pre:.3f} (old full-day pre was ~0.79), "
          f"share_margin_negative={share_neg_pre:.2%} (old full-day pre was ~18%)")
    assert 1 < margin_per_trip_pre < 15, "platform_margin_per_trip wildly out of range -- check money columns."
    assert 0.4 < driver_share_pre < 0.95, "driver_share wildly out of range."
    assert 0.02 < share_neg_pre < 0.5, "share_margin_negative wildly out of range."

    # --- day x firm aggregates (for R to plot the small-multiples figure) ---
    # Each "date" here is an ANCHOR date for a 9-hour evening/overnight
    # window -- [date 17:00, date+1 02:00), the identical clock-hour span as
    # the During-Ida window -- not a full 24h calendar day. This makes every
    # panel in the figure (trips, revenue, fare_per_mile, driver_share,
    # platform_margin_per_trip, ...) compare the SAME time-of-day slice
    # across every day in the range, so the During-Ida point is measured
    # against genuinely like periods rather than full-day totals diluted by
    # daytime hours (user request 2026-08-29, following on the matched-window
    # redesign of the pre/during/post table above).
    #
    # Sourced from d1_all (ALL window tags, including "buffer") rather than
    # d1_full/window_source: several anchor windows straddle the pre/during/
    # post boundary and need buffer-tagged hours for complete coverage --
    # e.g. the 2021-09-02 anchor window needs 2021-09-02 17:00-24:00, which
    # is tagged "buffer" (it falls after `during` ends and before `post`
    # starts), not "post". Restricting to d1_full would silently truncate
    # those boundary-adjacent anchor windows to a partial few hours.
    start_secs = during_start.hour * 3600 + during_start.minute * 60 + during_start.second
    end_secs = during_end.hour * 3600 + during_end.minute * 60 + during_end.second

    pickup = d1_all["pickup_datetime"]
    secs_since_midnight = pickup.dt.hour * 3600 + pickup.dt.minute * 60 + pickup.dt.second
    floor_date = pickup.dt.floor("D")
    in_evening = secs_since_midnight >= start_secs   # e.g. 17:00-23:59:59
    in_early_am = secs_since_midnight < end_secs     # e.g. 00:00-01:59:59

    anchor_date = pd.Series(pd.NaT, index=pickup.index, dtype="datetime64[ns]")
    anchor_date.loc[in_evening] = floor_date.loc[in_evening]
    anchor_date.loc[in_early_am] = (floor_date - pd.Timedelta(days=1)).loc[in_early_am]

    # Keep the same anchor-date range as the old full-day figure (pre_start
    # to post_end - 1 day) so the plotted date range is unchanged; this also
    # excludes edge anchor dates whose window would run past the buffered
    # read range D1 was built from.
    pre_start_date = pd.Timestamp(windows_json["windows"]["pre"]["start"]).tz_localize(None).normalize()
    post_end_date = pd.Timestamp(windows_json["windows"]["post"]["end"]).tz_localize(None).normalize()
    last_anchor_date = post_end_date - pd.Timedelta(days=1)

    in_range = anchor_date.notna() & (anchor_date >= pre_start_date) & (anchor_date <= last_anchor_date)
    d1_9h = d1_all.loc[in_range].copy()
    d1_9h["date"] = anchor_date.loc[in_range].dt.date
    print(f"\nDay-anchored 9h-window trips for the figure: {len(d1_9h):,} rows, "
          f"{d1_9h['date'].nunique()} anchor dates "
          f"({pre_start_date.date()} to {last_anchor_date.date()})")

    day_agg = collapse(d1_9h, ["date", "platform"])
    day_agg = add_all_platform_rows(day_agg, ["date", "platform"])
    day_keep_cols = [
        "date", "platform", "n_trips",
        "revenue_passenger", "passenger_outlay_total",
        "revenue_driver", "revenue_driver_ex_tips", "tips_total",
        "driver_share", "driver_share_incl_tips",
        "platform_margin", "margin_rate", "passthrough_total", "share_margin_negative",
        "fare_per_trip", "outlay_per_trip", "fare_per_mile", "fare_per_minute",
        "platform_margin_per_trip", "mean_trip_miles", "mean_trip_time", "mean_speed_mph",
        "mean_wait_time", "share_shared_match",
    ]
    day_agg = day_agg[day_keep_cols].sort_values(["date", "platform"])
    day_agg.to_parquet(DAY_OUT_PATH, index=False, engine="pyarrow")
    print(f"\nWrote {len(day_agg)} rows to {DAY_OUT_PATH}")

    # --- percent-change columns, pre_matched -> during and during -> post_matched ---
    print("\nPercent change, per-day basis (All platforms):")
    pre_row = window_agg[(window_agg["window"] == "pre_matched") & (window_agg["platform"] == "All")].iloc[0]
    for w in ["during", "post_matched"]:
        row = window_agg[(window_agg["window"] == w) & (window_agg["platform"] == "All")].iloc[0]
        for m in ["trips_per_day", "revenue_passenger_per_day", "fare_per_mile", "platform_margin_per_day"]:
            pct = (row[m] - pre_row[m]) / pre_row[m] * 100
            print(f"  pre -> {w}: {m}: {pct:+.1f}%")

    print("\nDone.")


if __name__ == "__main__":
    main()
