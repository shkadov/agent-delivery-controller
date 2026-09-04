# Agent Delivery Controller

ADC defines a machine-readable delivery protocol for coding agents and provides a small reference
CLI that validates task scope, permissions, and verification evidence. Source-control and CI
enforcement remain with GitHub.

Start with [the protocol specification](docs/protocol.md). The implementation is still being
dogfooded and is not a finished controller.

## Development

Requires Python 3.12 and `uv`.

```console
uv sync
git config core.hooksPath hooks
uv run adc validate
uv run adc schema --output docs/schema
uv run ruff check .
uv run mypy
uv run pytest
```

## Known limitations

- The trusted pull-request policy workflow has not been split from the head-controlled test
  workflow yet. Until it is split and required by branch protection, an agent can weaken its own
  checks.
- Junit produced by a head-controlled workflow is corroborating evidence, not tamper-proof proof.
- The pull-request path has fixture coverage but has not completed a real bot-authored PR run.
- Status values are schema-validated; lifecycle transitions are not yet enforced.

## License

Apache License 2.0. See `LICENSE`.
