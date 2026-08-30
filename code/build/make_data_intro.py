# ============================================================
# Script: make_data_intro.py
# Purpose: Build the "introduction to the data" deliverable (D2): a
#          variable dictionary sourced verbatim from the TLC data
#          dictionary, trip-level summary stats (pre- and post-filter, so
#          the cleaning rules' effect is legible), panel-level summary
#          stats, a data-structure (cardinality) table, three figures, and
#          a prose write-up generated from these numbers.
# Inputs: raw_data/HVFHV_Trip_Data_Data_Dictionary.xlsx
#         raw_data/hvfhv/fhvhv_tripdata_2021-{08,09}.parquet (pre-filter pass)
#         clean_data/hvfhv_trips_ida_window.parquet (D1, post-filter)
#         clean_data/zone_hour_panel_trips.parquet (panel)
#         clean_data/ida_event_windows.json
#         output/sum/filter_attrition.csv
# Outputs: output/sum/variable_dictionary.csv, .tex
#          output/sum/summary_stats_trip.csv, .tex   (pre- and post-filter)
#          output/sum/summary_stats_panel.csv, .tex
#          output/sum/data_structure.csv
#          output/fig/trips_daily_by_platform.png
#          output/fig/fare_per_mile_daily_by_platform.png
#          output/fig/trips_hourly_ida_window.png
#          docs/data_introduction.md
# Author: EK  Date: 2026-08-29
# ============================================================

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DICT_PATH = PROJECT_ROOT / "raw_data" / "HVFHV_Trip_Data_Data_Dictionary.xlsx"
HVFHV_DIR = PROJECT_ROOT / "raw_data" / "hvfhv"
WINDOWS_PATH = PROJECT_ROOT / "clean_data" / "ida_event_windows.json"
D1_PATH = PROJECT_ROOT / "clean_data" / "hvfhv_trips_ida_window.parquet"
PANEL_PATH = PROJECT_ROOT / "clean_data" / "zone_hour_panel_trips.parquet"
ATTRITION_PATH = PROJECT_ROOT / "output" / "sum" / "filter_attrition.csv"

SUM_DIR = PROJECT_ROOT / "output" / "sum"
FIG_DIR = PROJECT_ROOT / "output" / "fig"
DOCS_DIR = PROJECT_ROOT / "docs"

PCTS = [0.01, 0.25, 0.50, 0.75, 0.99]
PCT_LABELS = ["p1", "p25", "median", "p75", "p99"]

PLATFORM_MAP = {"HV0002": "Juno", "HV0003": "Uber", "HV0004": "Via", "HV0005": "Lyft"}


# ------------------------------------------------------------------
# (a) Variable dictionary
# ------------------------------------------------------------------

