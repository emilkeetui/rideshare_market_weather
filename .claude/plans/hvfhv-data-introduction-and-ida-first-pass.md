# Plan: HVFHV Data Introduction + Ida First-Pass Event Windows

**For:** a Sonnet implementer session in `z:\ek559\fhv_extreme_weather`
**Drafted:** 2026-08-29
**Read first:** `CLAUDE.md` and `.claude/rules/*.md`. This plan does not restate those rules.
It records where reality differs from them, and what to build.

---

## 0. Ground truth — verified on the machine, 2026-08-29

Do not re-derive these, but do not blindly trust them either. Verification commands are given.

### 0.1 The event is Hurricane **Ida**, not Harvey

The request said "i think its hurricane harvey." Harvey made landfall in Texas in **August
2017** and flooded Houston; it never affected New York City. The NYC TLC HVFHV dataset does
not begin until **February 2019**, so Harvey is not merely the wrong storm for this project —
it is unreachable with this data source at all.

The event this repository is built around, and the only one the local files cover, is the
remnants of **Hurricane Ida over NYC on 2021-09-01**. Every window below is anchored to Ida.
**The user confirmed Ida on 2026-08-29.** This is settled; do not revisit it.

### 0.2 R is 4.6.1, not 4.5.2

`CLAUDE.md` and `.claude/rules/r-code-conventions.md` both give
`C:\Program Files\R\R-4.5.2\bin\Rscript.exe`. **That path does not exist.** The installed
interpreter is:

```
"C:/Program Files/R/R-4.6.1/bin/Rscript.exe"
```

Verified present: `arrow`, `fixest`, `ggplot2`, `data.table`, `sf`, `modelsummary`, `dplyr`,
`kableExtra`. Use R-4.6.1 everywhere, and as a final step update the two docs so the stale
path stops propagating.

### 0.3 `duckdb` is not installed — and is not needed

Present in `Z:/ek559/nys_algal_bloom/NYS algal bloom/code2/Scripts/python.exe`:
`pandas 2.2.3`, `pyarrow 23.0.1`, `geopandas 1.0.1`, `requests`, `openpyxl`, `matplotlib`.
Missing: `duckdb`, `rasterstats`, `xarray`, `rioxarray`.

`CLAUDE.md` permits installing packages without asking, but **do not install duckdb for this
task.** Each parquet file contains a **single row group**, so duckdb's predicate pushdown buys
nothing. Stream with pyarrow instead — this is the mandated pattern for every trip-level read
here:

```python
pf = pq.ParquetFile(path)
for batch in pf.iter_batches(batch_size=1_000_000, columns=cols):
    ...
```

Measured baseline: streaming 9 columns across all 14.9M September rows took **38.8 seconds**
at trivial memory. `rasterstats`/`xarray`/`rioxarray` serve the gridded-weather step, which is
**out of scope** — do not install them.

### 0.4 What the local data actually is

| Fact | Value | Verified by |
|---|---|---|
| Files | `raw_data/hvfhv/fhvhv_tripdata_2021-{08,09,10,11,12}.parquet` | `ls` |
| Size | 382–430 MB each, ~2.0 GB total | `ls -la` |
| Sept 2021 rows | **14,886,055** | `pq.ParquetFile(...).metadata.num_rows` |
| Row groups per file | **1** — hence stream, don't rely on pushdown | same |
| Columns | 24, exactly the 2021 schema in `CLAUDE.md` | `schema_arrow` |
| Timestamps | `timestamp[us]`, **timezone-naive**, local wall clock America/New_York | `schema_arrow` |
| `PULocationID`/`DOLocationID` | `int64` | `schema_arrow` |
| Taxi zones | 265 in `taxi_zone_lookup.csv`; shapefile under `taxi_zones_shp/taxi_zones/` | `head`, `ls` |
| `clean_data/` | **empty** — nothing built yet | `ls` |
| `code/analysis/` | **empty** — no R written yet | `ls` |
| Existing code | `code/build/download_hvfhv.py`, `code/build/map_taxi_zones.py` | `ls` |

### 0.5 Platform composition — **Juno does not exist in 2021**

Measured across all of September 2021:

| `hvfhs_license_num` | Firm | Trips | Share |
|---|---|---:|---:|
| `HV0003` | Uber | 10,557,442 | 70.9% |
| `HV0005` | Lyft | 4,240,481 | 28.5% |
| `HV0004` | Via | 88,132 | 0.6% |
| `HV0002` | Juno | **0** | 0.0% |

Juno ceased operations in November 2019. The per-firm deliverable therefore has **three**
firms, not four. Do not emit an empty Juno row — state the absence in the codebook and table
notes. Via at 0.6% will produce noisy per-firm statistics; report it, but flag the share.

### 0.6 Filter attrition, measured (September 2021)

| Filter | Rows hit | Share |
|---|---:|---:|
| `base_passenger_fare <= 0` | 41,152 | 0.28% |
| `trip_miles <= 0` | 3,450 | 0.02% |
| `PULocationID >= 264` | 798 | 0.005% |
| `request_datetime` null | 0 | 0% |

The filters are cheap and will not distort the sample.

### 0.7 Three measured traps in the flag columns

Tabulated over September 2021 — these are not in the data dictionary and each one will
silently produce a wrong number if assumed away.

