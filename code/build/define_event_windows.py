# ============================================================
# Script: define_event_windows.py
# Purpose: Derive the pre / during / post Hurricane Ida windows from
#          observed ASOS precipitation rather than from memory (CLAUDE.md:
#          "Do not hardcode Ida's timeline from memory"), and freeze them
#          to a single JSON file so every downstream script uses identical
#          bounds.
# Inputs: raw_data/weather/asos/asos_nyc_2021.csv (UTC timestamps)
# Outputs: clean_data/ida_event_windows.json
# Author: EK  Date: 2026-08-29
# ============================================================

import json
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASOS_PATH = PROJECT_ROOT / "raw_data" / "weather" / "asos" / "asos_nyc_2021.csv"
OUTPUT_PATH = PROJECT_ROOT / "clean_data" / "ida_event_windows.json"

# NWS threshold for "moderate rain" is >0.1 in/hr; used here only to locate
# the contiguous storm run, not as a scientific intensity classification.
STORM_THRESHOLD_IN = 0.10

PRE_DAYS = 14
POST_DAYS = 14


def main() -> None:
    if OUTPUT_PATH.exists():
        print(f"WARNING: {OUTPUT_PATH} already exists — overwriting.")

    print(f"Reading {ASOS_PATH}")
    df = pd.read_csv(ASOS_PATH, na_values=["M"])
    df["valid"] = pd.to_datetime(df["valid"])

    # ASOS timestamps are UTC (tz=Etc/UTC in the download request). Convert
    # to America/New_York exactly once, here, at this boundary; everything
    # downstream is local time.
    df["valid_utc"] = df["valid"].dt.tz_localize("UTC")
    df["valid_local"] = df["valid_utc"].dt.tz_convert("America/New_York")
    df["hour_local"] = df["valid_local"].dt.floor("h")

    # p01i = precip (in) since previous ob; missing means no precip reported,
    # not unknown -- ASOS reports M for missing sensor readings, but for
    # precip specifically the absence of a numeric value on non-precip hours
    # is the expected pattern, not a data gap that would bias a rainfall max.
    df["p01i"] = df["p01i"].fillna(0.0)

    # City-wide hourly rainfall = max across the four stations (the peak
    # localized cell, not an average that would dilute it) -- Ida's flash
    # flooding was extremely localized (CLAUDE.md), so the max is the
    # relevant summary for locating the storm window.
    hourly = (
        df.groupby("hour_local")["p01i"]
        .max()
        .rename("city_precip_in")
        .reset_index()
        .sort_values("hour_local")
        .reset_index(drop=True)
    )
    hourly["city_precip_mm"] = hourly["city_precip_in"] * 25.4

    peak_idx = hourly["city_precip_in"].idxmax()
    peak_hour = hourly.loc[peak_idx, "hour_local"]
    peak_value_in = hourly.loc[peak_idx, "city_precip_in"]

    print(f"Peak hour (local): {peak_hour}  ({peak_value_in:.2f} in)")
    if not (peak_hour.date().isoformat() == "2021-09-01" and peak_hour.hour >= 17):
        raise RuntimeError(
            f"Peak precip hour {peak_hour} is not on the evening of "
            f"2021-09-01 local time -- UTC->EDT conversion is likely wrong. "
            f"Stop and fix before trusting this window."
        )

    # Contiguous run of hours exceeding STORM_THRESHOLD_IN that contains the
    # peak hour. A single below-threshold hour ends the run -- Ida's heavy
    # rain was a single tight burst (see the printed series below), so no
    # gap-tolerance is needed.
    above = hourly["city_precip_in"] > STORM_THRESHOLD_IN
    run_id = (above != above.shift(fill_value=False)).cumsum()
    peak_run_id = run_id.loc[peak_idx]
    run_mask = above & (run_id == peak_run_id)
    run_hours = hourly.loc[run_mask, "hour_local"]

    during_start = run_hours.min()
    during_end_incl = run_hours.max()          # last hour *in* the run
    during_end_excl = during_end_incl + pd.Timedelta(hours=1)  # half-open

    duration_hours = (during_end_excl - during_start).total_seconds() / 3600
    print(f"Storm threshold: {STORM_THRESHOLD_IN} in/hr")
    print(f"During-Ida window: [{during_start}, {during_end_excl})  "
          f"({duration_hours:.0f} hours)")

    if duration_hours > 36:
        raise RuntimeError(
            f"Derived during-Ida window is {duration_hours:.0f} hours, "
            f"longer than the ~36-hour sanity bound. Stop and inspect "
            f"the threshold / run-detection logic before proceeding."
        )

    print("\nHourly precip (max across stations), 2021-08-31 to 2021-09-03:")
    window_print = hourly[
        (hourly["hour_local"] >= pd.Timestamp("2021-08-31", tz="America/New_York"))
        & (hourly["hour_local"] < pd.Timestamp("2021-09-03", tz="America/New_York"))
    ]
    for _, row in window_print.iterrows():
        marker = " <== during" if run_mask.loc[row.name] else ""
        print(f"  {row['hour_local']}  {row['city_precip_in']:.4f} in{marker}")

    # Non-overlapping, whole-day boundaries so day-of-week composition
    # matches between pre and post.
    during_start_day = during_start.normalize()
    during_end_day = during_end_incl.normalize()  # last calendar day touched

    pre_end = during_start_day                                   # exclusive
    pre_start = pre_end - pd.Timedelta(days=PRE_DAYS)             # inclusive

    post_start = during_end_day + pd.Timedelta(days=1)            # inclusive
    post_end = post_start + pd.Timedelta(days=POST_DAYS)          # exclusive

    print(f"\nPre window:    [{pre_start}, {pre_end})  ({PRE_DAYS} days)")
    print(f"During window: [{during_start}, {during_end_excl})")
    print(f"Post window:   [{post_start}, {post_end})  ({POST_DAYS} days)")

    # Labor Day 2021-09-06 confounder -- always inside `post` given the
    # derived boundaries; recorded here so every downstream table note can
    # cite this file rather than re-deriving it.
    labor_day = pd.Timestamp("2021-09-06", tz="America/New_York")
    labor_day_in_post = post_start <= labor_day < post_end
    print(f"Labor Day 2021-09-06 falls in post window: {labor_day_in_post}")
    if not labor_day_in_post:
        print("NOTE: Labor Day did NOT fall in the post window as expected "
              "given the plan's stated dates -- re-check before writing "
              "table notes that assume it does.")

    windows = {
        "pre":    {"start": pre_start.isoformat(),    "end": pre_end.isoformat()},
        "during": {"start": during_start.isoformat(), "end": during_end_excl.isoformat()},
        "post":   {"start": post_start.isoformat(),   "end": post_end.isoformat()},
    }

    payload = {
        "event": "Hurricane Ida remnants, NYC",
        "derived_from": "raw_data/weather/asos/asos_nyc_2021.csv "
                         "(KNYC/KLGA/KJFK/KEWR, hourly p01i, max across stations)",
        "timezone": "America/New_York",
        "storm_threshold_in": STORM_THRESHOLD_IN,
        "peak_hour_local": peak_hour.isoformat(),
        "peak_value_in": float(peak_value_in),
        "peak_value_mm": float(peak_value_in * 25.4),
        "windows": windows,
        "pre_days": PRE_DAYS,
        "post_days": POST_DAYS,
        "confounders": {
            "labor_day_2021_09_06_in_post_window": bool(labor_day_in_post),
            "note": "US Labor Day (Monday 2021-09-06) falls inside the post "
                    "window. The 14-day pre window (2021-08-18 to 2021-08-31 "
                    "as derived) contains no federal holiday, so pre and "
                    "post are not symmetric -- one reason the before/after "
                    "comparison is a descriptive benchmark, not a causal "
                    "estimate.",
        },
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\nWrote {OUTPUT_PATH}")

    # Sanity: no overlap between windows.
    bounds = [
        (pd.Timestamp(windows[w]["start"]), pd.Timestamp(windows[w]["end"]))
        for w in ("pre", "during", "post")
    ]
    for i in range(len(bounds) - 1):
        assert bounds[i][1] <= bounds[i + 1][0], "Windows overlap -- fix boundary logic."
    print("Verified: pre / during / post windows do not overlap.")


if __name__ == "__main__":
    main()
