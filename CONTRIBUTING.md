# Contributing

## Setup

```bash
uv sync --extra dev
./scripts/install_metal.sh   # macOS local Orpheus (optional)
speak --write-config ~/.config/speak/config.json
pre-commit install
```

## Workflow

1. Branch from `main`
2. Focused changes
3. `make check`
4. Update `CHANGELOG.md` under `[Unreleased]` if user-visible
5. Open a PR

## Guidelines

- Local Orpheus: EN/DE only. Groq: EN + Arabic only (see `GROQ_LANG_TO_MODEL`)
- No secrets in the repo (`config.json` is gitignored)
- Unit-test pure logic; integration tests opt-in (`SPEAK_RUN_INTEGRATION=1`)
- Prefer small PRs

See [docs/development.md](docs/development.md).
