# ============================================================
# Script: download_asos.py
# Purpose: Download hourly-resolution ASOS/METAR station observations
#          (temperature, wind speed, gust, 1-hour precip, visibility) for
#          the four NYC-area stations, spanning the Ida analysis window.
#          Used downstream by define_event_windows.py to derive the storm
#          window from observed weather rather than from memory, per
#          CLAUDE.md ("Do not hardcode Ida's timeline from memory").
# Inputs: none (pulls from the Iowa State IEM ASOS archive, public CGI)
# Outputs: raw_data/weather/asos/asos_nyc_2021.csv
# Source: https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py
#         Stations: KNYC (Central Park), KLGA, KJFK, KEWR
#         Request window: 2021-08-14 00:00 UTC -> 2021-10-01 00:00 UTC
#         Data vars: tmpf, sknt, gust, p01i, vsby ; tz=UTC
#         Access date: 2026-08-29
# Author: EK  Date: 2026-08-29
# ============================================================

import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "raw_data" / "weather" / "asos"
OUTPUT_PATH = OUTPUT_DIR / "asos_nyc_2021.csv"

STATIONS = ["KNYC", "KLGA", "KJFK", "KEWR"]

BASE_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"

# Window covers the pre/during/post Ida windows with buffer on both ends.
# Timestamps returned are UTC (tz=Etc/UTC below) -- converted to
# America/New_York exactly once, downstream in define_event_windows.py.
PARAMS = {
    "data": "tmpf,sknt,gust,p01i,vsby",
    "year1": "2021", "month1": "8", "day1": "14",
    "year2": "2021", "month2": "10", "day2": "1",
    "tz": "Etc/UTC",
    "format": "onlycomma",
    "latlon": "no",
    "elev": "no",
    "missing": "M",
    "trace": "0.0001",
    "direct": "no",
    "report_type": "3",  # hourly (routine + specials); avoids 1-min noise
}


def build_url() -> str:
    station_qs = "&".join(f"station={s}" for s in STATIONS)
    param_qs = "&".join(f"{k}={v}" for k, v in PARAMS.items())
    return f"{BASE_URL}?{station_qs}&{param_qs}"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if OUTPUT_PATH.exists():
        print(f"SKIP: {OUTPUT_PATH} already exists "
              f"({OUTPUT_PATH.stat().st_size:,} bytes). Not re-downloading.")
        return

    url = build_url()
    print(f"GET  {url}")
    print(f"  -> {OUTPUT_PATH}")

    tmp_dest = OUTPUT_PATH.with_suffix(".csv.part")
    urllib.request.urlretrieve(url, tmp_dest)

    size = tmp_dest.stat().st_size
    if size < 1000:
        # A too-small response usually means the CGI returned an error page,
        # not data -- fail loudly rather than leaving a bad file in place.
        text = tmp_dest.read_text(errors="replace")[:500]
        tmp_dest.unlink()
        raise RuntimeError(
            f"ASOS response suspiciously small ({size} bytes). "
            f"First 500 chars:\n{text}"
        )

    tmp_dest.replace(OUTPUT_PATH)
    print(f"DONE {OUTPUT_PATH.name}: {size:,} bytes")

    with open(OUTPUT_PATH, "r") as f:
        header = f.readline().strip()
        n_lines = sum(1 for _ in f) + 1
    print(f"Header: {header}")
    print(f"Rows (incl. header): {n_lines:,}")


if __name__ == "__main__":
    sys.exit(main())