**(a) `access_a_ride_flag` carries no trip-level information in 2021 — it is a platform
reporting convention.** Cross-tabbed by platform over both months:

```
=== 2021-08 ===              === 2021-09 ===
  HV0003 (Uber)  ' '  10,196,747     HV0003 (Uber)  ' '  10,557,442
  HV0004 (Via)   'N'      93,709     HV0004 (Via)   'N'      88,132
  HV0005 (Lyft)  'N'   4,209,240     HV0005 (Lyft)  'N'   4,240,481
```

The split is **perfectly determined by platform**: Uber submits a single space on every row,
Lyft and Via submit `N` on every row, and there is **not one `Y` in either month**. The field
varies across firms, not across trips, so it measures nothing about any individual trip.

Consequences: (i) `CLAUDE.md`'s suggestion to consider excluding `access_a_ride_flag == "Y"`
is **moot for 2021** — there are no such rows; (ii) for Lyft and Via this is an affirmative
"no MTA-administered trips reported," but for Uber it is **silence**, so any MTA paratransit
trips Uber did perform are indistinguishable from ordinary trips across 70% of the market.
Do not write a filter that silently does nothing. Record the distribution in the codebook,
note the Uber blind spot as a limitation, and move on.

**Do not confuse this with the WAV fields.** `access_a_ride_flag` is about *who administers
and pays for* the trip (the MTA, under contract). `wav_request_flag` / `wav_match_flag` are
about *vehicle type* (wheelchair-accessible), and those do vary at the trip level — 5.2%
matched in September. The dictionary compounds the confusion by describing
`on_scene_datetime` as "Accessible Vehicles-only," which refers to **WAV**, not Access-A-Ride.

**(b) Pooling was effectively suspended — `shared_match_flag` is ~0.19% Y.**

```
shared_match_flag: {'N': 14,858,337, 'Y': 27,718}
```

Shared rides were still largely paused post-COVID in September 2021. Report
`share_shared_match` for completeness, but do not build any analysis on pooling behaviour —
there is almost no variation. `wav_match_flag` is healthier at 774,858 Y (5.2%).

**(c) `dispatching_base_num` is a genuine repeated entity with tiny cardinality.**

```
dispatching_base_num:  33 distinct   (B02395, B02510, B02512, B02617, B02682, ...)
originating_base_num:  37 distinct, contains nulls
```

33 bases across ~15M trips means the base is a real, usable grouping dimension — worth
documenting in the "what repeats" section even though nothing in this task uses it.

---

## 1. What is being delivered

Four things, in order. Each is a hard gate for the next.

| # | Deliverable | Lands at |
|---|---|---|
| **D1** | Cleaned trip-level file for the Ida window | `clean_data/hvfhv_trips_ida_window.parquet` |
| **D2** | Data introduction: variables, summary statistics, structure | `output/sum/`, `output/fig/`, `docs/data_introduction.md` |
| **D3** | Shareable sample dataset, zipped for a coauthor | `output/share/fhv_ida_sample_<YYYYMMDD>.zip` |
| **D4** | First-pass firm × window aggregates | `clean_data/firm_window_aggregates.parquet`, `output/reg/`, `output/fig/` |

---

## 2. Conceptual guardrails — read before building D4

The request asked for "firm profit," "number of customers," and "average ride cost." Two of
those three are **not observable in this dataset**. Building them as though they were would
put a number in a table that a referee will delete.

### 2.1 The fare accounting — read this before building any profit variable

**The user specified (2026-08-29):**

```
driver_pay_total    = driver_pay + tips
profit_per_trip     = base_passenger_fare - (driver_pay + tolls + bcf
                                             + airport_fee + congestion_surcharge + sales_tax)
profit_total        = Σ profit_per_trip
revenue_passenger   = base_passenger_fare
```

Two of these are right and one has an accounting problem that must be surfaced in the write-up.

**The problem: the surcharges are additive, not carved out of `base_passenger_fare`.** The TLC
dictionary defines the field as "base passenger fare **before** tolls, tips, taxes, and fees."
Verified empirically on 3,988,681 September 2021 trips:

| Ratio | Median | Interpretation |
|---|---:|---|
| `sales_tax / base_passenger_fare` | **0.08877** | exactly the NYS 8.875% rate, assessed **on** the base fare |
| `bcf / base_passenger_fare` | **0.03006** | Black Car Fund levy, ~3% **on** the base fare |
| `congestion_surcharge` when > 0 | **$2.75** | the flat FHV rate, added to the trip |

These are surcharges the platform **collects on top of the fare and remits** — sales tax to
NYS, the congestion surcharge to NYS, `bcf` to the Black Car Fund, `airport_fee` to the airport
operator, `tolls` to the toll authority. They are pass-throughs: collected and remitted, net
zero to the firm. They were never inside `base_passenger_fare`, so subtracting them removes
money the firm never had.

**What that does to the number:**

| Formula | Mean $/trip | Median | Share negative |
|---|---:|---:|---:|
| Specified: `fare − (driver_pay + tolls + bcf + airport_fee + congestion_surcharge + sales_tax)` | **−0.050** | 0.230 | **47.9%** |
| Corrected: `fare − driver_pay` | **5.241** | 3.770 | 17.8% |

