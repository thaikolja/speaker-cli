# Contributing

## Setup

```bash
uv sync --extra dev
./scripts/install_metal.sh   # macOS local Orpheus
cp .env.example .env         # optional Groq key
pre-commit install
```

## Workflow

1. Create a branch from `main`
2. Make focused changes
3. Run `make check`
4. Update `CHANGELOG.md` under `[Unreleased]` if user-visible
5. Open a PR

## Guidelines

- EN/DE only unless discussed
- No secrets in the repo
- Unit-test pure logic; keep integration tests optional
- Prefer small PRs

See [AGENTS.md](AGENTS.md) for agent-specific rules.
