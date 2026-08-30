---
name: commit
description: Stage, commit, create PR, and merge to main. Use for the standard commit-PR-merge cycle.
argument-hint: "[optional: commit message]"
allowed-tools: ["Bash", "Read", "Glob"]
---

# Commit, PR, and Merge

Stage changes, commit with a descriptive message, create a PR, and merge to main.

## Steps

0. **If this is not yet a git repo** (`git rev-parse --git-dir` fails), stop and offer to
   `git init`. Write `.gitignore` first — `raw_data/`, `clean_data/`, `output/`, `lit/`,
   `.claude/settings.local.json`, `.claude/logs/` (optional), `__pycache__/` — before the
   first `git add`, so the multi-GB data folders are never staged.

1. **Check current state:**

```bash
git status
git diff --stat
git log --oneline -5
```

2. **Create a branch** from the current state:

```bash
git checkout -b <short-descriptive-branch-name>
```

3. **Stage files** — add specific files (never use `git add -A`):

```bash
git add <file1> <file2> ...
```

Do NOT stage `.claude/settings.local.json` or any files containing secrets.
Do NOT stage anything in `raw_data/` or `clean_data/` (data is not versioned).

4. **Commit** with a descriptive message:

If `$ARGUMENTS` is provided, use it as the commit message. Otherwise, analyze the staged
changes and write a message that explains *why*, not just *what*.

```bash
git commit -m "$(cat <<'EOF'
<commit message here>

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

5. **Push and create PR:**

```bash
git push -u origin <branch-name>
gh pr create --title "<short title>" --body "$(cat <<'EOF'
## Summary
<1-3 bullet points>

## Test plan
<checklist>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

6. **Merge and clean up:**

```bash
gh pr merge <pr-number> --merge --delete-branch
git checkout main
git pull
```

7. **Report** the PR URL and what was merged.

## Important

- Always create a NEW branch — never commit directly to main
- Exclude `settings.local.json`, `raw_data/`, `clean_data/`, `output/`, `lit/` from staging.
  HVFHV parquet files are ~1 GB each — never let one reach the index.
- Use `--merge` (not `--squash` or `--rebase`) unless asked otherwise
- Never push without being explicitly asked
