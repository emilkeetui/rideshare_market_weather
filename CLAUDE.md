# CLAUDE.md — Ride-share adaptation to extreme weather (NYC, Hurricane Ida)

## Project Overview

This project measures how much ride-share firms (Uber, Lyft, Via, Juno) and their
consumers can adapt to extreme weather events. The climate-adaptation literature asks
how much firms and consumers can mitigate the welfare cost of climate change and extreme
weather; this project answers that question in the market for high-volume for-hire
vehicle (HVFHV) trips in New York City, starting with **Hurricane Ida (landfall remnants
over NYC, 1 September 2021)**.

**Core question:** During an extreme weather event, does the ride-share platform preserve
or increase revenue through price adjustment, and what happens to consumer surplus?

**Theoretical priors (to be tested, not assumed):**
- **Pre-event:** demand to leave affected areas rises shortly before landfall → prices rise
  → driver supply follows demand.
- **During event:** demand falls; prices must rise sharply to compensate drivers for risk
  and for degraded road conditions. Whether revenue rises or falls depends on whether the
  price increase offsets the volume decline (i.e., on the elasticity of the realized
  demand curve conditional on the supply shift).
- **Post-event:** recovery path in volume and price; possible persistent displacement in
  flooded areas.

Both signs on revenue are live hypotheses. Do not write code, tables, or prose that
presumes a positive revenue effect.

---

## Empirical Strategy (three designs, in order of ambition)

### Design 1 — Within-city, spatial DiD (primary)
Compare NYC taxi zones **inside** the Ida-affected footprint (heavy rainfall / flash
flooding / basement-flooding reports) to zones **outside** the footprint but still within
NYC, before vs. after landfall.

```
Y_zt = β (Affected_z × Post_t) + η_z + τ_t + ε_zt
```

- Unit: **taxi zone × hour** (aggregate up to zone × day for slower-moving outcomes)
- Treatment intensity: continuous (mm of rain, peak wind, flood-report density) preferred
  over a binary affected/not indicator — the storm footprint is not sharp.
- FE: zone + time (date × hour), or zone + date and hour-of-week.
- SEs: clustered at the **taxi zone** level; consider two-way zone × date clustering.

### Design 2 — Simple before/after in affected zones
Earnings and volume in affected zones, one week before vs. one week after landfall.
Weakest design (no control for citywide time shocks) — report as a descriptive
benchmark, never as the headline causal estimate.

### Design 3 — Cross-city DiD (NYC treated, Chicago control)
Chicago publishes Transportation Network Provider (TNP) trip records with fares. If the
Chicago data covers 2021 at sufficient granularity, run:

```
Y_ct = β (NYC_c × Post_t) + η_c + τ_t + ε_ct
```

**Known constraint:** NYC HVFHV records report `base_passenger_fare` and driver pay for
every trip; Chicago TNP reports fare **rounded/binned** and at coarser geography (census
tract, and pickup times rounded to 15 minutes). Confirm comparability before promising
this design. Chicago is a plausible control only for *volume* and *rough* fare levels,
not for precise price series.

### Event-study form (required for all DiD designs)
Report the dynamic version with leads and lags in event time (hours or days relative to
landfall) before any single-coefficient DiD. Pre-event leads are the parallel-trends test
**and** are economically interesting here — the pre-landfall demand spike is a prediction
of the theory, not a violation of the design. Interpret pre-trends carefully: an
anticipatory price/volume spike is anticipation, not a failed design, but it must be
modeled explicitly rather than absorbed into "Post".

---

## Directory Structure

