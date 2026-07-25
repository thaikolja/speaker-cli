# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Email the maintainer privately with:

- description of the issue
- steps to reproduce
- impact assessment if known

## Secrets

- Never commit `.env` or API keys
- Use `.env.example` as a template only
- Rotate any key that may have been exposed historically

## Scope

This project runs local models and optional cloud TTS. Treat generated audio and usage logs as potentially sensitive if they contain private text.
