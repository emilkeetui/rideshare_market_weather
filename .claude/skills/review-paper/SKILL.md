---
name: review-paper
description: Comprehensive manuscript review covering argument structure, DiD/event-study validity, econometric specification, welfare interpretation, citation completeness, and potential referee objections. Use for reviewing the chapter or related papers.
argument-hint: "[paper filename in lit/ or path to .tex/.pdf]"
allowed-tools: ["Read", "Grep", "Glob", "Write", "Task"]
---

# Manuscript Review

Produce a thorough, constructive review — the kind a top-field referee would write.

**Input:** `$ARGUMENTS` — path to a paper (.tex or .pdf), or a filename in `lit/`.

---

## Steps

1. **Locate and read the manuscript.** Check direct path, then `lit/`.

2. **Read the full paper** end-to-end. For long PDFs, read in 5-page chunks.

3. **Evaluate across 7 dimensions** (see below).

4. **Generate 3-5 "referee objections"** — tough questions a top-5 journal referee would ask.

5. **Save to** `.claude/logs/paper-review-[name].md`

---

## Review Dimensions

### 1. Argument Structure
- Research question clearly stated?
- Introduction motivates the question?
- Logical flow: question → method → results → conclusion?
- Conclusions supported by evidence? Limitations acknowledged?

### 2. Identification Strategy (most critical for this project)
- Is the treatment — storm exposure at the taxi-zone level — measured credibly, and is
  the exposure measure (gridded rainfall, wind, flood reports) defensible at the spatial
  and temporal resolution the design claims?
- Is the comparison group plausibly a counterfactual? Unaffected NYC zones are close in
  time and market but may be **spillover-contaminated** — riders and drivers move across
  zones, so SUTVA is a live threat, not a formality. Does the paper confront this?
- Is the event window defensible, and is the timezone of the event timing stated?
- **Anticipation:** pre-landfall demand and price movement is a prediction of the theory,
  not just a pre-trends violation. Does the paper model anticipation explicitly rather
  than absorbing it into "post"?
- Selection: zones that flood are not random. Are they poorer, lower-lying, further from
  Manhattan? Does the design lean on zone FE alone, and is that enough?
- Robustness: continuous vs. binary exposure, placebo events (Tropical Storm Henri,
  matched calm weeks), airport-zone exclusion, alternative time FE?
- For the cross-city (Chicago) design: is fare comparability established against the
  actual Chicago schema, or assumed?

### 3. Econometric Specification
- Correct standard errors (taxi-zone clustered; is two-way zone × date considered)?
- With one storm and a modest number of zones, is the effective number of clusters large
  enough for asymptotic inference? Is randomization/permutation inference considered?
- Appropriate FE structure (zone + time)?
- Event study reported with an explicit reference period, and before any single-coefficient DiD?
- Is the price measure well-defined? The fare is directly observed
  (`base_passenger_fare`), so the question is not measurement but **composition**: does
  the paper control for the fact that trips taken during the storm differ in length,
  duration, and routing? Per-mile/per-minute normalization or OD-pair fixed effects
  should be doing that work. If a residualized fare index is used instead, check it was
  fit out of sample on a pre-storm window.
- Is the panel balanced, and are zero-trip zone-hours handled explicitly (zeros vs. missing)?
- Economically meaningful effect sizes, not just statistical significance?

### 4. Welfare and Interpretation (project-specific)
- Are **transfers** (higher fares on trips that still happened), **deadweight loss**
  (foregone trips), and **driver risk compensation** kept separate? Summing them into a
  single "consumer loss" is a substantive error.
- Is the revenue result decomposed into volume and price? A revenue number without its
  decomposition is not an adaptation result.
- Does the paper distinguish platform revenue from driver earnings from consumer surplus?
- Is any surge-pricing normative claim (price gouging vs. efficient rationing) argued
  rather than assumed?
- Does the paper avoid presupposing the sign of the revenue effect in its framing?

### 5. Literature Positioning
- Key literatures cited: climate/weather adaptation by firms and consumers; ride-share
  and platform/surge pricing; transportation demand under weather shocks; disaster
  economics and evacuation behavior?
- Contribution clearly differentiated from existing work?
- Missing citations a referee would flag?

### 6. Writing Quality
- Clarity, concision, academic tone
- Consistent notation (variable names match between text and tables)
- Abstract effectively summarizes the paper
- Tables and figures self-contained (labels, notes, sources)

### 7. Presentation
- Tables: column headers identify the design and sample? Sample sizes in footnotes?
- Clustering level and event-study reference period stated in the notes?
- Event-study figure present, with pre-period leads visible and landfall marked?
- Volume, price, and revenue outcomes shown together?
- Map of the treatment footprint (exposure by taxi zone) present?

---

## Output Format

```markdown
# Manuscript Review: [Paper Title]
Date: YYYY-MM-DD

## Summary Assessment
**Overall:** [Strong Accept / Accept / R&R / Reject]

[2-3 paragraphs: main contribution, strengths, key concerns]

## Strengths
1. ...

## Major Concerns
### MC1: [Title]
- Dimension: [Argument / Identification / Econometrics / Welfare / Literature / Writing / Presentation]
- Issue: ...
- Suggestion: ...
- Location: ...

## Referee Objections
### RO1: [Question]
Why it matters: ...
How to address: ...

## Ratings
| Dimension | Score (1-5) |
|---|---|
| Argument | |
| Identification | |
| Econometrics | |
| Welfare & interpretation | |
| Literature | |
| Writing | |
| Presentation | |
| **Overall** | |
```
