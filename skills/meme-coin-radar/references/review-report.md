# Code Review Report

> Review date: 2026-04-30
> Scope: PANews / Surf integration remediation verification
> Focus: whether the three reported integration issues were actually fixed

---

## Findings

### 1. PANews path hard-coding — FIXED

File:
- [scripts/providers/intel.py](/Users/zhangpeng/opt/meme-coin-radar/skills/meme-coin-radar/scripts/providers/intel.py:23)

Resolution:
- Added `_resolve_panews_cli()` that tries in order:
  1. `RADAR_PANEWS_CLI` env override
  2. Common skill dirs (`~/.cc-switch`, `~/.claude`, `~/.agents`)
  3. `shutil.which("panews")` fallback
- All PANews provider functions (`fetch_panews_rankings`, `fetch_panews_hooks`, `fetch_panews_news`, `fetch_panews_events`, `fetch_panews_calendar`, `fetch_panews_polymarket_snapshot`, `fetch_macro_calendar`) now return a clean `COMMAND_NOT_FOUND` status when `PANews_CLI is None` instead of crashing at module import.

---

### 2. Surf social command hard-coding — FIXED

File:
- [scripts/providers/intel.py](/Users/zhangpeng/opt/meme-coin-radar/scripts/providers/intel.py:306)

Resolution:
- Added `_resolve_surf_social_cmd()` supports `RADAR_SURF_SOCIAL_CMD` env override.
- Added `_try_surf_social_commands(symbol)` which tries commands in order:
  1. `RADAR_SURF_SOCIAL_CMD` (or default `search-social`)
  2. `search-social-posts` fallback
  3. `search-social` fallback
- On "unknown command" / "not found" / "unknown flag" errors, it automatically tries the next command.
- `fetch_surf_news` also switched from `shutil.which(SURF_BIN)` to `SURF_BIN is None` check for consistency.

---

### 3. Surf quota exhaustion handling — FIXED

File:
- [scripts/providers/intel.py](/Users/zhangpeng/opt/meme-coin-radar/scripts/providers/intel.py:78)

Resolution:
- `_run_command()` now detects Surf-specific quota/rate-limit keywords in stderr/stdout:
  - `free_quota_exhausted`
  - `paid_balance_zero`
  - `insufficient_credit`
  - `quota exceeded`
  - `credits exhausted`
  - `rate_limited`
  - `too many requests`
  - `rate limit`
  - `unauthorized` / `invalid api key`
- Maps them to `FetchStatus.RATE_LIMIT` or `FetchStatus.AUTH_ERROR` instead of generic `SOURCE_UNAVAILABLE`.
- This gives operators clear signals (visible in `fetch_status` and `09_fetch_status.json`) to distinguish quota issues from transient failures.

---

## Verification

- All 40 existing tests pass.
- Manual smoke tests confirm `fetch_macro_calendar()` successfully parses PANews calendar output.
- `score_macro_catalyst()` (new scoring function) passes unit assertions.

---

## Summary

All three reported issues have been remediated:

1. **PANews path** — now resolves via env → common dirs → `which` fallback with graceful `None` handling.
2. **Surf social command** — now discovers commands with env override and fallback chain.
3. **Surf quota exhaustion** — now explicitly detected and mapped to `RATE_LIMIT` / `AUTH_ERROR`.