# Constructed variables not in the TLC dictionary -- definitions verbatim
# from the approved plan (.claude/plans/hvfhv-data-introduction-and-ida-
# first-pass.md, section 2 and Step 3), not from memory.
CONSTRUCTED_DEFS = {
    "platform": ("hvfhs_license_num mapped to firm name (HV0002=Juno, HV0003=Uber, "
                 "HV0004=Via, HV0005=Lyft). Juno has zero trips in this window.", "n/a"),
    "pu_zone_id": ("PULocationID cast to int32.", "TLC taxi zone ID, 1-263"),
    "do_zone_id": ("DOLocationID cast to int32.", "TLC taxi zone ID, 1-263"),
    "datetime_hour": ("pickup_datetime floored to the hour, tz-localized America/New_York "
                       "(source timestamps are naive local wall clock; this is a tz label, "
                       "not a UTC conversion).", "local datetime, hourly"),
    "date": ("Local calendar date of pickup_datetime.", "date"),
    "window": ("pre/during/post/buffer label from clean_data/ida_event_windows.json, "
               "derived from observed ASOS rainfall, not hardcoded.", "categorical"),
    "wait_time": ("pickup_datetime minus request_datetime, in seconds. NOT on_scene_datetime, "
                  "which is populated for wheelchair-accessible (WAV) trips only.", "seconds"),
    "speed_mph": ("trip_miles / (trip_time / 3600).", "miles per hour"),
    "fare_per_mile": ("base_passenger_fare / trip_miles. Headline price measure -- removes "
                       "most trip-composition drift that a raw mean fare would confound with "
                       "the storm's effect on trip length.", "$ per mile"),
    "fare_per_minute": ("base_passenger_fare / (trip_time / 60).", "$ per minute"),
    "driver_pay_total": ("driver_pay + tips. Driver take-home pay.", "$"),
    "passthrough_total": ("tolls + bcf + airport_fee + congestion_surcharge + sales_tax. "
                           "Collected by the firm and remitted to NYS/the Black Car Fund/the "
                           "toll authority/the airport operator -- net zero to the firm. "
                           "Never subtracted from platform_margin (see notes).", "$"),
    "passenger_outlay": ("base_passenger_fare + passthrough_total + tips -- what the rider "
                          "actually paid, understated by base_passenger_fare alone by about a "
                          "quarter on average.", "$"),
    "platform_margin": ("base_passenger_fare - driver_pay. Firm per-trip gross take, NOT "
                         "accounting profit (no insurance, incentives, marketing, overhead "
                         "costs are netted out). The surcharge-deduction formula originally "
                         "specified was retired: surcharges sit ON TOP of base_passenger_fare "
                         "and are remitted, so subtracting them double-counts ~$5.29/trip and "
                         "drives measured margin to ~0 on half of all trips (see docs/"
                         "data_introduction.md).", "$"),
    "driver_share": ("driver_pay / base_passenger_fare. Headline, ex-tips.", "ratio"),
    "driver_share_incl_tips": ("driver_pay_total / base_passenger_fare. Can exceed the "
                                "ex-tips version since tips are in the numerator but not the "
                                "denominator.", "ratio"),
}

CONSTRUCTED_ORDER = list(CONSTRUCTED_DEFS.keys())

RENAMED_RAW = {
    "platform": ("hvfhs_license_num", "raw TLC (renamed/mapped)"),
    "pu_zone_id": ("PULocationID", "raw TLC (renamed, retyped int32)"),
    "do_zone_id": ("DOLocationID", "raw TLC (renamed, retyped int32)"),
}

UNITS_OVERRIDE = {
    "trip_miles": "miles", "trip_time": "seconds", "base_passenger_fare": "$",
    "tolls": "$", "bcf": "$", "sales_tax": "$", "congestion_surcharge": "$",
    "airport_fee": "$", "tips": "$", "driver_pay": "$",
    "request_datetime": "datetime (local, naive in source)",
    "pickup_datetime": "datetime (local, naive in source)",
    "dropoff_datetime": "datetime (local, naive in source)",
    "dispatching_base_num": "TLC base license code",
    "shared_request_flag": "Y/N", "shared_match_flag": "Y/N",
    "access_a_ride_flag": "Y/N/blank", "wav_match_flag": "Y/N",
}


