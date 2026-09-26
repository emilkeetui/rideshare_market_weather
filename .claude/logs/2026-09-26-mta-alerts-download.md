# Session: 2026-09-26 — MTA service alerts download

## Objective
Download raw MTA service alerts (data.ny.gov `7kct-peq7`) for NYCT Subway and NYCT Bus,
April 2020 onward, as the substitute-mode disruption source. Panel construction deferred.

## Changes Made
- code/build/download_mta_alerts.py: new SODA downloader, agency × year CSVs into
  raw_data/subway/mta_alerts/

## Design Decisions
| Decision | Rationale |
|----------|-----------|
| Subway + NYCT Bus (not LIRR/MNR/B&T) | User choice; bus is the other within-city substitute |
| One CSV per agency × year | Resume-safe; only the current, growing year is re-pulled |
| `date` stored untouched (no tz conversion) | Source is a floating timestamp; tz verified via Ida spot check, not assumed |
| No parsing of affected/header | User asked to defer construction |

| **`date` is UTC, not local** | Ida suspensions start 2021-09-02 02:14 (=22:14 EDT), ~20 min after ASOS KNYC peak rain 01:51 UTC; alert trough at 08-09 (=4-5am local), 1 h earlier in Jun-Jul than Jan-Feb (DST). Convert once in the consuming build step |

## Verification Results
- [x] Script runs end-to-end (exit 0, ~2 min); second run skips 2020-2025, re-pulls 2026 only
- [x] Row counts match server count(*) per file: Subway 291,401; Bus 102,145; 0 duplicate alert_id (subway 2021)
- [x] Ida suspensions appear 02:00-07:00 UTC on 2021-09-02 = evening/night of 2021-09-01 EDT
- Note: NYCT Bus alerts effectively start 2021 (only 5 rows in 2020)

## Open Questions / Blockers
- Pre-April-2020 coverage would need the GTFS-RT archive (not in scope)

## Next Steps
- Parse `affected` + `header` into line × hour suspension panel when needed