The specified formula makes the platforms lose money on **half of all NYC trips** at the unit
level, and produces a mean per-trip profit of roughly zero. That is an artefact of
double-counting $5.29 of pass-throughs — 20.9% of the mean base fare — not a finding about
2021 ride-share economics. (The corrected version's 17.8% negative share is plausible and real:
driver incentive guarantees do push individual trips below the fare.)

**Resolved by the user on 2026-08-29: use `base_passenger_fare − driver_pay`.** The formula
with the surcharge deductions is retired and is **not** to be built, reported, or carried as a
robustness column. The definitions to implement are:

```
revenue_passenger  = base_passenger_fare                          # firm revenue
driver_pay_total   = driver_pay + tips                            # driver take-home
platform_margin    = base_passenger_fare - driver_pay             # firm per-trip profit
profit_total       = Σ platform_margin
passthrough_total  = tolls + bcf + airport_fee + congestion_surcharge + sales_tax
passenger_outlay   = base_passenger_fare + passthrough_total + tips
```

`passthrough_total` survives the retirement of the profit variant because it is independently
useful: it is the wedge between the fare and what the rider actually pays, and it feeds
`passenger_outlay`. It is **never** subtracted from `platform_margin`.

**`passenger_outlay` is worth having on its own.** What the rider actually pays is
base + surcharges + tips ≈ **$31.7 mean**, not the $25.35 base fare. The consumer side of this
project needs the number the consumer actually faced — `base_passenger_fare` understates it by
about a quarter.

**Carry the accounting note forward into the write-up anyway.** The surcharge-deduction
formula is a natural mistake to make from the column names alone, and a coauthor holding only
the shared sample is well placed to make it. `docs/data_introduction.md` and the D3 `README.md`
must both state, in one short paragraph: the surcharges are additive to `base_passenger_fare`,
the firm remits them, deducting them double-counts about $5.29/trip and drives measured margin
to roughly zero on half of all trips. Document the trap; do not ship the variable.

**Neither margin is profit.** Both are gross take at the trip level. Neither nets out
insurance, driver incentives and referral bonuses, marketing, R&D, support, payment
processing, or corporate overhead, and both Uber and Lyft ran large consolidated losses in
2021. Prefer `platform_margin` in column names and axis labels. Where the word "profit" is
used because the user asked for it, the table note must say it is **gross margin per trip, not
accounting profit**.

### 2.2 "Number of customers" is not observable — report `n_trips`

There is **no rider identifier**. A customer taking four trips is four rows, indistinguishable
from four customers. `n_trips` is a trip count, not a headcount, and the two diverge exactly
when behaviour changes — which is the thing being measured. Name the column `n_trips` and put
the caveat in the notes. Same on the supply side: no driver or vehicle ID, so `n_drivers` is
not constructible (`CLAUDE.md` already forbids it).

A pooled trip can carry more than one separately-booked rider, a second reason trips ≠
customers — though per §0.7(b) this affects only 0.19% of trips in 2021.

### 2.3 "Average ride cost" — be explicit about whose cost

Ambiguous between the passenger's price and the platform's cost. Report all of:

- `fare_per_trip` — mean `base_passenger_fare`, the passenger's price. **Composition-sensitive.**
- `fare_per_mile`, `fare_per_minute` — the headline price measures per `CLAUDE.md`.
- `pay_per_trip` — mean `driver_pay`, the platform's main variable cost.

The composition caveat bites here specifically: during a storm the surviving trips are
plausibly longer and slower, which moves mean fare even at a constant price. That is why
`fare_per_mile` is the headline and `fare_per_trip` sits beside it, not instead of it.

### 2.4 Revenue — settled by the user

`revenue_passenger` = Σ `base_passenger_fare`. This is firm revenue. Pass-throughs (`tolls`,
`bcf`, `sales_tax`, `congestion_surcharge`, `airport_fee`) and `tips` are excluded, correctly:
the firm collects and remits them and keeps none of them. Say so in the notes.

The driver side, per the user's specification:

- `revenue_driver` = Σ `driver_pay_total` = Σ (`driver_pay` + `tips`) — driver take-home.
  Tips belong here: they are paid by the passenger on top of the fare and pass through to the
  driver in full.
- Also carry `revenue_driver_ex_tips` = Σ `driver_pay` — this is the term that appears in the
  profit formula, and the one that makes `revenue_passenger − revenue_driver_ex_tips` decompose
  exactly into `platform_margin`. Keeping both prevents an accidental mismatch between the
  revenue table and the profit table.

Note the asymmetry and state it in the notes: `driver_share` computed as
`driver_pay_total / base_passenger_fare` can exceed the fare-based margin identity because the
numerator includes tips that are not in the denominator. Report `driver_share` on the ex-tips
basis as the headline (median ≈ **0.79**, verified) and the tips-inclusive version beside it.

### 2.5 Sign discipline

Both directions of the revenue effect are live hypotheses. No comment, variable name, table
note, or sentence may presume the storm raised or lowered revenue. Flag implausible
*magnitudes*, never unexpected *signs*.

---

## 3. Implementation

### Step 1 — `code/build/download_asos.py` (new)

**Why:** `CLAUDE.md` forbids hardcoding Ida's timeline from memory. The three event windows
*are* the D4 deliverable, so the storm hours must be **derived from observed weather**. This
is the cheapest way to do that.

- Source: Iowa State IEM ASOS archive,
  `https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py`
