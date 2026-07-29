# Troubleshooting

## `groq_api_key not set` / Groq skipped

- Set `GROQ_API_KEY` or `groq_api_key` in config.
- Run `speak --write-config ~/.config/speak/config.json` and edit the file.

## Groq rate limit / char limit

- Input max **200** characters for Orpheus.
- Free tier: 10 RPM / 100 RPD / 1.2K TPM / 3.6K TPD — ledger in `~/.cache/speak/groq_usage.json`.
- Wait or shorten text; auto falls back to local / say.

## German never uses Groq

Expected: Groq has **no German TTS model**. Auto chain is local → say.

## Arabic never uses local

Expected: local Orpheus GGUFs are EN/DE only. Auto chain is Groq → say.

## `llama-cpp-python is required`

Local path needs Metal build on Apple Silicon:

```bash
make install-metal
```

Without it, auto falls back to say (after Groq if applicable).

## Playback failed

- Ensure `afplay` (macOS) or `ffplay` (ffmpeg) is available.
- File is kept until process exit (`atexit`); path is `speech_file` in config.

## Wrong language / voice

- Short English words are forced to `en` (langdetect is noisy on tiny strings).
- German umlauts force `de`.
- Override: `--engine say --say-voice Anna` or force Groq voice with `--groq-voice hannah`.

## Verbose diagnostics

```bash
speak -v "Hello"
SPEAKER_ORT_VERBOSE=1 speak --engine local "Hello"
```

## Interrupted

`Ctrl+C` exits with code **130** and deletes the temp WAV immediately.
