# ============================================================
# Script: download_hvfhv.py
# Purpose: Download NYC TLC High Volume FHV (HVFHV) monthly trip-record
#          parquet files for the Ida analysis window. Files contain all
#          four HVFHV platforms (Uber HV0003, Lyft HV0005, Via HV0004,
#          Juno HV0002) mixed together -- there is no per-platform bulk
#          download, so Uber-only filtering happens downstream in
#          clean_hvfhv.py via hvfhs_license_num == "HV0003".
# Inputs: none (pulls from TLC's public CloudFront bucket)
# Outputs: raw_data/hvfhv/fhvhv_tripdata_2021-MM.parquet (MM = 08..12)
# Source: https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page
#         URL pattern confirmed against toddwschneider/nyc-taxi-data
#         setup_files/raw_data_urls.txt (github.com/toddwschneider/nyc-taxi-data),
#         which itself points at TLC's own bulk CloudFront files -- that repo
#         does not offer year/month subsetting, it is a Postgres import
#         pipeline over the same monthly files downloaded here.
# Author: EK  Date: 2026-07-30
# ============================================================

import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "raw_data" / "hvfhv"

BASE_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data"

# Aug-Dec 2021: covers the Ida analysis window (2021-08-15 to 2021-09-15,
# landfall 2021-09-01) plus Henri placebo (2021-08-21/22) and a post-period
# for recovery-path analysis. Full year 2021 is ~4.3 GB and was not requested.
MONTHS = ["2021-08", "2021-09", "2021-10", "2021-11", "2021-12"]


def get_remote_size(url: str) -> int:
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req) as resp:
        return int(resp.headers.get("Content-Length", 0))


def download_file(url: str, dest: Path, expected_size: int) -> None:
    if dest.exists() and dest.stat().st_size == expected_size:
        print(f"SKIP  {dest.name} already present ({expected_size:,} bytes)")
        return
    if dest.exists():
        print(f"RE-DOWNLOAD {dest.name}: local size {dest.stat().st_size:,} != "
              f"remote size {expected_size:,}")

    print(f"GET   {url}")
    print(f"  ->  {dest}  ({expected_size:,} bytes)")
    tmp_dest = dest.with_suffix(".parquet.part")
    urllib.request.urlretrieve(url, tmp_dest)

    actual_size = tmp_dest.stat().st_size
    if actual_size != expected_size:
        raise RuntimeError(
            f"Size mismatch for {dest.name}: expected {expected_size:,}, "
            f"got {actual_size:,}"
        )
    tmp_dest.replace(dest)
    print(f"DONE  {dest.name} ({actual_size:,} bytes)")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Size + report before pulling anything (CLAUDE.md cost-estimation rule).
    plan = []
    total_bytes = 0
    for month in MONTHS:
        filename = f"fhvhv_tripdata_{month}.parquet"
        url = f"{BASE_URL}/{filename}"
        size = get_remote_size(url)
        plan.append((url, OUTPUT_DIR / filename, size))
        total_bytes += size

    print(f"\nPlanned downloads: {len(plan)} files, "
          f"{total_bytes / 1e9:.2f} GB total\n")

    for url, dest, size in plan:
        download_file(url, dest, size)

    print("\nFinal contents of raw_data/hvfhv:")
    total_on_disk = 0
    for f in sorted(OUTPUT_DIR.glob("fhvhv_tripdata_2021-*.parquet")):
        sz = f.stat().st_size
        total_on_disk += sz
        print(f"  {f.name}: {sz:,} bytes")
    print(f"Total on disk: {total_on_disk / 1e9:.2f} GB")


if __name__ == "__main__":
    sys.exit(main())
