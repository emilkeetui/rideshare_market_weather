---
name: regression-table
description: Run a regression table script (default did_ida.r), verify LaTeX output in output/reg/, check column labels and event-study notes against the CLAUDE.md spec, and report pass/fail.
argument-hint: "[script name, default: did_ida.r] [optional: specific table name]"
allowed-tools: ["Bash", "Read", "Grep"]
---

# Regression Table Workflow

Run the regression script, verify the LaTeX output, and confirm the table meets the
econometric quality standard in `.claude/rules/quality-gates.md`.

**Input:** `$ARGUMENTS` — script name (default: `did_ida.r`) and optionally a specific
table name to check (e.g. `es_fare_per_mile_flooded`).

---

## Steps

### Step 1: Run the Script

```bash
"C:/Program Files/R/R-4.6.1/bin/Rscript.exe" --vanilla code/analysis/${SCRIPT:-did_ida.r}
```

Capture the exit code. If non-zero: report the error and stop.

### Step 2: Confirm Output Exists

```bash
ls -lt output/reg/*.tex | head -10
```

Confirm the expected `.tex` files were created or updated (check mtimes — a stale file
from a previous run is a silent failure).

### Step 3: Check Table Content

For each newly generated `.tex` file:

1. **Column headers** — confirm they identify the design and the sample:
   - Design: within-city DiD / simple before-after / Chicago cross-city DiD
   - Sample: all zones / excl. airport zones (132, 138, 1) / Manhattan vs. outer boroughs

2. **Sample size footnote** — N present and plausible for a zone × hour panel
   (~262 zones × 24 h × N days, so tens of thousands in a one-month window)

3. **Clustering level** — must appear in the notes:
   ```bash
   grep -i "cluster" output/reg/<table>.tex
   ```
   Flag if absent. Expected: taxi-zone level (`pu_zone_id`), or two-way zone × date.

4. **Event-study reference period** — must appear in the notes for any event study:
   ```bash
   grep -iE "reference|ref\.|omitted" output/reg/<table>.tex
   ```
   Flag if absent — an event study without a stated reference period is uninterpretable.

5. **Outcome decomposition** — confirm the volume, price, and revenue outcomes are
   reported together across the table set. Flag a revenue table that ships without its
   `n_trips` and `fare_per_mile` counterparts.

6. **Magnitudes** — check that coefficients are economically plausible relative to the
   pre-storm means. **Do not flag a coefficient for its sign** — both directions of the
   revenue effect are live hypotheses in this project. Flag implausible magnitudes
   (e.g. an implied fare increase of several hundred percent) instead.

7. **Stars legend** — confirm `*** p<0.01, ** p<0.05, * p<0.1`

### Step 4: Report

```
Regression Table Report
─────────────────────────────
Script:    [script name]
Exit code: 0 ✓

Tables generated:
  output/reg/[name].tex
    Design:     [within-city DiD / before-after / Chicago DiD]
    Columns:    [list]
    N:          [value] ✓ / [MISSING]
    Cluster:    [level] ✓ / [NOT STATED]
    ES ref:     [period] ✓ / [NOT STATED / n/a]
    Decomp:     [volume + price + revenue present / incomplete]
    Magnitudes: [plausible / flag: implied X% change]
    Quality:    [score]/100

Overall: PASS / FAIL
Issues:  [list any]
```