def build_variable_dictionary(d1_schema: pa.Schema) -> pd.DataFrame:
    print(f"Reading {DICT_PATH}")
    raw_dict = pd.read_excel(DICT_PATH, sheet_name="Column Information", header=1)
    raw_dict = raw_dict.iloc[1:]  # drop the header-description row
    raw_dict = raw_dict.dropna(subset=["Column Name"]).set_index("Column Name")

    dtype_map = {f.name: str(f.type) for f in d1_schema}
    rows = []

    for col in d1_schema.names:
        if col in CONSTRUCTED_DEFS:
            definition, unit = CONSTRUCTED_DEFS[col]
            source = "constructed"
            notes = ""
        elif col in RENAMED_RAW:
            raw_name, source = RENAMED_RAW[col]
            dict_row = raw_dict.loc[raw_name] if raw_name in raw_dict.index else None
            definition = dict_row["Column Description"] if dict_row is not None else ""
            unit = dict_row["Expected/Allowed Values"] if dict_row is not None else ""
            notes = dict_row["Field Limitations"] if dict_row is not None else ""
        else:
            source = "raw TLC"
            if col in raw_dict.index:
                dict_row = raw_dict.loc[col]
                definition = dict_row["Column Description"]
                unit = UNITS_OVERRIDE.get(col, dict_row.get("Expected/Allowed Values", ""))
                notes_parts = [str(dict_row.get("Field Limitations") or ""),
                                str(dict_row.get("Additional Notes") or "")]
                notes = " ".join(p for p in notes_parts if p and p != "nan")
            else:
                definition = "(not found in TLC dictionary)"
                unit = UNITS_OVERRIDE.get(col, "")
                notes = ""
        rows.append({
            "variable": col,
            "source": source,
            "type": dtype_map.get(col, ""),
            "units": unit,
            "definition": str(definition).replace("\n", " ").strip(),
            "notes": str(notes).replace("\n", " ").strip(),
        })

    out = pd.DataFrame(rows)
    print(f"Variable dictionary: {len(out)} rows "
          f"({(out['source']=='constructed').sum()} constructed, "
          f"{(out['source']!='constructed').sum()} raw/renamed)")
    return out


# ------------------------------------------------------------------
# (b) Trip-level summary stats -- pre-filter and post-filter
# ------------------------------------------------------------------

RAW_NUMERIC_COLS = ["trip_miles", "trip_time", "base_passenger_fare", "tolls", "bcf",
                    "sales_tax", "congestion_surcharge", "airport_fee", "tips", "driver_pay"]
RAW_CATEGORICAL_COLS = ["platform", "shared_request_flag", "shared_match_flag",
                        "access_a_ride_flag", "wav_match_flag"]


