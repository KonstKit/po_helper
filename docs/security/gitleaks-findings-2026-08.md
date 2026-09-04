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
| 1 | `atlassian-api-token` | `analysis_output/runs/*.csv` (17 findings) | `3d169f5` (2026-01-23) | **False positive** |
| 2 | `generic-api-key` | `backend/test_gitlab_sync.py` (1 finding) | `c31e420` (initial commit, 2025-12-14) | **Real-looking credential — rotate** |

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

## Group 2 — real-looking GitLab token (1) — ACTION REQUIRED

`backend/test_gitlab_sync.py`, initial commit `c31e420`:

```python
GITLAB_TOKEN = "wSiGrq8…(redacted, full value in history)"  # Common token
# Test repositories - use one accessible by the token
"…/Andersen/primacare/backend"  # This token has access to this project
```

- Old-format GitLab personal access token (20 chars, pre-`glpat-` style).
- The comments (Common token / this token has access to this project)
  read like a **real shared token**, not a dummy.
- The file no longer exists on `main` — only in history.

### Required actions

1. **Rotate the token now** (GitLab: revoke the token whose value is
   visible at the commit link above / via git history, issue a new one,
   update consumers). The value is deliberately redacted in this report
   so the tip does not republish it. Rotation makes the
   historical copy inert — the single most important step, and it is
   outside git. Only the maintainer can do this.
2. Optional, after rotation: purge the history (`git filter-repo
   --replace-text` with the token, or BFG) and force-push. Destructive
   for every clone; coordinate first. After a purge, remove the token
   entry from `.gitleaks.toml` so any recurrence is re-flagged.
3. The finding is baselined in `.gitleaks.toml` by commit + path (the
   value is not copied anywhere on the tip), so the nightly scan
   reflects reality instead of failing forever. Any leak of the token
   in any other file or commit still fails the scan.

## Why not rewrite history right away

Rotation already neutralizes the leaked value. History rewrite without
rotation changes nothing for an attacker who already copied the token;
history rewrite with rotation is a hygiene bonus. Since a force-push
rewrites the shared `main`, it needs an explicit go-ahead from the
maintainer.