- Stations: `KNYC` (Central Park), `KLGA`, `KJFK`, `KEWR`
- Window: 2021-08-14 → 2021-10-01; `data=tmpf,sknt,gust,p01i,vsby`; `tz=UTC`
- Output: `raw_data/weather/asos/asos_nyc_2021.csv` — a **registered download folder**, so
  this is permitted. New file only; never overwrite.
- A few hundred KB. No cost approval needed.
- Record the full request URL and access date in the script header.
- ASOS timestamps are **UTC**. Do not convert here — conversion happens once, in Step 2.

### Step 2 — `code/build/define_event_windows.py` (new)

Derives the three windows and freezes them so every downstream script uses identical bounds.

1. Read the ASOS CSV; parse as UTC; convert **once** with
   `.tz_localize("UTC").tz_convert("America/New_York")`. All downstream time is local.
2. Aggregate `p01i` (hourly precip, inches) to station × hour; take the **max across the four
   stations** as `city_precip_in`; convert to mm.
3. Define `during_ida` as the contiguous run of hours around 2021-09-01 exceeding a stated
   threshold, padded to whole hours. **Print the derived boundaries, the threshold, the peak
   hour and the peak value.** The peak is expected on the **evening of 2021-09-01 EDT**; if it
   lands on 2021-09-02 local, the UTC conversion is wrong — **stop and fix it.**
4. Define, non-overlapping, on whole-day boundaries so day-of-week composition matches:
   - `pre`    = the 14 full days ending at the start of the `during` window's first day
   - `during` = as derived in (3)
   - `post`   = the 14 full days beginning the day after the `during` window's last day
5. Write `clean_data/ida_event_windows.json` with all three windows as ISO-8601 **including
   the `-04:00` offset**, plus threshold, peak hour, and peak value.

**Confounder to record in the JSON and carry into every table note:** US Labor Day was
**Monday 2021-09-06**, inside the post window. The holiday weekend depresses commuting and
shifts trip composition on its own. A 14-day pre window (2021-08-18 → 08-31) contains no
federal holiday, so pre and post are **not** symmetric. This is one reason the before/after
comparison is a descriptive benchmark, not a causal estimate.

### Step 3 — `code/build/clean_hvfhv.py` (new; step 2 of the documented pipeline)

**Input:** the 2021-08 and 2021-09 files only. Do not touch Oct–Dec — outside every window.

**Window:** read `ida_event_windows.json` and filter `pickup_datetime` to the union of the
three windows plus one day of buffer. **Do not hardcode dates.** Expect roughly
2021-08-18 → 2021-09-16.

**Method:** `pf.iter_batches(batch_size=1_000_000, columns=cols)`, filter each batch, append
to a `pq.ParquetWriter`. Never materialise a month.

**Columns kept:** `hvfhs_license_num`, `dispatching_base_num`, `request_datetime`,
`pickup_datetime`, `dropoff_datetime`, `PULocationID`, `DOLocationID`, `trip_miles`,
`trip_time`, `base_passenger_fare`, `tolls`, `bcf`, `sales_tax`, `congestion_surcharge`,
`airport_fee`, `tips`, `driver_pay`, `shared_request_flag`, `shared_match_flag`,
`access_a_ride_flag`, `wav_match_flag`. Dropped: `originating_base_num`, `on_scene_datetime`
(Accessible-Vehicles-only, near-entirely null), `wav_request_flag`.

**Filters** — applied identically to pre, during, and post. An asymmetric filter is itself a
treatment effect:

- `base_passenger_fare > 0` and `<= 1000`
- `trip_miles > 0` and `<= 100`
- `trip_time > 60` and `<= 21600`
- `PULocationID <= 263` and `DOLocationID <= 263`
- `driver_pay > 0` — **not** in `CLAUDE.md`'s list. Measure how often it binds; keep it with a
  justifying comment if rare and symmetric, drop it if it bites unevenly across windows.

**Required diagnostic:** a filter-attrition table giving rows dropped by each rule
**separately for pre, during, and post**, as counts and shares → `output/sum/filter_attrition.csv`.
A filter biting much harder during the storm is discarding treatment-relevant data and must be
surfaced, not buried.

**Constructed columns:**

**First, fill the surcharge nulls.** `tolls`, `bcf`, `sales_tax`, `congestion_surcharge`,
`airport_fee`, and `tips` are each zero or null on a large share of trips (`airport_fee` is
non-zero on only 6.9%, `tolls` on 14.3%, `congestion_surcharge` on 39.4%). A single null
propagates through the sum and turns the whole profit figure into `NaN`. Apply `.fillna(0)` to
all six **before** any arithmetic, and print the null count per column first so the fill is
documented rather than silent.

```
platform             <- hvfhs_license_num -> {HV0002 Juno, HV0003 Uber, HV0004 Via, HV0005 Lyft}
pu_zone_id           <- PULocationID as int32
do_zone_id           <- DOLocationID as int32
datetime_hour        <- pickup_datetime floored to hour, tz-localized America/New_York
date                 <- local calendar date
wait_time            <- (pickup_datetime - request_datetime) seconds  # NOT on_scene_datetime
speed_mph            <- trip_miles / (trip_time / 3600)
window               <- {"pre","during","post",NA} from ida_event_windows.json

# --- price ---
fare_per_mile        <- base_passenger_fare / trip_miles
fare_per_minute      <- base_passenger_fare / (trip_time / 60)

# --- money, per §2.1 ---
driver_pay_total       <- driver_pay + tips                      # driver take-home
passthrough_total      <- tolls + bcf + airport_fee + congestion_surcharge + sales_tax
passenger_outlay       <- base_passenger_fare + passthrough_total + tips
platform_margin        <- base_passenger_fare - driver_pay       # firm per-trip profit
driver_share           <- driver_pay / base_passenger_fare       # headline, ex-tips
driver_share_incl_tips <- driver_pay_total / base_passenger_fare
```

