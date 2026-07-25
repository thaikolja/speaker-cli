# AGENTS.md — guidance for coding agents

This file tells automated coding agents how to work in this repository.

## What this project is

**speaker** is a TTS CLI with command **`speak`**:

1. **Default (`SPEAK_ENGINE=auto`):** Groq Orpheus API (`troy`) after key + reachability preflight  
2. **Fallback:** local Orpheus (EN/DE) via `local_orpheus.py` + llama.cpp Metal  
3. **Last resort:** macOS `say`

User may force a single backend with `SPEAK_ENGINE=groq|local|say`. Do not change the default `auto` chain unless asked.

## Hard rules

- **Never commit secrets** (API keys, `.env`, tokens). Use `.env.example` only.
- **Never re-hardcode `GROQ_API_KEY`** in source.
- **Do not expand language support** beyond EN/DE unless asked.
- **Do not add heavy deps** (torch, vllm, piper, edge-tts) without a clear need — Mac path is llama.cpp + onnxruntime.
- **Do not commit** `Orpheus-TTS/` clone, `*.gguf`, `speech.wav`, `.groq_usage.json`.
- Keep responses and diffs **small**; match existing style (no drive-by refactors).

## Layout

| Path | Role |
|------|------|
| `main.py` | CLI (`speak`), preflight, rate limits, fallbacks, playback, cleanup |
| `local_orpheus.py` | Local GGUF Orpheus + SNAC decode |
| `tests/` | Unit tests (no model download) |
| `scripts/install_metal.sh` | Metal `llama-cpp-python` install |
| `pyproject.toml` | deps + ruff/pytest/mypy config; console scripts `speak` / `speaker` |

## Commands agents should run

```bash
uv sync --extra dev
uv run ruff check . --fix
uv run ruff format .
uv run mypy main.py local_orpheus.py tests
uv run pytest
```

After changing Metal-related install notes, keep `scripts/install_metal.sh` accurate.

Local full TTS (optional, slow, needs models):

```bash
./scripts/install_metal.sh
uv run python main.py "Hello from the agent."
# or: uv run speak "Hello from the agent."
```

End-user install (document in README):

```bash
uv tool install git+https://github.com/thaikolja/speaker-cli.git
```

## Testing expectations

- Prefer **unit tests** for pure logic (`estimate_tokens`, `fits_groq_limits`, `preflight_groq`, `lang_code`, WAV write, voice pick, `speak` order).
- Mark anything needing network/GPU/audio as `@pytest.mark.integration` and **do not** require it in CI.
- Mock `subprocess`, filesystem, Groq client, and engines when testing orchestration.

## Code style

- Python 3.11+, `from __future__ import annotations`
- Ruff for lint + format (line length 100)
- No unnecessary comments
- Type-annotate public functions

## Product constraints to remember

- Groq Orpheus input **max 200 characters**
- Free-tier style limits encoded in `ORPHEUS_*` constants — update if docs change:  
  https://console.groq.com/docs/rate-limits  
  https://console.groq.com/docs/text-to-speech/orpheus
- Preflight uses a cheap `models.list` (not TTS) with `PREFLIGHT_TIMEOUT_S`
- Open-source voices ≠ Groq names (`troy` is API-only; local default is `leo`)
- Delete generated audio after playback (`DELETE_AFTER_S`)

## PR checklist for agents

1. `ruff check` + `ruff format` clean  
2. `pytest` green  
3. `mypy` clean on touched modules  
4. CHANGELOG `[Unreleased]` updated for user-visible changes  
5. No secrets in diff  
