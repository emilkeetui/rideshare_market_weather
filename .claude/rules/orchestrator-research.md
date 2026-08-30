# Orchestrator Protocol: Research Mode

**After a plan is approved, implement autonomously. Surface only genuine decision points.**

## The Loop

```
Plan approved → orchestrator activates
  │
  Step 1: IMPLEMENT — execute plan steps in order
  │
  Step 2: RUN — execute the script(s) end-to-end
  │         Python: "Z:/.../python.exe" code/build/script.py
  │         R:      "C:/Program Files/R/R-4.6.1/bin/Rscript.exe" --vanilla code/analysis/script.r
  │
  Step 3: CHECK OUTPUT
  │         • Script exits 0 (no error)
  │         • Expected output file exists in clean_data/ or output/
  │         • Row counts plausible (not 0, not suspiciously small)
  │         • No NaN leakage in key columns (pu_zone_id, datetime_hour, fare/pay, precip)
  │         • datetime_hour is tz-aware America/New_York
  │
  Step 4: FIX (if Step 3 fails)
  │         Diagnose → fix → re-run (back to Step 2)
  │         Max 3 fix loops before surfacing to user
  │
  Step 5: SCORE — apply quality-gates.md rubric
  │
  └── Score ≥ 80?
        YES → present summary to user
        NO  → fix critical issues → re-run → re-score (max 3 total rounds)
              After max rounds → present with remaining issues listed
```

## Panel-Build Checks (Step 3, extended)

After rebuilding `clean_data/zone_hour_panel.parquet`:
1. `(pu_zone_id, datetime_hour, platform)` is unique
2. Peak `precip_mm` falls on the evening of 2021-09-01 **local** time — the single
   fastest check that the UTC→EDT conversion is right
3. Zone coverage is ~262 zones; date range matches the requested window
4. `fare_per_mile` and `driver_share` medians are in plausible ranges
   (see `verification-protocol.md`)

## Regression Table Checks (Step 3, extended)

After generating a `.tex` table in `output/reg/`:
1. Column headers identify the design (within-city DiD, before/after, Chicago DiD) and
   the sample (all zones / excl. airports / by borough)
2. Sample size in the footnote is plausible
3. Clustering level and event-study reference period appear in the notes
4. Volume, price, and revenue outcomes are reported together, not in isolation
5. **Do not flag a coefficient for its sign.** Both directions of the revenue effect are
   live hypotheses. Flag implausible *magnitudes* instead (e.g. a 40× price increase).

## Decision Points — Stop and Ask

Stop and ask the user when:
- Fix loop hits 3 iterations without resolving the error
- Output row count is 0 or implausibly small (likely a merge or filter failure)
- The weather merge and the trip data disagree about when the storm hit
- A download would exceed a few GB, or an operation would take > 10 minutes
- A file that should not be overwritten exists at the output path
- The Chicago data turns out not to support the fare comparison Design 3 assumes —
  report what the schema actually offers rather than proceeding on the assumption

## "Just Do It" Mode

When the user says "just do it" / "handle it" / "go ahead":
- Skip the final approval pause
- Run the full implement → run → check → fix loop
- Present a summary when done (output path, row counts, quality score)
- Still stop for the download-size and data-availability decision points above
