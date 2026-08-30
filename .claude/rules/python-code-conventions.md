# Python Code Conventions

**Python owns the whole build side of this project:** downloads, trip-level cleaning,
gridded-weather processing, spatial joins to taxi zones, and panel construction. It hands
R a collapsed `zone × hour` panel and nothing larger.

## Python Executable

**Always use the full venv path. Never use `python`, `python3`, or `py`.**

```bash
"Z:/ek559/nys_algal_bloom/NYS algal bloom/code2/Scripts/python.exe" script.py
# or inline:
"Z:/ek559/nys_algal_bloom/NYS algal bloom/code2/Scripts/python.exe" -c "import pandas; ..."
```

## Header Block (required on every script)

```python
# ============================================================
# Script: [name].py
# Purpose: [one-line description]
# Inputs: [files read]
# Outputs: [files written]
# Author: EK  Date: YYYY-MM-DD
# ============================================================
```

## Naming and Style

- Snake_case for all variable and function names
- Variable names must match the CLAUDE.md glossary exactly
- No hardcoded absolute paths — use `pathlib.Path` relative to the project root
- `random.seed()` / `np.random.seed()` required in any script using randomness
- Match the style of surrounding code

## Field Definitions — consult the dictionary, don't infer

`raw_data/HVFHV_Trip_Data_Data_Dictionary.xlsx` is the TLC's official field
documentation. Read it before assuming what a column means. Three traps it documents:

- `hvfhs_license_num` values are **four digits**: `HV0002` Juno, `HV0003` Uber,
  `HV0004` Via, `HV0005` Lyft. Filtering on `HV03` silently returns nothing.
- `on_scene_datetime` is **Accessible-Vehicles-only** and null for most trips. Build
  `wait_time` from `pickup_datetime − request_datetime`.
- `driver_pay` is already **net of commission, surcharges, and taxes**, and excludes
  tolls and tips — so `base_passenger_fare − driver_pay` is the platform's take.

Quote the relevant dictionary line in a comment wherever a definition drives a filter
or a constructed variable.

## Large-Data Discipline (the dominant constraint)

HVFHV monthly parquet is ~1 GB / ~20M rows. Never read one whole.

```python
# Push column selection and row filters into the read
cols = ["hvfhs_license_num", "request_datetime", "pickup_datetime", "dropoff_datetime",
        "PULocationID", "DOLocationID", "trip_miles", "trip_time",
        "base_passenger_fare", "driver_pay", "tolls", "shared_request_flag"]
df = pd.read_parquet(path, columns=cols, engine="pyarrow",
                     filters=[("pickup_datetime", ">=", start),
                              ("pickup_datetime", "<", end)])
```

- `duckdb` is preferred for the collapse step — it streams and avoids materializing the
  full month: `duckdb.sql("SELECT PULocationID, date_trunc('hour', pickup_datetime) ... FROM 'f.parquet' GROUP BY ALL")`
- Process month by month; never concatenate all of 2021 in memory
- Subset gridded weather to the NYC bounding box **during** the read, not after
  (`rioxarray.open_rasterio(...).rio.clip_box(...)` / `xarray.sel(lat=slice(...), lon=slice(...))`)
- Print row counts at each stage so a silent filter blowout is visible

## Timezone Rule (critical, project-specific)

- TLC trip timestamps are **local wall-clock, America/New_York**, with **no tz marker**.
- MRMS / Stage IV / HRRR / ASOS are **UTC**.
- Convert weather to America/New_York **once**, in `build_weather_panel.py`, and store
  only local time downstream:
  ```python
  ts_local = ts_utc.tz_localize("UTC").tz_convert("America/New_York")
  ```
- 1 September 2021 is EDT (UTC−4). A silent UTC/EDT mixup shifts the entire event window
  by 4 hours and will silently destroy the event-study estimates.
- Every script that touches a timestamp must state its timezone in a comment.
- When writing parquet, store `datetime_hour` as tz-aware `America/New_York` and verify
  it survives the round trip.

## Parquet I/O

- **Write:** `df.to_parquet(path, index=False, engine="pyarrow")`
- **Read:** `pd.read_parquet(path, engine="pyarrow")`
- Always specify `engine="pyarrow"` explicitly

**Cross-language schema rule (critical):** before writing any parquet an R script reads,
enforce types and drop geometry:

```python
# Enforce types
df["pu_zone_id"] = df["pu_zone_id"].astype("int32")
df["platform"]   = df["platform"].astype(str)
# datetime_hour must be tz-aware America/New_York, NOT naive and NOT UTC
assert str(df["datetime_hour"].dt.tz) == "America/New_York", "datetime_hour tz is wrong"

# Drop geometry if this is a GeoDataFrame
if hasattr(df, "geometry"):
    df = df.drop(columns="geometry")

# Log dtypes before write — catch silent mismatches
print(df.dtypes)

df.to_parquet(output_path, index=False, engine="pyarrow")
```

## Spatial Operations

- Log CRS before and after every spatial join:
  ```python
  print(f"Left CRS: {left_gdf.crs}")
  print(f"Right CRS: {right_gdf.crs}")
  assert left_gdf.crs == right_gdf.crs, "CRS mismatch — reproject before joining"
  ```
- Standard CRS for this project: **EPSG:4326** (WGS84) for storage and for weather grids;
  **EPSG:2263** (NY State Plane Long Island, ft) for NYC area/distance work. The TLC taxi
  zone shapefile ships in EPSG:2263 — reproject explicitly, don't assume.
- **Gridded weather → taxi zone** is an area-weighted zonal aggregation, not a centroid
  lookup. Use `rasterstats.zonal_stats` or an explicit intersection-area weighting; taxi
  zones vary by orders of magnitude in area and a centroid sample misrepresents the
  large outer-borough zones. State the method in a comment.
- **Point data → taxi zone** (311 complaints, gauges): `gpd.sjoin(..., predicate="within")`;
  report the count of points that fall in no zone rather than dropping them silently.

## Output and File Safety

- Write all outputs to `clean_data/`, never `raw_data/` — except downloads into the
  registered folders in `.claude/hooks/protect-raw-data.py`
- Check for existing output before writing:
  ```python
  if output_path.exists():
      print(f"WARNING: {output_path} already exists — overwriting")
  ```
- After writing, validate:
  ```python
  result = pd.read_parquet(output_path, engine="pyarrow")
  print(f"Written {len(result):,} rows x {result.shape[1]} columns to {output_path}")
  print(f"Date range: {result['datetime_hour'].min()} to {result['datetime_hour'].max()}")
  print(f"Zones: {result['pu_zone_id'].nunique()}")
  ```

## Downloads

- Resume-safe: skip files already present with the expected size; do not re-download
- Print the URL, target path, and byte count before starting
- Estimate total download size and report it **before** starting a multi-GB pull
- Record the source URL and access date in the script header
