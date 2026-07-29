# Configuration

## Search order

1. `--config PATH`
2. `$SPEAK_CONFIG`
3. `./config.json` (cwd — gitignored)
4. `~/.config/speak/config.json`
5. `~/.config/speaker/config.json` (legacy)

First existing file wins. Missing/invalid files warn and fall back to built-in defaults.

## Bootstrap

```bash
mkdir -p ~/.config/speak
speak --write-config ~/.config/speak/config.json
# edit groq_api_key
```

See [`config.example.json`](../config.example.json).

## Environment

| Variable | Effect |
|----------|--------|
| `GROQ_API_KEY` | Overrides `groq_api_key` in config |
| `SPEAK_CONFIG` | Config file path |
| `SPEAKER_ORT_VERBOSE=1` | Verbose ONNX Runtime logs |
| `SPEAKER_USE_COREML=1` | Try CoreML EP for SNAC |
| `SPEAK_RUN_INTEGRATION=1` | Enable `@pytest.mark.integration` tests |

## Settings fields

| Key | Default | Notes |
|-----|---------|--------|
| `engine` | `auto` | `auto` \| `groq` \| `local` \| `say` (+ aliases) |
| `speed` | `1.0` | Clamped to `[speed_min, speed_max]` |
| `groq_api_key` | `""` | Prefer env for secrets |
| `groq_model` | `""` | Empty → derive from language |
| `groq_voice` | `""` | Empty → derive from language |
| `groq_direction` | `""` | EN model only (`cheerful`, `whisper`, …) |
| `groq_max_chars` | `200` | Groq Orpheus limit |
| `groq_rpm` / `rpd` / `tpm` / `tpd` | free-tier defaults | Client-side ledger |
| `local_voice_en` / `local_voice_de` | `leo` | Local tags (not Groq names) |
| `n_gpu_layers` / `n_ctx` | `-1` / `2048` | llama.cpp |
| `say_voice` | `""` | Empty → auto-pick |
| `delete_after_s` | `10.0` | Kept for API compat; cleanup is `atexit` |
| `speech_file` / `usage_file` | under `~/.cache/speak/` | Expand `~` |
| `verbose` / `quiet` | `false` | Logging / status |

CLI flags override every field (see [cli-reference.md](cli-reference.md)).
