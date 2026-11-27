<!-- se-harness PR template — filled by the PM agent from the final /se-review report.
     Keep every section; write "none" rather than deleting one. -->

## Summary

<!-- 2–4 sentences: what this PR does and why. -->

- **Requirement:** <!-- direct text summary, or linear:ABC-123 with link -->

## Implementation

<!-- Key decisions, areas/files touched, anything the human reviewer should know
     (new endpoints, schema changes, notable trade-offs, deferred work). -->

## Review — se-harness review board

- **Feature:** `<feature-slug>` · **Rounds:** N · **Status:** closed | accepted-risk

| Reviewer | Sign-off |
|---|---|
| PM (requirements) | ✅ / ❌ |
| Architect | ✅ / ❌ |
| DBA | ✅ / ❌ |
| QA | ✅ / ❌ |
| Code reviewer | ✅ / ❌ |

### Requirements coverage (PM)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | <!-- criterion --> | met / deferred | <!-- file / test / user quote for deferrals --> |

### What was reviewed

<!-- One line per reviewer: scope covered + notable findings (now resolved).
- Architect: contract fidelity vs API-CONTRACT.md, tenancy flags, REST shape
- DBA: tenant column/index on new tables, repository-only access, RLS, migrations
- QA: see "What was tested"
- Code reviewer: correctness, conventions, hygiene, security smells -->

### What was tested (QA)

<!-- From qa.md: tests added/changed, error paths asserted (422/404/409),
     tenant-isolation cases, requirement edge cases covered. -->

### Comments resolved / waived

| ID | Severity | Resolution |
|---|---|---|
| <!-- QA-1 --> | <!-- MAJOR --> | <!-- fixed — …  /  waived — reason  /  rejected — reason --> |

## Housekeeping

- **Pitfalls added:** <!-- P-00X — title (docs/PITFALLS.md), or "none" -->
- **Version bumps:** <!-- file old → new (docs/VERSION-HISTORY.md), or "none" -->