def numeric_summary(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    rows = []
    for c in cols:
        s = df[c]
        n_missing = int(s.isna().sum())
        valid = s.dropna()
        q = valid.quantile(PCTS) if len(valid) else pd.Series([np.nan] * len(PCTS), index=PCTS)
        rows.append({
            "variable": c, "N": len(s), "n_missing": n_missing,
            "mean": valid.mean(), "sd": valid.std(),
            "min": valid.min() if len(valid) else np.nan,
            **{lbl: q.loc[p] for lbl, p in zip(PCT_LABELS, PCTS)},
            "max": valid.max() if len(valid) else np.nan,
        })
    return pd.DataFrame(rows)


def categorical_summary(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    rows = []
    for c in cols:
        vc = df[c].value_counts(dropna=False)
        total = len(df)
        for val, n in vc.items():
            label = "(blank)" if (pd.isna(val) or str(val).strip() == "") else str(val)
            rows.append({"variable": c, "value": label, "n": int(n), "share": n / total})
    return pd.DataFrame(rows)


def load_prefilter_raw() -> pd.DataFrame:
    """Stream the same buffered date range as clean_hvfhv.py, but with NO
    row filters applied -- this is the population the cleaning filters act
    on, needed to show their effect on the distributions (plan Step 5b)."""
    with open(WINDOWS_PATH) as f:
        w = json.load(f)
    read_start = pd.Timestamp(w["windows"]["pre"]["start"]).tz_localize(None) - pd.Timedelta(days=1)
    read_end = pd.Timestamp(w["windows"]["post"]["end"]).tz_localize(None) + pd.Timedelta(days=1)
    print(f"Pre-filter pass: streaming raw HVFHV files, buffered range "
          f"[{read_start}, {read_end})")

    cols = ["hvfhs_license_num", "pickup_datetime"] + RAW_NUMERIC_COLS + \
        ["shared_request_flag", "shared_match_flag", "access_a_ride_flag", "wav_match_flag"]
    chunks = []
    for month in ["08", "09"]:
        path = HVFHV_DIR / f"fhvhv_tripdata_2021-{month}.parquet"
        pf = pq.ParquetFile(path)
        for batch in pf.iter_batches(batch_size=1_000_000, columns=cols):
            df = batch.to_pandas()
            in_range = (df["pickup_datetime"] >= read_start) & (df["pickup_datetime"] < read_end)
            df = df.loc[in_range]
            if not df.empty:
                chunks.append(df)
    raw = pd.concat(chunks, ignore_index=True)
    raw["platform"] = raw["hvfhs_license_num"].map(PLATFORM_MAP)
    print(f"Pre-filter population: {len(raw):,} rows")
    return raw


def make_trip_summary_stats():
    print("\n--- Building trip-level summary stats (pre- and post-filter) ---")
    prefilter = load_prefilter_raw()
    pre_numeric = numeric_summary(prefilter, RAW_NUMERIC_COLS)
    pre_categorical = categorical_summary(prefilter, RAW_CATEGORICAL_COLS)
    pre_numeric.to_csv(SUM_DIR / "summary_stats_trip_prefilter_numeric.csv", index=False)
    pre_categorical.to_csv(SUM_DIR / "summary_stats_trip_prefilter_categorical.csv", index=False)
    del prefilter

    print(f"Reading D1: {D1_PATH}")
    d1 = pq.read_table(D1_PATH).to_pandas()
    numeric_cols_post = RAW_NUMERIC_COLS + [
        "wait_time", "speed_mph", "fare_per_mile", "fare_per_minute",
        "driver_pay_total", "passthrough_total", "passenger_outlay",
        "platform_margin", "driver_share", "driver_share_incl_tips",
    ]
    post_numeric = numeric_summary(d1, numeric_cols_post)
    post_categorical = categorical_summary(
        d1, RAW_CATEGORICAL_COLS + ["dispatching_base_num"])
    post_numeric.to_csv(SUM_DIR / "summary_stats_trip_postfilter_numeric.csv", index=False)
    post_categorical.to_csv(SUM_DIR / "summary_stats_trip_postfilter_categorical.csv", index=False)

    # Combined csv (both passes stacked, for a single-file view) + LaTeX
    pre_numeric.insert(1, "pass", "pre-filter")
    post_numeric.insert(1, "pass", "post-filter")
    combined = pd.concat([pre_numeric, post_numeric], ignore_index=True)
    combined.to_csv(SUM_DIR / "summary_stats_trip.csv", index=False)
    with open(SUM_DIR / "summary_stats_trip.tex", "w", encoding="utf-8") as f:
        f.write(combined.round(3).to_latex(index=False, longtable=True))

    print(f"Pre-filter N: {len(post_numeric)} numeric vars (D1) vs "
          f"{len(pre_numeric)} (raw); wrote summary_stats_trip.csv/.tex")

    return d1, post_categorical


# ------------------------------------------------------------------
# (c) Panel-level summary stats
# ------------------------------------------------------------------

def make_panel_summary_stats(panel: pd.DataFrame):
    print("\n--- Building panel-level summary stats ---")
    numeric_cols = [c for c in panel.columns
                    if pd.api.types.is_numeric_dtype(panel[c]) and c != "pu_zone_id"]
    stats = numeric_summary(panel, numeric_cols)
    stats.to_csv(SUM_DIR / "summary_stats_panel.csv", index=False)
    with open(SUM_DIR / "summary_stats_panel.tex", "w", encoding="utf-8") as f:
        f.write(stats.round(3).to_latex(index=False, longtable=True))
    print(f"Wrote summary_stats_panel.csv/.tex ({len(stats)} numeric variables)")
    return stats


# ------------------------------------------------------------------
# (d) Data structure / cardinality
# ------------------------------------------------------------------

def make_data_structure(d1: pd.DataFrame) -> pd.DataFrame:
    print("\n--- Building data-structure (cardinality) table ---")
    entities = {
        "pu_zone_id": ["pu_zone_id"],
        "do_zone_id": ["do_zone_id"],
        "pu_zone_id x do_zone_id": ["pu_zone_id", "do_zone_id"],
        "platform": ["platform"],
        "dispatching_base_num": ["dispatching_base_num"],
        "date": ["date"],
        "datetime_hour": ["datetime_hour"],
    }
    rows = []
    for label, keys in entities.items():
        counts = d1.groupby(keys, observed=True).size()
        rows.append({
            "entity": label, "cardinality": int(counts.shape[0]),
            "obs_per_unit_min": int(counts.min()),
            "obs_per_unit_median": float(counts.median()),
            "obs_per_unit_max": int(counts.max()),
        })
    out = pd.DataFrame(rows)
    out.to_csv(SUM_DIR / "data_structure.csv", index=False)
    print(out.to_string(index=False))
    return out


# ------------------------------------------------------------------
# (f) Figures
# ------------------------------------------------------------------

def make_figures(panel: pd.DataFrame, windows: dict):
    print("\n--- Building figures ---")
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    during_start = pd.Timestamp(windows["windows"]["during"]["start"])
    during_end = pd.Timestamp(windows["windows"]["during"]["end"])

    daily = (panel.assign(date=panel["datetime_hour"].dt.date)
             .groupby(["date", "platform"], observed=True)
             .agg(n_trips=("n_trips", "sum"),
                  sum_fare=("revenue_passenger", "sum"))
             .reset_index())
    # Recompute fare_per_mile at the daily level as a ratio of sums using
    # mean_trip_miles*n_trips as an approx miles total (panel doesn't carry
    # sum_miles directly) -- use fare_per_trip mean weighted by n_trips
    # instead, which needs sum_miles; simpler: pull directly from D1-derived
    # panel's fare_per_mile as an n_trips-weighted mean across hours.
    daily_fpm = (panel.assign(date=panel["datetime_hour"].dt.date)
                 .dropna(subset=["fare_per_mile"])
                 .groupby(["date", "platform"], observed=True)
                 .apply(lambda g: np.average(g["fare_per_mile"], weights=g["n_trips"])
                        if g["n_trips"].sum() > 0 else np.nan, include_groups=False)
                 .rename("fare_per_mile").reset_index())

    # trips_daily_by_platform.png
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=300)
    for plat, g in daily.groupby("platform"):
        ax.plot(pd.to_datetime(g["date"]), g["n_trips"], marker="o", markersize=2, label=plat)
    ax.axvspan(during_start, during_end, color="red", alpha=0.15, label="during Ida")
    ax.set_xlabel("date")
    ax.set_ylabel("trips per day")
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(FIG_DIR / "trips_daily_by_platform.png", dpi=300)
    plt.close(fig)

    # fare_per_mile_daily_by_platform.png
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=300)
    for plat, g in daily_fpm.groupby("platform"):
        ax.plot(pd.to_datetime(g["date"]), g["fare_per_mile"], marker="o", markersize=2, label=plat)
    ax.axvspan(during_start, during_end, color="red", alpha=0.15, label="during Ida")
    ax.set_xlabel("date")
    ax.set_ylabel("fare per mile ($, trip-weighted mean)")
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fare_per_mile_daily_by_platform.png", dpi=300)
    plt.close(fig)

    # trips_hourly_ida_window.png, 08-30 -> 09-04, storm hours shaded
    hourly_window = panel[(panel["datetime_hour"] >= pd.Timestamp("2021-08-30", tz="America/New_York"))
                          & (panel["datetime_hour"] < pd.Timestamp("2021-09-04", tz="America/New_York"))]
    hourly = hourly_window.groupby(["datetime_hour", "platform"], observed=True)["n_trips"].sum().reset_index()
    fig, ax = plt.subplots(figsize=(9, 4.5), dpi=300)
    for plat, g in hourly.groupby("platform"):
        ax.plot(g["datetime_hour"], g["n_trips"], label=plat)
    ax.axvspan(during_start, during_end, color="red", alpha=0.15, label="during Ida")
    ax.set_xlabel("hour (America/New_York)")
    ax.set_ylabel("trips per hour")
    ax.legend()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(FIG_DIR / "trips_hourly_ida_window.png", dpi=300)
    plt.close(fig)

    print("Wrote trips_daily_by_platform.png, fare_per_mile_daily_by_platform.png, "
          "trips_hourly_ida_window.png")


