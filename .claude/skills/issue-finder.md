---
name: issue-finder
description: Fast codebase traversal and issue finder — scans the omni-leadgen pipeline for bugs, security issues, performance problems, and missing error handling using vexp + Serena.
---

# Issue Finder — omni-leadgen

When this skill is invoked, perform a **comprehensive automated audit** of the codebase.

## Step 1 — Graph-ranked context scan

Call `run_pipeline` with the audit task to get the highest-centrality files and their relationships:

```
run_pipeline({
  "task": "audit entire pipeline for bugs, security issues, silent failures, missing error handling, and performance problems",
  "preset": "debug",
  "max_tokens": 12000,
  "include_file_content": true
})
```

## Step 2 — Parallel issue sweep

Spawn **5 parallel Explore agents**, each focused on a specific issue category. Pass the vexp context from Step 1 into each agent prompt so they don't need to re-query the codebase.

### Agent 1 — Security
Focus: hardcoded secrets, credentials in code, SQL injection risks, SMTP credential exposure, token leakage in logs, unvalidated external input (job URLs, company names, Hunter API responses), open redirect risks in Flask routes.

### Agent 2 — Silent failures & error handling
Focus: bare `except Exception: pass` blocks, functions that return empty string on failure without logging, missing retries on network calls, DB writes that don't catch `sqlite3.OperationalError`, LLM calls with no fallback, IMAP/SMTP errors swallowed silently.

### Agent 3 — Performance & concurrency
Focus: N+1 DB queries (calling `get_all_leads()` then looping), sequential operations that should be parallel, missing DB indexes for common filters, SQLite write contention under ThreadPoolExecutor, unbounded memory usage (large lists kept in RAM), blocking calls on Flask request threads.

### Agent 4 — Data quality & pipeline correctness
Focus: leads that get stuck in wrong status (e.g. enriched but never drafted), email deduplication gaps, duplicate company detection (same company different capitalisation), missing `follow_up_at` on old sent leads, leads with null `decision_maker_email` marked as `enriched`, email body truncation edge cases in `sanitize_text()`.

### Agent 5 — Dead code & maintainability
Focus: unused imports, duplicate logic between `enricher.py` and `multi_enricher.py`, functions defined but never called, config values set but never read, scripts that overlap in functionality (drafter.py vs draft_emails.py), overly long functions (>80 lines) that should be split.

## Step 3 — Synthesis

After all agents complete, produce a **prioritised issue report**:

```
## Issue Report — omni-leadgen

### 🔴 Critical (fix before next push)
- [issue] — [file:line] — [why it matters]

### 🟡 Important (fix this sprint)
- [issue] — [file:line] — [why it matters]

### 🟢 Low priority (good to have)
- [issue] — [file:line] — [why it matters]

### ℹ️ Observations
- [pattern or structural note that isn't a bug but is worth knowing]
```

For each issue include:
- Exact file and line number
- One-sentence description of the bug/risk
- Suggested fix (one line or code snippet)

## Output rules
- Do NOT fix issues during this skill — report only
- Do NOT re-read files you already have from vexp context
- Deduplicate findings across agents before reporting
- If an agent finds nothing in its category, say "✅ None found" — don't pad
