# Plan: OD-cell weather panel + binned driver-share regression, 2021

**Implementer:** Sonnet. **Approved by user:** 2026-09-30.
Read `CLAUDE.md` and `.claude/rules/*.md` first. Python venv path, header blocks,
raw_data read-only, timezone and parquet rules all apply.

## Goal

Estimate how `driver_share` (= `driver_pay / base_passenger_fare`, trip level) responds
to binned rainfall and temperature at the **origin zone (pickup hour)** and the
**destination zone (dropoff hour)**. Use all 2021 HVFHV trips, collapsed to cells that
reproduce the trip-level OLS exactly.

### Estimating equation (R, fixest)

```
driver_share_c = Σ_b β_b 1[pu_precip_bin=b] + Σ_k γ_k 1[pu_temp_bin=k]
               + Σ_b δ_b 1[do_precip_bin=b] + Σ_k θ_k 1[do_temp_bin=k]
               | platform + pu_zone_id^pu_hod + do_zone_id^do_hod + month + dow
weights = n_trips
```
- Cell c = `platform × pu_zone_id × do_zone_id × datetime_hour × do_datetime_hour`.
- `pu_hod` = hour of day of the pickup; `do_hod` = hour of day of the dropoff.
- `month` (1–12) and `dow` (1–7) are both taken from the **pickup** date, local time.
- **The user's fixed-effect choice is final; do not change it.** It was revised on
  2026-09-30 from `doy + dow` to `month + dow`. The two are not collinear: every month
  contains every weekday. With no date FE, the weather β are identified from variation
  across days within a month as well as across zones and hours within a day. The table
  notes must say so.
- The weighted cell-mean regression is numerically identical to trip-level OLS because
  every regressor and FE is constant within a cell. State this in a comment.
- **Standard errors:** two-way clustered by `pu_zone_id` + `date`. Weather is mostly a
  citywide daily shock, so date clustering matters. Both cluster dimensions are unions
  of cells, so these SEs equal the trip-level clustered SEs.
- **Sign discipline:** no comment, note, or check may presume a direction for any β.

## Step 0 — Git (needs the user's answer before any code)

The branch `weather-grids-2019-2026` has uncommitted weather-build work. The user
decides whether to commit it first. Then create branch `od-weather-driver-share` and
work there.

## Step 1 — `code/build/build_od_weather_cells.py`

**Inputs**
- `raw_data/hvfhv/fhvhv_tripdata_2021-MM.parquet` (12 files, 174.6M raw rows)
- `clean_data/weather_zone_hour.parquet` (existing; **do not rebuild**). Schema:
  `pu_zone_id int32, datetime_hour ts[tz=America/New_York], precip_mm, temp_c,
  precip_cover_share, temp_cover_share, mrms_product`.

**Output:** `clean_data/od_weather_cells_2021/cells_2021-MM.parquet`, one file per
month, read in R as a dataset. Per-month files make the build resume-safe and keep
memory bounded. A month file that already exists is **skipped** unless `--force` is
passed.

**CLI:** `--months 08` (comma list; default all 12) and `--force`.

**Per-month logic (DuckDB, streaming; never pandas on the raw month):**

1. Read only the columns needed: `hvfhs_license_num, pickup_datetime,
   dropoff_datetime, PULocationID, DOLocationID, trip_miles, trip_time,
   base_passenger_fare, driver_pay, access_a_ride_flag`.
2. Apply the **same filter rules as `code/build/clean_hvfhv.py` `FILTER_RULES`**,
   written in SQL with a comment pointing to that list:
   - fare > 0 and ≤ 1000
   - miles > 0 and ≤ 100
   - trip_time > 60 and ≤ 21600
   - PU and DO zones ≤ 263
   - driver_pay > 0

   Also apply two more:
   - exclude `access_a_ride_flag = 'Y'`. MTA-administered paratransit is not
     market-priced (CLAUDE.md, "Sample cuts").
   - keep only pickups inside the file's own month, `[MM-01, next MM-01)`. This
     makes cells unique across files; trips that sit in the wrong file are dropped.

   Print the number of rows each rule drops, per month. Write
   `output/sum/od_cells_filter_attrition_2021.csv`, one row per month × rule.
3. Map `hvfhs_license_num` with `PLATFORM_MAP` (copy it from `clean_hvfhv.py`;
   HV0003 Uber, HV0004 Via, HV0005 Lyft; 4-digit codes).
