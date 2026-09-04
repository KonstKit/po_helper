# Gitleaks findings — разбор 18 leaks в истории main (август 2026)

Source: scheduled security-scans runs on main — 2026-08-30 (run
`33301479641`, artifact `gitleaks-results.sarif`, gitleaks 8.24.3) and
2026-08-31 (run `33374329819`). Both failed with `leaks found: 18`.
The repo is **private**, which limits exposure but does not remove it:
anyone with repo read access (current/future collaborators, CI logs)
can read the history.

## Verdict summary

| Group | Rule | Files | Commit | Classification |
|---|---|---|---|---|
| 1 | `atlassian-api-token` | `analysis_output/runs/*.csv` (17 findings) | `3d169f5` (2026-01-23; purged rewrite: `d558c0e`) | **False positive** |
| 2 | `generic-api-key` | `backend/test_gitlab_sync.py` (1 finding) | `c31e420` (initial commit, 2025-12-14; purged 2026-09-04, rewritten to `75c8152`) | **Resolved: rotated + purged** |

## Group 1 — false positives (17)

The static-analysis exports under `analysis_output/runs/` list function
names with metadata. The function `listConfluencePagesLocal`
(`frontend/src/services/api/knowledge.ts`) is **exactly 24 characters
long** and appears in an Atlassian-flavored context, which is what the
`atlassian-api-token` rule matches (a 24-char base62 token after a
Confluence keyword). It is an ordinary exported function name inside
generated CSV tooling output, not a credential.

All 17 findings are the same function name in three CSV variants
(`methods.csv`, `unused_prod.csv`, `unused_with_tests.csv`) across six
analysis runs in one commit. The whole `analysis_output/` tree was
later removed from the tip but remains in history.

Remediation: a path-based allowlist for `analysis_output/` in the
repo-root `.gitleaks.toml` (committed alongside this report) — no
rotation needed.

## Group 2 — real-looking GitLab token (1) — RESOLVED

`backend/test_gitlab_sync.py`, initial commit `c31e420` (pre-purge content shown; the value below was replaced with `***REMOVED***` in the purged history):

```python
GITLAB_TOKEN = "wSiGrq8…(redacted, full value in history)"  # Common token
# Test repositories - use one accessible by the token
"…/Andersen/primacare/backend"  # This token has access to this project
```

- Old-format GitLab personal access token (20 chars, pre-`glpat-` style).
- The comments (Common token / this token has access to this project)
  read like a **real shared token**, not a dummy.
- The file no longer exists on `main` — only in history.

### Resolution (2026-09-04)

1. **Token rotated** on the GitLab side by the maintainer — the
   historical value is inert.
2. **History purged** the same day: `git filter-repo --replace-text`
   replaced the value with `***REMOVED***` across all 204 commits and
   the rewritten `main` was force-pushed (verified: zero occurrences
   of the value anywhere in the new history). Merged remote branches
   were deleted so no stale ref kept the old objects reachable.
3. The `.gitleaks.toml` entry for this finding was **removed** —
   nothing to baseline anymore; any recurrence of the value would be
   flagged by the scanner again.

## Why not rewrite history right away

Rotation already neutralizes the leaked value. History rewrite without
rotation changes nothing for an attacker who already copied the token;
history rewrite with rotation is a hygiene bonus. Since a force-push
rewrites the shared `main`, it needs an explicit go-ahead from the
maintainer.