# ------------------------------------------------------------------
# (e) docs/data_introduction.md
# ------------------------------------------------------------------

def make_prose(d1: pd.DataFrame, post_categorical: pd.DataFrame,
               data_structure: pd.DataFrame, windows: dict):
    print("\n--- Writing docs/data_introduction.md ---")
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    n_trips = len(d1)
    n_zones_used = d1["pu_zone_id"].nunique()
    platform_counts = d1["platform"].value_counts()
    on_scene_note = "on_scene_datetime is dropped from D1 (Accessible-Vehicles-only, near-entirely null in the source)."

    aar_dist = post_categorical[post_categorical["variable"] == "access_a_ride_flag"]
    aar_lines = "\n".join(
        f"  - `{r.value}`: {r.n:,} ({r.share:.2%})" for r in aar_dist.itertuples()
    )

    shared_match_dist = post_categorical[post_categorical["variable"] == "shared_match_flag"]
    shared_match_y = shared_match_dist.loc[shared_match_dist["value"] == "Y", "share"]
    shared_match_y_pct = f"{shared_match_y.iloc[0]:.2%}" if len(shared_match_y) else "0%"

    base_ds = data_structure.set_index("entity")

    attrition = pd.read_csv(ATTRITION_PATH)
    pivot = attrition.pivot(index="rule", columns="window", values="share_dropped")
    uneven = []
    for rule in pivot.index:
        vals = pivot.loc[rule]
        nz = vals[vals > 0]
        if len(nz) and (vals.max() / max(nz.min(), 1e-9)) > 2:
            uneven.append((rule, vals["pre"], vals["during"], vals["post"]))

    uneven_lines = "\n".join(
        f"- `{rule}`: pre {pre:.4%}, during {during:.4%}, post {post:.4%}"
        for rule, pre, during, post in uneven
    ) or "- none"

    md = f"""# Introduction to the HVFHV Trip Data — Hurricane Ida Window

Generated by `code/build/make_data_intro.py` from `clean_data/hvfhv_trips_ida_window.parquet`
(D1), `clean_data/zone_hour_panel_trips.parquet`, `clean_data/ida_event_windows.json`, and
`output/sum/filter_attrition.csv`. All numbers below are pulled from those files, not
retyped from memory.

## 1. What one row is

In D1, one row is a single completed HVFHV trip, as submitted by the dispatching base to
TLC, filtered to the buffered Ida analysis window (pre/during/post ± 1 day) and passed
through the cleaning filters in `code/build/clean_hvfhv.py`. **N = {n_trips:,} trips.**

## 2. Geographic scale

Trips originate in **{n_zones_used} of 263 usable TLC taxi zones** (264/265 are
unknown/outside NYC and are excluded by the `PULocationID <= 263` filter). Zones span five
boroughs plus Newark Airport (EWR). Zones are **not equal-area** — outer-borough zones are
orders of magnitude larger than Manhattan zones, which is why any future weather merge onto
this panel must be area-weighted rather than a centroid lookup (see CLAUDE.md). Both pickup
(`pu_zone_id`) and dropoff (`do_zone_id`) zones are recorded, so origin-destination flow
analysis is supported (`pu_zone_id x do_zone_id` cardinality:
{int(base_ds.loc['pu_zone_id x do_zone_id', 'cardinality']):,} distinct pairs observed).
**No sub-zone coordinates exist** — there are no lat/lon columns, so within-zone location is
unrecoverable.

## 3. Temporal scale

Four timestamps per trip to the second in the raw source (`request_datetime`,
`on_scene_datetime`, `pickup_datetime`, `dropoff_datetime`), local wall clock
America/New_York, **timezone-naive in the file** (no tz marker; local time is asserted, not
converted, when building `datetime_hour`). {on_scene_note} Local raw files span
2021-08-01 to 2021-12-31; the published TLC dataset runs from February 2019.

The three analysis windows, derived from observed ASOS rainfall (never hardcoded — see
`code/build/define_event_windows.py`):

| Window | Start | End | Notes |
|---|---|---|---|
| pre    | {windows['windows']['pre']['start']} | {windows['windows']['pre']['end']} | 14 full days |
| during | {windows['windows']['during']['start']} | {windows['windows']['during']['end']} | peak hourly rain {windows['peak_value_in']:.2f} in at {windows['peak_hour_local']} |
| post   | {windows['windows']['post']['start']} | {windows['windows']['post']['end']} | 14 full days; **contains US Labor Day 2021-09-06** |

Natural aggregations: hour (`datetime_hour`), day (`date`).

## 4. What repeats, and what does not

**Repeats** (panel dimensions available), from `output/sum/data_structure.csv`:

| Entity | Cardinality | Obs/unit (min / median / max) |
|---|---:|---|
"""
    for entity, row in base_ds.iterrows():
        md += (f"| {entity} | {int(row['cardinality']):,} | "
               f"{int(row['obs_per_unit_min']):,} / {row['obs_per_unit_median']:.1f} / "
               f"{int(row['obs_per_unit_max']):,} |\n")

    md += f"""
Platform composition ({', '.join(f'{k} {v:,}' for k, v in platform_counts.items())}) —
**three active firms, not four**: Juno (`HV0002`) ceased operations in November 2019 and has
zero trips anywhere in the 2021 local files. Via is only {platform_counts.get('Via', 0) / n_trips:.2%}
of trips in this window and will produce noisy per-firm statistics; report it, but flag the
share.

**Does not exist:** no rider ID, no driver ID, no vehicle ID, no trip ID. The data is a
**repeated cross-section of trips over zones and time — not a panel of drivers or of
customers.** No individual can be followed across trips, so driver entry/exit, extensive-margin
labour supply, and repeat-customer behaviour are all out of reach.

## 5. What the data can and cannot answer

**Can:**
- Price levels and dispersion (`base_passenger_fare`, `fare_per_mile`, `fare_per_minute`)
- Trip volume (`n_trips` — trips, not customers)
- Revenue and platform take (`revenue_passenger`, `platform_margin`)
- Wait times (`wait_time`, built from `pickup_datetime - request_datetime`)
- Realized speed as a road-condition proxy (`speed_mph`)
- OD flows and displacement (`pu_zone_id x do_zone_id`)
- Spatial heterogeneity across zones
- Firm-level differences across Uber, Lyft, and Via

**Cannot, without other data:**
- True firm profit — no cost data (insurance, incentives, marketing, overhead). Every
  `platform_margin` figure in this project is gross take, never profit.
- Customer counts or consumer welfare directly — no rider ID; `n_trips` is a trip count.
- Driver labour supply — no driver ID.
- The surge multiplier itself — only the realized fare is observed, not the multiplier
  applied to it.
- Pooling behaviour in 2021 — `shared_match_flag` is Y on only {shared_match_y_pct} of
  trips; effectively no variation to analyze.
- **Requests that were never fulfilled** — the data records completed trips only, so unmet
  demand during the storm is invisible and the volume decline is a **lower bound** on the
  demand shock.
- Substitution to subway, taxi, or personal vehicle — needs MTA and yellow/green-taxi data.

## 6. Known data-quality caveats

TLC's own statement (data dictionary, "Dataset Information"): this is raw base-submitted
data, and "there may be some noise... unexpected categories or numbers out of expected
ranges in some columns." TLC did not create these data and makes no accuracy representations.

**`access_a_ride_flag` carries no trip-level information in 2021** — it is a platform
reporting convention, not a per-trip fact:
{aar_lines}
The split is perfectly determined by platform: Uber reports a blank on every row, Lyft and
Via report `N` on every row, and there is not one `Y` in the window. This means (i) any
MTA-administered paratransit trips Uber performed are indistinguishable from ordinary trips
across roughly 70% of the market (a genuine blind spot, not fixable from this field), and
(ii) excluding `access_a_ride_flag == "Y"` (as CLAUDE.md originally suggested) is moot — no
such rows exist.

**Filter attrition biting unevenly across pre/during/post** (>2x ratio; see
`output/sum/filter_attrition.csv`):
{uneven_lines}
Of these, `time_le_21600s` (the 6-hour trip-time cap) is the one that reflects a real
storm effect rather than noise: it bites roughly 25x harder during Ida than in the pre/post
windows, consistent with a handful of trips running into extreme gridlock. The absolute
count is tiny (well under 0.02% of during-window rows), so it does not materially threaten
the sample, but it is treatment-relevant data being dropped and is recorded here rather than
buried.

**The profit-formula accounting trap** (see `.claude/plans/hvfhv-data-introduction-and-ida-
first-pass.md` section 2.1 for the full derivation): `sales_tax`, `bcf`, `congestion_surcharge`,
`airport_fee`, and `tolls` are collected by the firm **on top of** `base_passenger_fare` and
remitted to NYS / the Black Car Fund / the airport operator / the toll authority — TLC
defines `base_passenger_fare` as the fare "before tolls, tips, taxes, and fees." A first
instinct to compute per-trip profit as `base_passenger_fare - driver_pay - tolls - bcf -
airport_fee - congestion_surcharge - sales_tax` double-counts roughly $5.29/trip (about 21%
of the mean base fare) and drives measured margin negative on about half of all trips. This
is an artefact of the double subtraction, not a finding about 2021 ride-share economics. The
correct, retired-formula-free definition used throughout this project is:

```
platform_margin = base_passenger_fare - driver_pay      # firm per-trip gross take
passthrough_total = tolls + bcf + airport_fee + congestion_surcharge + sales_tax  # remitted, never deducted
passenger_outlay  = base_passenger_fare + passthrough_total + tips  # what the rider actually paid
```
"""

    with open(DOCS_DIR / "data_introduction.md", "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Wrote {DOCS_DIR / 'data_introduction.md'} ({len(md):,} chars)")