4. Trip-level `driver_share = driver_pay / base_passenger_fare`. Quote the dictionary
   in a comment: driver_pay is "total driver pay, excl. tolls and tips, and net of
   commission, surcharges, and taxes". **Do not trim values > 1**: the TLC minimum-pay
   floor produces them on short, cheap trips, and they are part of the mechanism.
5. `datetime_hour = date_trunc('hour', pickup_datetime)` and
   `do_datetime_hour = date_trunc('hour', dropoff_datetime)`. Both are **naive local
   wall clock (America/New_York)**; TLC timestamps carry no tz marker. Say so in a
   comment.
6. GROUP BY `platform, pu_zone_id, do_zone_id, datetime_hour, do_datetime_hour`:
   - `n_trips` (int32)
   - `sum_driver_share`
   - `sum_fare` (Σ base_passenger_fare)
   - `sum_driver_pay`
   - `sum_trip_miles`
   - `sum_trip_time`

   Do **not** store a ratio of sums as the dependent variable: the trip-level estimand
   is the mean of ratios (`sum_driver_share / n_trips`). The sums are kept so a
   fare-weighted share (Σpay/Σfare) can be built later.
7. **Weather join, on naive wall-clock hours.** Build a lookup from
   `weather_zone_hour.parquet` (only the 2021-01-01 → 2022-01-01 06:00 local window;
   dropoffs spill past midnight on Dec 31):
   - convert `datetime_hour` to naive local wall clock (`tz_localize(None)` on the
     tz-aware value, **not** a UTC conversion);
   - **DST fall-back (2021-11-07 01:00):** two weather rows map to the same naive hour.
     Average them and print how many keys were collapsed (expect 263);
   - **DST spring-forward (2021-03-14 02:00):** this hour doesn't exist, so no weather
     row matches. Print the count of trips/cells with that pickup or dropoff hour (expect
     ≈0);
   - assert that the lookup key `(zone, naive_hour)` is unique.

   LEFT JOIN twice:
   - on `(pu_zone_id, datetime_hour)` → `pu_precip_mm, pu_temp_c`
   - on `(do_zone_id, do_datetime_hour)` → `do_precip_mm, do_temp_c`

   Keep the weather **continuous** in the file; binning happens in R so bin edges can
   change without a rebuild.
8. Add integer columns so R doesn't have to:
   - `pu_hod`, `do_hod` (int8)
   - `month` (int8, pickup date)
   - `dow` (int8, ISO 1=Mon, pickup date)
   - `doy` (int16, pickup date). Not in the main spec; stored so a date-FE robustness
     check needs no rebuild.
   - `date` (date32, pickup date)
9. Before writing:
   - localize `datetime_hour` and `do_datetime_hour` to tz-aware `America/New_York`
     with `ambiguous=False` (the Nov-7 01:00 hour is labelled EST) and
     `nonexistent="shift_forward"`. Never use `"NaT"`, which would silently null keys.
     Document both choices in a comment. Only those two hours are affected, and the
     integer FE columns are computed from the naive wall clock beforehand;
   - assert the tz is America/New_York;
   - cast ids to int32 and `platform` to str;
   - print dtypes;
   - write with `engine="pyarrow", index=False`.
10. Per-month verification, printed and appended to
    `output/sum/od_cells_build_log_2021.csv`:
    - raw rows, rows after filters, Σ`n_trips` (must equal rows after filters), cells;
    - key uniqueness on the 5-column key (assert);
    - NaN share of each weather column (expect ≈0.15%; flag if > 1%);
    - median trip-level driver share (≈ Σsum_driver_share/Σn_trips; expect 0.6–0.9).

**August check (the benchmark month):**
- ≈13.9M filtered trips and ≈9.0M cells (measured 2026-09-30 before the AAR and
  driver_pay filters; expect slightly fewer);
- the citywide max-`pu_precip_mm` hour must be **2021-09-01 21:00 EDT**. Run this on
  the September file; for August only, check that no hour exceeds Ida's 58 mm.

## Step 2 — `code/analysis/driver_share_weather_bins.r`

Source `code/analysis/fhv_reg.r` (for `wrap_for_beamer`).