```
fhv_extreme_weather/
├── raw_data/                    # Source data, READ-ONLY
│   ├── hvfhv/                   # NYC TLC High Volume FHV trip records (parquet, monthly)
│   ├── taxi_zones/              # TLC taxi zone shapefile + zone lookup CSV
│   ├── weather/
│   │   ├── mrms/                # NOAA MRMS QPE — 1 km, 2-min/hourly radar rainfall
│   │   ├── stage_iv/            # NCEP Stage IV — 4 km hourly gauge-adjusted precip
│   │   ├── asos/                # ASOS/METAR station obs (KNYC, KLGA, KJFK, KEWR) — wind, precip
│   │   ├── nysm/                # NY State Mesonet (if NYC-metro stations available)
│   │   └── hrrr/                # HRRR analysis — 3 km hourly wind (if needed)
│   ├── flooding/
│   │   ├── nyc311/              # NYC 311 flooding / catch-basin / sewer complaints
│   │   ├── fema_nfhl/           # FEMA flood hazard layer (floodplain exposure)
│   │   └── usgs_gauges/         # USGS stream/tide gauge stage during Ida
│   ├── chicago_tnp/             # Chicago TNP trip records (control city, Design 3)
│   └── subway/                  # MTA turnstile / ridership (substitute mode control)
│       └── mta_alerts/          # MTA service alerts, NYCT Subway + Bus, 2020-04 on (date is UTC!)
│
├── clean_data/                  # Intermediate pipeline outputs
│   ├── hvfhv_trips_2021.parquet         # cleaned trip-level records, 2021
│   ├── zone_hour_panel.parquet          # MAIN ANALYSIS DATASET: zone × hour
│   ├── zone_day_panel.parquet           # zone × day aggregate
│   ├── weather_zone_hour.parquet        # zone × hour rainfall/wind/flood exposure
│   └── chicago_tract_hour_panel.parquet # Chicago control panel (Design 3)
│
├── code/
│   ├── build/                   # Data construction (Python)
│   │   ├── download_hvfhv.py            # step 1: pull 2021 TLC parquet files
│   │   ├── clean_hvfhv.py               # step 2: trip-level cleaning, fare/pay filters
│   │   ├── build_weather_panel.py       # step 3: gridded weather → taxi zone × hour
│   │   ├── build_flood_exposure.py      # step 4: 311 + FEMA + gauges → zone exposure
│   │   ├── build_zone_hour_panel.py     # step 5: collapse trips → zone × hour + merge weather
│   │   └── build_chicago_panel.py       # step 6: Chicago control panel
│   └── analysis/                # Estimation (R)
│       ├── descriptives.r               # price/volume time series, maps
│       ├── did_ida.r                    # main within-city DiD + event study
│       ├── did_chicago.r                # cross-city DiD
│       ├── welfare.r                    # consumer surplus / incidence calculations
│       └── fhv_reg.r                    # shared regression utilities
│
└── output/
    ├── fig/                     # .png figures
    ├── reg/                     # regression .tex tables
    └── sum/                     # summary stat .tex tables
```

---

## Data Sources

### Primary: NYC TLC High Volume FHV Trip Records
- Landing page: https://data.cityofnewyork.us/Transportation/2021-High-Volume-FHV-Trip-Records/5ufr-wvc5/about_data
- Canonical bulk parquet: https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page
  (`fhvhv_tripdata_2021-MM.parquet`, one file per month, ~1 GB each)
- Downloader repo (2021 subset): https://github.com/toddwschneider/nyc-taxi-data
- **~20M trips/month.** See COST ESTIMATION below — never load a full month unfiltered
  into memory in R.

**Local data dictionary:** `raw_data/HVFHV_Trip_Data_Data_Dictionary.xlsx` (TLC official,
dataset created 2023-12-14). It is the authority on field definitions — consult it rather
than inferring a field's meaning, and quote it in build-script comments where a definition
matters.

Key trip-level fields (2021 schema), per the dictionary:

