---
name: data-analysis
description: End-to-end R analysis workflow for this project — load zone_hour_panel.parquet, explore, run fixest DiD and event-study regressions, produce publication-ready LaTeX tables and PNG figures.
argument-hint: "[analysis goal or 'zone_hour_panel' for main dataset]"
allowed-tools: ["Read", "Grep", "Glob", "Write", "Edit", "Bash", "Task"]
---

# Data Analysis Workflow

End-to-end analysis in R: load the collapsed panel, explore, run DiD / event-study
regressions with `fixest`, and produce publication-ready output.

**Input:** `$ARGUMENTS` — an analysis goal (e.g. "event study for fare_per_mile, flooded
zones") or a dataset path (e.g. `clean_data/zone_hour_panel.parquet`).

---

## Constraints

- Follow `.claude/rules/r-code-conventions.md` at all times
- Use `arrow::read_parquet()` to load the collapsed panel — never `read_csv()`
- **R must not touch trip-level data.** If the analysis needs a variable that isn't in the
  panel, that's a change to `code/build/build_zone_hour_panel.py`, not an R-side workaround.
- All analysis scripts go in `code/analysis/`
- All outputs: tables → `output/reg/*.tex`; figures → `output/fig/*.png`
- Run `/review-r` on the generated script before presenting results

---

## Workflow Phases

### Phase 1: Setup

1. Read `.claude/rules/r-code-conventions.md`
2. Read `CLAUDE.md` — confirm variable names, the three designs, and the sign discipline
3. Create the script with a header block (name, purpose, inputs, outputs, author, date)
4. Load packages: `arrow`, `fixest`, `ggplot2`, `dplyr`, `data.table`, `sf` (for maps)
5. Load the panel and check the schema — the timezone check is not optional:

```r
df <- arrow::read_parquet("clean_data/zone_hour_panel.parquet")
str(df)
stopifnot(attr(df$datetime_hour, "tzone") == "America/New_York")
```

### Phase 2: Exploratory Check

- Summary statistics on volume, price, and revenue outcomes
- Zone coverage and date range; confirm the analysis window (2021-08-15 to 2021-09-15)
- Confirm `(pu_zone_id, datetime_hour, platform)` keys are unique
- Plot the raw citywide time series of `n_trips`, `fare_per_mile`, and
  `revenue_passenger` around landfall **before running any regression** — the descriptive
  picture should be legible on its own
- Confirm peak `precip_mm` falls on the evening of 2021-09-01 local time
- Check for zero-trip zone-hours and decide explicitly how they are handled

### Phase 3: Regression

**Always run the event study first, then the summary DiD.**

```r
# Event study (primary) — explicit reference period, one hour before landfall
es <- feols(n_trips ~ i(event_hour, affected, ref = -1) | pu_zone_id + datetime_hour,
            data = df_sub, cluster = ~ pu_zone_id)

# Continuous-exposure event study (preferred over binary `affected`)
es_cont <- feols(n_trips ~ i(event_hour, precip_max_mm, ref = -1) | pu_zone_id + datetime_hour,
                 data = df_sub, cluster = ~ pu_zone_id)

# Summary DiD
did <- feols(n_trips ~ affected:post_ida | pu_zone_id + datetime_hour,
             data = df_sub, cluster = ~ pu_zone_id)

# Price on the OD-pair panel — the cleanest price comparison. Same route, before vs.
# during, so trip composition is absorbed rather than controlled for.
did_p <- feols(log(fare_per_trip) ~ affected:post_ida | pu_zone_id^do_zone_id + datetime_hour,
               data = df_od, cluster = ~ pu_zone_id)
```

Run the same specification across the **three outcome families together** — volume
(`n_trips`), price (`fare_per_mile`, `fare_per_minute`), and revenue (`revenue_passenger`,
`revenue_driver`, `platform_margin`). Revenue is the product of the first two; reporting
it alone is incomplete.

Apply the sample cuts in CLAUDE.md (with/without airport zones; Manhattan vs. outer
boroughs; platform-specific if `platform` variation is being used).

### Phase 4: Output

**Tables:**
```r
etable(es, did,
       file = "output/reg/[table_name].tex",
       tex = TRUE,
       notes = paste("SEs clustered at the taxi-zone level. Event-study reference period:",
                     "one hour before landfall (event_hour = -1). N = XX."))
```
Notes must state the clustering level and the reference period.

**Figures:**
```r
ggsave("output/fig/[fig_name].png", plot = p,
       width = 7, height = 5, dpi = 300, bg = "white")
```
Event-study coefficient plots need a visible zero line and a marked landfall hour.

### Phase 5: Review

Run `/review-r` on the generated script. Address all Critical issues before presenting.

---

## Sanity Checks Before Reporting

- Peak rainfall in the panel lands on the evening of 2021-09-01 **local** time
- Pre-period leads are plotted, not suppressed. A pre-landfall spike in price or volume
  is a prediction of the project's theory (anticipatory demand) — report it as a finding
  and model it explicitly rather than absorbing it into `post_ida`.
- Continuous-exposure and binary-`affected` results tell the same qualitative story;
  if not, investigate the tercile cut before reporting either
- Placebo windows (Tropical Storm Henri, 2021-08-21/22; matched calm weeks) show
  substantially smaller effects
- Magnitudes are economically plausible (a 40× price swing is a bug, not a finding)
- **Do not flag a coefficient for its sign.** Whether prices rose enough to offset the
  volume loss is the open empirical question — not an assumption to check the code against.
- Welfare statements keep transfers, deadweight loss, and driver risk compensation separate
