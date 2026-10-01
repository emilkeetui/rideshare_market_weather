# ============================================================
# Script: build_rain6h_lookup.py
# Purpose: Trailing 6-hour rainfall lookup (zone x hour): rain6h_mm = sum of
#          precip_mm over hours t-6..t-1 (current hour EXCLUDED), on true
#          elapsed time, NaN if fewer than 5 of the 6 hours are non-missing.
# Inputs: clean_data/weather_zone_hour.parquet (read only)
# Outputs: clean_data/rain6h_zone_hour_2021.parquet
#          (zone_id int32, datetime_hour tz-aware America/New_York [us], rain6h_mm float)
# Timezone: datetime_hour is tz-aware America/New_York; sorting on the tz-aware
#          value orders by true elapsed time (DST hours are distinct rows).
# Author: EK  Date: 2026-09-30
# ============================================================
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "clean_data" / "weather_zone_hour.parquet"
CELL_FILE = ROOT / "clean_data" / "od_weather_cells_2021" / "cells_2021-08.parquet"
OUT = ROOT / "clean_data" / "rain6h_zone_hour_2021.parquet"
NY = "America/New_York"

w = pd.read_parquet(SRC, columns=["pu_zone_id", "datetime_hour", "precip_mm"], engine="pyarrow")
assert str(w["datetime_hour"].dt.tz) == NY
lo, hi = pd.Timestamp("2020-12-31 00:00", tz=NY), pd.Timestamp("2022-01-02 00:00", tz=NY)
w = w[(w["datetime_hour"] >= lo) & (w["datetime_hour"] < hi)].sort_values(["pu_zone_id", "datetime_hour"]).reset_index(drop=True)
print(f"window rows {len(w):,}; zones {w['pu_zone_id'].nunique()}; rows/zone {w.groupby('pu_zone_id').size().unique()}")

# Complete consecutive hourly sequence per zone (NaN values allowed). Compare in UTC
# so DST hours count as true elapsed hours.
d = w.groupby("pu_zone_id")["datetime_hour"].diff().dropna()
assert (d == pd.Timedelta(hours=1)).all(), "gaps or duplicates in hourly index"
assert not w.duplicated(["pu_zone_id", "datetime_hour"]).any()

# Excludes the current hour (shift(1)) so it does not overlap the current-hour rain bins.
g = w.groupby("pu_zone_id")["precip_mm"]
w["rain6h_mm"] = g.shift(1).groupby(w["pu_zone_id"]).rolling(6, min_periods=5).sum().reset_index(level=0, drop=True)
# NB: sum of >=5 non-missing hours (missing hour counts as 0 in the sum).

keep_lo, keep_hi = pd.Timestamp("2021-01-01 00:00", tz=NY), pd.Timestamp("2022-01-01 12:00", tz=NY)
o = w[(w["datetime_hour"] >= keep_lo) & (w["datetime_hour"] < keep_hi)].copy()
unit = pq.read_schema(CELL_FILE).field("datetime_hour").type.unit
o = pd.DataFrame({"zone_id": o["pu_zone_id"].astype("int32"),
                  "datetime_hour": o["datetime_hour"].astype(f"datetime64[{unit}, {NY}]"),
                  "rain6h_mm": o["rain6h_mm"].astype("float32")})
if OUT.exists():
    print(f"WARNING: {OUT} exists - overwriting")
print(o.dtypes)
o.to_parquet(OUT, index=False, engine="pyarrow")

r = pd.read_parquet(OUT, engine="pyarrow")
x = r[r["datetime_hour"] < pd.Timestamp("2022-01-01", tz=NY)]
print(f"written {len(r):,} rows; zones {r['zone_id'].nunique()}; tz {r['datetime_hour'].dt.tz}; unit {unit}")
print(f"2021 NaN share {x['rain6h_mm'].isna().mean():.3%}; p99 {x['rain6h_mm'].quantile(.99):.1f}; max {x['rain6h_mm'].max():.1f}; "
      f"share>=0.1 {(x['rain6h_mm']>=0.1).mean():.3f}")
print(f"keys unique: {not r.duplicated(['zone_id','datetime_hour']).any()}")