| Field | Meaning |
|---|---|
| `hvfhs_license_num` | **HV0002** = Juno, **HV0003** = Uber, **HV0004** = Via, **HV0005** = Lyft (four digits, not two) |
| `dispatching_base_num`, `originating_base_num` | TLC base that dispatched / received the request |
| `request_datetime` | when the passenger requested to be picked up |
| `on_scene_datetime` | driver arrived at pickup — **Accessible Vehicles only**, so mostly null |
| `pickup_datetime`, `dropoff_datetime` | trip start / end |
| `PULocationID`, `DOLocationID` | TLC taxi zone in which the trip began / ended |
| `trip_miles`, `trip_time` | total passenger-trip miles; total passenger-trip seconds |
| `base_passenger_fare` | **base passenger fare before tolls, tips, taxes, and fees — the price actually paid. This is the price variable, directly observed.** |
| `tolls`, `bcf`, `sales_tax`, `congestion_surcharge`, `airport_fee`, `tips` | fare components (bcf = Black Car Fund; airport_fee = $2.50 at LGA/EWR/JFK) |
| `driver_pay` | **total driver pay, excl. tolls and tips, and net of commission, surcharges, and taxes** — the supply-side variable |
| `shared_request_flag`, `shared_match_flag` | pooled ride requested (Y/N) / actually shared (Y/N) |
| `access_a_ride_flag` | trip administered on behalf of the MTA (Y/N) |
| `wav_request_flag`, `wav_match_flag` | wheelchair-accessible requested / matched (Y/N) |

**Price is directly observed.** `base_passenger_fare` is the dollar amount the passenger
paid on that trip. There is nothing to reconstruct, and no proxy is needed for the price
outcome. Because `driver_pay` is net of commission, `base_passenger_fare − driver_pay`
is a clean measure of the platform's take.

**The one caveat — composition, not measurement.** There is no surge *multiplier* field,
so a raw mean of `base_passenger_fare` across trips confounds the price level with trip
composition: during Ida the trips that still happened were plausibly longer, slower, and
differently routed than normal, which moves the mean fare even at a constant price. This
is an ordinary controls problem. Handle it in this order:
1. **`fare_per_mile` and `fare_per_minute`** — the headline price measures; normalizing by
   distance and duration removes most composition drift.
2. **Origin–destination pair fixed effects** — compare the fare on the *same* route before
   vs. during the storm. This is the cleanest price comparison available.
3. **`price_resid`** (optional robustness only) — residualize log fare on trip
   characteristics; see the Variable Glossary.

**TLC's own stated limitation:** "As this is the raw trip data provided to TLC, there may
be some noise... unexpected categories or numbers out of expected ranges in some columns."
TLC did not create these data and makes no accuracy representations. This is the
justification for the cleaning filters below — cite it there.

### Weather — temporally and spatially precise (the key data gap)

The user does not have precise intra-city rainfall/wind/flood timing. These are the
recommended sources, best first:

| Source | Variable | Resolution | Access |
|---|---|---|---|
| **NOAA MRMS QPE** | radar quantitative precip estimate | **1 km, 2-min / hourly** | NCEI archive, GRIB2 |
| **NCEP Stage IV** | gauge-adjusted precip | 4 km, hourly | NCAR RDA ds507.5 |
| **ASOS / METAR** | wind speed/gust, precip, visibility | point, 1–5 min | Iowa State IEM ASOS archive |
| **NY State Mesonet** | precip, wind | point, 5-min | nysmesonet.org (registration) |
| **HRRR analysis** | 10 m wind | 3 km, hourly | NOAA AWS open-data bucket |
| **NYC 311** | flooding/sewer/catch-basin complaints | address-level, timestamped | NYC Open Data |
| **FEMA NFHL** | floodplain zones | polygon | FEMA Map Service Center |
| **USGS gauges** | stream/tide stage | point, 15-min | USGS NWIS |

**Ida-specific note:** the NYC record was set at Central Park on the evening of
1 September 2021 — 3.15 in of rain in one hour (roughly 20:51–21:51 EDT). Flash flooding
was extremely localized, so **station data alone is not sufficient**: MRMS/Stage IV
gridded rainfall is what gives spatial precision, and 311 flooding reports give the
best available proxy for realized street-level flooding.

