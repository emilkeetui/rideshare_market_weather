# ============================================================
# Script: download_hvfhv.py
# Purpose: Download NYC TLC High Volume FHV (HVFHV) monthly trip-record
#          parquet files for a range of months. Files contain all four
#          HVFHV platforms (Uber HV0003, Lyft HV0005, Via HV0004, Juno
#          HV0002) mixed together -- there is no per-platform bulk download,
#          so platform filtering happens downstream in clean_hvfhv.py.
# Inputs: none (pulls from TLC's public CloudFront bucket)
# Outputs: raw_data/hvfhv/fhvhv_tripdata_YYYY-MM.parquet
#          clean_data/hvfhv_download_manifest.csv (provenance: url, bytes,
#          Last-Modified, ETag, access date per month)
# Source: https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page
#         Bucket: https://d37ci6vzurychx.cloudfront.net/trip-data/
#         URL pattern confirmed against toddwschneider/nyc-taxi-data
#         setup_files/raw_data_urls.txt, which points at the same TLC files.
#         The same records are on NYC Open Data as yearly datasets
#         (2019 4p5c-cbgn ... 2024 bqxa-629f); the bucket is used because it
#         is parquet, smaller, and more current (accessed 2026-09-26).
# Availability (HEAD probe 2026-09-26): 2019-02 (first HVFHV month) through
#         2026-07. Before 2019-02 Uber/Lyft trips exist only in the plain FHV
#         files (fhv_tripdata_*), which carry no fare or driver pay.
# Schema drift (parquet footers, 2026-09-26) -- handle when cleaning:
#         2019-02, 2020-04, 2020-10: airport_fee is a null-typed column
#                  (2019-02 also wav_match_flag); other months have double.
#         2023-02+: strings stored as large_string and
#                  PULocationID/DOLocationID as int32 (int64 before).
#         2025-01+: adds cbd_congestion_fee (congestion pricing) -- 25 cols.
# Usage:
#   python download_hvfhv.py                                 # 2021-08..2021-12 (original Ida pull)
#   python download_hvfhv.py --start 2020-04 --end latest    # through latest published month
# Author: EK  Date: 2026-07-30 (generalised to month ranges 2026-09-26)
# ============================================================

import argparse
import csv
import datetime as dt
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "raw_data" / "hvfhv"
# Manifest lives in clean_data/ rather than raw_data/ because it is rewritten
# on every run, and raw_data/ files must never be modified.
MANIFEST_PATH = PROJECT_ROOT / "clean_data" / "hvfhv_download_manifest.csv"

BASE_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data"
FIRST_HVFHV_MONTH = "2019-02"
DISK_MARGIN_BYTES = 10 * 1024**3
N_RETRIES = 3
CHUNK_BYTES = 8 * 1024**2
MANIFEST_FIELDS = ["file", "url", "bytes", "last_modified", "etag", "accessed"]


def month_range(start: str, end: str) -> list[str]:
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    months = []
    while (y, m) <= (ey, em):
        months.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months


def head(url: str) -> dict | None:
    """Return remote metadata, or None if the file is not published."""
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return {
                "bytes": int(resp.headers.get("Content-Length", 0)),
                "last_modified": resp.headers.get("Last-Modified", ""),
                "etag": resp.headers.get("ETag", "").strip('"'),
            }
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            return None
        raise


def download_file(url: str, dest: Path, expected_size: int) -> str:
    """Download to a .part file and rename. Never overwrites an existing
    raw file: a size mismatch is reported and skipped for the user to decide."""
    if dest.exists():
        local_size = dest.stat().st_size
        if local_size == expected_size:
            print(f"SKIP  {dest.name} already present ({expected_size:,} bytes)")
            return "present"
        print(f"MISMATCH {dest.name}: local {local_size:,} != remote "
              f"{expected_size:,} -- NOT overwriting raw file; resolve manually")
        return "mismatch"

    tmp_dest = dest.with_suffix(".parquet.part")
    for attempt in range(1, N_RETRIES + 1):
        try:
            print(f"GET   {url}  ({expected_size / 1e6:,.1f} MB, attempt {attempt})")
            t0 = time.time()
            with urllib.request.urlopen(url, timeout=120) as resp, open(tmp_dest, "wb") as out:
                shutil.copyfileobj(resp, out, CHUNK_BYTES)
            actual_size = tmp_dest.stat().st_size
            if actual_size != expected_size:
                raise RuntimeError(f"size mismatch: expected {expected_size:,}, "
                                   f"got {actual_size:,}")
            tmp_dest.replace(dest)
            secs = time.time() - t0
            print(f"DONE  {dest.name} ({actual_size:,} bytes, {secs:.0f}s, "
                  f"{actual_size / 1e6 / max(secs, 1e-9):.1f} MB/s)")
            return "downloaded"
        except (urllib.error.URLError, TimeoutError, ConnectionError, RuntimeError) as e:
            print(f"FAIL  {dest.name} attempt {attempt}: {e}")
            if attempt == N_RETRIES:
                raise
            time.sleep(10 * attempt)
    return "failed"


