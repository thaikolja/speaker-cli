# Backends

## 1. Groq Orpheus (cloud)

Docs: [Text to Speech](https://console.groq.com/docs/text-to-speech) · [Orpheus](https://console.groq.com/docs/text-to-speech/orpheus) · [Rate limits](https://console.groq.com/docs/rate-limits)

| Lang | Model | Default voice |
|------|--------|----------------|
| English | `canopylabs/orpheus-v1-english` | `troy` |
| Arabic | `canopylabs/orpheus-arabic-saudi` | `fahad` |

- **Max input:** 200 characters (`groq_max_chars`)
- **Format:** WAV only
- **EN voices:** `autumn`, `diana`, `hannah`, `austin`, `daniel`, `troy`
- **AR voices:** `abdullah`, `fahad`, `sultan`, `lulwa`, `noura`, `aisha`
- **Vocal directions (EN only):** `--direction cheerful` → input becomes `[cheerful] …`
- **Free tier (verify in console):** 10 RPM, 100 RPD, 1.2K TPM, 3.6K TPD

Client-side usage ledger: `~/.cache/speak/groq_usage.json` (24h rolling).

## 2. Local Orpheus (optional Metal)

Requires `./scripts/install_metal.sh` (llama-cpp-python + Metal).

| Lang | Hugging Face GGUF | Default voice |
|------|-------------------|---------------|
| EN | `isaiahbjork/orpheus-3b-0.1-ft-Q4_K_M-GGUF` | `leo` |
| DE | `freddyaboulton/3b-de-ft-research_release-Q4_K_M-GGUF` | `leo` |

SNAC decode: `onnx-community/snac_24khz-ONNX` (CPU by default).

Local open-source voice tags **differ** from Groq (`leo` ≠ `troy`).

## 3. macOS `say` (last resort)

- Parses `say -v ?` for installed voices
- Preferred lists for `en` / `de`; skips novelty voices
- Works for other languages if the system has a matching voice

## Forced engines

```bash
speak --engine groq "Hello"     # no fallback
speak --engine local "Hallo"    # no fallback
speak --engine say "Anything"   # no fallback
```