**Do not hardcode Ida's timeline from memory.** Verify landfall/rainfall timing against
the downloaded weather data and cite the source in the build script.

### Control city (Design 3)
- Chicago TNP trip records: https://data.cityofchicago.org (Transportation Network Providers — Trips)
- Verify granularity before committing to this design (see Design 3 caveat above).

---

## Core Principles

- **Plan first** — enter plan mode before non-trivial tasks; plans saved to `~/.claude/plans/`
- **Verify after** — run the script and confirm output exists at the end of every task
- **Quality gates** — 80 = commit, 90 = peer-review ready, 95 = aspirational
- **[LEARN] tags** — when corrected, save `[LEARN:category] wrong → right` to memory;
  session logs in `.claude/logs/YYYY-MM-DD-<topic>.md`
- **Both signs are live** — never assume the revenue effect's direction in code or prose

## Naming Plans
Always name plans with a name that describes the plan, such as `mrms-rainfall-zone-hour-merge.md`,
never a whimsical name such as `playful-puzzling-sparkle.md`.

---

## DATA SAFEGUARDS — READ CAREFULLY

### raw_data/ is strictly read-only
- **Never write to, modify, overwrite, or delete any file in `raw_data/`.**
- Never run `rm`, `unlink()`, `file.remove()`, or any destructive operation targeting `raw_data/`.
- All cleaning and transformation must write outputs to `clean_data/`.
- **Exception:** new source downloads may be written into `raw_data/` subfolders that are
  explicitly registered as download targets in `.claude/hooks/protect-raw-data.py`.
  Destructive operations are blocked there too.

### Before any file operation
- When an intermediate or cleaned data file is needed in another file, check that it
  exists already and do not recreate it if it does.
- Only recreate an existing intermediate/clean file if important changes to the build
  script mean downstream analysis needs the new structure.
- Never overwrite an existing file in `clean_data/` without first confirming the user
  wants to replace it, and stating what will change about the file.

### Git discipline
- The project is **not yet a git repo.** Offer to `git init` before the first build script
  is written; data folders belong in `.gitignore` from the start.
- Before any multi-file editing session, check `git status`. If there are uncommitted
  changes, flag this and ask whether to commit first.
- Suggest a `git branch` before major transformations; merge to main after the user
  confirms they are satisfied.

---

## COST ESTIMATION — REQUIRED BEFORE LARGE OPERATIONS

The HVFHV data is **large**: ~20M trips per month, ~1 GB per monthly parquet, ~250M trips
for 2021. This dominates the cost profile of this project.

Before any expensive operation, **estimate and report expected cost/time first**, then
wait for approval.

### Mandatory practices for HVFHV data
- **Never** read a full monthly parquet into R with `arrow::read_parquet()` unfiltered.
- Push filters into the scan: `arrow::open_dataset()` → `filter()` → `collect()`, or
  `pd.read_parquet(..., columns=[...], filters=[...])` in Python.
- Select only needed columns — the fare/pay/flag columns are a small subset of the schema.
- For the Ida analysis the relevant window is roughly **2021-08-15 to 2021-09-15**;
  pull the analysis window first and only expand to the full year when a specific
  question (seasonality, placebo events) requires it.
- Collapse to `zone × hour` in Python; R should almost never touch trip-level data.

### How to estimate
- Install and load any R or Python packages needed to run the scripts without asking.
- File sizes: `file.info()` in R, `os.path.getsize()` / `du -sh` before loading.
- Flag if an operation will produce output > 1 GB or take > 10 minutes.
- For API/bulk downloads: estimate request count, total bytes, and rate limits first.
- Gridded weather (MRMS) is also large — one storm-day of 2-min 1 km QPE is many GB.
  Subset to the NYC bounding box **during** download, not after.

---

## Coding Conventions