**Never subtract `passthrough_total` from `platform_margin`.** See §2.1 — those surcharges sit
on top of the fare and are remitted, so deducting them double-counts.

Do **not** apply a `platform_margin >= 0` filter. Negative margins are real — 17.8% of trips
under the headline definition, driven by driver incentive guarantees — and dropping them would
truncate exactly the tail that a storm is likely to move.

`tz_localize("America/New_York")` on the naive TLC timestamps is correct — they are already
local wall clock. No DST transition falls inside this window, so `ambiguous`/`nonexistent`
handling will not trigger; assert no `NaT` is produced anyway.

Print before writing: median `driver_share` should sit in **0.6–0.9**, median `fare_per_mile`
a few dollars. Far outside means the fare and pay columns are misaligned — stop.

**Output:** `clean_data/hvfhv_trips_ida_window.parquet`.

> **Deliberate naming deviation.** `CLAUDE.md` names this step's output
> `clean_data/hvfhv_trips_2021.parquet`. That name implies full-year coverage this file does
> not have. Use `hvfhv_trips_ida_window.parquet` and note the deviation in the script header.

> **Size — approved, proceed.** ~16M trips × ~28 columns ≈ **600 MB–1 GB**, crossing the 500 MB
> threshold in `.claude/rules/data-safeguards.md`. **The user waived this safeguard for this
> file on 2026-08-29**, so write it without pausing. Still print the actual size afterwards, and
> the waiver does not extend to any other output.

### Step 4 — `code/build/build_zone_hour_panel_trips.py` (new)

Collapse D1 to `pu_zone_id × datetime_hour × platform`, producing every zone×hour outcome in
the `CLAUDE.md` glossary constructible without weather, plus the money columns settled in §2.1:

- **Volume:** `n_trips`
- **Money (sums):** `revenue_passenger`, `revenue_driver` (= Σ `driver_pay_total`),
  `revenue_driver_ex_tips`, `platform_margin`, `passthrough_total`, `passenger_outlay`,
  `tips_total`
- **Price:** `fare_per_trip`, `fare_per_mile`, `fare_per_minute`, `outlay_per_trip`
- **Driver side:** `pay_per_trip`, `pay_per_mile`, `driver_share`, `driver_share_incl_tips`
- **Service quality / conditions:** `wait_time`, `mean_trip_miles`, `mean_trip_time`,
  `mean_speed_mph`
- **Composition:** `share_shared_request`, `share_shared_match`, `share_margin_negative`
  (share of trips in the cell with `platform_margin < 0` — a cheap read on how hard incentive
  guarantees were running that hour)

Ratio outcomes must be **ratios of sums**, not means of ratios (`Σfare / Σmiles`, not
`mean(fare/miles)`) — the latter is dominated by very short trips. State this in a comment.

Zero-trip zone-hours: **fill explicitly as zeros** on the full `zone × hour × platform`
cross-product, and document the choice. Volume is a key outcome; a storm hour with no trips is
data, not a missing value. Row-count guard: 263 zones × 3 platforms × ~745 hours ≈ **588k rows**.

**Output:** `clean_data/zone_hour_panel_trips.parquet`.

> **Do not write `clean_data/zone_hour_panel.parquet`.** That filename is reserved by the
> documented pipeline for the panel *with* the zone-level weather merge, which needs
> MRMS/Stage IV and is out of scope here. A half-built file under the canonical name would
> silently mislead every downstream script. The `_trips` suffix is the whole point.

**Schema enforcement before write** (R reads this file):

```python
df["pu_zone_id"] = df["pu_zone_id"].astype("int32")
df["platform"]   = df["platform"].astype(str)
assert str(df["datetime_hour"].dt.tz) == "America/New_York"
print(df.dtypes)
df.to_parquet(path, index=False, engine="pyarrow")
```

Read it back and confirm the timezone survived the round trip.

### Step 5 — `code/build/make_data_intro.py` (new) → **D2**

The "introduction to the data" deliverable. Six outputs.

**(a) `output/sum/variable_dictionary.csv` + `.tex`** — one row per variable:
`variable`, `source` (raw TLC / constructed), `type`, `units`, `definition`, `notes`. Take raw
definitions **verbatim from `raw_data/HVFHV_Trip_Data_Data_Dictionary.xlsx`**, sheet
`Column Information`, via `openpyxl` — do not retype from memory. Give constructed variables
their own definitions, clearly marked.

**(b) `output/sum/summary_stats_trip.csv` + `.tex`** — trip-level, every numeric variable:
`N`, `n_missing`, `mean`, `sd`, `min`, `p1`, `p25`, `median`, `p75`, `p99`, `max`. The
requested mean/min/max/sd, plus the percentiles that reveal the tail behaviour a min/max pair
hides. Produce it **twice** — pre-filter and post-filter — so the cleaning rules' effect is
legible. Add a categorical block for `platform`, the three flags (report the §0.7(a) blank
category explicitly), and `dispatching_base_num`, with counts and shares.