**Arguments:** `commandArgs` → `months` (default all 12) and `tag` (e.g. `aug2021`,
`2021`), used in output names.

1. Load with `arrow::open_dataset("clean_data/od_weather_cells_2021")`, filter months,
   `select` only the needed columns, `collect()`. Run `str()`, then assert that
   `datetime_hour` has tzone America/New_York and that the ids are integer.
2. `driver_share = sum_driver_share / n_trips`.
3. Bins, defined as named constants at the top of the script. The edges come from the
   2021 zone-hour distribution: 92.5% of hours are dry; p95 0.52 mm, p99 3.6 mm,
   p99.9 13.7 mm.
   - Precipitation (mm/h), left-closed:
     `dry [0,0.1)` (**reference**), `[0.1,0.5)`, `[0.5,2)`, `[2,5)`, `[5,10)`,
     `[10,Inf)`. Use 0.1 rather than 0 because area-weighted MRMS gives tiny positive
     values.
   - Temperature (°C): `<0`, `[0,5)`, `[5,10)`, `[10,15)`, `[15,20)` (**reference**),
     `[20,25)`, `[25,30)`, `≥30`.
   - The same edges apply to `pu_` and `do_`.
4. Drop cells with NA weather and report how many (cells and trips).
5. Named formula:
   ```r
   fml_bins <- driver_share ~ i(pu_precip_bin, ref = "dry") + i(pu_temp_bin, ref = "[15,20)") + i(do_precip_bin, ref = "dry") + i(do_temp_bin, ref = "[15,20)") | platform + pu_zone_id^pu_hod + do_zone_id^do_hod + month + dow
   est <- feols(fml_bins, data = df, weights = ~n_trips, cluster = ~pu_zone_id + date,
                lean = TRUE, mem.clean = TRUE, nthreads = 16)
   ```
   Call `rm(df); gc()` before anything else heavy. **Run one model per R session.**
6. Outputs (suffix `_{tag}`):
   - `output/reg/driver_share_weather_bins_{tag}.tex`. Bare `etable()`, then
     `wrap_for_beamer()`. Notes must state:
     - the reference bins;
     - the clustering (pu_zone_id + date);
     - that weights = trips per cell, so estimates equal trip-level OLS;
     - the FEs;
     - that there is no date FE: identification includes variation across days
       within a month;
     - that AAR trips are excluded;
     - N cells and N trips.
   - `output/fig/driver_share_weather_bins_{tag}.png`: four facets (origin rain,
     origin temp, destination rain, destination temp). Point estimate ± 95% CI against
     bin order, with the reference bin plotted at 0. No gridlines, no title.
     `ggsave(width = 9, height = 6, dpi = 300)`.
   - `output/sum/driver_share_bin_counts_{tag}.csv`: trips and cells per bin for each
     of the four bin variables. Thin bins mean noisy coefficients, and the reader needs
     to see this.
   - `output/reg/driver_share_weather_bins_{tag}.rds`: `coeftable(est)` plus `nobs`
     and the timing. Save the coefficient table, not the model object.

## Step 3 — August benchmark: go/no-go gate (**stop and report to user**)

1. `build_od_weather_cells.py --months 08,09`. September is needed for the timezone
   peak-rainfall check.
2. Run the R script on **August only** (`months=8`, `tag=aug2021`), while measuring
   wall time and **peak memory** of the Rscript process. Poll from PowerShell every 5 s:
   ```powershell
   $p = Start-Process -FilePath "C:\Program Files\R\R-4.6.1\bin\Rscript.exe" -ArgumentList "--vanilla","code/analysis/driver_share_weather_bins.r","8","aug2021" -PassThru -NoNewWindow
   $peak = 0; while (-not $p.HasExited) { try { $p.Refresh(); $peak = [math]::Max($peak, $p.PeakWorkingSet64) } catch {}; Start-Sleep 5 }
   "peak_GB=$([math]::Round($peak/1GB,2))"
   ```
   Also log `system.time()` around `feols` inside the script.
3. **Identifying-variation check** (August only, cheap). Run
   `feols(c(pu_temp_c, pu_precip_mm) ~ 1 | <same FEs>, weights = ~n_trips)` and report
   1 − within-R² share: how much weather variance survives the FEs. The concern
   recorded on 2026-09-30 is that temperature varies little across zones within an
   hour. With `month + dow` there is no date FE, so day-to-day weather variation
   remains and this should be much less of a problem than under a date FE. Report the
   number; don't act on it. Note: in an August-only run the `month` FE has one level and
   does nothing, so the benchmark's identifying variation is close to, but not exactly,
   the full-year version.