### Language split
- **Python** — all data acquisition, cleaning, geospatial work, and panel construction
  (big-data throughput, `pyarrow`/`duckdb`, `geopandas`, `xarray`/`rioxarray` for GRIB).
- **R** — all estimation, tables, and figures (`fixest`, `ggplot2`).

Rationale: the trip data is too large to comfortably manipulate in R, and the weather
grids need the Python geospatial stack. R sees only the collapsed panel.

### R
R is at `C:\Program Files\R\R-4.6.1\bin\Rscript.exe`.

Beamer-compatible tables — after every bare-tabular `etable()` write, call
`wrap_for_beamer(path)` (define it once in `code/analysis/fhv_reg.r` and source it from
any script that generates `.tex` tables). It prepends a `\@ifclassloaded{beamer}`
conditional so `\input{reg/table}` works unchanged in both beamer frames and regular
LaTeX documents, and moves the `notes =` text outside the adjustbox so it renders below
the table. Both documents must load `\usepackage{adjustbox}`.

**Rules for tables that always compile (adjustbox + float nesting):**
- `wrap_for_beamer()` is ONLY for bare-tabular `etable()` output (no `style.tex("aer")`,
  no manual `\begin{table}`). Never call it on a file that already contains
  `\begin{table}` — wrapping a float in `adjustbox` causes
  `! LaTeX Error: Not in outer par mode.`
- For any table needing a caption/label/cross-reference, use
  `etable(..., style.tex = style.tex("aer", adjustbox = TRUE), title = ..., label = ...)`
  and do NOT call `wrap_for_beamer()` afterward.
- Correct nesting is always float-outside, box-inside:
  `\begin{table} → \caption → \centering → \begin{adjustbox} → tabular → \end{adjustbox} → notes → \end{table}`
- For hand-assembled multi-panel tables, put `adjustbox` inside the table float around
  each panel's tabular individually, not around the whole `\begin{table}` block.

### Python environment
Use this path to the project virtualenv:
```bash
"Z:/ek559/nys_algal_bloom/NYS algal bloom/code2/Scripts/python.exe" script.py
# or inline:
"Z:/ek559/nys_algal_bloom/NYS algal bloom/code2/Scripts/python.exe" -c "..."
```
Do **not** use `python`, `python3`, or `py` — they will not be found.

### Style
- Snake_case for all object and variable names
- Every script gets a header block:
  ```r
  # ============================================================
  # Script: [name].r
  # Purpose: [one-line description]
  # Inputs: [files read]
  # Outputs: [files written]
  # Author: EK  Date: [YYYY-MM-DD]
  # ============================================================
  ```
- Save cleaned datasets as `.parquet` (the panels are large); `.rds` only for small
  R-only objects. Never write into `raw_data/`.

### Quality Thresholds

| Score | Gate | Meaning |
|-------|------|---------|
| 80 | Commit | Runs without error, structurally sound |
| 90 | Peer-review ready | Reproducible, matches spec, clean code |
| 95 | Excellence | Aspirational; minimal reviewer friction |

---

## Project-Specific Variable Names & Concepts

**Unit of observation:** `zone_id × datetime_hour` (NYC taxi zone × hour), 2021.
Secondary panels: `zone_id × date`, and OD-pair (`PULocationID × DOLocationID`) × hour
for the evacuation-flow analysis.

### Identifiers and geography

| Concept | Variable name |
|---|---|
| TLC taxi zone of pickup | `pu_zone_id` (from `PULocationID`) |
| TLC taxi zone of dropoff | `do_zone_id` (from `DOLocationID`) |
| Borough of pickup zone | `pu_borough` |
| Hour timestamp (America/New_York, floor to hour) | `datetime_hour` |
| Date (America/New_York) | `date` |
| Hours since Ida peak-rainfall onset (signed, event time) | `event_hour` |
| Platform (HV0002 Juno, HV0003 Uber, HV0004 Via, HV0005 Lyft) | `platform` |

