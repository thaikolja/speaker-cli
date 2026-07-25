# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
with [Conventional Commits](https://www.conventionalcommits.org/) style section tags
(`feat` / `fix` / `chore` / `docs` / `security` / …).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### feat
- (feat) CLI entrypoint `speak` (alias `speaker`); intended global install via `uv tool install` / pipx
- (feat) Groq-first orchestration: key + reachability preflight (`models.list`), then local Orpheus EN/DE, then macOS `say`
- (feat) `preflight_groq()` — cheap connectivity check before TTS

### docs
- (docs) README quick start for `speak` + Groq; Metal/local documented as optional offline path
- (docs) AGENTS.md priority inverted to match product (Groq → local → say)
- (chore) fixed README: CI/Python/License/Ruff badges
- (docs) available models table (local EN/DE GGUF, Groq, macOS say) in README
- (docs) concise module/public API pydocs in `main.py` and `local_orpheus.py` (no restating inline comments)
- (docs) header docs on `scripts/install_metal.sh`

### fix
- (fix) load ``GROQ_API_KEY`` from ``~/.config/speaker/.env``, ``~/.speaker.env``, cwd ``.env``, or ``SPEAKER_ENV`` (global ``speak`` no longer requires exporting the key every session)
- (fix) lazy-import ``llama_cpp`` / ``LocalOrpheus`` so ``speak --help`` and Groq work without Metal install
- (fix) SNAC decoder defaults to CPU to avoid macOS CoreAnalytics "Context leak" console spam; set `SPEAKER_USE_COREML=1` to opt back in

## [0.0.1] — 2026-07-25

### feat
- (feat) local-first Orpheus TTS for English and German via llama.cpp (Metal) + SNAC
- (feat) models: `isaiahbjork/orpheus-3b-0.1-ft-Q4_K_M-GGUF` (EN), `freddyaboulton/3b-de-ft-research_release-Q4_K_M-GGUF` (DE)
- (feat) default local voice `leo`; Groq fallback voice `troy`
- (feat) fallback chain: local Orpheus → Groq Orpheus API → macOS `say`
- (feat) Groq rate-limit pre-check (200-char cap, RPM/RPD/TPM/TPD)
- (feat) auto-delete generated WAV after playback (default 10s)
- (feat) CLI: `speaker` / `python main.py [text] [-f file]`

### chore
- (chore) pytest, ruff, mypy, pre-commit, GitHub Actions CI
- (chore) `AGENTS.md` for coding agents
- (chore) MIT license, CONTRIBUTING, SECURITY

### security
- (security) Groq API key only via `GROQ_API_KEY` / `.env` (no hardcoded secrets)

[Unreleased]: https://github.com/kolja/speaker/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/kolja/speaker/releases/tag/v0.0.1
