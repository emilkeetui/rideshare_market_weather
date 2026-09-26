# ============================================================
# Script: download_mta_alerts.py
# Purpose: Download raw MTA service alerts for NYCT Subway and NYCT Bus,
#          April 2020 onward -- the substitute-mode disruption source
#          (subway/bus suspensions during Ida and other events). Raw
#          download only; no parsing into a line/zone x hour panel here.
# Inputs: none (pulls from the data.ny.gov SODA API)
# Outputs: raw_data/subway/mta_alerts/mta_alerts_{agency}_{YYYY}.csv
#          (agency in nyct_subway, nyct_bus; one file per calendar year)
# Source: "MTA Service Alerts: Beginning April 2020", dataset 7kct-peq7
#         https://data.ny.gov/Transportation/MTA-Service-Alerts-Beginning-April-2020/7kct-peq7
#         API: https://data.ny.gov/resource/7kct-peq7.csv  (posted monthly)
#         Access date: 2026-09-26
# Notes:  Each row is one alert *message update* (alert_id), grouped into
#         incidents by event_id. It is not a closure table: the affected
#         routes are in `affected` ("D | N | R"), the type in `status_label`
#         (suspended, part-suspended, delays, ...), and the affected
#         segment/stations only in the free-text `header`/`description`.
# Author: EK  Date: 2026-09-26
# ============================================================

import csv
import io
import json
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "raw_data" / "subway" / "mta_alerts"

BASE_URL = "https://data.ny.gov/resource/7kct-peq7"

# Agency values exactly as they appear in the source `agency` column.
AGENCIES = {"NYCT Subway": "nyct_subway", "NYCT Bus": "nyct_bus"}

# Dataset begins 2020-04-28; pull through the current calendar year.
FIRST_YEAR = 2020
CURRENT_YEAR = date.today().year

PAGE_SIZE = 50_000

# Timezone: `date` is a Socrata floating timestamp (no tz marker) and the
# dataset documentation does not state its zone. Empirically it is UTC,
# NOT local time (checked 2026-09-26):
#   - Ida: first subway suspension alerts are stamped 2021-09-02 02:14,
#     i.e. 22:14 EDT, ~20 min after the ASOS Central Park peak-rain hour
#     (valid 2021-09-02 01:51 UTC = 21:51 EDT, 3.15 in).
#   - The hour-of-day alert trough sits at 08-09, i.e. 4-5 am local, and
#     shifts one hour earlier in Jun-Jul than in Jan-Feb (DST signature).
# Stored untouched here; convert UTC -> America/New_York once, in the
# build step that consumes these files.


def soda_get(fmt: str, params: dict) -> bytes:
    url = f"{BASE_URL}.{fmt}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=300) as resp:
        return resp.read()


def year_where(agency: str, year: int) -> str:
    return (f"agency='{agency}' AND date >= '{year}-01-01T00:00:00' "
            f"AND date < '{year + 1}-01-01T00:00:00'")


def server_count(where: str) -> int:
    body = soda_get("json", {"$select": "count(*)", "$where": where})
    return int(json.loads(body)[0]["count"])


def download_year(agency: str, slug: str, year: int) -> None:
    out_path = OUTPUT_DIR / f"mta_alerts_{slug}_{year}.csv"
    # The current year is still growing, so it is always re-pulled.
    if out_path.exists() and year != CURRENT_YEAR:
        print(f"SKIP {out_path.name}: exists ({out_path.stat().st_size:,} bytes)")
        return

    where = year_where(agency, year)
    expected = server_count(where)
    if expected == 0:
        print(f"SKIP {agency} {year}: 0 rows on server")
        return
    print(f"GET  {agency} {year}: {expected:,} rows -> {out_path}")

    tmp_path = out_path.with_suffix(".csv.part")
    n_rows = 0
    offset = 0
    with open(tmp_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        while True:
            body = soda_get("csv", {"$where": where, "$order": "alert_id",
                                    "$limit": PAGE_SIZE, "$offset": offset})
            # csv module handles quoted fields with embedded newlines.
            rows = list(csv.reader(io.StringIO(body.decode("utf-8"))))
            header, page = rows[0], rows[1:]
            if offset == 0:
                writer.writerow(header)
            writer.writerows(page)
            n_rows += len(page)
            offset += PAGE_SIZE
            if len(page) < PAGE_SIZE:
                break

    if n_rows != expected:
        raise RuntimeError(f"{agency} {year}: downloaded {n_rows:,} rows, "
                           f"server count(*) is {expected:,}. "
                           f"Left {tmp_path.name} for inspection.")

    if out_path.exists():
        print(f"WARNING: {out_path.name} already exists -- overwriting (current year)")
    tmp_path.replace(out_path)
    print(f"DONE {out_path.name}: {n_rows:,} rows, {out_path.stat().st_size:,} bytes")


def ida_spot_check() -> None:
    path = OUTPUT_DIR / "mta_alerts_nyct_subway_2021.csv"
    # Window is UTC (see timezone note): 2021-09-01 22:00 -> 09-02 08:00 UTC
    # = 18:00 -> 04:00 EDT, bracketing the ~21:51 EDT peak-rain hour.
    print("\nIda spot check: NYCT Subway suspension alerts by UTC hour, "
          "2021-09-01 22:00 -> 2021-09-02 08:00 UTC (EDT = UTC-4)")
    counts: dict[tuple[str, str], int] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ts = row["date"]
            if "2021-09-01T22:00" <= ts < "2021-09-02T08:00":
                if "suspended" in row["status_label"]:
                    key = (ts[:13], row["status_label"])
                    counts[key] = counts.get(key, 0) + 1
    for (hour, label), n in sorted(counts.items()):
        print(f"  {hour}Z  {label:<25} {n:>4}")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    totals = {}
    for agency, slug in AGENCIES.items():
        for year in range(FIRST_YEAR, CURRENT_YEAR + 1):
            download_year(agency, slug, year)
        n = 0
        for p in sorted(OUTPUT_DIR.glob(f"mta_alerts_{slug}_*.csv")):
            with open(p, newline="", encoding="utf-8") as f:
                n += sum(1 for _ in csv.reader(f)) - 1
        totals[agency] = n

    print("\nTotal rows on disk by agency:")
    for agency, n in totals.items():
        print(f"  {agency:<12} {n:>9,}")

    ida_spot_check()


if __name__ == "__main__":
    sys.exit(main())
