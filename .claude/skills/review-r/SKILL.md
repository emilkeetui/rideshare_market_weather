---
name: review-r
description: Run the R code review protocol on R scripts in this project. Checks code quality, reproducibility, DiD/event-study correctness, timezone handling, and parquet I/O standards. Produces a report without editing files.
argument-hint: "[filename or 'all']"
allowed-tools: ["Read", "Grep", "Glob", "Write", "Task"]
---

# Review R Scripts

Run the comprehensive R code review protocol for this project's analysis scripts.

## Steps

1. **Identify scripts to review:**
   - If `$ARGUMENTS` is a specific filename: review that file only
   - If `$ARGUMENTS` is `all`: review all `.r` / `.R` files in `code/analysis/`

2. **Read `.claude/rules/r-code-conventions.md`** for current project standards.

3. **For each script, launch the `r-reviewer` agent** with full path, instructing it to:
   - Follow the 10-category review protocol in the agent file
   - Pay special attention to: `datetime_hour` timezone (America/New_York), the
     event-study reference period, zone-level clustering, the volume/price/revenue
     decomposition, and that R is not reading trip-level data
   - Save report to `.claude/logs/[script-name]-r-review.md`

4. **After all reviews complete**, present a summary:
   - Total issues per script
   - Breakdown: Critical / Major / Minor
   - Top issues to fix first

5. **IMPORTANT: Do NOT edit any R source files.** Report only. Fixes applied after user review.

## Report Format

```
R Code Review: [script-name]
Date: YYYY-MM-DD
Score: XX/100

Critical Issues (block commit):
  - [location]: [issue] → [suggested fix]

Major Issues (block peer-review):
  - [location]: [issue] → [suggested fix]

Minor Issues:
  - [location]: [issue] → [suggested fix]

Passed checks:
  ✓ [check name]
```
