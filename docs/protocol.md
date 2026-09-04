# ADC repository protocol

ADC reads a `.agent-delivery/` directory in the target repository:

```text
.agent-delivery/
  product.yaml
  roadmap.yaml
  current/
    block.yaml
    tasks/B01.yaml
  reports/B01.md
  evidence/B01.json
  archive/
```

YAML documents are strict: unknown keys, missing required keys, invalid states, unsafe paths,
duplicate identifiers, and invalid permission combinations fail validation. Repository paths use
forward slashes, are relative to the repository root, and name files rather than directories.

## Product

`product.yaml` states the durable goal, constraints, repositories, allowed GitHub agent actors,
action ceiling, and sensitive path patterns. A task cannot grant itself a permission disabled by
the product ceiling.

```yaml
goal: Make agent delivery machine-checkable
constraints:
  - GitHub Actions only
repositories:
  - self
agents:
  - automation-bot
action_ceiling:
  repository_write: true
  merge: false
  external_write: false
  production_write: false
  workflow_write: true
  dependency_write: true
  infra_write: false
sensitive_paths:
  - ".github/workflows/**"
  - ".agent-delivery/**"
  - "**/*.lock"
  - "**/package-lock.json"
  - "**/requirements*.txt"
  - "**/pyproject.toml"
  - "**/.env*"
  - "**/terraform/**"
  - "**/infra/**"
  - "**/Dockerfile*"
```

## Roadmap and current block

`roadmap.yaml` orders blocks and gives each at least one observable exit criterion.

```yaml
blocks:
  - id: PHASE1
    goal: Validate the protocol
    exit_criteria:
      - All rejection-path tests pass
```

`current/block.yaml` selects a roadmap block and declares its exact set of tasks.

```yaml
id: PHASE1
goal: Validate the protocol
status: implementing
task_ids: [B01]
```

## Task

Every active task is one YAML document in `current/tasks/`. Two active tasks may not name the same
file. `.agent-delivery/**` is controller-owned and can never appear in task scope. `max_files` is a
hard complexity budget for the number of changed files.

```yaml
id: B01
goal: Collect trusted PR identity
status: ready
owner: agent-1
scope:
  files:
    - .github/scripts/pr_identity.py
    - .github/scripts/test_pr_identity.py
  max_files: 2
permissions:
  repository_write: true
  merge: false
  external_write: false
  production_write: false
  workflow_write: false
  dependency_write: false
  infra_write: false
acceptance:
  - Exact head SHA is verified
  - Malformed identity fails closed
verification:
  commands:
    - python3 .github/scripts/test_pr_identity.py
  ci_tests:
    - test_pr_identity
stop_conditions:
  - Required scope expands
  - External permission is needed
```

Task states are `ready`, `implementing`, `verified`, `merged`, `archived`, and terminal
`cancelled`. Only a human may set `cancelled`.

## Identity

Phase 2 will identify agent PRs by GitHub actor using `product.yaml: agents`. It will also require
both the expected git author identity and an `ADC-Task: B01` commit trailer as a cheap local signal.
Local scope checks inspect the staged diff. Install both supplied hooks and set `ADC_TASK` while
committing: `pre-commit` checks scope and permissions, while `commit-msg` can inspect the final
trailer. Verification commands run only in CI and emit junit; the dependent `adc-check` job
evaluates that artifact. `git commit --no-verify` remains an escape hatch because the PR job repeats
all checks against every commit.

Agent pull requests are recognized by `product.yaml: agents`. Human actors are exempt from ADC and
continue to be governed by CODEOWNERS and branch protection.

The test job derives one task ID from the commits' `ADC-Task` trailers, records the exact PR head in
the junit artifact, and runs `adc ci-run TASK`. The dependent job invokes:

```console
adc check TASK --pr NUMBER --junit junit --tested-sha-file junit/tested-sha \
  --command-results junit/commands.json
```

After merge, the controller compares each scoped blob rather than root trees:

```console
adc check TASK --post-merge --reviewed-sha SHA --merged-sha SHA
```

## Validation and schemas

```console
adc validate [PROTOCOL_DIR]
adc schema --output docs/schema
```

The schemas describe individual documents. `adc validate` additionally checks cross-document
invariants: current block presence in the roadmap, exact task membership, unique file ownership,
and task permissions within the product action ceiling.
