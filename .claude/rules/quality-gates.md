# Quality Gates

| Score | Gate | Meaning |
|-------|------|---------|
| 80 | Commit | Runs correctly, structurally sound |
| 90 | Peer-review ready | Clean, reproducible, matches spec |
| 95 | Excellence | Aspirational; minimal reviewer friction |

## R Scripts — Threshold Criteria

**80 (commit):**
- Runs end-to-end without error
- Header block present and complete
- No hardcoded absolute paths
- Parquet I/O uses `arrow::read_parquet()` / `arrow::open_dataset()`
- Variable names match CLAUDE.md glossary
- Panel regressions use `fixest::feols()` with zone and time FE, clustered SEs

**90 (peer-review ready):**
- All of the above, plus:
- Cross-language schema check present (`datetime_hour` tz-aware America/New_York)
- Event study reported with an explicit reference period, before any single-coefficient DiD
- `feols()` formula objects named and reusable
- Clustering level stated in table notes
- Non-obvious steps have comments
- Output files (tables, figures) exist and are non-trivially non-zero

## Python Scripts — Threshold Criteria

**80 (commit):**
- Runs end-to-end without error using the full venv path
- Header block present and complete
- All outputs go to `clean_data/`; `raw_data/` writes only in registered download folders
- Parquet writes use `engine="pyarrow"`, `index=False`
- Column selection and row filters pushed into the parquet read — no unfiltered
  full-month HVFHV load
- Timestamps handled with an explicit timezone

**90 (peer-review ready):**
- All of the above, plus:
- UTC → America/New_York conversion done once, at the documented boundary, and asserted
- CRS logged and asserted before every spatial join
- Gridded weather aggregated to zones by area weighting, not centroid sampling, with the
  method stated in a comment
- `df.dtypes` printed before final parquet write
- Output row count, date range, and zone count validated after write
- Existing output file warned before overwrite
- Downloads are resume-safe and report size before starting

## Analysis Panels — Threshold Criteria

**80:**
- `(pu_zone_id, datetime_hour, platform)` keys are unique
- Date range and zone coverage match the requested window
- No NaN in key columns

**90:**
- Peak rainfall lands on the evening of 2021-09-01 local time (timezone verified)
- Zero-trip zone-hours handled explicitly (present as zeros or documented as absent)
- `fare_per_mile` and `driver_share` medians in plausible ranges
- Trip totals within an order of magnitude of the published TLC monthly counts

## LaTeX Tables — Threshold Criteria

**80 (commit):**
- Column headers identify the design and sample cut
- Sample size footnote present with plausible N
- No `\undefined` or `??` references
- Coefficient cells are non-trivially non-zero

**90 (peer-review ready):**
- All of the above, plus:
- Clustering level and event-study reference period stated in the notes
- Volume, price, and revenue outcomes reported together
- Stars legend correct (*** p<0.01, ** p<0.05, * p<0.1)
- Table compiles without errors or overfull hboxes