4. **Projection:** full year ≈ 12× August in cells (August 9.0M → 2021 ≈ 108M).
   Scale time linearly. For memory, scale the X-related part linearly and add the
   fixed overhead.
5. **Stop and report to the user:**
   - August cells and trips, peak GB, wall time;
   - projected full-year time and memory;
   - projected size of the full cell files on disk (expect 3–5 GB, over the 500 MB
     threshold, so it needs explicit approval);
   - the identifying-variation numbers;
   - the August coefficient table/figure paths.

   Go criteria to propose: projected peak < 90 GB (machine has 128 GB, ~100 GB free)
   and projected time < 3 h. If either fails, propose this fallback for the user to
   choose: 3-hour blocks in place of hour of day in the two zone × hour FEs. Weather
   stays hourly. **Do not change the FE spec without the user's approval.**

## Step 4 — Full year (only after the user approves Step 3)

1. `build_od_weather_cells.py` (all months; Aug/Sep files are skipped as they already
   exist). Estimate ~2 min/month.
2. Check:
   - each month's Σn_trips is 11–17M;
   - the 2021 total is ≈ the raw 174.6M minus the filters;
   - key uniqueness per file.
3. Run the R script with `tag=2021`, using the same peak-memory polling.
4. Verify:
   - outputs exist;
   - the `.tex` notes contain the clustering, reference bins, and N;
   - flag **implausible magnitudes only** (e.g. |β| > 0.2 on a share whose median is
     ~0.75), never signs.

## Step 5 — Close out

- Score the work against `quality-gates.md`. Python 90 and R 90 are expected (header,
  tz asserts, dtypes printed, validated after write).
- Log to `.claude/logs/2026-09-30-od-weather-driver-share.md`: decisions (cell
  definition, AAR exclusion, bin edges, DST handling, clustering), benchmark numbers,
  and results paths.
- Offer `/commit`; do not commit unprompted.

## Decision points: stop and ask

- The Step 3 gate (always).
- Any fix loop that hits 3 iterations.
- Σn_trips ≠ filtered rows, duplicate keys, or a weather NaN share > 1%.
- The September peak-rain hour is not 2021-09-01 21:00 EDT.
- Any existing file in `clean_data/` (other than the new cell folder) would be
  overwritten.

## Revision 2026-09-30 (user, after August benchmark)

1. **Keep trips ending outside NYC (DO zone 265, ~3.8% of trips).** Drop only DO 264
   ("Unknown", 1 trip/month) and PU ≥ 264. These trips have no destination weather.
   Give them a destination-rain level `outside_nyc`. It is absorbed by the
   `do_zone_id^do_hod` FE for zone 265 (fixest drops it as collinear), so these trips
   identify only the origin-rain coefficients. Exclude zone 265 from the weather NaN
   gate. Rebuild Aug/Sep with `--force` (the user approved the change).
2. **No temperature bins** in the regression. temp_c stays in the cell files, unused.
3. **Finer rain bins (mm/h, left-closed):** dry [0,0.1) = **reference**, [0.1,0.25),
   [0.25,0.5), [0.5,1), [1,2), [2,4), [4,6), [6,10), [10,15), [15,25), [25,40), ≥40.
   In Aug+Sep the top two bins span only 4 storm-days each.
4. **Next run:** build the remaining 10 months, then Aug+Sep regression with peak-memory
   measurement → full-year projection → stop for user.

## Revision 2 (user, 2026-09-30 night)

1. Keep the 11 current-hour rain bins (ref = dry).
2. **Add bins for rain over the previous 6 hours** at origin and destination. The window
   is hours t−6…t−1 and excludes the current hour, so it doesn't overlap the
   current-hour bins.
   - Computed on true elapsed time (tz-aware), as a sum of non-missing hours when at
     least 5 of the 6 are present; NaN otherwise.
   - Bins (mm, left-closed): dry [0,0.1) = ref, [0.1,0.5), [0.5,1), [1,2), [2,5),
     [5,10), [10,20), [20,35), [35,50), [50,75), ≥75.
   - 2021 zone-hours: 16% have ≥0.1 mm; ≥75 mm spans 7 days; NaN 0.6%. The correlation
     with current-hour rain is 0.36.
   - Built as a separate small lookup, `clean_data/rain6h_zone_hour_2021.parquet`
     (`code/build/build_rain6h_lookup.py`), joined in R on the tz-aware timestamps.
     The cell files are NOT rebuilt.
