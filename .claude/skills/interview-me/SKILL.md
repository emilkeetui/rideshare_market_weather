---
name: interview-me
description: Interactive interview to formalize a research idea into a structured specification with hypotheses and empirical strategy
argument-hint: "[brief topic or 'start fresh']"
allowed-tools: ["Read", "Write"]
---

# Research Interview

Conduct a structured interview to formalize a research idea into a concrete specification.

**Input:** `$ARGUMENTS` — a brief topic description or "start fresh" for open-ended exploration.

---

## How This Works

This is a **conversational** skill. Ask questions one or two at a time, probe based on
answers, and build toward a structured research specification document.

**Do NOT use AskUserQuestion.** Ask questions directly in text responses. Wait for answers.

---

## Interview Structure

### Phase 1: Big Picture (1-2 questions)
- "What phenomenon are you trying to understand?"
- "Why does this matter? Who should care about the answer?"

### Phase 2: Theoretical Motivation (1-2 questions)
- "What's your intuition for what drives this?"
- "What would standard theory predict? Do you expect something different?"

### Phase 3: Data and Setting (1-2 questions)
- "What data do you have? What would you ideally want?"
- "Is there a specific context, time period, or institutional setting?"

### Phase 4: Identification (1-2 questions)
- "Is there a natural experiment or source of variation you can exploit?"
- "What's the biggest threat to a causal interpretation?"

### Phase 5: Expected Results (1-2 questions)
- "What would you expect to find? What would surprise you?"
- "What would the results imply for policy or theory?"

### Phase 6: Contribution (1 question)
- "How does this differ from existing work? What's the gap?"

---

## After the Interview

Produce a **Research Specification Document** and save to `.claude/logs/research-spec-[topic].md`.

```markdown
# Research Specification: [Title]
Date: YYYY-MM-DD

## Research Question
[One sentence]

## Motivation
[2-3 paragraphs]

## Hypothesis
[Testable prediction with expected direction]

## Empirical Strategy
- Method: [e.g., 2SLS]
- Treatment: [What varies]
- Control: [Comparison group]
- Instrument: [If IV]
- Key identifying assumption: [What must hold]
- Robustness checks: [Pre-trends, placebos, etc.]

## Data
- Primary dataset: [Name, coverage]
- Key variables: [Treatment, outcome, controls]
- Sample: [Unit of observation, time period, N]

## Expected Results
[What to find and why]

## Contribution
[How this advances the literature]

## Open Questions
[Issues raised during the interview]
```
