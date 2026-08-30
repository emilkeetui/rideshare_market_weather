#!/usr/bin/env python3
"""
Hook: protect-raw-data.py
Fires on PreToolUse for Bash, Write, and Edit.
Hard-blocks (exit 2) any operation that would write to raw_data/.

Exception: this project acquires most of its raw data by download (TLC parquet,
MRMS/Stage IV GRIB, ASOS, 311, Chicago TNP), so NEW files may be written into the
registered download folders below. Destructive operations are still blocked there.
Add a folder to EXEMPT_DIRS only when a build script needs to download into it.
"""

import json
import sys
import os
import re

WRITE_VERBS = {">", ">>", "write", "rm", "unlink", "mv", "cp", "del",
               "truncate", "tee", "touch", "mkdir", "install", "move", "copy"}

# Destructive verbs are blocked ANYWHERE in raw_data, including exempt download dirs.
DESTRUCTIVE_VERBS = {"rm", "unlink", "del", "truncate", "mv", "move"}

# Narrow exception: NEW source downloads may be written into these subfolders only.
# Existing raw data stays read-only; destructive ops here are still blocked above.
EXEMPT_DIRS = (
    "raw_data/hvfhv",
    "raw_data/taxi_zones",
    "raw_data/weather",
    "raw_data/flooding",
    "raw_data/chicago_tnp",
    "raw_data/subway",
)

# Regex alternation of the exempt leaf names, used to find non-exempt raw_data refs.
_EXEMPT_LEAVES = "|".join(d.split("/", 1)[1] for d in EXEMPT_DIRS)
_NON_EXEMPT_RE = re.compile(r"raw_data/(?!(?:%s))" % _EXEMPT_LEAVES)


def _is_exempt(normalized: str) -> bool:
    return any(ex in normalized for ex in EXEMPT_DIRS)


def check_bash(command: str) -> bool:
    """Return True (block) if command writes into raw_data/ outside an exempt dir."""
    cmd_lower = command.lower().replace("\\", "/")
    if "raw_data/" not in cmd_lower:
        return False
    tokens = set(cmd_lower.split())
    # Always block destructive ops targeting raw_data, even in exempt download dirs.
    if tokens & DESTRUCTIVE_VERBS:
        return True
    write_attempt = bool(tokens & WRITE_VERBS) or ">" in command
    if not write_attempt:
        return False
    # Allow the write only if every raw_data/ reference is inside an exempt subfolder.
    return bool(_NON_EXEMPT_RE.search(cmd_lower))


def check_path(path: str) -> bool:
    """Return True (block) if path is inside raw_data/ but not an exempt download dir.

    Matches both absolute paths (".../raw_data/x") and project-relative paths
    ("raw_data/x") — Write/Edit are routinely called with the latter.
    """
    normalized = path.replace("\\", "/").lower()
    in_raw = (
        "/raw_data/" in normalized
        or normalized.startswith("raw_data/")
        or normalized.endswith("/raw_data")
        or normalized == "raw_data"
    )
    if not in_raw:
        return False
    return not _is_exempt(normalized)


def main():
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    blocked = False

    if tool == "Bash":
        command = tool_input.get("command", "")
        if check_bash(command):
            blocked = True
            print(
                f"\n[BLOCKED] raw_data/ is strictly read-only.\n"
                f"Command attempted: {command[:200]}\n"
                f"All pipeline outputs must go to clean_data/.\n"
                f"New downloads are allowed only in: {', '.join(EXEMPT_DIRS)}",
                file=sys.stderr
            )

    elif tool in ("Write", "Edit"):
        path = tool_input.get("file_path", "")
        if check_path(path):
            blocked = True
            print(
                f"\n[BLOCKED] raw_data/ is strictly read-only.\n"
                f"Attempted to write: {path}\n"
                f"All pipeline outputs must go to clean_data/.\n"
                f"New downloads are allowed only in: {', '.join(EXEMPT_DIRS)}",
                file=sys.stderr
            )

    sys.exit(2 if blocked else 0)


if __name__ == "__main__":
    main()
