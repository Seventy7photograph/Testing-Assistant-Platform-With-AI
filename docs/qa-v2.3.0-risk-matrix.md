# v2.3.0 QA Risk Matrix

> Scope: V2.3 automation artifact generation, JUnit ingestion, structured events,
> work items, reminders, delivery workspace, storage and release.
> Method: risk-based testing (`Impact × Probability`); score ≥ 10 receives failure-mode analysis.
> This curated suite does not claim a statistical failure rate.

## Risk Matrix

| ID | Risk | Impact | Probability | Score | Zone | Primary evidence |
| --- | --- | ---: | ---: | ---: | --- | --- |
| R-01 | Generated project contains unsafe Python or cannot run | 5 | 4 | 20 | CRITICAL | validator unit tests; generated pytest project against local mock API |
| R-02 | Secret or credential material leaks into artifact/event/log | 5 | 3 | 15 | CRITICAL | secret-scan test; artifact content assertions; event sanitization test |
| R-03 | JUnit results are silently mismatched or dropped | 4 | 4 | 16 | CRITICAL | parser dialect tests; API import test with matched + unmatched cases |
| R-04 | Reminder repeats or crosses timezone boundaries incorrectly | 3 | 4 | 12 | HIGH | reminder poll/ack API tests; Shanghai timezone regression; browser reminder |
| R-05 | JSON and SQLite behavior diverges | 4 | 3 | 12 | HIGH | parameterized persistence tests for both backends |
| R-06 | Delivery workspace breaks on route or viewport | 4 | 3 | 12 | HIGH | Vue typecheck/build; Playwright desktop and 390 px viewport |
| R-07 | Release version/tag/docs disagree | 3 | 3 | 9 | MEDIUM | version grep; full test/build; tag and GitHub Release inspection |
| R-08 | Deleting a run/asset leaves dangling records or events | 3 | 3 | 9 | MEDIUM | linked-delete conflict test; cascade event-delete API test |

## Failure Mode Analysis

### R-01: Generated Python is unsafe or non-runnable

- **Trigger:** Template change, unsafe case content, missing import, or path/query mismatch.
- **Blast radius:** Downloaded test project could fail before exercising the target or introduce unsafe code.
- **Detection:** AST/compile scan, banned import/call tests, zip content inspection, real pytest run.
- **Current mitigation:** Fixed templates; cases are JSON data rather than generated Python; no automatic execution.
- **Coverage gap addressed:** A generated project is run against a real local HTTP mock, including JSONPath array assertions.

### R-02: Secret leakage

- **Trigger:** Literal token in OpenAPI examples, case data, event message, or generated `.env.example`.
- **Blast radius:** Credentials persist in local files or downloadable archives.
- **Detection:** Pattern-based secret scan; content assertions; event message inspection.
- **Current mitigation:** Environment placeholders, download blocked on validation failure, logarithmic metadata only.
- **Coverage gap addressed:** API and artifact tests assert no literal test secret and no authorization value in events.

### R-03: JUnit mapping ambiguity

- **Trigger:** Missing `case_id`, property format, unknown historical case, duplicate names, or malformed XML.
- **Blast radius:** Release verdict uses incorrect pass/fail counts or loses failure evidence.
- **Detection:** Parser fixtures for passed/failed/error/skipped/property; API import assertions.
- **Current mitigation:** Unknown cases remain in `unmatched_cases`; malformed XML fails closed with 422.
- **Coverage gap addressed:** Both matched and unmatched cases are verified in one imported run.

### R-04: Reminder duplication and time semantics

- **Trigger:** Repeated polling, page reload, naive timestamps, or acknowledgement race.
- **Blast radius:** Duplicate interruptions or missed deadlines.
- **Detection:** API poll/ack idempotency test, timezone test, browser notification check.
- **Current mitigation:** `reminded_at` server-side dedupe, UTC+8 fallback when tzdata is unavailable.
- **Coverage gap addressed:** Poll-after-ack returns no item; missing ID acknowledgement is harmless.

### R-05: Storage divergence

- **Trigger:** New collection wired into JSON but not SQLite, or vice versa.
- **Blast radius:** Data appears saved but disappears after switching/reopening backend.
- **Detection:** Parameterized create/update/reopen test for JSON and SQLite.
- **Current mitigation:** Both stores implement the same object-store protocol.
- **Coverage gap addressed:** Work item title/body/status/pin survive repository reopen in both backends.

### R-06: Workspace route or responsive regression

- **Trigger:** Template syntax, stale route metadata, fixed-width layout, or missing API field.
- **Blast radius:** Main V2.3 workflow cannot be completed or mobile content is clipped.
- **Detection:** `vue-tsc`, production build, Playwright generation/import/items/reminder flow, scroll-width measurement.
- **Current mitigation:** Single workspace with segmented tabs; responsive grid collapses at 760 px.
- **Coverage gap addressed:** 390 px viewport measured `scrollWidth == clientWidth == 390`.

## Coverage Alignment

| Zone | Required coverage | Implemented for v2.3 |
| --- | --- | --- |
| CRITICAL | Unit + integration + real execution path | R-01/R-02/R-03 each have deterministic unit/API evidence; R-01 also runs the generated project |
| HIGH | Happy path + top error paths + periodic manual review | R-04/R-05/R-06 have API and browser evidence |
| MEDIUM | Happy path and release check | R-07/R-08 verified during release gate |

## Reassessment Triggers

- Any change to generated Python templates or validator allow/deny lists.
- Any new JUnit producer/dialect.
- Any reminder scheduling change, timezone configuration, or background worker introduction.
- Any change to storage collection wiring or deletion semantics.
- Any escaped defect involving loss of work items, incorrect run status, or unsanitized logs.

## Release Gate

The release is go only when:

1. New V2.3 backend tests pass.
2. Full `pytest` suite passes.
3. Frontend typecheck and production build pass.
4. Playwright completes generation, JUnit import, follow-up, reminder, and mobile layout checks.
5. Version, CHANGELOG, README, tag and GitHub Release agree.

## Verification Results

| Gate | Result |
| --- | --- |
| New V2.3 backend tests | 12 passed: artifact validator/generator, JUnit parser/API, real generated project, work items, reminders, JSON/SQLite |
| Full backend suite | 430 collected / 430 passed |
| Frontend | `vue-tsc --noEmit` + production Vite build passed |
| Browser | Desktop generation → JUnit import → matched/unmatched → follow-up → save/complete → reminder passed; zero console errors in fresh session |
| Responsive | 390 px viewport measured `scrollWidth = clientWidth = 390`; no horizontal overflow |
| Offline scripts | `demo_offline.py`, `demo_report_offline.py`, `acceptance_check.py` passed |
