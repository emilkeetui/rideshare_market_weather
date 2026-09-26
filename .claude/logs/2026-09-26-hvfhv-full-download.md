# Session: 2026-09-26 — HVFHV full-history download (2020-04 → latest)

## Objective
Download all NYC HVFHV monthly trip-record parquet files from 2020-04 to the latest
published month (2026-07 as of today) into `raw_data/hvfhv/`.

## Inventory before download
- Local: 2021-08 … 2021-12 (5 files, sizes match remote).
- TLC bucket: 2019-02 … 2026-07 available (90 files, 40.86 GB); 2026-08 not yet posted.
- NYC Open Data: yearly HVFHV datasets 2019–2024 only; same records, not used for bulk.
- Pre-2019 `fhv_tripdata` (2015-01 … 2019-01) has no fare/pay — excluded.

## Design Decisions
| Decision | Rationale |
|----------|-----------|
| Start at 2020-04 (user correction; plan originally proposed 2019-02) | User choice |
| Bulk CloudFront parquet, not Socrata API | Same records, far smaller/faster |
| Never overwrite an existing raw file on size mismatch — log + skip | raw_data read-only rule |
| Generalise download_hvfhv.py with --start/--end; defaults keep Aug–Dec 2021 | Reproducibility of the original pull |

## Schema drift (from remote footers)
- 2019-02: `airport_fee`, `wav_match_flag` null-typed.
- 2026-07: adds `cbd_congestion_fee`; PU/DOLocationID INT32 (INT64 in 2021).

- Full scan adds: 2020-04 and 2020-10 airport_fee also null-typed; from 2023-02
  strings are large_string and PU/DOLocationID int32; cbd_congestion_fee from 2025-01.
- Deviation from plan: manifest written to clean_data/hvfhv_download_manifest.csv
  (not raw_data/hvfhv/) because it is rewritten each run.

## Verification Results
- [x] Script exit 0; 71 downloaded at ~40 MB/s (~14 min), 5 skipped, no FAIL/MISMATCH
- [x] 76 files (2020-04 … 2026-07), 33.42 GB, sizes = manifest, no .part left
- [x] Footer row counts: 4.3M (2020-04 COVID low) → 11–22M thereafter; total 1,337,878,593
- 2026-08/09 not yet published

## Open Questions / Blockers
- None.

## Next Steps
- clean_hvfhv.py multi-year schema union (not in scope).
- Re-run `download_hvfhv.py --start 2020-04 --end latest` monthly to pick up new months.
