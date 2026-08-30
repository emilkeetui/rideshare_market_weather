---
name: lit-review
description: Structured literature search and synthesis with citation extraction and gap identification
argument-hint: "[topic, paper title, or research question] [--no-verify]"
allowed-tools: ["Read", "Grep", "Glob", "Write", "WebSearch", "WebFetch", "Task"]
---

# Literature Review

Conduct a structured literature search and synthesis on the given topic.

**Input:** `$ARGUMENTS` — a topic, paper title, research question, or phenomenon.

---

## Steps

1. **Parse the topic** from `$ARGUMENTS`. If a specific paper is named, use it as the anchor.

2. **Search for related work (local corpus first):**
   - Check `lit/` directory for uploaded PDFs
   - Read any existing `.bib` files in the project for papers already cited
   - Use `WebSearch` to find recent publications (if available)
   - Use `WebFetch` for working-paper repositories (NBER, SSRN, RePEc) when reachable

3. **Organize findings** into:
   - **Theoretical contributions** — mechanisms, frameworks
   - **Empirical findings** — key results, effect sizes, data sources
   - **Methodological innovations** — identification strategies, estimators
   - **Open debates** — unresolved disagreements

4. **Identify gaps and opportunities**

5. **Extract citations** in BibTeX format

6. **Save the report** to `.claude/logs/lit-review-[topic].md`

---

## Output Format

```markdown
# Literature Review: [Topic]
Date: YYYY-MM-DD

## Summary
[2-3 paragraph overview]

## Key Papers

### [Author (Year)] — [Short Title]
- **Contribution:** [1-2 sentences]
- **Method:** [Identification strategy / data]
- **Finding:** [Result with effect size]
- **Relevance:** [Why it matters for this project]

## Gaps and Opportunities
1. [Gap 1]
2. [Gap 2]

## BibTeX Entries
[bibtex entries]
```

## Post-Flight Verification (mandatory, CoVe)

Before returning the draft review to the user, run the Post-Flight Verification protocol in
[`.claude/rules/post-flight-verification.md`](../../rules/post-flight-verification.md).
Literature reviews are **very high** hallucination risk: WebSearch can return
plausible-sounding fabricated citations, and this skill cannot reliably catch its own
mistakes. CoVe catches them architecturally.

1. **Extract claims** — every cited paper, every paraphrased finding ("Smith 2019 shows X"),
   and every negative-literature assertion ("no prior work studies Y") is one atomic claim.
2. **Generate verification questions** per claim (author/year/venue correct? finding and
   sign/magnitude actually reported? gap claim honest?).
3. **Spawn `claim-verifier`** via `Task` (`subagent_type=claim-verifier`, fresh context).
   Pass the claims table, the verification questions, and source pointers (URLs, DOIs,
   `lit/` paths). **Do NOT pass the draft prose** — the fresh-context independence is what
   makes CoVe work.
4. **Reconcile:** PASS → attach the green Post-Flight block; PARTIAL → flag unverifiable
   claims with uncertainty markers in text and BibTeX; FAIL → **remove or rewrite the
   contradicted citations** before returning. Never ship a FAIL.

**Skip conditions:** `--no-verify` flag, or the user hands you ≤3 papers they have already
read and confirmed. Append the Post-Flight block (collapsed) to the report.

---

## Important

- **Do NOT fabricate citations.** If you cannot verify a paper's details, flag it for verification. Post-Flight Verification catches most fabrications automatically; this rule is the backup.
- Note working papers vs. published papers — working papers may change.
- Prioritize work using similar identification strategies (spatial DiD / event studies
  around weather shocks) and the four core literatures for this project: climate and
  extreme-weather adaptation by firms and consumers; ride-share platform and surge
  pricing; transportation demand under weather shocks; disaster economics and
  evacuation behavior.
- Verify factual data/event claims too, not just citations — storm timing, rainfall
  records, and dataset schema details are as fabricable as a reference.
