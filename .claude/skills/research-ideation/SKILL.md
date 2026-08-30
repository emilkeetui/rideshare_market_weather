---
name: research-ideation
description: Generate structured research questions, testable hypotheses, and empirical strategies from a topic or dataset
argument-hint: "[topic, phenomenon, or dataset description]"
allowed-tools: ["Read", "Grep", "Glob", "Write"]
---

# Research Ideation

Generate structured research questions, testable hypotheses, and empirical strategies.

**Input:** `$ARGUMENTS` — a topic, phenomenon, or dataset description.

---

## Steps

1. **Understand the input.** Read `$ARGUMENTS`. Check `lit/` for related papers.
   Read `CLAUDE.md` for project context and existing empirical strategy.

2. **Generate 3-5 research questions** ordered descriptive → causal:
   - **Descriptive:** What are the patterns?
   - **Correlational:** What factors are associated?
   - **Causal:** What is the effect?
   - **Mechanism:** Through what channel?
   - **Policy:** What are the implications?

3. **For each question, develop:**
   - **Hypothesis:** Testable prediction with expected sign
   - **Identification strategy:** DiD, IV, RDD, synthetic control
   - **Data requirements:** What's needed and whether it exists in the project
   - **Key assumptions:** What must hold
   - **Potential pitfalls:** Common threats
   - **Related literature:** 2-3 papers

4. **Rank by feasibility and contribution.**

5. **Save to** `.claude/logs/research-ideation-[topic].md`

---

## Principles

- Think like a referee: immediately identify the identification challenge for causal questions
- Prioritize questions answerable with the existing data (TLC HVFHV zone × hour panel
  merged to gridded rainfall, wind, and 311 flood reports)
- Start from the three designs in CLAUDE.md — within-city spatial DiD, simple
  before/after, and the NYC-vs-Chicago cross-city DiD — and say which one a question needs
- **Firm and consumer adaptation is the frame.** Good questions here distinguish price
  adaptation from quantity adaptation, and platform revenue from driver earnings from
  consumer surplus. A question that can only speak to one of the three is narrower than
  it looks — say so.
- Do not presuppose the sign of the revenue effect. A question whose interest depends on
  revenue rising is a weaker question than one that is interesting either way.
- Extreme-weather events are rare and clustered; be explicit about how many treated
  events a design actually has and what that does to inference
- Flag when a question needs data the project does not yet have (driver-side supply
  decisions, rider identities, rejected/unfilled requests, competitor modes) rather than
  proposing a proxy without saying it is one