**(c) `output/sum/summary_stats_panel.csv` + `.tex`** — the same statistics on
`zone_hour_panel_trips.parquet`, so both units of observation are documented.

**(d) `output/sum/data_structure.csv`** — the "what is repeated" answer, machine-readable: for
each candidate entity, its column, cardinality, and observations-per-unit (min/median/max).
Cover `pu_zone_id`, `do_zone_id`, `pu_zone_id × do_zone_id`, `platform`,
`dispatching_base_num`, `date`, `datetime_hour`.

**(e) `docs/data_introduction.md`** — the prose companion, written from the generated numbers,
never from memory. Required sections:

1. **What one row is.** A single completed HVFHV trip, as submitted by the base to TLC.
2. **Geographic scale.** TLC taxi zone — 263 usable of 265 (264/265 are unknown/outside NYC) —
   across five boroughs plus EWR. Zones are **not** equal-area; outer-borough zones are orders
   of magnitude larger than Manhattan ones, which is why any future weather merge must be
   area-weighted rather than a centroid lookup. Both pickup and dropoff zones are recorded, so
   origin–destination flow analysis is supported. **No sub-zone coordinates** — there are no
   lat/lon columns, so within-zone location is unrecoverable.
3. **Temporal scale.** Four timestamps per trip to the second (`request`, `on_scene`,
   `pickup`, `dropoff`), local wall clock America/New_York, timezone-naive in the file. Local
   files span 2021-08-01 → 2021-12-31; the published dataset runs from Feb 2019. Natural
   aggregations: hour, day. Report `on_scene_datetime`'s actual null rate.
4. **What repeats, and what does not** — the core structural section:
   - **Repeats:** taxi zone, OD pair, platform (3 active firms), `dispatching_base_num`
     (33 distinct), and every time unit. These are the panel dimensions available.
   - **Does not exist:** no rider ID, no driver ID, no vehicle ID, no trip ID. The data is a
     **repeated cross-section of trips over zones and time — not a panel of drivers or of
     customers.** No individual can be followed across trips, so driver entry/exit, extensive-
     margin labour supply, and repeat-customer behaviour are all out of reach.
   - Include the observations-per-unit table from (d) so the dimensions are quantified.
5. **What the data can and cannot answer.** Two honest lists.
   - *Can:* price levels and dispersion; trip volume; revenue and platform take; wait times;
     realized speed as a road-condition proxy; OD flows and displacement; spatial heterogeneity
     across zones; firm-level differences across Uber, Lyft, and Via.
   - *Cannot, without other data:* true firm profit (no cost data); customer counts or consumer
     welfare directly (no rider ID); driver labour supply (no driver ID); the surge multiplier
     itself (only the realized fare); pooling behaviour in 2021 (0.19% matched — no variation);
     and **requests that were never fulfilled — the data records completed trips only, so
     unmet demand during the storm is invisible and the volume decline is a lower bound on the
     demand shock.** Substitution to subway, taxi, or personal vehicle needs MTA and
     yellow/green-taxi data.
6. **Known data-quality caveats.** Quote TLC's own statement that this is raw base-submitted
   data with "unexpected categories or numbers out of expected ranges." Document the §0.7
   traps. Reference `output/sum/filter_attrition.csv`.

**(f) Figures** → `output/fig/`, 300 dpi, explicit width/height:
`trips_daily_by_platform.png`, `fare_per_mile_daily_by_platform.png`, and
`trips_hourly_ida_window.png` (hourly, 08-30 → 09-04, storm hours shaded). These belong to the
data introduction, so plotting them in Python here is acceptable; if you prefer the documented
language split, move them into the R script in Step 7. Pick one and be consistent.

### Step 6 — `code/build/make_share_sample.py` (new) → **D3**

A self-contained package a coauthor can open without this repo, this venv, or the 2 GB of raw
files. TLC trip records are fully public, so there is no confidentiality constraint — the only
constraints are size and self-containment.

**Zip contents:**

| File | What |
|---|---|
| `sample_trips.parquet` | 1% simple random sample of D1, `np.random.seed(20210901)`, seed printed and stated |
| `sample_trips.csv.gz` | the same rows, for a coauthor with no parquet reader |
| `zone_hour_panel_sample.parquet` | the **full** `zone_hour_panel_trips.parquet` — only ~588k rows |
| `taxi_zone_lookup.csv` | copied out of `raw_data/taxi_zones/` (reading is fine) |
| `variable_dictionary.csv` | from Step 5(a) |
| `summary_stats_trip.csv`, `summary_stats_panel.csv` | from Steps 5(b), 5(c) |
| `ida_event_windows.json` | from Step 2 |
| `README.md` | see below |

The 1% sample is ~160k trips — enough to prototype a specification, small enough to email.
Sample **trips, not zones or days**: a coauthor needs the full spatial and temporal extent, and
the panel file is included whole regardless.

`README.md` must state: the source and its URL; the exact window; the sampling rate and seed;
that this is a **1% sample and not for estimation**; the three firms present and Juno's
absence; the timezone convention; that `platform_margin` is not profit; that `n_trips` is not
customers; that unfulfilled requests are not observed. Include the variable dictionary inline.
A coauthor who reads only this file should be unable to make the three §2 mistakes.

