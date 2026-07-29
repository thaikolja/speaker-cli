# Development

## Setup

```bash
git clone https://github.com/thaikolja/speaker-cli.git
cd speaker-cli
uv sync --extra dev
# macOS local Orpheus (optional):
make install-metal
```

## Quality gates

```bash
make check
# or:
uv run ruff check .
uv run ruff format --check .
uv run mypy main.py local_orpheus.py tests
uv run pytest
```

Pre-commit:

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

## Tests

- Unit tests mock Groq / local / say (no network, no GGUF download).
- Integration (opt-in):

```bash
SPEAK_RUN_INTEGRATION=1 GROQ_API_KEY=… uv run pytest -m integration
```

## Layout

| Path | Role |
|------|------|
| `main.py` | CLI + orchestration |
| `local_orpheus.py` | Local GGUF + SNAC |
| `tests/` | pytest |
| `docs/` | This documentation |
| `scripts/install_metal.sh` | Metal llama-cpp-python |
| `config.example.json` | Sample config |
| `.env.example` | Sample env |

See also [CONTRIBUTING.md](../CONTRIBUTING.md).
