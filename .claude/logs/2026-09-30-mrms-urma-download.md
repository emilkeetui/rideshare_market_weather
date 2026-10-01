# Session: 2026-09-30 — mrms-urma-zone-hour-2019-2026

## Objective
Hourly rainfall (MRMS) and 2 m temperature (URMA) per taxi zone, 2019-01-01 → latest, cropped at download.
Plan: `~/.claude/plans/hashed-knitting-owl.md`. Branch `weather-grids-2019-2026`.

## Changes Made
- code/build/weather_grid_utils.py, download_mrms_qpe.py, download_urma_t2m.py, build_weather_panel.py (new)
- raw_data/weather/nyc_crop_box.json; pilot day files (2021-08-31..09-02, 2020-10-13/14) under mrms/ and urma/
- clean_data/mrms_download_manifest.csv, urma_download_manifest.csv (pilot rows; 2020-10-14 has duplicate rows from a --force re-pull — keep last)

## Design Decisions
| Decision | Rationale |
|----------|-----------|
| MRMS source switches at 2020-10-14 20Z (not 00Z) | IEM GaugeCorr last file 10-14 12Z (IEM has gap 13-19Z); AWS Pass2 first file 10-14 20Z. 7 hours missing on that day (dry). |
| URMA stored as `t2m_c` (°C) | GDAL GRIB driver returns TMP already converted to °C (GRIB_UNIT [C]); plan said Kelvin. |
| Merge MRMS+URMA once across all years in build step | avoids duplicate keys at UTC/local year edges |
| `--force` flag on MRMS downloader | needed to rewrite one day file after source-switch fix (hook blocks deletes) |

## Pilot results
- MRMS grids for both products identical (52x66 cells, 0.01°); URMA crop 32x31 (LCC 2.5 km); URMA crop == full-file band 3 (max diff 4e-7).
- Peak NYC-mean hour: file 02Z → datetime_hour 2021-09-01 21:00 EDT; ASOS KNYC p01i 3.15 in at 01:51Z Sep 2 (=21:51 EDT). Consistent.
- URMA (Central Park cell) vs ASOS KNYC tmpf: mean diff −0.2 °C, sd 0.8, range −1.8..+2.3.
- Zone weights sum to 1.000 for all 263 zones; cells/zone MRMS 1–51 (median 8), URMA 1–13 (median 3).
- Pilot build: peak precip hour 2021-09-01 21:00 EDT (timezone gate passes).
- Speed ≈ 6 s/day each (AWS, 8 workers); IEM ≈ 11 s/day. Stored crop ≈ 35 KB/day MRMS, ≈ 25 KB/day URMA.

## Open Questions / Blockers
- Full run (≈2,830 days) awaits user approval: ~413 GB URMA + ~45 GB MRMS transfer; ~4–5 h each if run in parallel.
- No level-shift test at the GaugeCorr→Pass2 break possible from the pilot (dry days); run after full pull.

## Next Steps
- Approve → launch both downloaders in background → build_weather_panel.py → verification gates → /commit.

## Update 2026-09-30 17:01 — full run in progress
- User approved the measured cost; both downloaders launched in background at 15:03 (nohup, stdout buffered so logs are empty; progress tracked by counting day files).
- Pace ≈ 6 s/day per stream; at 17:01 mrms=1149, urma=1272 of ~2836 day files. ETA URMA ~19:30, MRMS ~20:30.
- Monitor false alarm: `pgrep` is unavailable in this shell; monitors now only count files.
- Next: when both reach ~2836, dedupe manifests (keep last), build_weather_panel.py, run verification gates, then commit on branch after user confirms.

## Update 2026-09-30 19:07 — URMA done, MRMS finishing
- URMA complete: 2829 day files (2019-01-01..2026-09-29), 410 GB transferred, 14,157 s.
- Expected day count is 2829 (earlier "~2836" target was a miscount); monitor re-pointed at MRMS=2829.
- MRMS at 2521/2829 at 19:07; ETA ~19:50.
- Next: dedupe manifests (keep last), check missing hours, build_weather_panel.py, verification gates, GaugeCorr→Pass2 level-shift check, commit after user confirms.

## Update 2026-09-30 evening — full run complete, panel built
- MRMS: 2829 day files, 35 GB transferred; 99 missing hours (0.15%, all 404; by year 2019:7, 2020:26, 2021:36, 2022:21, 2023:6, 2024:3). URMA: 2829 days, 410 GB; 108 missing hours (0.16%), all in 2020.
- Manifests deduped to clean_data/{mrms,urma}_download_manifest_dedup.csv (originals untouched; MRMS had 24 duplicate rows from the 2020-10-14 --force re-pull).
- clean_data/weather_zone_hour.parquet: 17,856,911 rows x 7 cols, 136 MB, 263 zones, 2018-12-31 18:00 EST .. 2026-09-29 19:00 EDT.
- Gates: keys unique; 2021 citywide peak = 2021-09-01 21:00 EDT (58.1 mm); annual rain/zone 928–1446 mm (2019-2025 full years; 2025 low=928); temp −17.8..40.2 °C; Aug 2021 mean 25.0 °C; hours/zone/year = 8760/8784; NaN share ≈0.15% matches manifest; R reads datetime_hour as America/New_York, pu_zone_id int.
- Product break: no overlap in time between GaugeCorr (to 2020-10-14 12Z) and Pass2, so a level shift can't be tested directly; annual means 2019–2020 (1324, 1128) are within the 2021–2024 range (1110–1446). `mrms_product` column carries the indicator.
- Open: 2025 annual total (928 mm) is lowest; 2026 partial. Not investigated.