**Timezone rule:** TLC timestamps are local (America/New_York); weather grids are UTC.
Convert weather to America/New_York **once** in `build_weather_panel.py` and store only
local time downstream. Every script that touches a timestamp must state its timezone in
a comment. 1 September 2021 is EDT (UTC−4).

### Outcome variables (zone × hour)

| Concept | Variable name |
|---|---|
| Number of trips originating in zone | `n_trips` |
| Total passenger fare (sum of `base_passenger_fare`) | `revenue_passenger` |
| Total driver pay (sum of `driver_pay`) | `revenue_driver` |
| Platform take (revenue_passenger − revenue_driver) | `platform_margin` |
| Mean fare per trip (`base_passenger_fare`, directly observed) | `fare_per_trip` |
| **Mean fare per mile** (headline price measure) | `fare_per_mile` |
| Mean fare per minute | `fare_per_minute` |
| Residualized unit price (optional robustness only — see below) | `price_resid` |
| Mean driver pay per mile | `pay_per_mile` |
| Driver share of fare (`driver_pay / base_passenger_fare`) | `driver_share` |
| Mean wait time (`pickup_datetime − request_datetime`, sec — **not** `on_scene_datetime`, which is Accessible-Vehicles-only and mostly null) | `wait_time` |
| Mean trip distance (mi) | `mean_trip_miles` |
| Mean trip duration (s) | `mean_trip_time` |
| Mean speed (mi/h) — road-condition proxy | `mean_speed_mph` |
| Share of requests that are pooled | `share_shared_request` |
| Share of trips shared with a separately-booked passenger | `share_shared_match` |

**No driver identifier exists in this dataset.** The dictionary lists no hack license or
driver ID field, so unique-driver counts are not constructible. Supply must be proxied by
`n_trips`, `wait_time`, and `driver_pay` per trip. Do not add an `n_drivers` column.

### The price measure

`base_passenger_fare` is the observed price. Prefer, in order:

1. **`fare_per_mile` / `fare_per_minute`** — headline price measures. Normalizing by
   distance and duration removes most trip-composition drift.
2. **OD-pair fixed effects** — the same origin–destination pair before vs. during the
   storm is the cleanest available price comparison, and it absorbs route composition
   entirely. Use `feols(log(fare) ~ ... | pu_zone_id^do_zone_id + datetime_hour)` on the
   OD-pair panel.
3. **`price_resid`** — optional robustness only, when a single per-zone-hour price index
   is wanted. Residualize log fare on trip characteristics:

```
log(base_passenger_fare) = f(trip_miles, trip_time) + η_{PU zone} + η_{DO zone}
                           + τ_{hour-of-week} + u_trip
```
`price_resid` at zone × hour = mean of `u_trip` over trips originating in that zone-hour.
Estimate `f(·)` on a **pre-period sample that excludes the storm window**, then predict
out of sample onto the storm window — otherwise the storm's own prices are absorbed into
the baseline. State this explicitly wherever `price_resid` is used. This is a convenience
index, not a correction for a missing variable — the price itself is observed.

### Treatment / exposure variables (zone × hour)

| Concept | Variable name |
|---|---|
| Hourly rainfall over the zone (mm, area-weighted) | `precip_mm` |
| Cumulative storm rainfall to date (mm) | `precip_cum_mm` |
| Max hourly rainfall over the event (mm) | `precip_max_mm` |
| Mean 10 m wind speed (m/s) | `wind_ms` |
| Peak wind gust (m/s) | `gust_ms` |
| Count of 311 flooding complaints in zone-hour | `n_flood_311` |
| Cumulative 311 flooding complaints | `n_flood_311_cum` |
| Share of zone area in FEMA 100-yr floodplain | `share_floodplain` |
| Binary treated indicator (top-tercile `precip_max_mm`) | `affected` |
| Post-landfall indicator | `post_ida` |
| Storm window indicator (during heaviest rainfall) | `during_ida` |