**Output:** `output/share/fhv_ida_sample_<YYYYMMDD>.zip`. Create `output/share/`. Print the
final size; target under ~50 MB. If it exceeds 100 MB, drop `sample_trips.csv.gz` first, then
reduce to 0.5%.

### Step 7 — `code/build/build_firm_window_aggregates.py` + `code/analysis/ida_first_pass.r` → **D4**

The three-window firm comparison. The heavy collapse is Python's job; the table and figures are
R's, per the documented language split.

**Python** — from D1, grouped by `platform × window` →
`clean_data/firm_window_aggregates.parquet`:

| Column | Definition |
|---|---|
| `n_trips` | row count — **trips, not customers** |
| `n_days` | days in the window — windows differ in length, which is what makes them comparable |
| `trips_per_day` | `n_trips / n_days` |
| **Revenue** | |
| `revenue_passenger` | Σ `base_passenger_fare` — **firm revenue**, per the user's definition |
| `revenue_passenger_per_day` | the comparable version |
| `passenger_outlay_total` | Σ `passenger_outlay` — what riders actually paid, incl. surcharges and tips |
| **Driver side** | |
| `revenue_driver` | Σ (`driver_pay` + `tips`) — **driver pay**, per the user's definition |
| `revenue_driver_ex_tips` | Σ `driver_pay` — the term inside the profit formula |
| `tips_total` | Σ `tips` |
| `driver_share` | `revenue_driver_ex_tips / revenue_passenger` — headline (expect ≈ 0.79) |
| `driver_share_incl_tips` | `revenue_driver / revenue_passenger` |
| **Profit** — see §2.1 | |
| `platform_margin` | `revenue_passenger − revenue_driver_ex_tips` — **firm profit** |
| `platform_margin_per_day` | the comparable version |
| `margin_rate` | `platform_margin / revenue_passenger` |
| `passthrough_total` | Σ (`tolls`+`bcf`+`airport_fee`+`congestion_surcharge`+`sales_tax`) — remitted, **never** deducted from profit |
| `share_margin_negative` | share of trips with `platform_margin < 0` |
| **Price and trip characteristics** | |
| `fare_per_trip` | mean `base_passenger_fare` |
| `outlay_per_trip` | mean `passenger_outlay` |
| `fare_per_mile` | Σ fare / Σ miles |
| `fare_per_minute` | Σ fare / (Σ trip_time / 60) |
| `profit_per_trip` | `platform_margin / n_trips` (expect ≈ $5.24 in a normal window) |
| `mean_trip_miles` | mean `trip_miles` — the "average ride distance" asked for |
| `mean_trip_time` | mean `trip_time`, seconds |
| `mean_speed_mph` | Σ miles / (Σ trip_time / 3600) |
| `mean_wait_time` | mean `wait_time`, seconds |
| `share_shared_match` | share with `shared_match_flag == "Y"` |

**Assert these identities** — they are the cheapest checks that the money columns were filled
and summed correctly, and they catch a stray null immediately:

```
revenue_passenger - revenue_driver_ex_tips == platform_margin
revenue_driver - revenue_driver_ex_tips    == tips_total
passenger_outlay == revenue_passenger + passthrough_total + tips_total
```

Emit the same rows for an `All` platform total. Carry `sd` and `N` for each mean so the table
can show dispersion, and add pre→during and pre→post **percent-change** columns for every
measure.

> **The `during` window is far shorter than 14 days.** Every level comparison must therefore be
> **per day** (or per hour), never a raw total. A raw `during` total will be smaller than the
> `pre` total purely because it spans fewer days; reading that as a storm effect is an
> arithmetic error, not a finding. Make per-day the default in the table and put raw totals in a
> clearly-labelled separate block.

Also emit `clean_data/firm_day_aggregates.parquet` — the same measures at `platform × date` —
so R can plot daily series rather than three points.

**R** (`code/analysis/ida_first_pass.r`, run with R-4.6.1):

- Read with `arrow::read_parquet()`; `str()` and confirm types.
- `output/reg/firm_window_first_pass.tex` — firms in columns, measures in rows, three window
  blocks. Hand-assembled via `kableExtra` or `modelsummary::datasummary`. This is descriptive,
  **not** `etable()` output, so **do not** call `wrap_for_beamer()` on it. Follow the
  float-outside / adjustbox-inside nesting rule in `CLAUDE.md`.
- `output/fig/firm_window_first_pass.png` — small multiples (trips/day, revenue_passenger/day,
  fare_per_mile, mean_trip_miles, platform_margin/day, driver_share), daily series by platform
  with the storm window shaded.
- Report `driver_share` and `driver_share_incl_tips` as **adjacent rows** so the tip wedge is
  visible in one glance.
- **Required table notes:** the exact window boundaries and the threshold that produced them;
  the profit definition spelled out as `base_passenger_fare − driver_pay`, with the note that
  surcharges the firm collects and remits are **not** deducted because they sit on top of the
  fare; that this is gross margin, not accounting profit; that `n_trips` counts trips, not
  customers; that driver pay includes tips while firm revenue does not; that Labor Day
  2021-09-06 falls in the post window; that Juno is absent; that Via is 0.6% of trips; that all
  level comparisons are per-day.

