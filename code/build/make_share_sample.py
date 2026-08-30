# ============================================================
# Script: make_share_sample.py
# Purpose: Package a self-contained, coauthor-shareable sample of the Ida
#          window data (D3) -- no confidentiality constraint since TLC trip
#          records are fully public, so the only constraints are size and
#          self-containment (no dependency on this repo/venv/raw files).
# Inputs: clean_data/hvfhv_trips_ida_window.parquet
#         clean_data/zone_hour_panel_trips.parquet
#         raw_data/taxi_zones/taxi_zone_lookup.csv
#         clean_data/ida_event_windows.json
#         output/sum/variable_dictionary.csv, summary_stats_trip.csv,
#         summary_stats_panel.csv
# Outputs: output/share/fhv_ida_sample_<YYYYMMDD>.zip
# Author: EK  Date: 2026-08-29
# ============================================================

import gzip
import shutil
import zipfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parents[2]
D1_PATH = PROJECT_ROOT / "clean_data" / "hvfhv_trips_ida_window.parquet"
PANEL_PATH = PROJECT_ROOT / "clean_data" / "zone_hour_panel_trips.parquet"
ZONE_LOOKUP_PATH = PROJECT_ROOT / "raw_data" / "taxi_zones" / "taxi_zone_lookup.csv"
WINDOWS_PATH = PROJECT_ROOT / "clean_data" / "ida_event_windows.json"
SUM_DIR = PROJECT_ROOT / "output" / "sum"
SHARE_DIR = PROJECT_ROOT / "output" / "share"

SEED = 20210901
SAMPLE_RATE = 0.01
MAX_ZIP_MB = 100
TARGET_ZIP_MB = 50

README_TEMPLATE = """# HVFHV Ida-Window Sample -- Read This First

## Source
NYC TLC High Volume For-Hire Vehicle (HVFHV) trip records, publicly released by the NYC
Taxi & Limousine Commission:
https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page
Landing page: https://data.cityofnewyork.us/Transportation/2021-High-Volume-FHV-Trip-Records/5ufr-wvc5/about_data

## What is in this package
- `sample_trips.parquet` / `sample_trips.csv.gz` -- a **{sample_pct:.0%} simple random
  sample of trips** ({n_sample:,} of {n_full:,} trips), `np.random.seed({seed})`. **This is a
  prototyping sample, not for estimation** -- point estimates from it will be noisy, and it
  is not stratified by zone, hour, or platform.
- `zone_hour_panel_sample.parquet` -- the **full** zone x hour x platform panel
  ({n_panel:,} rows). Not sampled -- it is small enough to include whole, and a coauthor
  needs the complete spatial/temporal extent to see aggregate patterns.
- `taxi_zone_lookup.csv` -- TLC taxi zone ID to borough/zone-name lookup.
- `variable_dictionary.csv` -- one row per variable, raw definitions verbatim from the TLC
  data dictionary, constructed-variable definitions from this project's build scripts.
- `summary_stats_trip.csv`, `summary_stats_panel.csv` -- pre-/post-filter trip-level and
  panel-level summary statistics (N, mean, sd, min, percentiles, max).
- `ida_event_windows.json` -- the pre/during/post window boundaries, derived from observed
  ASOS rainfall (never hardcoded), with the threshold, peak hour, and peak rainfall value.

## Window and sample
- Analysis window: pre `{pre_start}` to `{pre_end}`, during `{during_start}` to
  `{during_end}`, post `{post_start}` to `{post_end}` (all America/New_York).
- Sampling: {sample_pct:.0%} simple random sample of trips (not zones or days), seed
  `{seed}`, drawn after all cleaning filters were applied.

## Three things that are easy to get wrong with this data -- read before using it

1. **Only three firms are active in 2021: Uber, Lyft, and Via.** Juno (`HV0002`) ceased
   operations in November 2019 and has zero trips anywhere in this window. Via is a small
   share of trips ({via_pct:.1%}) and will produce noisy per-firm statistics.

2. **`platform_margin` (`base_passenger_fare - driver_pay`) is gross take per trip, NOT
   profit.** It nets out nothing else: no insurance, driver incentives, marketing, R&D,
   support, payment processing, or corporate overhead. Both Uber and Lyft ran large
   consolidated losses in 2021. Do not report it as "profit" without that caveat.

   **Do not deduct `passthrough_total` (tolls + Black Car Fund + airport fee + congestion
   surcharge + sales tax) from `platform_margin`.** These surcharges sit ON TOP of
   `base_passenger_fare` (TLC defines the fare as "before tolls, tips, taxes, and fees") and
   are collected by the firm only to be remitted -- to NYS, the Black Car Fund, the airport
   operator, the toll authority. Subtracting them double-counts about $5.29/trip (roughly a
   fifth of the mean fare) and drives measured margin to roughly zero on half of all trips.
   That is an accounting artefact of double-subtraction, not a finding.

3. **`n_trips` counts trips, not customers.** There is no rider ID in this dataset. A
   customer taking four trips is four rows, indistinguishable from four different customers.
   Likewise there is no driver ID -- do not construct or expect an `n_drivers` column.

   **Unfulfilled requests are not observed.** The data records completed trips only, so a
   drop in `n_trips` during the storm is a *lower bound* on the true demand shock -- some of
   the decline is demand that showed up and was never served.

## Variable definitions
See `variable_dictionary.csv` for the complete list. The money variables used throughout
this project:
```
revenue_passenger  = base_passenger_fare                          # firm revenue
driver_pay_total    = driver_pay + tips                            # driver take-home
platform_margin     = base_passenger_fare - driver_pay             # firm per-trip gross take (NOT profit)
passthrough_total   = tolls + bcf + airport_fee + congestion_surcharge + sales_tax  # remitted, never deducted from margin
passenger_outlay    = base_passenger_fare + passthrough_total + tips  # what the rider actually paid
```
"""