**Prefer continuous exposure (`precip_max_mm`, `n_flood_311_cum`) over the binary
`affected`.** The Ida footprint was not sharp; a binary cut throws away the intensity
variation that identifies the dose-response. Report the binary version as a robustness
check with the tercile cut stated in the table notes.

### Consumer-side / welfare
- Consumer loss is **not** directly observed. Approximate with (a) change in consumer
  surplus under an estimated demand curve, (b) foregone trips × pre-storm surplus per
  trip, and (c) the fare increase paid by trips that still happened (transfer to
  platform/driver, not deadweight loss — keep transfers and DWL separate).
- Distinguish clearly in every table and figure: **transfer** (rider → platform/driver
  via higher prices) vs. **deadweight loss** (trips that did not happen) vs.
  **driver risk compensation** (a real cost, not pure rent).

### Sample cuts
- **Analysis window:** 2021-08-15 to 2021-09-15 (Ida landfall 2021-09-01)
- **Placebo windows:** same calendar weeks in 2021 without severe weather; and
  Tropical Storm Henri (2021-08-21/22) as a second, weaker event
- **Airport zones** (JFK 132, LGA 138, EWR 1) behave differently — report with and without
- **Manhattan core vs. outer boroughs** — Ida's flash flooding hit Queens and Brooklyn
  basement apartments hardest; the treatment is not Manhattan-centric

### Filters applied in cleaning (state in the build script)

Justified by TLC's own caveat in the data dictionary: these are raw base submissions, not
TLC-generated, and contain "unexpected categories or numbers out of expected ranges."

- Drop trips with `base_passenger_fare <= 0` or implausibly large (> $1,000)
- Drop `trip_miles <= 0` or `> 100`; `trip_time <= 60s` or `> 6h`
- Drop `PULocationID`/`DOLocationID` of 264/265 (unknown/outside NYC)
- Consider excluding `access_a_ride_flag == "Y"` from the main sample — MTA-administered
  paratransit trips are not market-priced and do not respond to surge
- **Do not filter on `on_scene_datetime`** — the dictionary states it is populated for
  Accessible Vehicles only, so it is null for most trips. Use
  `pickup_datetime − request_datetime` for `wait_time`, not `on_scene_datetime`.
- Keep the drop rules identical across the pre and post window — an asymmetric filter
  is itself a treatment effect. Report how many rows each filter drops, separately for
  the pre and storm windows: a filter that bites much harder during the storm is
  discarding treatment-relevant data.

---

## Skills Quick Reference

| Command | What It Does |
|---------|-------------|
| `/data-analysis [goal]` | End-to-end R analysis with fixest; produces tables + figures |
| `/regression-table [script]` | Run regression script; verify LaTeX output and event-study coefficients |
| `/review-r [file]` | R code review: DiD spec, parquet I/O, reproducibility, output |
| `/review-python [file]` | Python review: parquet schema, CRS, timezone, raw_data protection |
| `/review-paper [file]` | Full manuscript review with referee objections |
| `/lit-review [topic]` | Literature search + synthesis + BibTeX (with CoVe verification) |
| `/research-ideation [topic]` | Research questions + identification strategies |
| `/interview-me [topic]` | Conversational research spec interview |
| `/commit [msg]` | Branch → stage → commit → PR → merge |
| `/learn [skill-name]` | Extract discovery into persistent skill |
| `/context-status` | Show active plan, session log, hook status |

---

## What to Ask Before Acting

If any of the following apply, **stop and ask** rather than proceeding:

1. The task requires writing to `raw_data/` outside a registered download folder
2. The operation will take > 10 minutes or produce > 500 MB of output
3. A file already exists at the output path
4. A download would exceed a few GB (full-year HVFHV, full-day MRMS at native resolution)
5. The Chicago control design would require assuming fare comparability that has not
   been verified against the actual Chicago schema