3. **Memory option 1:** trim the data before `feols`. It must not change any estimate.
4. Stars: `signif.code = c("***"=0.01, "**"=0.05, "*"=0.10)` (project convention).
5. Not adopted: named-storm indicators, wind, temperature.
6. The DST 02:xx Mar-14 trips (68) stay in the cells and drop in R via NA weather. The
   July NaN check stays a warning. Neither was decided by the user; leave as is.

## Revision 3 (user, 2026-10-01): batched FWL estimator

Spec B (11+11 current-hour + 10+10 six-hour bins, the same FEs, cluster pu_zone_id + date)
projects to 122 GB in feols. Replace the full-year fit with an exact batched
Frisch–Waugh–Lovell estimator.

**User's success criterion:** coefficients, standard errors and significance identical
to what the same `feols` call would produce. Operationally:
- relative difference < 1e-6 on every coefficient and SE;
- absolute difference < 1e-6 on p-values;
- identical stars;
- identical N.

It must hold on Aug+Sep spec B, Aug+Sep spec A, and Aug-only spec B, all against
`feols` with identical options.

Mechanics:
1. **Singletons:** remove them exactly as feols does, iteratively across all FE
   dimensions.
2. **Demeaning:** `fixest::demean` (weights = n_trips, same FEs, same `fixef.tol` /
   `fixef.iter` as the feols default) on y and on the 42 dummy columns in batches.
   Store the demeaned columns, about 35 GB for the full year.
3. **Coefficients:** β from chunked X̃'WX̃ and X̃'Wỹ.
4. **Clustered vcov:** two-way, from chunked per-cluster score sums. It must reproduce
   fixest's default `ssc()` exactly: adj, `fixef.K = "nested"`, `cluster.adj`,
   `cluster.df = "min"`, `t.df = "min"`. It must also reproduce the
   non-positive-definite fix. Read the fixest source rather than guessing.
5. **Table:** a hand-built `.tex` in etable style + `wrap_for_beamer`, with the same
   notes.

Then the full year, if the Aug+Sep peak memory projects to under 85 GB.

## Revision 4 (user, 2026-10-01): fare vs pay decomposition

Run the same spec B regression (same bins, FEs, weights, clustering, NA drops, batched
FWL) with three trip-level dependent variables:
- `log_fare` = mean over the cell's trips of log(base_passenger_fare);
- `log_pay` = mean of log(driver_pay);
- `log_share` = mean of log(driver_pay / base_passenger_fare).

By linearity β_log_share = β_log_pay − β_log_fare exactly, which gives an exact
decomposition of which side moves. The current cells lack Σlog columns, so rebuild into a
NEW folder `clean_data/od_weather_cells_2021_v2/`, identical plus `sum_log_fare` and
`sum_log_pay`. The original folder is untouched.

Make the FWL multi-outcome: demean X once and the y's together. Validate against
`feols(c(...))` on Aug+Sep with the same criterion as Revision 3.

## Revision 5 (user, 2026-10-01): per-mile prices and OD-pair FE

Goal: separate price changes from trip-length composition.
- Cells v3: `clean_data/od_weather_cells_2021_v3/` = v2 + `sum_log_miles`,
  `sum_log_time` (new folder; v1/v2 untouched).
- **Run P** (same FEs as spec B). Outcomes: log_fare_per_mile, log_pay_per_mile,
  log_fare_per_min, log_pay_per_min, log_miles, log_minutes.
  Exact identities: β(log fare/mile) = β(log fare) − β(log miles), etc.
- **Run OD** (spec B FEs + `pu_zone_id^do_zone_id`). Outcomes: driver_share, log_share,
  log_fare, log_pay, log_fare_per_mile, log_pay_per_mile, log_miles, log_minutes.
  This compares the same route across weather conditions.
- Same bins, weights, clustering (pickup zone + date), NA drops, batched FWL. Validate
  each against feols on Aug+Sep with the Revision 3 criterion.