> **This is Design 2 from `CLAUDE.md` — the weakest design.** No control for citywide time
> shocks, seasonality, or the holiday. Label it a **descriptive benchmark** in the table title,
> the notes, and any summary prose. Do not describe any number in it as a causal effect. The
> causal work is the within-city spatial DiD, which needs the weather panel and is not in scope.

### Step 8 — housekeeping

- Update `R-4.5.2` → `R-4.6.1` in `CLAUDE.md` and `.claude/rules/r-code-conventions.md`.
- Write `.claude/logs/<YYYY-MM-DD>-data-introduction.md` per `.claude/rules/session-logging.md`,
  logging decisions **as they happen**, not at the end.
- `CLAUDE.md` offers to `git init` before the first build script. Offer it; if accepted,
  `.gitignore` must exclude `raw_data/`, `clean_data/`, `output/share/`, and `*.parquet`.

---

## 4. Verification gates

Do not report a step complete until its gate passes. Run the script, confirm the output exists,
check the numbers.

**After Step 2 (windows)**
- [ ] Peak `city_precip_in` hour is on the **evening of 2021-09-01 local time**. If it lands on
      2021-09-02, the UTC→EDT conversion is wrong — stop and fix.
- [ ] The three windows do not overlap; `pre` and `post` are exactly 14 days each.

**After Step 3 (cleaning)**
- [ ] Exit 0; `clean_data/hvfhv_trips_ida_window.parquet` exists; actual size reported.
- [ ] Row count in the 14–18M range for a ~29-day window.
- [ ] Median `driver_share` in 0.6–0.9; median `fare_per_mile` a few dollars.
- [ ] `datetime_hour` is tz-aware America/New_York and survives a parquet round trip.
- [ ] Filter attrition reported separately for pre / during / post; comment on any rule biting
      more than ~2× harder during the storm.
- [ ] Only `HV0003`, `HV0004`, `HV0005` appear.

**After Step 4 (panel)**
- [ ] `(pu_zone_id, datetime_hour, platform)` is **unique** — assert it.
- [ ] ~263 zones present; hour range matches the window with no gaps.
- [ ] No NaN in `pu_zone_id`, `datetime_hour`, `platform`, `n_trips`.
- [ ] Load in R: `str()` shows `pu_zone_id` `<int>` and `datetime_hour` POSIXct with
      `tzone = "America/New_York"`. **A UTC round trip is a hard stop.**

**After Step 5 (intro)**
- [ ] Every file exists and is non-trivially non-zero.
- [ ] Every numeric column in D1 appears in the summary table — none silently dropped.
- [ ] `docs/data_introduction.md` numbers match the generated CSVs. Spot-check three.

**After Step 6 (sample)**
- [ ] Zip opens; every listed file present; size reported.
- [ ] `sample_trips.parquet` reads standalone and holds ~1% of D1's rows.
- [ ] README states the seed, the sampling rate, and all three §2 caveats.

**After Step 7 (first pass)**
- [ ] R exits 0; the `.tex` and `.png` both exist.
- [ ] `n_trips` across the three windows sums to ≤ D1's row count (the windows need not tile it).
- [ ] Magnitudes plausible: `fare_per_mile` in single-digit dollars, `driver_share` 0.6–0.9,
      citywide `trips_per_day` in the hundreds of thousands.
- [ ] **Do not flag any change for its sign.** Both directions are live hypotheses.
- [ ] All comparisons are per-day; no raw `during` total compared to a raw 14-day total.

---

## 5. Decision points — stop and ask

1. ~~Before Step 3: the ~500–800 MB output crosses the data-safeguards threshold.~~
   **Pre-approved by the user 2026-08-29** — the size safeguard is explicitly waived for
   `clean_data/hvfhv_trips_ida_window.parquet`. Still report the actual size after writing.
   The waiver covers this one file, not a general licence to skip cost estimates.
2. **If any `clean_data/` or `output/` target already exists:** stop, say what would change, ask.
   Never overwrite silently.
3. **If the derived storm window looks wrong** — peak precipitation not on the evening of
   2021-09-01 local, or a `during` window longer than ~36 hours — stop. This is the timezone bug
   the project is most exposed to.
4. ~~If the user did mean Harvey.~~ **Resolved: the user confirmed Ida on 2026-08-29.**
5. **If any money identity in Step 7 fails**, or `share_margin_negative` is far from ~18%, or
   `profit_per_trip` is far from ~$5.24 in the pre window, stop — a component column was not
   null-filled or the fare and pay columns are misaligned.
6. **After 3 failed fix attempts** on any single error, surface it rather than continuing.

---

## 6. Explicitly out of scope

Do not start these:

- MRMS / Stage IV / HRRR gridded weather and the zone-level weather merge
- `clean_data/weather_zone_hour.parquet` and `clean_data/zone_hour_panel.parquet`
- NYC 311 flooding complaints, FEMA NFHL, USGS gauges
- The within-city spatial DiD and event study (`code/analysis/did_ida.r`)
- Chicago TNP and Design 3
- Any welfare or consumer-surplus calculation
- The Tropical Storm Henri placebo
- October–December 2021 data

The point of this task is to characterise the data honestly and produce one descriptive
benchmark. The causal work comes after the weather panel exists.
