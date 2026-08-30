---
name: context-status
description: |
  Show current context status and session health.
  Use to check how much context has been used, whether auto-compact is
  approaching, and what state will be preserved.
allowed-tools: ["Read", "Bash", "Glob"]
---

# /context-status — Check Session Health

Show the current session status including context usage estimate, active plan, and
session log state.

## Workflow

### Step 1: Find Active Plan

```bash
ls -lt ~/.claude/plans/*.md 2>/dev/null | head -3
```

### Step 2: Find Session Log

```bash
ls -lt .claude/logs/*.md 2>/dev/null | head -1
```

### Step 3: Check Hook Configuration

```bash
cat .claude/settings.json
```

### Step 4: Report Status

```
Session Status
─────────────────────────────────
Active Plan:   [path or "none"]
Session Log:   [path or "none — create one in .claude/logs/"]

Hook Configuration
  • protect-raw-data:  [configured / missing]
  • verify-reminder:   [configured / missing]
  • log-reminder:      [configured / missing]
  • pre-compact:       [configured / missing]

Preservation Check
  • Pre-compact hook saves: active plan path, current task, session log note
  • After compression: read CLAUDE.md + most recent plan + git log --oneline -5
```

## Notes

- Context % is not directly observable — watch for slowdowns as a signal
- If auto-compact is imminent, ensure session log is current before it fires
- All important state is saved to disk (plans in ~/.claude/plans/, logs in .claude/logs/)
