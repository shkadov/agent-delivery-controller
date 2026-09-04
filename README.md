# Agent Delivery Controller

ADC is a small control plane for machine-checkable coding-agent delivery. It validates task
scope, permissions, verification evidence, and lifecycle transitions while leaving source
control and CI enforcement to GitHub.

The project is in its protocol-foundation phase. `adc validate` and strict JSON Schemas are
available; execution and evidence collection in `adc check` follow in Phase 2.

## Development

Requires Python 3.12 and `uv`.

```console
uv sync
uv run adc validate
uv run adc schema --output docs/schema
uv run ruff check .
uv run mypy
uv run pytest
```

See [docs/protocol.md](docs/protocol.md) for the repository protocol.