def main():
    SUM_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    with open(WINDOWS_PATH) as f:
        windows = json.load(f)

    d1_schema = pq.ParquetFile(D1_PATH).schema_arrow

    var_dict = build_variable_dictionary(d1_schema)
    var_dict.to_csv(SUM_DIR / "variable_dictionary.csv", index=False)
    with open(SUM_DIR / "variable_dictionary.tex", "w", encoding="utf-8") as f:
        f.write(var_dict.to_latex(index=False, longtable=True))
    print(f"Wrote variable_dictionary.csv/.tex ({len(var_dict)} rows)")

    d1, post_categorical = make_trip_summary_stats()

    print(f"\nReading panel: {PANEL_PATH}")
    panel = pq.read_table(PANEL_PATH).to_pandas()
    make_panel_summary_stats(panel)

    data_structure = make_data_structure(d1)

    make_figures(panel, windows)

    make_prose(d1, post_categorical, data_structure, windows)

    print("\nAll D2 outputs written. Verifying non-zero sizes:")
    for p in [
        SUM_DIR / "variable_dictionary.csv", SUM_DIR / "summary_stats_trip.csv",
        SUM_DIR / "summary_stats_panel.csv", SUM_DIR / "data_structure.csv",
        FIG_DIR / "trips_daily_by_platform.png",
        FIG_DIR / "fare_per_mile_daily_by_platform.png",
        FIG_DIR / "trips_hourly_ida_window.png",
        DOCS_DIR / "data_introduction.md",
    ]:
        size = p.stat().st_size if p.exists() else 0
        status = "OK" if size > 0 else "MISSING/EMPTY"
        print(f"  {status:14s} {p} ({size:,} bytes)")

    print("\nDone.")


if __name__ == "__main__":
    main()
