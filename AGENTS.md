# AGENTS.md — guidance for coding agents

This file tells automated coding agents how to work in this repository.

## What this project is

**speak** is a TTS CLI (`speak` console script only):

1. **English (`engine=auto`):** Groq → local Orpheus → macOS `say`  
2. **German (`engine=auto`):** local Orpheus DE GGUF → Groq → macOS `say`  
3. Forced `engine=groq|local|say` applies to all languages

Defaults live in **`config.json`**. CLI flags override config.

## Hard rules

- **Never commit secrets** (API keys, real `config.json` with keys). Use `config.example.json` only.
- **Never re-hardcode API keys** in source.
- **Do not expand language support** beyond EN/DE unless asked.
- **Do not add heavy deps** (torch, vllm, piper, edge-tts) without a clear need — Mac path is llama.cpp + onnxruntime.
- **Do not commit** `Orpheus-TTS/` clone, `*.gguf`, `speech.wav`, usage ledgers.
- Keep responses and diffs **small**; match existing style (no drive-by refactors).
- Console script is **`speak` only** (no `speaker` alias).

## Layout

| Path | Role |
|------|------|
| `main.py` | CLI, `Settings` / config.json, orchestration, playback |
| `local_orpheus.py` | Local GGUF Orpheus + SNAC decode |
| `config.example.json` | Documented defaults |
| `tests/` | Unit tests (no model download) |
| `scripts/install_metal.sh` | Metal `llama-cpp-python` install |
| `pyproject.toml` | deps + ruff/pytest/mypy; script `speak` |

## Commands agents should run

```bash
uv sync --extra dev
uv run ruff check . --fix
uv run ruff format .
uv run mypy main.py local_orpheus.py tests
uv run pytest
```

## Testing expectations

- Unit tests for pure logic and orchestration (mock engines / Groq).
- Prefer isolated `Settings` in tests (`set_settings` / tmp paths).
- Mark network/GPU/audio as `@pytest.mark.integration` — not required in CI.

## Code style

- Python 3.11+, `from __future__ import annotations`
- Ruff for lint + format (line length 100)
- No unnecessary comments
- Type-annotate public functions

## Product constraints

- Groq Orpheus input **max 200 characters** (configurable via `groq_max_chars`)
- Free-tier style limits in Settings / config — update if docs change  
  https://console.groq.com/docs/rate-limits  
  https://console.groq.com/docs/text-to-speech/orpheus
- Tempo is pitch-preserving (ffmpeg `atempo` or WSOLA)
- Open-source voices ≠ Groq names (`troy` is API-only; local default `leo`)
- Delete generated audio after playback (`delete_after_s`)

## PR checklist

1. `ruff check` + `ruff format` clean  
2. `pytest` green  
3. `mypy` clean on touched modules  
4. CHANGELOG `[Unreleased]` updated for user-visible changes  
5. No secrets in diff  
