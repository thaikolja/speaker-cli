# speaker

[![CI](https://img.shields.io/github/actions/workflow/status/kolja/speaker/ci.yml?branch=main&label=CI)](../../actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Ruff](https://img.shields.io/badge/code%20style-ruff-000000?logo=ruff)](https://docs.astral.sh/ruff/)

Local-first **text-to-speech** for **English** and **German**.

Default path runs [Orpheus](https://github.com/canopyai/Orpheus-TTS) **on your machine** (Apple Silicon Metal via llama.cpp). If local inference fails, it falls back to the [Groq Orpheus API](https://console.groq.com/docs/text-to-speech/orpheus), then to macOS `say`.

```
text → local Orpheus (EN/DE)
         ↓ fail
       Groq troy (rate-limited, ≤200 chars)
         ↓ fail / over limit
       macOS say (Samantha / Anna)
```

## Available models

| Path | Language | Model ID / asset | Default voice | Notes |
|------|----------|------------------|---------------|--------|
| **Local (default)** | English | [`isaiahbjork/orpheus-3b-0.1-ft-Q4_K_M-GGUF`](https://huggingface.co/isaiahbjork/orpheus-3b-0.1-ft-Q4_K_M-GGUF) | `leo` | ~2.2 GB Q4_K_M GGUF |
| **Local (default)** | German | [`freddyaboulton/3b-de-ft-research_release-Q4_K_M-GGUF`](https://huggingface.co/freddyaboulton/3b-de-ft-research_release-Q4_K_M-GGUF) | `leo` | ~2.0 GB Q4_K_M GGUF |
| **Groq fallback** | English | `canopylabs/orpheus-v1-english` | `troy` | API; max **200** chars; rate-limited |
| **macOS fallback** | EN / DE | system `say` | Samantha / Anna | always offline |

### Local Orpheus voice tags (EN weights)

`tara` · `leah` · `jess` · `leo` · `dan` · `mia` · `zac` · `zoe`

DE uses the German GGUF with the same tag format (default `leo`). Groq’s `troy` is **API-only** and not in the open weights.

Configured in code: `LANG_TO_REPO` / `DEFAULT_VOICE` in [`local_orpheus.py`](local_orpheus.py), Groq constants in [`main.py`](main.py).

## Requirements

- macOS (playback uses `afplay`; `say` is the last-resort fallback)
- Python **3.11+**
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- ~5 GB disk for EN + DE GGUF models (downloaded on first use)
- Apple Silicon recommended (Metal acceleration)

## Quick start

```bash
# clone
git clone <your-repo-url> speaker && cd speaker

# deps
uv sync --extra dev

# Metal llama.cpp (required for local Orpheus)
./scripts/install_metal.sh

# optional Groq fallback
cp .env.example .env   # set GROQ_API_KEY

# speak
uv run python main.py "Hello, this is a local test."
uv run python main.py "Guten Tag, das ist ein Test."
uv run speaker -f notes.txt
```

First run per language downloads the GGUF listed under **Available models**.

## Configuration

| Variable / constant | Meaning |
|---------------------|---------|
| `GROQ_API_KEY` | Optional API fallback |
| `LOCAL_VOICE_EN` / `LOCAL_VOICE_DE` | Local Orpheus voice tags (default `leo`) |
| `ORPHEUS_VOICE` | Groq voice (default `troy`) |
| `DELETE_AFTER_S` | Seconds before deleting `speech.wav` (default `10`) |

## Development

```bash
uv sync --extra dev
./scripts/install_metal.sh          # local machine only
uv run ruff check .
uv run ruff format .
uv run mypy main.py local_orpheus.py
uv run pytest
pre-commit install                   # once
pre-commit run --all-files
```

### Project layout

```
main.py              # CLI + fallback orchestration
local_orpheus.py     # Metal/llama.cpp Orpheus engine (+ model IDs)
tests/               # unit tests (no GPU/models required)
scripts/             # install helpers
.github/workflows/   # CI
```

## CI

GitHub Actions runs on push/PR to `main`:

- `ruff check` + `ruff format --check`
- `mypy`
- `pytest` with coverage

Local model download and audio playback are **not** run in CI.

## License

MIT — see [LICENSE](LICENSE).

Upstream Orpheus models and code have their own licenses (Apache-2.0 / project terms on Hugging Face and [canopyai/Orpheus-TTS](https://github.com/canopyai/Orpheus-TTS)).

## Acknowledgments

- [Canopy Labs Orpheus TTS](https://github.com/canopyai/Orpheus-TTS)
- GGUF builds listed in **Available models**
- [llama-cpp-python](https://github.com/abetlen/llama-cpp-python), SNAC decoder
