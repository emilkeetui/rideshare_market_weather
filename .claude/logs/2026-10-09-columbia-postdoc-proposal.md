# Session: 2026-10-09 — Columbia Climate School postdoc research proposal

## Objective
Draft a research proposal for the Columbia Climate School Postdoctoral Research Program
(proposed mentor: Dr. Jacqueline M. Klopp, CSUD). Structure follows the FIFA research
prospectus (v10); argument from "Research design assignments"; estimation and data from
paper_outline_slides.pdf. Delivered as a Claude Doc:
https://claude.ai/code/artifact/00d86dd2-4bda-43cb-b4d5-788eb150fa8e

## Design Decisions
| Decision | Rationale |
|----------|-----------|
| Supply proxy = request-to-pickup wait; on_scene dispatch delay as Uber-only check | Dictionary says on_scene is AV-only; 2026-10-02 audit found it populated for Uber only |
| Event time = onset of peak rainfall (21:00 EDT 1 Sep 2021), not HURDAT2 landfall | Ida's remnants made no NYC landfall |
| Flood IV framed as conditional on rainfall, strongest for surge storms | Rain shifts demand directly, so rainfall-path IV fails exclusion unconditionally |
| Regulatory-boundary RD contingent on NJ trip data | TLC data cover only NYC-origin trips |
| Preliminary evidence from 2021 OD-cell regressions + driver-pay-institutions log | Already computed; framed as motivating, not answering |

## Verification
- CoVe claim-verifier: 19 claims; 3 FAIL fixed (Castillo 2025 Econometrica + finding: drivers lose;
  Chen et al. 2019 is JPE; statute is General Business Law §396-r, governor's declaration),
  2 PARTIAL reworded/cited as WP. Columbia program page blocked (Cloudflare); program rules not verified.

## Open Questions
- Applicant name/affiliation and PhD details are placeholders.
- Appointment length (assumed two years) and program proposal format/length unverified.
- Whether to credit Xibo Wan (author of the slides) in the proposal.

## Revision 1 (user, 2026-10-09)
- Audience changed to economists; Xibo Wan added as co-author; scope = all storms 2019–2026 (stacked design primary);
  NJ boundary RD and Route 2 data contingencies removed ("we have all the data we need").
- Program page fetched via Wayback (June 2026 snapshot): proposal max 5 pages double-spaced, 11pt, 1-inch margins,
  refs excluded, title required, must address global sustainable development; mentoring team of 2+ encouraged;
  12-month appointment + possible 12-month extension; 2025 cycle deadline was Oct 31 (2026 date unconfirmed).
- Rewrote doc body (~2,300 words) with a two-sided markup/markdown model: s = (1 - 1/eps_D - c/p)/(1 + 1/eps_S).
  Likely still over the 5-page cap; flagged to user. Cengiz et al. (2019) added from memory, not CoVe-verified.

## Revision 2 (user, 2026-10-09): cut to 5 pages, keep user's voice
- Rebuilt body from user's own sentences (Research design assignments 1-3; paper_outline_slides), grammar fixes only.
- Restored slides' storm-track IV wording (replacing rain x elevation IV); slides' efficient-surge vs rent-extraction
  table + transit-competition row from Assignment 3. Dropped unsourced "$5.2bn / 80,000 drivers" figures.
- Body ~1,350 words + 2 equations + 1 table (est. ~5 double-spaced pages; verify after export).
- References trimmed to the 12 still cited.

## Revision 3 (user): $5.2bn/80,000 drivers restored; saved as Overleaf LaTeX
- proposal/columbia_postdoc_proposal.tex (standalone, thebibliography + natbib). Compiles with 0 errors/undefined refs; body ends on p.5 (~half page spare), refs on p.6.
- Statute bibitem removed (natbib author-year needs a year; statute named in text). Not committed.

## Revision 4 (user, 2026-10-11): Data section moved before Empirical Strategy
- New "3 Data and Variables" (prose + single-spaced Table 1 defining Y outcomes, FloodExposed, EventHour, X, demand/supply proxies, transit disruption, IV + controls); strategy text now refers back to Table 1 instead of defining variables inline.
- Preliminary evidence split into its own section after the strategy.
- Assumption flagged to user: X_{z,t} defined as hourly zone rainfall (was undefined). "k hours from landfall" -> "from the event hour" (consistent with Rev. 0 decision).
- Compiles, 0 errors/overfull; body ends p.5, refs p.6. Not committed.

## Revision 5 (user, 2026-10-11): accurate Ida driver shares + preliminary-evidence spec
- Recomputed from raw 2021-09 HVFHV (agg. sum pay / sum fare; clean filters, excl. WAV/AAR/DO 1,264,265): Uber 90.7% (21:00) -> 72.8% (00:00), normal Sep 84.6%; Lyft 72.1% -> 44.5%, normal 72.8%. Old text implied Lyft started at 89% — corrected.
- Preliminary Evidence now states sample (2021, filters from build_od_weather_cells.py, 171.4M trips / 106.4M cells), the spec-B equation from driver_share_weather_bins.r, and coefs (-0.0827, -0.0738).
- Body now runs ~1/4 page onto p.6 (over 5-page cap) — flagged to user.
