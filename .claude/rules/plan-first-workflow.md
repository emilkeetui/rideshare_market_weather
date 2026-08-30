# Plan-First Workflow

**For any non-trivial task, enter plan mode before writing code.**

## The Protocol

1. **Enter Plan Mode** — use `EnterPlanMode`
2. **Check MEMORY** — read any relevant memory entries for this task
3. **Requirements Specification (complex/ambiguous tasks)** — use `AskUserQuestion` for up
   to 3-5 clarifying questions before drafting the plan
4. **Draft the plan** — what changes, which files, in what order
5. **Save to disk** — the plan mode system saves to `~/.claude/plans/` automatically
6. **Present to user** — wait for approval via `ExitPlanMode`
7. **Save initial session log** — capture goal and key context in `.claude/logs/`
8. **Implement via orchestrator** — see `orchestrator-research.md`

## Non-Trivial Threshold

Enter plan mode when ANY of these apply:
- Task touches more than 2 files
- Task modifies a regression specification or pipeline step
- Task requires a new data build step
- Requirements are ambiguous ("improve", "analyze", "fix the tables")
- Task will take more than 10 minutes
- Task requires downloading new source data (TLC months, weather grids, Chicago TNP) —
  plan the download size and target folder before pulling anything
- Task touches the timezone/weather merge, where an error is silent rather than loud

Skip plan mode for: obvious typo fixes, single-line patches, adding a comment.

## Session Logs

After plan approval, immediately create a session log:
```
.claude/logs/YYYY-MM-DD-<short-topic>.md
```

Log: objective, approach, key decisions, verification results, open questions.

## Context Survival

Before context compression (triggered automatically):
- `pre-compact.py` hook saves state and prints a recovery checklist
- After compression, first message: read CLAUDE.md + most recent plan + `git log --oneline -5`

## Plans on Disk

Plans survive compression. The plan mode system saves them to `~/.claude/plans/`.
Reference them after compression with the recovery checklist above.

## For All Tasks: Before Acting

Even when plan mode is not triggered:
- State assumptions explicitly — don't silently choose one interpretation.
- If multiple interpretations exist, surface them and ask.
- If a simpler approach exists, say so and push back.
- If something is unclear, stop and name what's confusing before proceeding.

## When Editing Existing Code

- Touch only what the task requires — don't improve adjacent code or formatting.
- If you notice unrelated dead code, mention it; don't delete it.
- Remove only the imports, variables, or functions that *your* changes made unused.
