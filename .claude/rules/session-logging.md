# Session Logging

**Location:** `.claude/logs/YYYY-MM-DD-<topic>.md`

## Three Triggers (all proactive)

### 1. Post-Plan Log
After plan approval, immediately create a log capturing:
- Objective and approach
- Key context (which dataset, which regression spec)
- Any assumptions made during planning

### 2. Incremental Logging
Append 1-3 lines whenever:
- A design decision is made (e.g., "used continuous `precip_max_mm` rather than binary
  `affected` as the headline treatment")
- A problem is solved (e.g., "weather grid was UTC — converted to America/New_York in
  build_weather_panel.py; event window had been 4 hours off")
- The user corrects something (always log corrections)
- The approach changes mid-task

Do not batch — log immediately while the reasoning is fresh.

### 3. End-of-Session Log
When wrapping up:
- High-level summary of what was accomplished
- Quality scores (if applicable)
- Open questions or blockers
- Next steps

## Log Template

```markdown
# Session: YYYY-MM-DD — <topic>

## Objective
[What this session set out to accomplish]

## Changes Made
- [file]: [what changed and why]

## Design Decisions
| Decision | Rationale |
|----------|-----------|
| | |

## Verification Results
- [ ] Script runs end-to-end
- [ ] Output exists at expected path
- [ ] Row counts plausible

## Open Questions / Blockers
-

## Next Steps
-
```

## The `log-reminder.py` Hook
After 15 responses without a log update, the Stop hook will block and remind you.
This is a feature, not a bug — incremental logging prevents context loss.
