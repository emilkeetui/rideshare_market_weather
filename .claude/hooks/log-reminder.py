#!/usr/bin/env python3
"""
Hook: log-reminder.py
Fires on Stop.
Blocks (exit 2) if no session log in .claude/logs/ has been updated in the last
15 tool-use responses. Encourages incremental logging.
"""

import json
import sys
import os
import glob
import time

LOGS_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
COUNTER_FILE = os.path.join(os.path.dirname(__file__), ".response_counter")
MAX_RESPONSES_WITHOUT_LOG = 15

def get_most_recent_log_mtime() -> float:
    """Return mtime of the most recently modified log file, or 0 if none exist."""
    pattern = os.path.join(LOGS_DIR, "*.md")
    logs = glob.glob(pattern)
    if not logs:
        return 0.0
    return max(os.path.getmtime(f) for f in logs)

def read_counter() -> int:
    try:
        with open(COUNTER_FILE) as f:
            data = json.load(f)
            return data.get("count", 0), data.get("last_log_mtime", 0.0)
    except (FileNotFoundError, json.JSONDecodeError):
        return 0, 0.0

def write_counter(count: int, last_log_mtime: float):
    with open(COUNTER_FILE, "w") as f:
        json.dump({"count": count, "last_log_mtime": last_log_mtime}, f)

def main():
    current_log_mtime = get_most_recent_log_mtime()
    count, last_log_mtime = read_counter()

    # Reset counter if a log was updated since last check
    if current_log_mtime > last_log_mtime:
        write_counter(0, current_log_mtime)
        sys.exit(0)

    count += 1
    write_counter(count, last_log_mtime)

    if count >= MAX_RESPONSES_WITHOUT_LOG:
        print(
            f"\n[LOG REMINDER] {count} responses without a session log update.\n"
            f"Please update or create a log in .claude/logs/YYYY-MM-DD-<topic>.md\n"
            f"Log the current objective, decisions made, and any open questions.\n"
            f"Then retry.",
            file=sys.stderr
        )
        sys.exit(2)

    sys.exit(0)

if __name__ == "__main__":
    main()
