# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
with [Conventional Commits](https://www.conventionalcommits.org/) style section tags
(`feat` / `fix` / `chore` / `docs` / `security` / …).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.1] — 2026-07-29

### feat
- (feat) language-aware `engine=auto`: Groq first **only when Groq has a model** (EN/AR); DE → local then say; other → say
- (feat) Arabic Groq model + default voice (`orpheus-arabic-saudi` / `fahad`)
- (feat) empty `groq_model` / `groq_voice` derive from detected language
- (feat) Groq English vocal directions: `--direction` / `groq_direction` (`[cheerful]`, …)
- (feat) logging + `--verbose` / `--quiet`; status via `_status()`
- (feat) `KeyboardInterrupt` → exit code 130 and immediate WAV cleanup
- (feat) CLI is **`speak` only** with full optional flags
- (feat) **`config.json`** defaults (`--write-config`); pitch-preserving `speed`
- (feat) Groq preflight (`models.list`) + client-side rate ledger
- (feat) local Orpheus TTS for English and German via llama.cpp (Metal) + SNAC

### fix
- (fix) CLI exits immediately after playback (`atexit` cleanup, no 10s hang)
- (fix) `--engine` accepts aliases (`macos`, `cloud`, `orpheus`, …)
- (fix) German no longer attempts doomed Groq calls (no DE model)
- (fix) remove unused `python-dotenv` direct dep and duplicate `onnxruntime` pin
- (fix) gitignore cwd `config.json` and `AGENTS.md`; ship `.env.example`

### docs
- (docs) `docs/` site: architecture, configuration, backends, CLI, development, troubleshooting
- (docs) README matches production workflow
- (docs) repo URLs → `thaikolja/speaker-cli`

### chore
- (chore) pytest (70% coverage floor), ruff, mypy, pre-commit
- (chore) CI on ubuntu + macOS (Python 3.11/3.12) with `speak` smoke

### security
- (security) API key only via config / `GROQ_API_KEY` (no hardcoded secrets)

### breaking
- (breaking) empty default `groq_model` / `groq_voice` (derive from language; set explicitly to pin)
- (breaking) auto chain for German is local→say (no Groq hop)
- (breaking) console script `speaker` removed (use `speak`)

[Unreleased]: https://github.com/thaikolja/speaker-cli/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/thaikolja/speaker-cli/releases/tag/v0.0.1
