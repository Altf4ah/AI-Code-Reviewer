# AI PR Reviewer

A GitHub Action that automatically reviews pull requests using Claude. It fetches the PR diff, sends it to Claude for structured analysis, and posts inline comments directly on the changed lines — flagging security issues, bugs, and performance problems.

**Live demo:** open any PR in this repo to see it in action.

---

## What it does

When a PR is opened or updated, the action:

1. Fetches the diff via the GitHub REST API
2. Filters out noise files (lock files, minified JS, generated code, images)
3. Chunks large PRs into batches to respect context window limits
4. Sends each chunk to Claude with a structured prompt demanding JSON output
5. Posts inline review comments pinned to specific diff lines, with severity badges

Example output on a PR:

> 🔴 **CRITICAL** — **SQL injection via string format**
>
> `query = f"SELECT * FROM users WHERE id = {user_id}"` — user-controlled input is interpolated directly into the SQL string. Use parameterized queries: `cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))`.

---

## Setup

### 1. Add secrets

In your repo → Settings → Secrets → Actions, add:

| Secret | Value |
|--------|-------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |

`GITHUB_TOKEN` is provided automatically by GitHub Actions.

### 2. Copy the workflow

The workflow file lives at `.github/workflows/ai-review.yml`. Commit it to your repo and it will activate on the next PR.

### 3. Adjust permissions (if needed)

The workflow needs `pull-requests: write`. If your org restricts this, set it in Settings → Actions → General → Workflow permissions.

---

## Architecture

```
pull_request event
       │
       ▼
.github/workflows/ai-review.yml    ← triggers the runner
       │
       ▼
reviewer/main.py                   ← orchestrator
       │
       ├── github_client.py        ← fetches diff, posts comments
       │       GitHub REST API v3
       │
       └── claude_client.py        ← sends diff chunks to Claude
               Anthropic Messages API
               Model: claude-opus-4-5
```

### Key design decisions

**Structured JSON output.** The system prompt instructs Claude to return a JSON object with a fixed schema (`path`, `line`, `severity`, `title`, `body`). This makes parsing deterministic and avoids regex heuristics on prose. The client strips accidental markdown fences before parsing.

**Chunking for large PRs.** PRs touching many files are split into batches of 8 files per API call. Results are merged and posted in a single GitHub review. This avoids hitting token limits while keeping each call focused.

**File filtering.** Lock files, minified assets, generated code, and binary files are skipped before any API call. This reduces cost and avoids Claude commenting on things no human wrote.

**Inline comments vs. summary.** The GitHub Reviews API allows posting comments pinned to specific diff lines in a single request (`POST /pulls/:number/reviews`). If a line number doesn't match the actual diff (422 response), the client falls back to posting comments individually and drops any that can't be placed.

**Graceful degradation.** If Claude returns malformed JSON, a fallback summary comment is posted instead of crashing the action.

---

## Extending this

- **Add language-specific rules** — extend `SYSTEM_PROMPT` with language-aware checks (e.g. Django-specific CSRF patterns, React hook rules).
- **Track review metrics** — log severity counts to a dashboard (Grafana, Datadog) to measure code quality trends over time.
- **Critic loop** — run a second Claude call to verify the first reviewer's findings before posting, reducing false positives.
- **Cost guard** — count approximate tokens before each API call and skip oversized diffs with a warning comment.

---

## Local testing

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export GITHUB_TOKEN=ghp_...
export REPO_NAME=your-org/your-repo
export PR_NUMBER=42
export HEAD_SHA=abc123...
export BASE_SHA=def456...

pip install -r requirements.txt
python -m reviewer.main
```

---

## Limitations

- Line number matching relies on GitHub's `patch` field. Diff hunks don't always expose every line; Claude is instructed to use only visible `+` lines, but occasional mismatches will fall back gracefully.
- Very large monorepo PRs (500+ files) will hit GitHub's 100-file API limit. Pagination support is the next improvement.
- Claude may occasionally flag false positives. Severity levels (`critical` / `warning` / `info`) help triage — treat `info` as optional reading.
