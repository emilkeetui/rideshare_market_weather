#!/usr/bin/env python3
"""
Hook: verify-reminder.py
Fires on PostToolUse for Write and Edit.
Non-blocking reminder to run the script end-to-end after editing R or Python files.
60-second dedup window to avoid repeated messages.
"""

import json
import sys
import os
import time

CACHE_FILE = os.path.join(os.path.dirname(__file__), ".verify_reminder_cache")
DEDUP_SECONDS = 60
RESEARCH_EXTENSIONS = {".r", ".py"}
SKIP_PATTERNS = {"claude.md", "settings", "hooks", "rules", "skills", "agents", ".json", ".md"}

def is_research_file(path: str) -> bool:
    if not path:
        return False
    path_lower = path.lower()
    ext = os.path.splitext(path_lower)[1]
    if ext not in RESEARCH_EXTENSIONS:
        return False
    for skip in SKIP_PATTERNS:
        if skip in path_lower:
            return False
    return True

def within_dedup_window() -> bool:
    try:
        mtime = os.path.getmtime(CACHE_FILE)
        return (time.time() - mtime) < DEDUP_SECONDS
    except FileNotFoundError:
        return False

def touch_cache():
    with open(CACHE_FILE, "w") as f:
        f.write(str(time.time()))

def main():
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool = hook_input.get("tool_name", "")
    if tool not in ("Write", "Edit"):
        sys.exit(0)

    path = hook_input.get("tool_input", {}).get("file_path", "")
    if not is_research_file(path):
        sys.exit(0)

    if within_dedup_window():
        sys.exit(0)

    touch_cache()
    filename = os.path.basename(path)
    print(
        f"\n[VERIFY] {filename} was modified. "
        f"Run the script end-to-end to confirm expected output before marking this task done.",
        file=sys.stderr
    )
    sys.exit(0)

if __name__ == "__main__":
    main()
