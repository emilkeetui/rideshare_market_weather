# Post-Flight Verification (Chain-of-Verification / CoVe)

**For outputs with high fabrication risk — literature reviews above all — verify claims
in fresh context before returning to the user.**

WebSearch can return plausible-sounding but fabricated citations, and a drafting model is
poorly placed to catch its own confident mistakes. CoVe fixes this architecturally: a
separate agent re-derives the facts from primary sources without seeing the draft prose.

## When to run

- **Mandatory:** `/lit-review` output, and any deliverable that asserts specific citations,
  effect sizes, or "no prior work on X" gap claims.
- **Skip conditions:**
  - `--no-verify` flag — user opts out for speed.
  - User hands you ≤3 papers they have personally read and confirmed.

## The protocol

1. **Extract claims.** Each cited paper, each paraphrased finding ("Smith 2019 shows X"),
   and each negative-literature assertion ("no prior work studies Y") is one atomic claim.
2. **Generate verification questions** per claim — specific and checkable: "Does Smith
   (2019, *JEEM*) actually report a decline in X? Are the author, year, and venue correct?"
3. **Spawn `claim-verifier`** via the `Task` tool (`subagent_type=claim-verifier`, fresh
   context). Pass the claims table, the verification questions, and source pointers (URLs,
   DOIs, `lit/` paths). **Do NOT pass the draft prose** — the fresh-context independence is
   what makes CoVe work.
4. **Reconcile against the verdict:**
   - **PASS** → attach a green Post-Flight block.
   - **PARTIAL** → flag each unverifiable claim with an uncertainty marker (in-text and in
     the BibTeX block), then attach an amber block.
   - **FAIL** → **remove or rewrite the contradicted citations** using the verifier's
     evidence before returning. Never ship a FAIL.

## Output block format

Append to the deliverable (collapsed by default):

```markdown
<details>
<summary>Post-Flight Verification — [PASS 🟢 | PARTIAL 🟡 | FAIL→fixed 🔴]</summary>

- Claims checked: N
- PASS: n / PARTIAL: n / FAIL: n
- Flagged / removed: [list, or "none"]
- Verifier: claim-verifier (fresh context, CoVe)
</details>
```
