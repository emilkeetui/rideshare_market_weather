# Verification Protocol

**Never mark a task "done" without having run the code and confirmed expected output.**

## After Editing an R Script

1. Run end-to-end:
   ```bash
   "C:/Program Files/R/R-4.6.1/bin/Rscript.exe" --vanilla code/analysis/<script>.r
   ```
2. Confirm the script exits 0 (no error message)
3. Confirm expected output file exists (`.tex` in `output/reg/`, `.png` in `output/fig/`)
4. For regression scripts: spot-check one coefficient — verify the **magnitude** is
   economically plausible. Do NOT flag a coefficient merely for having an unexpected sign;
   both directions of the revenue effect are live hypotheses in this project.

## After Editing a Python Script

1. Run with the full venv path:
   ```bash
   "Z:/ek559/nys_algal_bloom/NYS algal bloom/code2/Scripts/python.exe" code/build/<script>.py
   ```
2. Confirm exit 0
3. Confirm parquet output exists in `clean_data/`
4. Check the printed row count — flag if 0 or suspiciously small
5. If the output is consumed by R: load it in R and run `str(df)` to confirm
   `datetime_hour` is POSIXct with `tzone = "America/New_York"` and `pu_zone_id` is integer

## Panel-Construction Sanity Checks (run after every rebuild of `zone_hour_panel.parquet`)

- **Coverage:** ~262 usable taxi zones × 24 h × N days. A zone-hour count far below
  `n_zones × n_hours` means the panel is unbalanced — decide explicitly whether zero-trip
  hours should be present as zeros or absent, and document the choice.
- **Timezone:** the maximum-rainfall hour in the panel falls on the evening of
  2021-09-01 **local time**. If it lands in the early hours of 2021-09-02, the weather
  merge is off by the UTC offset — stop and fix.
- **Fare plausibility:** median `fare_per_mile` in a normal pre-storm hour is a few
  dollars. A value near zero or in the hundreds means a unit or filter error.
- **Driver share:** `driver_share` should sit broadly in the 0.6–0.9 range. Values > 1 or
  < 0.2 en masse indicate the fare/pay columns are misaligned.
- **No duplicate keys:** `(pu_zone_id, datetime_hour, platform)` must be unique.
- **Trip totals:** the monthly trip count should be on the order of 15–25M. An order of
  magnitude off means a filter dropped or duplicated data.

## After Generating a LaTeX Table

1. Visually inspect the `.tex` — confirm column headers match the intended sample/design
2. Confirm the sample size N in the footnote is plausible
3. Confirm the clustering level and the event-study reference period are stated in the notes
4. If embedded in a paper: compile and confirm no `??` references

## Hard Gates (block completion if any fail)

- Script exits with non-zero code → must fix before marking done
- Output file does not exist → must fix before marking done
- Output row count is 0 → must investigate and fix
- `datetime_hour` loads in R as UTC or timezone-naive → must fix the Python writer
- Peak-rainfall hour in the panel does not fall on the evening of 2021-09-01 local time
  → weather merge is wrong; must fix
- Duplicate `(pu_zone_id, datetime_hour, platform)` keys → must fix

## Econometric Sanity Checks

After generating DiD / event-study output:
- The **event study is reported before** any single-coefficient DiD, with an explicit
  reference period.
- Pre-period leads are shown, not hidden. A pre-landfall spike is a substantive finding
  (anticipatory demand), and it must be modeled explicitly rather than absorbed into
  `post_ida` — say so in the write-up.
- Continuous-exposure and binary-`affected` versions give the same qualitative story; if
  they diverge, investigate the tercile cut before reporting either.
- Placebo events (Tropical Storm Henri, 2021-08-21/22; matched non-storm weeks) show
  substantially smaller effects.
- Report **volume, price, and revenue together.** Revenue is the product of the first two;
  a revenue result presented without its decomposition is incomplete.
- Keep **transfers** (higher fares paid on trips that still happened) separate from
  **deadweight loss** (foregone trips) and from **driver risk compensation** in every
  welfare statement. Never sum them into a single "consumer loss" number.