def main() -> None:
    SHARE_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().strftime("%Y%m%d")
    zip_path = SHARE_DIR / f"fhv_ida_sample_{today}.zip"
    if zip_path.exists():
        print(f"WARNING: {zip_path} already exists -- overwriting per plan Step 6.")

    work_dir = SHARE_DIR / "_staging"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    print(f"Reading {D1_PATH}")
    d1 = pq.read_table(D1_PATH).to_pandas()
    n_full = len(d1)

    rng = np.random.default_rng(SEED)
    sample_idx = rng.choice(n_full, size=int(round(n_full * SAMPLE_RATE)), replace=False)
    sample = d1.iloc[np.sort(sample_idx)].reset_index(drop=True)
    n_sample = len(sample)
    print(f"Sampled {n_sample:,} of {n_full:,} trips ({n_sample/n_full:.2%}), seed={SEED}")

    via_pct = (d1["platform"] == "Via").mean()

    sample.to_parquet(work_dir / "sample_trips.parquet", index=False, engine="pyarrow")
    csv_path = work_dir / "sample_trips.csv"
    sample.to_csv(csv_path, index=False)
    with open(csv_path, "rb") as f_in, gzip.open(work_dir / "sample_trips.csv.gz", "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    csv_path.unlink()
    del d1, sample

    print(f"Copying {PANEL_PATH}")
    panel = pq.read_table(PANEL_PATH).to_pandas()
    n_panel = len(panel)
    shutil.copy2(PANEL_PATH, work_dir / "zone_hour_panel_sample.parquet")
    del panel

    shutil.copy2(ZONE_LOOKUP_PATH, work_dir / "taxi_zone_lookup.csv")
    shutil.copy2(SUM_DIR / "variable_dictionary.csv", work_dir / "variable_dictionary.csv")
    shutil.copy2(SUM_DIR / "summary_stats_trip.csv", work_dir / "summary_stats_trip.csv")
    shutil.copy2(SUM_DIR / "summary_stats_panel.csv", work_dir / "summary_stats_panel.csv")
    shutil.copy2(WINDOWS_PATH, work_dir / "ida_event_windows.json")

    import json
    with open(WINDOWS_PATH) as f:
        w = json.load(f)

    readme = README_TEMPLATE.format(
        sample_pct=SAMPLE_RATE, n_sample=n_sample, n_full=n_full, seed=SEED,
        n_panel=n_panel, via_pct=via_pct,
        pre_start=w["windows"]["pre"]["start"], pre_end=w["windows"]["pre"]["end"],
        during_start=w["windows"]["during"]["start"], during_end=w["windows"]["during"]["end"],
        post_start=w["windows"]["post"]["start"], post_end=w["windows"]["post"]["end"],
    )
    with open(work_dir / "README.md", "w", encoding="utf-8") as f:
        f.write(readme)

    def write_zip(rate_note=""):
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(work_dir.iterdir()):
                zf.write(p, arcname=p.name)
        return zip_path.stat().st_size / 1e6

    size_mb = write_zip()
    print(f"\nZip size: {size_mb:.1f} MB -> {zip_path}")

    if size_mb > MAX_ZIP_MB:
        print(f"Zip exceeds {MAX_ZIP_MB} MB -- dropping sample_trips.csv.gz and retrying.")
        (work_dir / "sample_trips.csv.gz").unlink()
        size_mb = write_zip()
        print(f"Zip size after dropping csv.gz: {size_mb:.1f} MB")

    if size_mb > MAX_ZIP_MB:
        print("Still over threshold -- this run does not auto-reduce further; "
              "stop and inspect before reducing the sample rate below 1%.")

    shutil.rmtree(work_dir)

    print("\nVerifying zip contents:")
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            print(f"  {info.filename}: {info.file_size:,} bytes")

    # Round-trip check: sample_trips.parquet reads standalone
    with zipfile.ZipFile(zip_path) as zf:
        zf.extract("sample_trips.parquet", path=SHARE_DIR / "_verify")
    check = pq.read_table(SHARE_DIR / "_verify" / "sample_trips.parquet").to_pandas()
    print(f"\nRound-trip check: sample_trips.parquet reads standalone, {len(check):,} rows "
          f"({len(check)/n_full:.2%} of D1)")
    shutil.rmtree(SHARE_DIR / "_verify")

    print(f"\nFinal: {zip_path} ({size_mb:.1f} MB), target <{TARGET_ZIP_MB} MB "
          f"({'OK' if size_mb < TARGET_ZIP_MB else 'OVER TARGET, but under hard cap'})")
    print("\nDone.")


if __name__ == "__main__":
    main()
