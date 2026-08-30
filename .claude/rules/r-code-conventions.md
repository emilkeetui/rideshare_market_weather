# R Code Conventions

**R's role in this project is estimation only** — regressions, tables, figures. All data
acquisition, cleaning, geospatial work, and panel construction happens in Python. R reads
the collapsed `zone × hour` panel, never trip-level data.

R is at `C:\Program Files\R\R-4.6.1\bin\Rscript.exe`.

## Header Block (required on every script)

```r
# ============================================================
# Script: [name].r
# Purpose: [one-line description]
# Inputs: [files read]
# Outputs: [files written]
# Author: EK  Date: YYYY-MM-DD
# ============================================================
```

## Naming and Style

- Snake_case for all object and variable names — no camelCase
- Variable names must match the CLAUDE.md glossary exactly (e.g., `fare_per_mile`,
  not `avg_fare_mi`; `precip_max_mm`, not `maxrain`)
- No hardcoded absolute paths — use paths relative to the project root
- `set.seed()` required in any script that uses randomness (bootstrap SEs, permutation tests)
- Match the style of surrounding code — indentation, spacing, naming patterns

## Parquet I/O

- **Read:** `arrow::read_parquet(path)` for the collapsed panel
- **Large files:** `arrow::open_dataset(path) |> filter(...) |> select(...) |> collect()` —
  never read a trip-level file into memory whole
- **Write:** `arrow::write_parquet(df, path)`
- Never use `read_csv()` / `write_csv()` for main analysis datasets
- Small R-only objects (fitted model lists, etc.): `.rds` via `saveRDS()` / `readRDS()`

**Cross-language schema check:** when reading a parquet written by a Python script,
immediately confirm types after loading:
```r
df <- arrow::read_parquet("clean_data/zone_hour_panel.parquet")
str(df)
# pu_zone_id     must be <int>
# datetime_hour  must be POSIXct with tzone = "America/New_York"
# platform       must be <chr>
```
If `datetime_hour` comes back in UTC, every hour-of-day fixed effect and the entire event
window are shifted by 4 hours. Stop and fix the Python writer before proceeding.

## Timezone Rule

All timestamps in the analysis panel are **America/New_York** (EDT, UTC−4, during the
Ida window). Never call `as.POSIXct()` without an explicit `tz =` argument — R will
silently use the machine locale. State the timezone in a comment wherever a timestamp
is parsed or an hour-of-day variable is constructed.

## Regression Style

- Keep `feols()` formula objects named for reuse:
  ```r
  fml_did <- n_trips ~ affected:post_ida | pu_zone_id + datetime_hour
  fml_es  <- n_trips ~ i(event_hour, affected, ref = -1) | pu_zone_id + datetime_hour
  ```
- Line-length exceptions for regression formulas — long formulas need no line breaks
- SEs clustered at the taxi-zone level: `cluster = ~ pu_zone_id`.
  Consider two-way `cluster = ~ pu_zone_id + date` and report which is used.
- Always use `fixest::feols()`; never `lm()` for panel regressions
- Event studies use `fixest::i()` with an explicit reference period (`ref = -1`), and
  the reference period must be stated in the table/figure notes
- **Report the event study before the single-coefficient DiD.** A pre-landfall spike in
  price or volume is a prediction of this project's theory, not a mechanical
  parallel-trends failure — but it must be shown, not absorbed into `post_ida`.

## Sign Discipline

Do not write code, comments, or table notes that presume the revenue effect is positive.
Both directions are live hypotheses. Sanity checks should flag *implausible magnitudes*,
not unexpected signs.

## Output

- Regression tables to `output/reg/*.tex` via `etable()` or `modelsummary()`
- Figures to `output/fig/*.png` — publication-ready, no titles unless necessary,
  informative axis labels, no gridlines on coefficient plots
- Summary statistics to `output/sum/*.tex`
- Maps of taxi zones: `sf` + `ggplot2::geom_sf()`, saved with explicit `width`/`height`/`dpi`

## Beamer-Compatible Tables

Define `wrap_for_beamer(path)` once in `code/analysis/fhv_reg.r` and source it from any
script generating `.tex` tables. See CLAUDE.md for the full adjustbox/float nesting rules —
in short: `wrap_for_beamer()` is only for bare-tabular `etable()` output, and never for a
file that already contains `\begin{table}`.
