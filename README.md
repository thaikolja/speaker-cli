# speak

[![CI](https://img.shields.io/github/actions/workflow/status/kolja/speaker/ci.yml?branch=main&label=CI)](../../actions/workflows/ci.yml) [![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/downloads/) [![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE) [![Ruff](https://img.shields.io/badge/code%20style-ruff-000000?logo=ruff)](https://docs.astral.sh/ruff/)

Easy **text-to-speech** CLI (`speak`) for **English** and **German**.

```
English (engine=auto):
  text → Groq Orpheus (troy)
           ↓ fail
         local Orpheus (EN)
           ↓ fail
         macOS say

German (engine=auto):
  text → macOS say (Anna, …)        # native
           ↓ fail
         local Orpheus (DE)
           ↓ fail
         Groq
```

## Quick start

```bash
uv tool install git+https://github.com/thaikolja/speaker-cli.git

# create config (all defaults + your API key)
mkdir -p ~/.config/speak
speak --write-config ~/.config/speak/config.json
# edit groq_api_key, engine, speed, …

speak "Hello from Groq."
speak "Guten Tag." --engine say
speak -f notes.txt --speed 1.25 --groq-voice hannah
speak --help
```

Config is **JSON** (not `.env`). Search order:

1. `--config PATH`
2. `$SPEAK_CONFIG`
3. `./config.json`
4. `~/.config/speak/config.json`
5. `~/.config/speaker/config.json` (legacy)

CLI flags override config. Every flag is optional and shows its default in `--help`.

## Configuration

See [`config.example.json`](config.example.json). Important keys:

| Key | Default | Meaning |
|-----|---------|---------|
| `engine` | `auto` | `auto` (EN→Groq first, DE→macOS say first) \| `groq` \| `local` \| `say` |
| `speed` | `1.0` | Pitch-preserving tempo (0.5–3.0) |
| `groq_api_key` | `""` | Groq key (or env `GROQ_API_KEY` override) |
| `groq_voice` | `troy` | Groq voice |
| `groq_model` | `canopylabs/orpheus-v1-english` | Groq model |
| `local_voice_en` / `local_voice_de` | `leo` | Local Orpheus tags |
| `say_voice` | `""` | Force macOS voice; empty = auto |
| `speech_file` / `usage_file` | under `~/.cache/speak/` | Runtime files |

Generate a full file anytime:

```bash
speak --write-config ~/.config/speak/config.json
```

## CLI flags (all optional)

```text
speak [text] [-f FILE] [--config PATH]
      [--engine auto|groq|local|say] [--speed N]
      [--groq-api-key KEY] [--groq-model ID] [--groq-voice NAME]
      [--max-chars N] [--rpm N] [--rpd N] [--tpm N] [--tpd N]
      [--api-timeout S] [--preflight-timeout S]
      [--local-voice-en TAG] [--local-voice-de TAG]
      [--n-gpu-layers N] [--n-ctx N]
      [--say-voice NAME] [--delete-after S]
      [--speech-file PATH] [--usage-file PATH]
      [--write-config PATH]
```

## Available models

| Path | Language | Model / asset | Default voice |
|------|----------|---------------|---------------|
| **Groq** | English | `canopylabs/orpheus-v1-english` | `troy` (max **200** chars) |
| **Local** | English | [`isaiahbjork/orpheus-3b-0.1-ft-Q4_K_M-GGUF`](https://huggingface.co/isaiahbjork/orpheus-3b-0.1-ft-Q4_K_M-GGUF) | `leo` |
| **Local** | German | [`freddyaboulton/3b-de-ft-research_release-Q4_K_M-GGUF`](https://huggingface.co/freddyaboulton/3b-de-ft-research_release-Q4_K_M-GGUF) | `leo` |
| **macOS** | EN / DE | system `say` | Samantha / Anna |

Local voice tags: `tara` · `leah` · `jess` · `leo` · `dan` · `mia` · `zac` · `zoe`

## Offline / local Orpheus (optional)

```bash
git clone https://github.com/thaikolja/speaker-cli.git
cd speaker-cli
uv sync --extra dev
./scripts/install_metal.sh
uv run speak "Hello offline." --engine local
```

Models download into the Hugging Face cache on first local use (`~/.cache/huggingface/hub/`).

## Requirements

- macOS (playback via `afplay`; `say` last resort)
- Python **3.11+**
- [uv](https://docs.astral.sh/uv/) (recommended)
- Optional: `ffmpeg` for higher-quality pitch-preserving tempo
- Optional: Metal `llama-cpp-python` for local Orpheus

## Development

```bash
uv sync --extra dev
./scripts/install_metal.sh          # local machine only
uv run ruff check .
uv run ruff format .
uv run mypy main.py local_orpheus.py
uv run pytest
```

## License

MIT — see [LICENSE](LICENSE).

Upstream Orpheus models/code have their own licenses (Hugging Face / [canopyai/Orpheus-TTS](https://github.com/canopyai/Orpheus-TTS)).
