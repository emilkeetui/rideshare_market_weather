# Session: 2026-09-30 — OD weather cells + binned driver-share regression

## Objective
Regress trip-level driver_share on binned rainfall/temperature at the origin (pickup hour) and destination (dropoff hour), 2021.
FE (user-specified, revised): platform + pu_zone_id^pu_hod + do_zone_id^do_hod + month + dow.
Plan: `~/.claude/plans/od-weather-driver-share-binned-regression-2021.md` (Sonnet implements).

## Design Decisions
| Decision | Rationale |
|----------|-----------|
| Cell = platform × PU × DO × pickup hour × dropoff hour, WLS by n_trips | Exactly reproduces trip-level OLS and clustered SEs; 30% of Aug-2021 trips end in a different hour from the one they started in, so dropoff hour must be in the key |
| DV = mean of trip ratios (sum_driver_share/n_trips) | Matches the trip-level estimand; sums kept for a later Σpay/Σfare |
| ~~doy + dow~~ → **month + dow** (user correction) | User prefers dow + month for a one-year sample. dow was redundant given doy within 2021; month + dow are not collinear. No date FE, so weather β also use across-day variation within a month (more temperature variation; daily citywide shocks are no longer absorbed). doy is still stored in the cells for a robustness check |
| Clustering pu_zone_id + date | Weather is a largely citywide daily shock |
| AAR trips excluded | Not market-priced |
| Weather kept continuous in the cells; binned in R | Bin edges can change without a rebuild |

## Measured during planning
- Aug 2021: 13.9M trips (fare>0, known zones) → 7.7M cells (PU hour) / 9.0M cells (PU+DO hour).
- 2021 raw rows 174.6M → ≈108M cells projected.
- Machine: 128 GB RAM (~101 GB free), 8 cores/16 threads, 156 GB free on Z:.
- Projected feols peak ≈ 60–70 GB with 24 bin dummies; time unmeasured → August benchmark gate.
- Zone 161 2021: 92.5% of hours dry; precip p95 0.52, p99 3.6, p99.9 13.7 mm/h.

## Open Questions / Blockers
- Commit the uncommitted weather-build work on weather-grids-2019-2026 before branching? (asked)

## Revision (user, post-benchmark)
- Keep DO zone 265 (outside NYC) trips; dest rain = absorbed `outside_nyc` level. Drop temperature bins. Rain bins refined to 11 wet bins (edges 0.1,.25,.5,1,2,4,6,10,15,25,40), ref = dry <0.1 mm/h. Approved: build remaining 10 months + Aug+Sep memory-scaling run.

## Next Steps
- Step 0 git → Sonnet implements Steps 1–3 → August benchmark gate → user approves full year.

