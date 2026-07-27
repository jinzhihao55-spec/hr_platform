# HR Platform Project Contract

> Status: evidence-backed baseline; product-owner confirmation is still required for items marked `TBD`.
> Project root: `/Users/jzh/jzh/2026实习/v1_7.21`

## 1. Goal

Build a single-user HR reporting agent that accepts four input categories:

1. employee roster;
2. leaver report;
3. OA/Release data;
4. recruitment data.

The system produces daily headcount changes (Row2-Row40), weekly reports,
calculation logs, downloadable Excel reports, and immutable publication history.
Qwen may assist with Excel/image parsing, OCR, and interaction, but final business
figures must come from deterministic rules.

## 2. Current Users and Workflow

The current V1 targets a local HR operator who:

1. selects a report date;
2. uploads the four required source types;
3. confirms OCR and ambiguous business classifications;
4. previews daily and weekly reports;
5. reviews sources, differences, validation results, and calculation logs;
6. publishes daily and weekly reports independently;
7. downloads immutable published artifacts and historical revisions.

TBD: final report recipients, multi-user roles, approval roles, and outbound
delivery channels.

## 3. Technology

- Backend: Python 3.12, FastAPI, Pandas, SQLAlchemy, Pydantic.
- Frontend: React 19, Vite, Axios, CSS.
- Data: MySQL 8+, Redis 7.4.
- AI/OCR: Alibaba Bailian Qwen through an OpenAI-compatible endpoint.
- Excel: openpyxl and related Python tooling.
- Gateway/deployment: Nginx, Docker Compose, with a separate Windows-native
  deployment path currently in use.
- Tests: Pytest, Vitest, Testing Library, and regression scripts.

## 4. Main Code Areas

- Backend entry: `backend/app/main.py`
- Frontend entry: `frontend/src/main.jsx`
- Frontend routes: `frontend/src/router.jsx`
- Database schema: `database/schema.sql`
- Migrations: `database/migrations/`
- Container deployment: `backend/deploy/compose.yaml`
- Regression entry: `backend/scripts/run_single_user_regression.py`

Core flow:

```text
React UI -> frontend services -> Nginx /api -> FastAPI routes
  -> upload/confirmation/preview/publication services
  -> deterministic calculation and validation
  -> immutable MySQL snapshots and protected report artifacts
```

## 5. Non-Negotiable Requirements

1. Final report numbers are calculated by deterministic rules.
2. LLMs must not generate, alter, or guess final business figures.
3. Missing or ambiguous data must block progress and require user confirmation.
4. Report rows must remain traceable to facts, filters, and calculation rules.
5. Daily and weekly reports are independently validated and published.
6. Publication records and snapshots are immutable.
7. Published inputs are revised through a new same-day Run, never overwritten.
8. Preview snapshots and final Excel outputs must agree.
9. Multiple employee IDs for one natural person must not double-count people.
10. Rolling facts retain their first-seen dates to prevent duplicate counting.
11. OCR and uncertain classifications retain human confirmation and audit records.
12. Raw uploads are deleted after parsing; structured facts and audits remain.
13. Plaintext identity-card numbers must never be stored.
14. Identity-linking keys must remain stable through backup and recovery.
15. Secrets, tokens, and real HR data must never enter Git.
16. Published artifacts are downloadable only from the protected output directory.
17. Production requires API token, MySQL, Redis, and identity-key configuration.
18. MySQL, Redis, and backend APIs must not be exposed directly to the public network.

## 6. Prohibited Actions

- Do not infer missing HR facts with a model.
- Do not bypass unresolved confirmations to publish.
- Do not mutate published Runs, facts, snapshots, or artifacts in place.
- Do not publish a stale preview after inputs changed.
- Do not expose secrets or sensitive fields in logs, frontend bundles, Git, or exports.
- Do not persist plaintext identity-card numbers.
- Do not silently replace report artifacts without hashes and snapshot validation.

## 7. Verification Contract

Before calling a change complete, run the relevant subset of:

- backend Pytest suite;
- 12-case synthetic publication regression;
- frontend tests, lint, and production build;
- Docker Compose config validation;
- API readiness and main Run/report route checks;
- privacy and secret scans using synthetic data only.

Business acceptance includes correct Row2-Row40 calculations, correct history and
format preservation, deduplication by natural person, first-seen inheritance,
human-confirmed OCR ambiguity, independent daily/weekly publication, and equality
between preview, publication snapshot, and downloaded Excel content.

## 8. Current State

- Current branch at baseline discovery: `feature/Mike_jin`.
- Current baseline commit at discovery: `23cd3a7`.
- Repository history contained three commits.
- Code appears to be at the single-user V1 implementation/deployment-validation stage.
- Daily/weekly reports, calculation logs, four-source ingestion, OCR, confirmation,
  preview, publication, revision history, data-protection guards, tests, and deployment
  assets are present.
- Production acceptance remains `TBD` until the product owner confirms it.

## 9. Known Risks

1. A Run created too early can retain an obsolete baseline; current mitigation is a
   same-day revision Run.
2. Historical `protected_path` values can become invalid after deployment-directory
   migration.
3. Rule-version examples show possible version drift (`2026-07-23` vs `2026-07-12`).
4. Docker Compose documentation and the current Windows-native deployment path diverge.
5. Older data-contract documentation may lag behind the current Run/Fact/Publication model.

## 10. Product-Owner Confirmations Still Needed

- final report audience and delivery channels;
- multi-user and approval-role requirements;
- supported production deployment method;
- whether production acceptance has been achieved;
- whether Runs should automatically follow the newest eligible baseline.
