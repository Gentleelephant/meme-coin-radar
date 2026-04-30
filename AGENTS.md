# AGENTS.md

## Purpose

This file records repo-specific maintenance rules that should be checked whenever an agent updates the project.

## Change Checklist

When making project changes, verify whether any of the following also need to be updated.

### Versioning

If the change affects behavior, outputs, interfaces, strategy logic, provider compatibility, or user-visible documentation, check whether the project version should be bumped.

Primary version source:

- `skills/meme-coin-radar/VERSION`

Version-related places to review when bumping:

- `skills/meme-coin-radar/VERSION`
- `skills/meme-coin-radar/SKILL.md`
- `skills/meme-coin-radar/scripts/auto-run.py`

Expected behavior:

- `VERSION` is the single source of truth for runtime version output.
- `auto-run.py` should include the current version in terminal output, `report.md`, `result.json`, and `00_scan_meta.json`.
- `SKILL.md` contains a static metadata version field and must be manually synchronized when the version changes.

Suggested bump rules:

- `major`: architecture or strategy model changes that materially alter project structure or interpretation
- `minor`: new capability, provider migration, scoring behavior change, output structure change
- `patch`: bug fix, compatibility fix, non-breaking maintenance update

### Provider / CLI Compatibility

If a provider depends on an external CLI or API, check whether compatibility assumptions changed.

Current examples:

- `skills/meme-coin-radar/scripts/providers/onchainos.py`
- `skills/meme-coin-radar/scripts/providers/binance.py`

For external integration changes:

- verify command syntax or API schema
- run a real smoke test when possible
- add or update regression tests for the compatibility fix

### Output Contract

If scan outputs, reports, or JSON fields change, review:

- `skills/meme-coin-radar/scripts/auto-run.py`
- downstream report expectations in references/docs
- any tests that validate output assumptions

### Tests

For meaningful logic or integration changes, update or add targeted tests under:

- `skills/meme-coin-radar/tests/`

Minimum expectation:

- add regression coverage for bug fixes
- run the most relevant tests before closing the task

### Review Documentation

If the task is a code review, save the review result to:

- `skills/meme-coin-radar/references/review-report.md`

Expected behavior:

- every review must overwrite the file with the current review's content
- do not append findings to an existing review document
- the review document should reflect only the latest review requested in the current task