## Implementation log (Sonnet, Steps 1-3)
- Built `code/build/build_od_weather_cells.py`; ran for 08,09 (~2.5 min/month). Filters mirror clean_hvfhv.py + not_aar + in_month. Independent per-rule fail counts in output/sum/od_cells_filter_attrition_2021.csv.
- Note: do_zone_le_263 drops ~3.8% of raw rows (DO zone 264/265), inherited from the clean_hvfhv rule set.
- Sept weather NaN share: pu_precip 0.945% / do_precip 0.971% (below the 1% stop, just barely); Aug 0%. temp 0%.
- Sept peak pu_precip_mm = 80.7 mm at 2021-09-01 21:00 EDT (tz check OK). Aug cell max 61.8 mm at 2021-08-27 17:00 EDT (plan said Aug should be < Ida's 58 mm; 58 mm appears to be a citywide-hourly-mean figure, cell-level zone max is 80.7 for Ida).
- R script `driver_share_weather_bins.r` has a 3rd arg mode "ident" for the identifying-variation check (separate session).
- Temp bin labels changed from "[15,20)"-style to "15-20" etc (lt0,0-5,...,ge30; left-closed) because i() mangled labels containing ')' in etable.
- Aug benchmark: feols ~95 s, peak R working set ~6.8-7.3 GB (PowerShell: Rscript spawns child R.exe, so poll Get-Process R; use [double] for Max). N cells 8,893,115 / trips 13,816,975; 0 NA-weather cells. Ident: pu_temp 48.2%, pu_precip 89.8% variance remains after FEs. 30 singleton obs dropped; vcov "not PD, fixed" warning from fixest (Aug has few date clusters/bins with 0 obs).

## Storm-bin check (2026-09-30 ~23:40, read-only on the full-year cells)
- 2021 origin-rain bins (trips / distinct days): 25-40 = 59k / 12 days; 40-60 = 9.4k / 6; 60+ = 19.5k / 3. Of the ≥40 mm/h trips, 87% are on 2021-09-01 (Ida).
- Days with the top zone-hour rain: 09-01 (80.7 mm), 07-08 (62.3), 08-27 (61.8, thunderstorm), 07-02 (53.0), 08-22 (52.5), 08-21 (44.8), 06-08, 07-09.
  These match dates of named systems (Elsa early July, Henri 08-21/22, Ida 09-01), but also include non-tropical convective storms of equal hourly intensity. Verify against NHC reports before labelling.
- Conclusion: no finer top bins (above 40 a bin = a few Ida hours). Hourly bins can't separate a tropical storm from an equally intense thunderstorm, and they miss flooding after the rain stops. Proposed to the user: named-storm-window indicators and cumulative/lagged rain bins.

## Revision 2026-09-30 (DO 265 kept, no temperature, 12 rain bins)
- Build: do_zone_le_263 -> do_zone_ne_264; DO 265 kept; NaN gate on in-NYC destinations; per-month CSV upsert; --no-write option; NaN gate now a warning (July 1.19%: 12 whole-city hours missing upstream).
- All 12 monthly cell files built (2.8 GB). 01-06 stats rebuilt with --no-write (files untouched, first build in this session).
- March: 68 cells at nonexistent 02:00 (all weather NaN, dropped in R); 38 duplicate tz-aware keys after shift_forward (naive keys unique). Nov: 28,362 cells touch 01:00, no dup keys.
- R: temperature removed; outside_nyc not auto-dropped by fixest (SE 165) -> passed as second ref level in i().
- Aug+Sep: feols 230.8 s, peak 15.7 GB (earlier run 16.4 GB); Aug-only new spec 110.7 s, 8.1 GB. Full-year projection ~90-97 GB: borderline/no-go vs 90 GB cap.

## Revision 2 (user)
- Keep 11 current-hour rain bins; add 10 bins for rain over the previous 6 h (t−6..t−1, ≥5 of 6 hours present) at origin & destination via a separate lookup parquet (no cell rebuild). Memory option 1 (trim before feols). Stars fixed to 0.01/0.05/0.10. No storm dummies/wind/temp.
- Concern: the design matrix grows from 22 to 42 columns, so memory may still exceed 90 GB after the trim. The agent measures Aug+Sep both with and without the 6h bins to separate the trim from the extra columns.
- User (2026-09-30): drop rows with missing weather. Already done in the R script (NA current-hour or 6h rain at origin, or at in-NYC destination → dropped; DO-265 kept). This covers the 68 Mar-14 02:xx trips and the July/Sept MRMS-gap hours. Cell files are left as built.

## Revision 2 (6h rain, trim, stars)
- New code/build/build_rain6h_lookup.py -> clean_data/rain6h_zone_hour_2021.parquet (NaN 0.594%, p99 17.0, max 212.6).
- R script rewritten: Arrow tz-aware joins, trim, spec cur|r6, stars 0.01/0.05/0.10. Trim equivalence: max |diff| 4.8e-14.
- Aug+Sep: A (cur, trim) 219 s / 12.6 GB; B (r6) 408 s / 21.1 GB; Aug B 199 s / 10.7 GB. Full-year B projection ~122 GB: fails 90 GB.

## Revision 3 (user, 2026-10-01)
- Spec B in feols projects to 122 GB (> cap). The user chose option 1: an exact batched FWL estimator. Success = coefs/SEs/significance identical to feols (tolerance 1e-6 rel; stars and N identical), validated on Aug+Sep A and B and Aug B before the full-year run.
- Exact merge across dates measured: 18.3M→12.9M cells (−30%), ≈86 GB. Rejected.

## Revision 3 (exact batched FWL)
- New code/analysis/fwl_batched.r (+ fwl_compare.r); driver has 4th arg engine feols|fwl.
- Validation vs feols (rel diff <= 4e-11 coef/SE, p <= 5e-12, stars/N/coef set identical): Aug+Sep B, Aug+Sep A, Aug B. K and adj factors identical.
- Memory fixes: env-consumed inputs, batch 3, chunk 2e6 (peak transient was the 5M-row scores chunk). Aug+Sep B peak 11.0 GB.
- Full year spec B FWL: N 106,438,465 cells, 2993 s wall, peak 59.1 GB (projection 58.3 GB).
- Tex underscore-escape bug in fwl_etable_tex (double backslash) fixed in source; the 2021 tex was repaired by hand-edit (same content as a rerun).

## Result (2026-10-01) — full-year spec B via batched FWL
- Validation, independently re-checked from the fwl_vs_feols_*.csv files: max rel diff coef 3.4e-11, SE 1.1e-11, p 4.5e-12; stars identical in all 3 runs (Aug+Sep B, Aug+Sep A, Aug B). N, K, adj identical. fixest default is K.fixef "nonnested" (the plan said "nested"; the agent followed fixest).
- Full year: 106,438,465 cells / 171.4M trips; 49.9 min; peak 59.1 GB. Outputs output/{reg,fig,sum}/driver_share_weather_bins_2021.*
- Large magnitudes, few days: origin current-hour ≥40 mm +0.107 (6 days); origin prev-6h 50–75 −0.083 (12 days), ≥75 −0.074 (6 days). Everything else |β| < 0.03.
- Loose ends: the .tex notes say "N cells = 106,438,499", which is before removing 34 singletons; the Observations row (106,438,465) is correct. FE rows are labelled pu_fe/do_fe. The val_/val4_ outputs are still on disk. Nothing committed.
- Revision 4 (user): decompose driver share into log fare and log pay (+ log share = log pay − log fare, exact by linearity). Needs Σlog columns → rebuild into clean_data/od_weather_cells_2021_v2 (no overwrite). Multi-outcome FWL, validated vs feols on Aug+Sep.

## Revision 4 (fare/pay decomposition)
- v2 cells (clean_data/od_weather_cells_2021_v2) = v1 + sum_log_fare/sum_log_pay; identical to v1 in all 12 months (output/sum/od_cells_v1_v2_check.csv).
- fwl_fit is multi-outcome; validated vs feols multi-LHS on Aug+Sep (all 4 outcomes pass, rel <= 2e-9). Identity log_share = pay - fare: 3.7e-8 abs at default tol (same in feols), 6.8e-14 at demean tol 1e-12.
- Full year decomp: 3552 s wall (FWL 3458 s), peak 61.0 GB; outputs driver_share_decomp_2021.{tex,png,rds}.

## Result (2026-10-01) — fare/pay decomposition, full year
- v2 cells (clean_data/od_weather_cells_2021_v2) match v1 in all 12 months. Multi-outcome FWL validated vs feols multi-LHS on Aug+Sep (independently re-checked: max rel coef 2e-9, SE 3e-11, p 1e-11; stars identical for all 4 outcomes).
- Full year: 61.0 GB peak, 59 min. Outputs output/{reg,fig}/driver_share_decomp_2021.*
- Identity log_share = log_pay − log_fare holds to ~1e-7 at the default demean tol (feols shows the same deviation); 1e-10 needs tol 1e-12 (~3 h). Judged negligible vs SEs ~1e-3; not rerun.
- Pattern: origin current-hour rain raises fare and pay almost one-for-one (share flat) up to 40 mm/h; at ≥40, pay +0.335 vs fare +0.286. Origin prev-6h ≥50 mm: fare rises more than pay → share falls. Destination rain: fare/pay barely move; the small share increases come from pay rising slightly relative to fare.
