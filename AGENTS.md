# AGENTS.md — guidance for coding agents

This file tells automated coding agents how to work in this repository.

## What this project is

**speak** is a TTS CLI (`speak` console script only).

`engine=auto` is language-aware — **Groq first only when Groq has a model** for that language:

| Detected lang | Chain |
|---------------|--------|
| English | Groq → local Orpheus → macOS `say` |
| Arabic | Groq → macOS `say` (no local AR GGUF) |
| German | local Orpheus DE → macOS `say` (no Groq DE model) |
| Other | macOS `say` |

Forced `engine=groq|local|say` applies to all languages and **does not fall back**.

Defaults live in **`config.json`**. CLI flags override config.

## Hard rules

- **Never commit secrets** (API keys, real `config.json` with keys). Use `config.example.json` / `.env.example` only.
- **Never re-hardcode API keys** in source.
- **Local Orpheus:** EN/DE only. **Groq:** EN + Arabic models only (see `GROQ_LANG_TO_MODEL` in `main.py`). Do not add heavy deps (torch, vllm, piper, edge-tts) without a clear need — Mac path is llama.cpp + onnxruntime.
- **Do not commit** `Orpheus-TTS/` clone, `*.gguf`, `speech.wav`, usage ledgers.
- Keep responses and diffs **small**; match existing style (no drive-by refactors).
- Console script is **`speak` only** (no `speaker` alias).

## Layout

| Path | Role |
|------|------|
| `main.py` | CLI, `Settings` / config.json, orchestration, playback |
| `local_orpheus.py` | Local GGUF Orpheus + SNAC decode |
| `config.example.json` | Documented defaults |
| `.env.example` | Optional `GROQ_API_KEY` / `SPEAK_CONFIG` |
| `docs/` | Architecture, config, backends, CLI, development, troubleshooting |
| `tests/` | Unit tests (no model download); integration opt-in |
| `scripts/install_metal.sh` | Metal `llama-cpp-python` install |
| `pyproject.toml` | deps + ruff/pytest/mypy; script `speak` |

## Commands agents should run

```bash
uv sync --extra dev
uv run ruff check . --fix
uv run ruff format .
uv run mypy main.py local_orpheus.py tests
uv run pytest
make check
```

## Testing expectations

- Unit tests for pure logic and orchestration (mock engines / Groq).
- Prefer isolated `Settings` in tests (`set_settings` / tmp paths).
- Mark network/GPU/audio as `@pytest.mark.integration` — skip unless `SPEAK_RUN_INTEGRATION=1`.

## Code style

- Python 3.11+, `from __future__ import annotations`
- Ruff for lint + format (line length 100)
- No unnecessary comments
- Type-annotate public functions
- Status → `_status()` / stdout; diagnostics → `log` / stderr

## Product constraints

- Groq Orpheus input **max 200 characters** (`groq_max_chars`)
- Free-tier limits in Settings — verify against docs if changing defaults  
  https://console.groq.com/docs/rate-limits  
  https://console.groq.com/docs/text-to-speech/orpheus
- English Groq supports vocal directions (`--direction` / `groq_direction`)
- Tempo is pitch-preserving (ffmpeg `atempo` or WSOLA) for 16-bit PCM
- Open-source voices ≠ Groq names (`troy` is API-only; local default `leo`)
- Empty `groq_model` / `groq_voice` → derive from detected language
- Generated audio deleted on interpreter exit (`atexit`)

## PR checklist

1. `ruff check` + `ruff format` clean  
2. `pytest` green  
3. `mypy` clean on touched modules  
4. CHANGELOG `[Unreleased]` updated for user-visible changes  
5. No secrets in diff  
