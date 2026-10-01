# Session: 2026-09-30 — NYC driver-pay institutions (background research)

## Objective
Summarize the rules and practice governing the driver's share of fare at Uber, Lyft, Via, Juno
in NYC, 2019–2026, with citations; deliver as a Claude Doc ("NYC Rideshare Driver Pay Rules, 2019–2026").

## Changes Made
- No project code or data files changed. Scratch scripts in the session scratchpad:
  `driver_share_by_year.py` (Sep 2020–25, Jul 2026 samples) and `ida_daily.py` (Sep 2021 daily/hourly).
- Read-only scans of raw_data/hvfhv (column/row filters pushed into duckdb).

## Design Decisions
| Decision | Rationale |
|---|---|
| Sampled one month per year instead of all 76 months | Full scan ~2 h (>10 min threshold); samples sufficient for trend |
| Floor = TLC non-WAV in-city rate; excluded DO zones 1/264/265, WAV, AAR | Out-of-town and WAV trips have different floors |
| Reddit / UberPeople not quoted | Reddit blocks crawler; UberPeople serves crawler paywall. Used press, Comptroller, unions |

## Key findings
- Floor fixed Feb 2020–Feb 2022 at $1.104/mi, $0.502/min (no 2021 CPI adj.) — no rule change in the Ida window.
- Sep 2021: Uber ~15% of trips at floor (slack), Lyft ~62%; by Jul 2026 77% / 87%.
- Aggregate driver share Uber 85% (2020) -> 77% (2026); Lyft ~72–81%.
- Ida night 22:00–02:00 EDT: fares ~3x floor; Uber pay ~2.1–2.5x floor (share 89%->72%); Lyft pay ~1.5x (share to 45%).
- Via (HV0004) driver_pay often 0 — hourly pay model; driver_share not interpretable.

## Verification Results
- [x] Assumed floor rates validated: <3% of Uber/Lyft trips pay below them in sampled months
- [x] CoVe claim-verifier: 28 claims, 24 PASS, 4 PARTIAL (wording fixed), 0 FAIL

## Open Questions / Next Steps
- Consider `fare_over_floor` / `pay_over_floor` as zone-hour outcomes (not yet in glossary).
