# Session: 2026-10-02 — hvfhv-data-quality

## Objective
Implement plan `~/.claude/plans/hvfhv-data-quality-audit-2020-2026.md`: data-quality audit of the full
HVFHV series 2020-04..2026-07 (missingness, legal completeness, summary stats) as a standalone LaTeX report.

## Changes Made
- Committed prior branch work (85dfc60) on od-weather-driver-share at user's request; branched hvfhv-data-quality.

## Design Decisions
| Decision | Rationale |
|----------|-----------|
| Commit existing changes first | User chose this at Step 0 |

## Verification Results
- [x] Step 1: 76 files present 2020-04..2026-07, sizes match manifest (33.4 GB)

## Open Questions / Blockers
-

## Next Steps
- audit_hvfhv_quality.py, benchmark download, legal research + CoVe, tables, report
- audit speed: 2020-04 35s, 2021-09 98s (14.9M rows) -> full run est 1.5-2h; spot check 2021-09 fare mean/min/max/median match DuckDB exactly
- wrote make_dq_report_tables.py (untested), download_tlc_aggregates.py (run; 2 CSVs in raw_data/hvfhv/tlc_aggregates); legal sources fetched: LL149/2018, 35 RCNY 59D-14 (2021 promulgation), TLC user guide
- references.bib written; waiting on full audit run (background, started 10:01, ~1.5-2h). Next: footers/combine/medians stages, run make_dq_report_tables.py --force (own dev outputs), write report tex, CoVe, compile.
- 2026-10-02 15:40: audit 76/76 done; footers match; combine done; medians approx single-scan running; findings: on_scene populated for Uber (dictionary says AV-only), originating_base blank for Lyft/Via, AAR flag blank for Uber thru 2023-11, benchmark gaps <0.1% (base agg), Juno/other = 0, Via last 2021-10
- 16:50 switched to exact per-variable medians (resumable, ~7 min/var, ~2h); single-scan t-digest killed after 90 min with no output

## Update 2026-10-02 21:15 — complete
- Exact full-period medians (quantile_cont over all 76 files, one query per variable, ~4-8 min each) finished ~20:30; single-scan t-digest was killed after 90 min with no output (approx path never completed; dq_median_exact_vs_tdigest not produced).
- make_dq_report_tables.py run (--force on own dev outputs); 76/76 months; audited rows 1,337,878,593 == parquet footers.
- Spot-check vs raw parquet (all exact): total rows, Uber trips 971,816,371, mean fare 24.727, fare<=0 1,517,558, AAR=Y 647,876, Via last trip date 2021-10-11 (1 trip), last full day 2021-10-10.
- Findings: on_scene_datetime populated for Uber (dictionary says AV-only; CLAUDE.md repeats it); originating_base_num blank ~99.8% Lyft/Via; access_a_ride_flag blank for Uber through 2023-11 (asymmetric AAR filter); Via records end 2021-10-11 though Via ran until 2021-12-20 (open question for TLC); driver_share>1 for 12.8% of rows; benchmark gaps <0.1% (same-source check); 2026-05 industry indicator 7.2% off.
- CoVe: PARTIAL (18 PASS / 7 PARTIAL / 0 FAIL); corrections applied (curfew end 06-07, Henri 08-21, storm labels, taxi-sections disclaimer, TheDrive date 2022).
- Compile: BIBINPUTS=<repo root> pdflatex -output-directory=docs/data_quality/build ...; bibtex run inside build dir. 10 pages, no undefined refs/cites, no overfull.
- Tooling gotcha: Bash-tool heredocs halve backslashes (\t became TAB); use Edit tool or chr(92) for LaTeX.
- Score ~88/100 (below 90: no dtype print/existing-output warning in audit script; storm-severity and effective-date claims unverified).

## Open Questions / Blockers
- Via: why records stop 2021-10-11; ask TLC.
- CLAUDE.md claim "on_scene_datetime mostly null" is wrong for Uber; Ida analysis wait_time uses pickup-request (fine), but exclusion rule for access_a_ride is asymmetric before 2023-11.
- Ida Central Park peak: 3.15 in (CLAUDE.md) vs 3.47 in (one source); resolve vs NWS.
- Changes not committed (branch hvfhv-data-quality).
