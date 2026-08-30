#!/usr/bin/env python3
"""
Hook: pre-compact.py
Fires on PreCompact.
Saves current task state to the most recent session log before context compression.
Output goes to stderr (stdout is ignored during PreCompact).
"""

import json
import sys
import os
import glob
from datetime import datetime, timezone

LOGS_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
PLANS_DIR = os.path.expanduser("~/.claude/plans")

def get_most_recent_log() -> str | None:
    pattern = os.path.join(LOGS_DIR, "*.md")
    logs = glob.glob(pattern)
    if not logs:
        return None
    return max(logs, key=os.path.getmtime)

def get_most_recent_plan() -> str | None:
    try:
        plans = glob.glob(os.path.join(PLANS_DIR, "*.md"))
        if not plans:
            return None
        return max(plans, key=os.path.getmtime)
    except Exception:
        return None

def append_compaction_note(log_path: str, plan_path: str | None):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    plan_ref = os.path.basename(plan_path) if plan_path else "none"
    note = (
        f"\n---\n"
        f"**[COMPACTION NOTE — {timestamp}]**  \n"
        f"Auto-compact triggered. Active plan: `{plan_ref}`.  \n"
        f"Resume by reading CLAUDE.md + most recent plan + `git log --oneline -5`.\n"
        f"---\n"
    )
    with open(log_path, "a") as f:
        f.write(note)

def main():
    plan_path = get_most_recent_plan()
    log_path = get_most_recent_log()

    # Print recovery checklist to stderr — visible to Claude after compaction
    checklist = (
        "\n[PRE-COMPACT] Context compression imminent. State saved.\n\n"
        "Recovery checklist for next message:\n"
        "  1. Read CLAUDE.md (project spec + variable glossary)\n"
        "  2. Read most recent plan in ~/.claude/plans/\n"
        "  3. Run: git log --oneline -5\n"
        "  4. Read most recent session log in .claude/logs/\n"
        "  5. State what you understand the current task to be\n"
    )
    if plan_path:
        checklist += f"\nActive plan: {plan_path}\n"
    if log_path:
        checklist += f"Session log:  {log_path}\n"

    print(checklist, file=sys.stderr)

    if log_path:
        try:
            append_compaction_note(log_path, plan_path)
        except Exception as e:
            print(f"[PRE-COMPACT] Could not append to log: {e}", file=sys.stderr)

    sys.exit(0)

if __name__ == "__main__":
    main()