def write_manifest(rows: list[dict]) -> None:
    existing = {}
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, newline="") as f:
            existing = {r["file"]: r for r in csv.DictReader(f)}
    for r in rows:
        existing[r["file"]] = r
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        w.writeheader()
        for key in sorted(existing):
            w.writerow(existing[key])
    print(f"Manifest: {MANIFEST_PATH} ({len(existing)} rows)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2021-08", help="first month, YYYY-MM")
    parser.add_argument("--end", default="2021-12",
                        help="last month, YYYY-MM, or 'latest' to probe up to today")
    args = parser.parse_args()

    if args.start < FIRST_HVFHV_MONTH:
        parser.error(f"HVFHV files start at {FIRST_HVFHV_MONTH}")
    probe_to_latest = args.end == "latest"
    end = dt.date.today().strftime("%Y-%m") if probe_to_latest else args.end
    months = month_range(args.start, end)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    accessed = dt.date.today().isoformat()

    # Size + report before pulling anything (CLAUDE.md cost-estimation rule).
    plan, missing = [], []
    for month in months:
        filename = f"fhvhv_tripdata_{month}.parquet"
        url = f"{BASE_URL}/{filename}"
        meta = head(url)
        if meta is None:
            missing.append(month)
            continue
        plan.append({"file": filename, "url": url, **meta, "accessed": accessed})

    if missing:
        published = {p["file"][15:22] for p in plan}
        gaps = [m for m in missing if published and m < max(published)]
        if gaps or not probe_to_latest:
            print(f"ERROR: months not published: {missing}")
            return 1
        print(f"Not yet published (skipped): {missing[0]} .. {missing[-1]}")
    if not plan:
        print("Nothing to download.")
        return 1

    to_get = [p for p in plan if not (OUTPUT_DIR / p["file"]).exists()]
    total_bytes = sum(p["bytes"] for p in plan)
    new_bytes = sum(p["bytes"] for p in to_get)
    free_bytes = shutil.disk_usage(OUTPUT_DIR).free
    print(f"\nRange: {plan[0]['file'][15:22]} .. {plan[-1]['file'][15:22]}  "
          f"({len(plan)} files, {total_bytes / 1e9:.2f} GB)")
    print(f"To download: {len(to_get)} files, {new_bytes / 1e9:.2f} GB; "
          f"free disk: {free_bytes / 1e9:.1f} GB\n")
    if new_bytes + DISK_MARGIN_BYTES > free_bytes:
        print("ERROR: not enough free disk space (need download + 10 GB margin)")
        return 1

    status = {}
    for p in plan:
        status[p["file"]] = download_file(p["url"], OUTPUT_DIR / p["file"], p["bytes"])
        # Record manifest after each file so an interrupted run keeps provenance.
        if status[p["file"]] in ("present", "downloaded"):
            write_manifest([p])

    print("\nFinal contents of raw_data/hvfhv:")
    total_on_disk = 0
    for f in sorted(OUTPUT_DIR.glob("fhvhv_tripdata_*.parquet")):
        sz = f.stat().st_size
        total_on_disk += sz
        print(f"  {f.name}: {sz:,} bytes")
    print(f"Total on disk: {total_on_disk / 1e9:.2f} GB")

    bad = {k: v for k, v in status.items() if v not in ("present", "downloaded")}
    if bad:
        print(f"\nUnresolved files: {bad}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
