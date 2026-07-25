# speaker

[![CI](https://img.shields.io/github/actions/workflow/status/kolja/speaker/ci.yml?branch=main&label=CI)](../../actions/workflows/ci.yml) [![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/downloads/) [![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE) [![Ruff](https://img.shields.io/badge/code%20style-ruff-000000?logo=ruff)](https://docs.astral.sh/ruff/)

Easy **text-to-speech** CLI for **English** and **German**.

```
text → Groq Orpheus (troy)          # if API key set + reachable
         ↓ fail / unreachable / over limit
       local Orpheus (EN/DE)        # Metal + GGUF on first use
         ↓ fail
       macOS say (Samantha / Anna)
```

## Quick start (recommended)

Global `speak` command via [uv](https://docs.astral.sh/uv/) (Python **3.11+**):

```bash
uv tool install git+https://github.com/thaikolja/speaker-cli.git
# or: pipx install git+https://github.com/thaikolja/speaker-cli.git

# API key (pick one):
export GROQ_API_KEY=gsk_your_key_here          # shell
# or permanent file for global `speak` (recommended):
mkdir -p ~/.config/speaker
echo 'GROQ_API_KEY=gsk_your_key_here' > ~/.config/speaker/.env

speak "Hello from Groq."
speak "Guten Tag, das ist ein Test."
speak -f notes.txt
```

A project-local `./.env` is also loaded when you run `speak` from that directory.
A repo `.env` is **not** used if you run `speak` from elsewhere (e.g. `~/Downloads`).

With a working `GROQ_API_KEY`, **no model download and no Metal install** are required.

> Groq Orpheus accepts at most **200 characters** and is rate-limited. Longer text or a down API falls through to local / `say`.

## Offline / local Orpheus (optional)

When Groq is unavailable, `speak` tries **local** Orpheus for EN/DE (downloads ~2 GB GGUF per language on first use):

```bash
git clone https://github.com/thaikolja/speaker-cli.git
cd speaker-cli
uv sync --extra dev
./scripts/install_metal.sh          # Apple Silicon Metal llama.cpp
uv run speak "Hello offline."
```

Models land in the Hugging Face cache (`~/.cache/huggingface/hub/` by default), not in this repo.

To use local quality from a global `uv tool` install, install Metal `llama-cpp-python` into that tool environment as well (or run from a clone as above). Without Metal, local fails and macOS `say` is used.

## Available models

| Path | Language | Model ID / asset | Default voice | Notes |
|------|----------|------------------|---------------|--------|
| **Groq (default)** | English | `canopylabs/orpheus-v1-english` | `troy` | API; max **200** chars; rate-limited |
| **Local fallback** | English | [`isaiahbjork/orpheus-3b-0.1-ft-Q4_K_M-GGUF`](https://huggingface.co/isaiahbjork/orpheus-3b-0.1-ft-Q4_K_M-GGUF) | `leo` | ~2.2 GB Q4_K_M GGUF |
| **Local fallback** | German | [`freddyaboulton/3b-de-ft-research_release-Q4_K_M-GGUF`](https://huggingface.co/freddyaboulton/3b-de-ft-research_release-Q4_K_M-GGUF) | `leo` | ~2.0 GB Q4_K_M GGUF |
| **macOS fallback** | EN / DE | system `say` | Samantha / Anna | always offline |

### Local Orpheus voice tags (EN weights)

`tara` · `leah` · `jess` · `leo` · `dan` · `mia` · `zac` · `zoe`

DE uses the German GGUF with the same tag format (default `leo`). Groq’s `troy` is **API-only** and not in the open weights.

Configured in code: Groq constants in [`main.py`](main.py), `LANG_TO_REPO` / `DEFAULT_VOICE` in [`local_orpheus.py`](local_orpheus.py).

## Requirements

- macOS (playback uses `afplay`; `say` is the last-resort fallback)
- Python **3.11+**
- [uv](https://docs.astral.sh/uv/) (recommended) or pipx / pip
- `GROQ_API_KEY` for the easy cloud path
- Optional: ~5 GB disk + Apple Silicon Metal for local EN + DE GGUF

## Configuration

| Variable / constant | Meaning |
|---------------------|---------|
| `GROQ_API_KEY` | Primary cloud path (preflight: key + `models.list`) |
| `SPEAK_ENGINE` / `SPEAKER_ENGINE` | `auto` (default chain), or force `groq` / `local` / `say` |
| `SPEAK_SPEED` / `ORPHEUS_SPEED` | Playback rate (0.5–3.0, default `1.0`). Applied client-side (Orpheus ignores API `speed`). |
| `SPEAKER_ENV` | Optional path to an env file to load first |
| `LOCAL_VOICE_EN` / `LOCAL_VOICE_DE` | Local Orpheus voice tags (default `leo`) |
| `ORPHEUS_VOICE` | Groq voice (default `troy`) |
| `DELETE_AFTER_S` | Seconds before deleting `speech.wav` (default `10`) |

Copy [`.env.example`](.env.example) to `.env` in the project (or export in your shell) when developing from a clone.

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
main.py              # CLI + Groq-first orchestration
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
