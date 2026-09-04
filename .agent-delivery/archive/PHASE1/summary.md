# PHASE1: protocol foundation

- Added strict Pydantic models for product, roadmap, block, task, and evidence documents.
- Added cross-document validation for task membership, file ownership, and action ceilings.
- Reserved `.agent-delivery/**` for controller/human writes.
- Added deterministic JSON Schema export and committed the generated schemas.
- Added 13 passing rejection-path and cross-document tests.
- Added one CI workflow with `ci`, `test`, and dependent `adc-check` jobs.
- Bootstrap verification: pytest, ruff, mypy strict, self-validation, and schema diff passed.
