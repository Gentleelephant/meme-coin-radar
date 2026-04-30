# Optimization Report

> Date: 2026-04-30
> Topic: PANews / Surf integration reliability gaps
> Purpose: organize concrete follow-up work for agent implementation

---

## Summary

The current social/news intel layer has three real integration risks:

1. `PANews` CLI path is hard-coded
2. `surf` social command name is version-sensitive and currently hard-coded
3. `surf` quota / free-tier exhaustion is not explicitly classified or circuit-broken

These are reliability issues, not scoring-model issues.

---

## Confirmed Gaps

### 1. PANews path is hard-coded

File:
- [scripts/providers/intel.py](/Users/zhangpeng/opt/meme-coin-radar/skills/meme-coin-radar/scripts/providers/intel.py:22)

Current code:
- `PANews_CLI = Path("/Users/zhangpeng/.cc-switch/skills/panews/scripts/cli.mjs")`

Problem:
- works only on one specific user/machine layout
- breaks portability across machines, accounts, CI, containers, or repo relocation

Status:
- confirmed in code

### 2. Surf social command is hard-coded as `search-social`

File:
- [scripts/providers/intel.py](/Users/zhangpeng/opt/meme-coin-radar/skills/meme-coin-radar/scripts/providers/intel.py:247)

Current code:
- `surf search-social --q ...`

Problem:
- if `surf 1.0.6` renamed this surface to `search-social-posts`, current code will fail on newer installations
- command compatibility is guessed, not discovered

Status:
- code-level risk confirmed
- local shell in this session does not have `surf` installed, so the exact live surface could not be re-verified here
- if agent already observed the rename on `surf 1.0.6`, treat it as a real compatibility issue

### 3. Surf quota exhaustion is not explicitly handled

Files:
- [scripts/providers/intel.py](/Users/zhangpeng/opt/meme-coin-radar/skills/meme-coin-radar/scripts/providers/intel.py:36)
- [scripts/providers/intel.py](/Users/zhangpeng/opt/meme-coin-radar/skills/meme-coin-radar/scripts/providers/intel.py:292)

Problem:
- provider failures are degraded generically
- there is no explicit classification for:
  - quota exhausted
  - credits exhausted
  - top-up required
  - HTTP 402 / 429 style errors
- there is also no circuit breaker, so the scan may keep retrying a provider that is known to be exhausted

Status:
- handling gap confirmed in code
- whether your current Surf account is already exhausted was not verifiable in this shell because `surf` is unavailable here

---

## Recommended Fixes

### P0. Make PANews CLI resolution configurable

Recommended resolution order:

1. environment variable `RADAR_PANEWS_CLI`
2. executable from `shutil.which("panews")`
3. current local fallback path

Suggested behavior:

- if `RADAR_PANEWS_CLI` points to a file, use `["node", path, ...]`
- if `panews` binary exists, call it directly
- only use the hard-coded path as last-resort compatibility fallback

Benefit:
- removes user-home coupling
- makes CI and multi-machine usage practical

### P0. Add Surf command discovery / compatibility fallback

Recommended approach:

1. support env override:
   - `RADAR_SURF_BIN`
   - `RADAR_SURF_SOCIAL_CMD`
2. if social command is `auto`, detect it once per process:
   - try `surf list-operations`
   - or try `surf <candidate> --help`
3. choose in this order:
   - `search-social-posts`
   - `search-social`

Cache:
- cache the detected command in-process so each scan does not rediscover it repeatedly

Benefit:
- survives Surf CLI surface changes
- avoids hard-coding one version’s command name

### P0. Explicitly classify Surf quota / rate-limit errors

Recommended detection patterns:

- `quota`
- `credit`
- `top up`
- `402`
- `429`
- `rate limit`
- `too many requests`

Recommended mapping:

- `429` / throttling -> `FetchStatus.RATE_LIMIT`
- quota / credit exhausted -> introduce `quota_exhausted` if desired, otherwise map to `RATE_LIMIT` with a precise message

Benefit:
- makes diagnostics actionable
- avoids mixing “provider down” with “billing exhausted”

### P1. Add Surf circuit breaker

Recommended behavior:

- if Surf returns quota/rate-limit exhaustion once, disable further Surf calls for the rest of the scan
- optionally persist a short TTL marker in cache, e.g. 1 to 6 hours

Suggested cache keys:

- `intel_cache_surf_disabled.json`
- or `intel_cache_surf_health.json`

Benefit:
- avoids repeated failing calls
- reduces latency and noisy logs
- preserves PANews + OKX fallback quality

### P1. Add provider feature flags

Recommended flags:

- `RADAR_ENABLE_SURF=true|false`
- `RADAR_ENABLE_PANEWS=true|false`
- `RADAR_SURF_BIN=surf`
- `RADAR_SURF_SOCIAL_CMD=auto`
- `RADAR_PANEWS_CLI=/path/to/cli.mjs`

Benefit:
- enables controlled rollout
- makes it easy to disable Surf temporarily when quota is exhausted

### P1. Improve degradation semantics in report/output

Current direction is already partly there with `source_degraded`.

Recommended additions:

- show `surf unavailable` vs `surf quota exhausted` distinctly
- preserve fallback scoring with `PANews + OKX`
- add a short note into report/result metadata when Surf was disabled mid-scan

Suggested output fields:

- `surf_disabled_reason`
- `surf_quota_exhausted`
- `surf_command_selected`

---

## Suggested Agent Split

### Task 1: PANews path resolution

Deliverables:

- configurable path resolution
- fallback order implementation
- regression tests

### Task 2: Surf command compatibility

Deliverables:

- command discovery for social search
- support for both `search-social-posts` and legacy `search-social`
- regression tests

### Task 3: Surf quota handling

Deliverables:

- explicit quota/rate-limit error classification
- circuit breaker / TTL disable behavior
- report/fetch-status visibility

### Task 4: Config and docs

Deliverables:

- new env vars documented
- `SKILL.md` / references updated
- operator guidance for disabling Surf when quota is exhausted

---

## Minimum Viable Implementation

If you want the smallest safe first pass, do this:

1. parameterize `PANews` CLI path
2. add Surf social command auto-detection
3. classify Surf quota/rate-limit failures explicitly
4. disable Surf for the rest of the scan after first quota exhaustion

That gets most of the reliability benefit without changing the scoring model.
