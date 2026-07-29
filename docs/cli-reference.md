# CLI reference

```bash
speak [text] [-f FILE] [options]
```

## Arguments

| Argument | Description |
|----------|-------------|
| `text` | Text to speak (optional if `-f` given) |
| `-f`, `--file` | UTF-8 file to read |

## Common options

| Flag | Description |
|------|-------------|
| `--engine` | `auto` \| `groq` \| `local` \| `say` (aliases: `macos`, `cloud`, `orpheus`, …) |
| `--speed` | Pitch-preserving tempo |
| `-d`, `--direction` | Groq EN vocal direction (`cheerful`, `whisper`, …) |
| `--config` | Path to `config.json` |
| `--write-config PATH` | Write full defaults JSON and exit |
| `-v`, `--verbose` | Debug logs on stderr |
| `-q`, `--quiet` | Suppress status lines; errors only |
| `--help` | Full flag list with defaults |

## Groq options

`--groq-api-key`, `--groq-model`, `--groq-voice`, `--max-chars`, `--rpm`, `--rpd`, `--tpm`, `--tpd`, `--api-timeout`, `--preflight-timeout`

Empty model/voice → derived from detected language.

## Local options

`--local-voice-en`, `--local-voice-de`, `--n-gpu-layers`, `--n-ctx`

## Other

`--say-voice`, `--delete-after`, `--speech-file`, `--usage-file`

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success (or `--write-config` wrote file) |
| `1` | Runtime error (all backends failed, forced engine failed, …) |
| `2` | Usage error (no text / empty file) |
| `130` | Interrupted (`Ctrl+C`) |

## Examples

```bash
speak "Hello world"
speak "Guten Tag, wie geht es Ihnen?"
speak -d cheerful "Great news today"
speak -f notes.txt --speed 1.25 --quiet
speak --engine say "Offline only"
speak --write-config ~/.config/speak/config.json
```
