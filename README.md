# speak

[![CI](https://img.shields.io/github/actions/workflow/status/thaikolja/speaker-cli/ci.yml?branch=main&label=CI)](../../actions/workflows/ci.yml) [![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/downloads/) [![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE) [![Ruff](https://img.shields.io/badge/code%20style-ruff-000000?logo=ruff)](https://docs.astral.sh/ruff/)

Text-to-speech CLI (`speak`): **Groq first when it supports the language**, then **local Orpheus**, then **macOS say**.

```
English:  text → Groq Orpheus → local Orpheus → macOS say
Arabic:   text → Groq Orpheus → macOS say
German:   text → local Orpheus (DE) → macOS say
Other:    text → macOS say
```

Forced `--engine groq|local|say` never falls back.

## Quick start

```bash
uv tool install git+https://github.com/thaikolja/speaker-cli.git

mkdir -p ~/.config/speak
speak --write-config ~/.config/speak/config.json
# set groq_api_key (or export GROQ_API_KEY)

speak "Hello from Groq."
speak "Guten Tag."
speak -d cheerful "Great news!"
speak -f notes.txt --speed 1.25
speak --engine say "Offline only"
speak --help
```

## Documentation

| Doc | Contents |
|-----|----------|
| [docs/architecture.md](docs/architecture.md) | Modules, chain, data flow |
| [docs/configuration.md](docs/configuration.md) | config.json, env, settings |
| [docs/backends.md](docs/backends.md) | Groq / local / say |
| [docs/cli-reference.md](docs/cli-reference.md) | Flags, exit codes, examples |
| [docs/development.md](docs/development.md) | Setup, tests, gates |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common failures |

## Config

JSON only (not `.env` for defaults). Search order: `--config` → `$SPEAK_CONFIG` → `./config.json` → `~/.config/speak/config.json`.

Optional env: `GROQ_API_KEY`, `SPEAK_CONFIG`. See [`.env.example`](.env.example) and [`config.example.json`](config.example.json).

## Models

| Path | Language | Model/Asset | Default Voice |
|------|----------|---------------|---------------|
| **Groq** | English | `canopylabs/orpheus-v1-english` | `troy` (max **200** chars) |
| **Groq** | Arabic | `canopylabs/orpheus-arabic-saudi` | `fahad` |
| **Local** | English | [GGUF EN](https://huggingface.co/isaiahbjork/orpheus-3b-0.1-ft-Q4_K_M-GGUF) | `leo` |
| **Local** | German | [GGUF DE](https://huggingface.co/freddyaboulton/3b-de-ft-research_release-Q4_K_M-GGUF) | `leo` |
| **say** | system | macOS voices | auto |

## Offline/local Orpheus (optional)

```bash
git clone https://github.com/thaikolja/speaker-cli.git
cd speaker-cli
uv sync --extra dev
make install-metal   # Apple Silicon Metal llama-cpp-python
speak --engine local "Hello offline."
```

## Development

```bash
uv sync --extra dev
make check
```

See [docs/development.md](docs/development.md).

## License

[MIT](LICENSE)
