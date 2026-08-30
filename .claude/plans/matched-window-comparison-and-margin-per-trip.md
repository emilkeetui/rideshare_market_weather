# Plan: Platform-margin-per-trip in D4 + time-of-day-matched pre/post windows

## Context

Two changes to the D4 "first-pass" deliverable (`code/build/build_firm_window_aggregates.py`
+ `code/analysis/ida_first_pass.r`):

1. **Add a platform-margin-per-trip variable to the table and figures.** The table already has
   this number under the name `profit_per_trip` ("Profit (margin) per trip" row) — but the
   figure's 6 small multiples don't include it, and the name doesn't match this project's
   stated naming preference (`CLAUDE.md` §2.1: "Prefer `platform_margin` in column names and
   axis labels... Where the word 'profit' is used... the table note must say it is gross
   margin per trip, not accounting profit"). Rename `profit_per_trip` →
   `platform_margin_per_trip` everywhere, and add it as a 7th figure panel.

2. **Redefine the pre/post comparison windows.** Currently D4 compares the 9-hour `during`
   storm window against 14 *full calendar days* (all 24 hours) before and after. That
   conflates the storm's effect with ordinary time-of-day demand patterns — `during` is a
   17:00–02:00 evening/overnight slice, while the old `pre`/`post` average in daytime hours
   too. The user wants the comparison restricted to the **same clock-hour window as the storm**
   (e.g., "if the hurricane was 12am to 9am, use that window"), replicated across days **2 to 4
   weeks before and after** the storm, then averaged. This isolates the storm's effect on that
   specific time-of-day slice and was **confirmed via AskUserQuestion to REPLACE** (not
   supplement) the existing full-day pre/post comparison in the D4 table and figure.

Everything else in the repo (D1's canonical `pre`/`during`/`post`/`buffer` tags, D2 docs, D3
share sample) is unaffected — this is scoped to D4 only, per the user's own framing ("table and
figures of the window first-pass").

## Design decisions

**Matched-window definition.** The `during` window is derived (already, in
`define_event_windows.py`) as `[during_start, during_end)` = `[2021-09-01T17:00, 2021-09-02T02:00)`
EDT, 9 hours. For offset `k` in `14..27` (14 replicates — "2 weeks" through just under "4
weeks"), define:
- `pre_matched[k]  = [during_start - k days, during_end - k days)`
- `post_matched[k] = [during_start + k days, during_end + k days)`

Shifting the whole interval by whole days automatically preserves the exact clock times and
handles the midnight-spanning 17:00→02:00 shape with no special-casing. This gives 14
pre-matched windows spanning **2021-08-05 → 2021-08-19** and 14 post-matched windows spanning
**2021-09-15 → 2021-09-29** — both entirely inside the raw `fhvhv_tripdata_2021-{08,09}.parquet`
files already on disk, so **no new downloads are needed**. I'll flag the exact offset choice
(14–27, not e.g. 14–28) in the printed output for review; it's an easy one-line change if you'd
rather shift it by a day.

**Bonus finding from this derivation:** Labor Day (2021-09-06) falls *before* the new
`post_matched` range (which starts 09-15), so the "Labor Day confounds post" caveat that's in
the current table notes **no longer applies** and will be removed/replaced. Neither matched
range crosses a federal holiday.

**Ratio construction: pool, don't average-of-ratios.** For rate/ratio outcomes
(`fare_per_mile`, `driver_share`, etc.), the 14 replicate windows are pooled into one set of
trips per side and ratios are computed as ratio-of-sums, consistent with the existing
project convention (CLAUDE.md: "ratio outcomes must be ratios of sums, not means of ratios").
For simple counts/totals normalized to a rate (`trips_per_day`), this is computed as
`total_trips / total_elapsed_days`, where `total_elapsed_days` = 14 × 9h ÷ 24h = **5.25 days**
per side — mathematically identical to averaging the 14 windows' individual daily rates,
since all 14 replicates are equal length. `during`'s own `n_days` stays 0.375 (9h ÷ 24h),
unchanged. This requires no restructuring of the existing "per day" column/label scheme in
the R table — only the population feeding it changes.

**New data file, not a D1 rebuild.** D1 (`clean_data/hvfhv_trips_ida_window.parquet`, 1.09 GB,
already gated/verified) currently only covers pre/during/post ± 1 day buffer
(~2021-08-17 → 2021-09-18). The matched windows need data back to 2021-08-05 and forward to
2021-09-29 — outside D1's current range. Rather than widening D1 (which would grow it to
~1.9 GB and change what "the ida window file" means for every other consumer — D2 docs, D3
share sample, `build_zone_hour_panel_trips.py` — none of which need this), build a **new,
smaller, separate file**: `clean_data/hvfhv_trips_matched_windows.parquet`, containing only
trips that fall inside the union of the 28 small windows (~10.5 days of matched-hour data
out of the ~55-day source span). Rough size estimate: 14.6M rows over the original ~32 covered
days ⇒ ~4.5–5M rows and ~350–400 MB for ~10.5 days of matched-hour trips — well under the
500 MB safeguard threshold, no waiver needed. This new script duplicates ~60 lines of
per-batch cleaning logic from `clean_hvfhv.py` (same filters, same constructed columns) rather
than refactoring the already-verified `clean_hvfhv.py` into a shared module — deliberately
minimal-risk, at the cost of some duplication.

**The existing daily-trend figure keeps its current date range.** `firm_day_aggregates.parquet`
stays sourced from D1 only (Aug 18–Sep 17, unchanged) — the matched windows' outer replicates
(back to Aug 5, forward to Sep 29) fall outside that plotted range, and extending the trend
line that far would need yet another data pull for full-day context volumes that isn't part of
what was asked. The matched-window comparison lives in the table and in the new
per-trip-margin figure panel (which uses `day_agg`'s existing date range), not as new shading
on the daily trend chart.

## Implementation

### 1. `code/build/define_event_windows.py` — add matched-window derivation
After deriving `during_start`/`during_end` (unchanged), add:
- `N_REPLICATES = 14`, `OFFSET_MIN_DAYS = 14`, `OFFSET_MAX_DAYS = 27` as named constants.
- Build `pre_matched_windows` and `post_matched_windows`: lists of 14
  `{"start":..., "end":..., "offset_days":...}` dicts each, per the formula above.
- Print the full list (start/end/offset) for both sides, and assert none overlaps the existing
  `pre`/`during`/`post` windows and all fall within `[2021-08-01, 2021-09-30]` (defensive check
  that the offsets stay inside the two downloaded raw files).
- Add both lists to the JSON payload as new top-level keys — **do not modify or remove any
  existing key** (`windows`, `peak_hour_local`, `storm_threshold_in`, `pre_days`, `post_days`,
  `confounders`) — every other script that reads this file must keep working unchanged.
- Re-run and confirm the new keys look right (14 entries each side, correct date ranges, no
  overlap).

### 2. NEW `code/build/clean_hvfhv_matched_windows.py`
Mirrors `clean_hvfhv.py`'s per-batch logic (same `FILTER_RULES`, same constructed columns:
`fare_per_mile`, `platform_margin`, `driver_share`, etc., same `out_cols` schema) but:
- Reads the same two raw files (`fhvhv_tripdata_2021-08.parquet`, `-09.parquet`).
- Reports the estimated output size (~350–400 MB per the estimate above) before writing.
- Per batch, tests each row's `pickup_datetime` against the 28 matched windows from the JSON;
  keeps rows that fall in any of them, tags `window` = `"pre_matched"` or `"post_matched"`, and
  adds an integer `replicate_offset_days` column (14–27, sign matching pre/post) for later
  diagnostics.
- Applies the identical filter rules and constructed columns as `clean_hvfhv.py`.
- Writes `clean_data/hvfhv_trips_matched_windows.parquet`. This is a **new file** — no existing
  output is touched or overwritten.
- Same validation prints as `clean_hvfhv.py`: row count, actual size, median `driver_share`
  (expect 0.6–0.9), median `fare_per_mile` (expect a few dollars), `datetime_hour` tz check,
  platform set check (`{Uber, Lyft, Via}`).

### 3. `code/build/build_firm_window_aggregates.py` — rewire the window comparison
- Read D1 as before, but keep only `window == "during"` from it.
- Read the new `hvfhv_trips_matched_windows.parquet`; its `window` column already carries
  `pre_matched`/`post_matched`.
- Concatenate (matching the shared `out_cols` schema; drop `replicate_offset_days` before
  concat or leave it NaN for the `during` rows — diagnostic-only column, not required by
  `collapse()`).
- Rename `profit_per_trip` → `platform_margin_per_trip` in `collapse()`, in
  `add_all_platform_rows()`, and in both `keep_cols` lists (window-level and day-level).
- Recompute `n_days` per window by reading elapsed duration from the JSON: `during` = existing
  logic (unchanged, 0.375); `pre_matched`/`post_matched` = sum of the 14 window durations ÷ 24
  (5.25 each), read from the new JSON keys rather than hardcoded.
- Update the sanity-check block to key off `pre_matched` instead of `pre`. Keep the same
  plausibility assertions (`profit`/`margin` range, `driver_share` range, negative-margin
  share range) but print actual values without hard-failing if they land outside the old
  full-day figures — the population is now evening/overnight-only, which may genuinely have
  different typical fares/driver-share, and that's a real result, not a bug, unless the number
  is wildly implausible (i.e., still keep the assert as a wide sanity net, not remove it).
- `day_agg`/`firm_day_aggregates.parquet` stays computed from D1 exactly as now (unchanged
  date range) — only the renamed `platform_margin_per_trip` column flows through automatically
  since it's produced by the same shared `collapse()` function.
- Update the script's header-block `Inputs:` line to list the new matched-windows file.

### 4. `code/analysis/ida_first_pass.r` — table + figure updates
- `window_order`: `c("pre_matched", "during", "post_matched")`.
- `window_labels`: e.g. `"Pre-Ida (matched hrs, 2–4 wks before)"`, `"During Ida (9 hours)"`
  (unchanged), `"Post-Ida (matched hrs, 2–4 wks after)"`.
- In `rate_rows`, rename the `profit_per_trip` row to `col = "platform_margin_per_trip"`,
  label `"Platform margin per trip"`.
- In `measure_specs` (the figure), add a 7th entry:
  `list(col = "platform_margin_per_trip", label = "Platform margin per trip ($)")`.
- `pack_rows()` row-index arithmetic must be re-derived if the row count changed (it hasn't —
  still 14 rate rows × 3 window blocks + 3 total rows × 3 window blocks = 51) — just confirm
  the block boundaries still line up after rebuilding `full_df`.
- Update `table_notes`: explain the matched-window methodology (same clock-hour window as the
  storm, 14 replicate days each 2–4 weeks out, pooled); **remove the Labor Day caveat** (no
  longer applies — verified above) and add a note that both matched ranges avoid federal
  holidays; keep the other existing caveats (gross margin not profit, `n_trips`≠customers,
  driver pay incl. tips vs. firm revenue, Juno absent, Via small share, per-day-comparison
  basis, descriptive-benchmark-not-causal framing).
- Update the bottom sanity-check `cat()` block to read `window == "pre_matched"` /
  `"post_matched"`.
- Figure ggplot code, shading, and the rest of the daily-series logic is unchanged (still
  sourced from `day_agg`, same date range as today).

### 5. Session log
Append to `.claude/logs/2026-08-29-data-introduction-plan.md` as the work happens (per
`.claude/rules/session-logging.md`) — the offset-band choice, the Labor Day finding, file
sizes, and gate results.

## Explicitly out of scope
- No changes to D1 (`hvfhv_trips_ida_window.parquet`), its canonical `pre`/`during`/`post`
  window definitions, or `clean_hvfhv.py`.
- No re-running of D2 (`make_data_intro.py`) or D3 (`make_share_sample.py`) — their existing
  outputs describe the original design and stay as-is.
- No changes to the daily-trend figure's plotted date range.
- No git commit — will leave the change staged for you to review, per this project's "only
  commit when explicitly asked" convention.

## Verification
1. `define_event_windows.py`: re-run, confirm 14+14 matched windows printed with correct dates
   (Aug 5–19 pre, Sep 15–29 post), no overlap assertion failures.
2. `clean_hvfhv_matched_windows.py`: exit 0; row count in the few-million range (report
   actual); file size under 500 MB (report actual); driver_share/fare_per_mile/tz/platform
   sanity checks all pass.
3. `build_firm_window_aggregates.py`: exit 0; money identities still hold; `n_days` = 0.375 /
   5.25 / 5.25; print and eyeball the new `platform_margin_per_trip`, `driver_share`,
   `fare_per_mile` numbers for `pre_matched`/`post_matched` for plausibility (not sign).
4. `ida_first_pass.r`: exit 0; `.tex` and `.png` both regenerate; visually confirm the table
   has 3 correctly-labeled window blocks including the new `platform_margin_per_trip` row, and
   the figure has 7 panels including the new one; confirm table notes no longer claim Labor Day
   falls in the post window.
5. Report final file sizes/paths and the headline matched-window vs. during numbers back to
   the user.
