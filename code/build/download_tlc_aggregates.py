# ============================================================
# Script: download_tlc_aggregates.py
# Purpose: Download TLC's independently published aggregate counts used as an external
#          benchmark for HVFHV trip-record completeness.
# Inputs: NYC Open Data Socrata API (no auth)
#   - FHV Base Aggregate Report, id 2v9c-2k7f: monthly total_dispatched_trips per base
#     (tabulated by TLC from raw base trip-record submissions)
#   - TLC Industry Indicators, id v6kb-cqej: trips_per_day by license class
#     (class "FHV - High Volume"), monthly
# Outputs: raw_data/hvfhv/tlc_aggregates/{fhv_base_aggregate_report_2v9c-2k7f,
#          tlc_industry_indicators_v6kb-cqej}.csv  (registered download folder, new files only)
#          raw_data/hvfhv/tlc_aggregates/provenance.csv (URL, bytes, access date)
# Access date: 2026-10-02
# Author: EK  Date: 2026-10-02
# ============================================================
import datetime as dt
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "raw_data" / "hvfhv" / "tlc_aggregates"
SETS = {"fhv_base_aggregate_report_2v9c-2k7f": "2v9c-2k7f",
        "tlc_industry_indicators_v6kb-cqej": "v6kb-cqej"}

OUT.mkdir(parents=True, exist_ok=True)
rows = ["file,url,bytes,access_date"]
for name, sid in SETS.items():
    path = OUT / f"{name}.csv"
    url = f"https://data.cityofnewyork.us/resource/{sid}.csv?$limit=1000000"
    if path.exists():
        print(f"{path.name} exists, skip")
    else:
        print(f"GET {url} -> {path}")
        urllib.request.urlretrieve(url, path)
    rows.append(f"{path.name},{url.split('?')[0]},{path.stat().st_size},{dt.date.today()}")
    print(f"{path.name}: {path.stat().st_size:,} bytes")
prov = OUT / "provenance.csv"
if not prov.exists():
    prov.write_text("\n".join(rows) + "\n")
