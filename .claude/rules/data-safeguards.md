# Data Safeguards

**raw_data/ is strictly read-only. Violations are blocked by the protect-raw-data hook.**

## raw_data/ Rules

- Never write, modify, overwrite, or delete any file in `raw_data/`
- Never run `rm`, `unlink()`, `file.remove()`, or any destructive operation on `raw_data/`
- Never use `>` redirection into `raw_data/`
- All cleaning and transformation outputs go to `clean_data/`

**Download exception.** This project acquires nearly all of its raw data by download, so
NEW files may be written into the registered download folders listed in
`.claude/hooks/protect-raw-data.py` (`raw_data/hvfhv`, `raw_data/taxi_zones`,
`raw_data/weather`, `raw_data/flooding`, `raw_data/chicago_tnp`, `raw_data/subway`).
Destructive operations are blocked there too. To add a new download target, add it to
`EXEMPT_DIRS` in the hook and say so — do not work around the hook.

The `protect-raw-data.py` hook hard-blocks (exit 2) any other attempt.

## Before Writing Any Intermediate File

1. Check whether the file already exists at the output path
2. If it exists: stop and ask the user whether to overwrite, and explain what will change
3. Only overwrite if the user explicitly confirms

**Exception:** if important changes to a build script mean downstream scripts need the
new version to run correctly, flag this and propose the overwrite with a diff summary.

## Before Loading Large Files — this project's dominant risk

The HVFHV trip data is ~1 GB per month and ~20M rows per month. A careless
`arrow::read_parquet()` on a full month will exhaust memory.

- **Never** load a monthly HVFHV parquet unfiltered. Push filters into the scan:
  - Python: `pd.read_parquet(path, columns=[...], filters=[...], engine="pyarrow")`
    or `duckdb.sql("SELECT ... FROM 'file.parquet' WHERE ...")`
  - R: `arrow::open_dataset(path) |> filter(...) |> select(...) |> collect()`
- Check size before reading: `os.path.getsize()` in Python, `file.info()$size` in R.
  Flag anything > 100 MB before loading into memory.
- Flag if an operation will produce output > 500 MB.
- **Gridded weather (MRMS, Stage IV, HRRR):** subset to the NYC bounding box during the
  download/read step, never after. A single storm-day of native-resolution MRMS is many GB.
- Collapse to `zone × hour` in Python. R should almost never touch trip-level data.

## Pipeline Output Paths

| Step | Script | Output |
|------|--------|--------|
| 1 | `code/build/download_hvfhv.py` | `raw_data/hvfhv/fhvhv_tripdata_2021-MM.parquet` |
| 2 | `code/build/clean_hvfhv.py` | `clean_data/hvfhv_trips_2021.parquet` |
| 3 | `code/build/build_weather_panel.py` | `clean_data/weather_zone_hour.parquet` |
| 4 | `code/build/build_flood_exposure.py` | `clean_data/weather_zone_hour.parquet` (flood cols) |
| 5 | `code/build/build_zone_hour_panel.py` | `clean_data/zone_hour_panel.parquet` **(main dataset)** |
| 6 | `code/build/build_chicago_panel.py` | `clean_data/chicago_tract_hour_panel.parquet` |
| 7 | `code/analysis/did_ida.r`, `did_chicago.r` | `output/reg/*.tex`, `output/fig/*.png` |
