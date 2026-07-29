# Architecture

## Overview

`speak` is a thin TTS CLI with three backends and a language-aware fallback chain.

```
user text
     │
     ▼
  lang_code()          detect en / de / ar / other
     │
     ▼
  engine=auto? ──no──► forced backend (no fallback)
     │
    yes
     ▼
  auto_order(lang)     viable backends only
     │
     ▼
  _speak_chain()       try until one succeeds
     │
     ├── groq   → speak_groq()   → WAV → scale → play → atexit delete
     ├── local  → LocalOrpheus   → WAV → scale → play → atexit delete
     └── say    → macOS say      → (no file)
```

## Modules

| Module | Responsibility |
|--------|----------------|
| [`main.py`](../main.py) | CLI, `Settings`, config load, usage ledger, tempo, playback, orchestration |
| [`local_orpheus.py`](../local_orpheus.py) | GGUF load (llama.cpp), SNAC ONNX decode, streaming tokens → PCM |

## Auto chain rules

Defined in `GROQ_LANG_TO_MODEL`, `LOCAL_LANGS`, and `auto_order()`:

| Language | Order | Why |
|----------|--------|-----|
| English | groq → local → say | Groq has EN model |
| Arabic | groq → say | Groq has AR model; no local AR GGUF |
| German | local → say | Local DE GGUF; no Groq DE model |
| Other | say | Neither cloud nor local model |

Forced `engine=groq|local|say` never falls back; failures raise.

## Data flow (Groq / local)

1. Preflight (Groq only): API key + `models.list`
2. Limits (Groq only): char + RPM/RPD/TPM/TPD ledger
3. Synthesize → write WAV under `speech_file` (default `~/.cache/speak/speech.wav`)
4. Pitch-preserving speed (`ffmpeg atempo` or WSOLA)
5. Play (`afplay`, then `ffplay`)
6. Delete WAV on interpreter exit (`atexit`)

## Config resolution

See [configuration.md](configuration.md).
