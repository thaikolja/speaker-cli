"""speak — Groq-first Orpheus TTS CLI with local and system fallbacks.

Priority: Groq Orpheus API (``troy``) → local Orpheus (EN/DE) → macOS ``say``.

Environment Variables
    ---------------------
    * ``GROQ_API_KEY`` — primary path; without it (or if unreachable), local/say.
    * Values from a project ``.env`` are loaded at import time.

CLI::

    speak "Hello world"
    speak -f notes.txt
    python main.py "Guten Tag"
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from dotenv import load_dotenv
from groq import APIConnectionError, APIStatusError, APITimeoutError, Groq, RateLimitError
from langdetect import detect

if TYPE_CHECKING:
    from local_orpheus import LocalOrpheus

load_dotenv()

ROOT = Path(__file__).resolve().parent
SPEECH_FILE = ROOT / "speech.wav"
USAGE_FILE = ROOT / ".groq_usage.json"

# Local Orpheus — EN tags: tara, leah, jess, leo, dan, mia, zac, zoe (no "troy")
LOCAL_VOICE_EN = "leo"
LOCAL_VOICE_DE = "leo"
N_GPU_LAYERS = -1
N_CTX = 2048

# Groq fallback — https://console.groq.com/docs/rate-limits
# https://console.groq.com/docs/text-to-speech/orpheus
ORPHEUS_MODEL = "canopylabs/orpheus-v1-english"
ORPHEUS_VOICE = "troy"
ORPHEUS_MAX_CHARS = 200
ORPHEUS_RPM = 10
ORPHEUS_RPD = 100
ORPHEUS_TPM = 1200
ORPHEUS_TPD = 3600
API_TIMEOUT_S = 30.0
PREFLIGHT_TIMEOUT_S = 5.0
DELETE_AFTER_S = 10.0

SAY_PREFERRED = {
    "en": ["Samantha", "Daniel"],
    "de": ["Anna", "Reed (Deutsch (Deutschland))", "Eddy (Deutsch (Deutschland))"],
}
SAY_SKIP = {
    "Albert",
    "Bad News",
    "Bahh",
    "Bells",
    "Boing",
    "Bubbles",
    "Cellos",
    "Wobble",
    "Fred",
    "Good News",
    "Jester",
    "Junior",
    "Kathy",
    "Organ",
    "Superstar",
    "Ralph",
    "Trinoids",
    "Whisper",
    "Zarvox",
    "Grandma",
    "Grandpa",
}

_engine: LocalOrpheus | None = None
_engine_lang: str | None = None


def estimate_tokens(s: str) -> int:
    """Rough token estimate for Groq pre-checks (~4 characters per token).

    Always returns at least ``1``, including for the empty string.
    """
    return max(1, (len(s) + 3) // 4)


def load_usage(path: Path = USAGE_FILE) -> list[dict]:
    """Load Groq usage events, dropping entries older than 24 hours."""
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text())
        cutoff = time.time() - 86400
        return [e for e in data.get("events", []) if e.get("ts", 0) >= cutoff]
    except (json.JSONDecodeError, OSError):
        return []


def save_usage(events: list[dict], path: Path = USAGE_FILE) -> None:
    """Persist usage events after pruning anything older than 24 hours."""
    cutoff = time.time() - 86400
    events = [e for e in events if e.get("ts", 0) >= cutoff]
    path.write_text(json.dumps({"events": events}, indent=2))


def record_usage(tokens: int, path: Path = USAGE_FILE) -> None:
    """Append one successful Groq call to the usage ledger."""
    events = load_usage(path)
    events.append({"ts": time.time(), "tokens": tokens})
    save_usage(events, path)


def fits_groq_limits(
    s: str,
    *,
    usage_path: Path = USAGE_FILE,
    max_chars: int = ORPHEUS_MAX_CHARS,
    rpm: int = ORPHEUS_RPM,
    rpd: int = ORPHEUS_RPD,
    tpm: int = ORPHEUS_TPM,
    tpd: int = ORPHEUS_TPD,
    now: float | None = None,
) -> tuple[bool, str]:
    """Whether ``s`` may be sent to Groq under char and rate limits.

    Returns
    -------
    ok, reason
        ``(True, "ok")`` or ``(False, human-readable reason)``.
    """
    if len(s) > max_chars:
        return False, f"input {len(s)} chars > {max_chars} max"
    tokens = estimate_tokens(s)
    ts = time.time() if now is None else now
    events = load_usage(usage_path)
    last_min = [e for e in events if e["ts"] >= ts - 60]
    if len(last_min) >= rpm:
        return False, f"RPM {len(last_min)}/{rpm}"
    if len(events) >= rpd:
        return False, f"RPD {len(events)}/{rpd}"
    used_tpm = sum(e["tokens"] for e in last_min)
    used_tpd = sum(e["tokens"] for e in events)
    if used_tpm + tokens > tpm:
        return False, f"TPM {used_tpm}+{tokens} > {tpm}"
    if used_tpd + tokens > tpd:
        return False, f"TPD {used_tpd}+{tokens} > {tpd}"
    return True, "ok"


def cleanup_speech(path: Path = SPEECH_FILE, delay_s: float = DELETE_AFTER_S) -> None:
    """Delete ``path`` now (``delay_s <= 0``) or after ``delay_s`` seconds."""

    def _delete() -> None:
        if delay_s > 0:
            time.sleep(delay_s)
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)

    if delay_s <= 0:
        path.unlink(missing_ok=True)
        return
    threading.Thread(target=_delete, daemon=True).start()


def write_wav_mono_i16(path: Path, sample_rate: int, audio: np.ndarray) -> None:
    """Write mono 16-bit PCM WAV (e.g. for ``afplay``)."""
    audio = np.ascontiguousarray(np.asarray(audio).squeeze(), dtype=np.int16)
    if audio.ndim != 1:
        audio = audio.reshape(-1)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(audio.tobytes())


def play_wav(path: Path) -> None:
    """Play a WAV via ``afplay`` (retries), then ``ffplay`` if needed."""
    path = path.resolve()
    last_err: Exception | None = None
    for _ in range(3):
        try:
            subprocess.run(["afplay", str(path)], check=True)
            return
        except Exception as e:
            last_err = e
            time.sleep(0.3)
    try:
        subprocess.run(
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)],
            check=True,
        )
        return
    except Exception:
        pass
    raise RuntimeError(f"playback failed: {last_err}")


def play_and_cleanup(path: Path = SPEECH_FILE) -> None:
    """Play ``path`` then schedule delayed deletion."""
    play_wav(path)
    cleanup_speech(path, DELETE_AFTER_S)


def lang_code(s: str) -> str:
    """Return ``de``, ``en``, or the raw langdetect code for other languages."""
    try:
        code = str(detect(s))
    except Exception:
        code = "en"
    if code.startswith("de"):
        return "de"
    if code.startswith("en"):
        return "en"
    return code


def get_local_engine(lang: str) -> LocalOrpheus:
    """Return a cached :class:`LocalOrpheus` for ``lang`` (one model resident).

    Imports ``local_orpheus`` lazily so ``speak --help`` and the Groq path work
    without optional Metal ``llama-cpp-python``.
    """
    global _engine, _engine_lang
    from local_orpheus import LocalOrpheus as _LocalOrpheus

    if lang not in ("en", "de"):
        raise ValueError(f"local Orpheus only supports en/de, got {lang}")
    if _engine is not None and _engine_lang == lang:
        return _engine
    _engine = None
    _engine_lang = None
    _engine = _LocalOrpheus(lang=lang, n_gpu_layers=N_GPU_LAYERS, n_ctx=N_CTX, verbose=False)
    _engine_lang = lang
    return _engine


def speak_local_orpheus(s: str, lang: str) -> None:
    """Synthesize with local Orpheus, play, and schedule WAV cleanup."""
    voice = LOCAL_VOICE_EN if lang == "en" else LOCAL_VOICE_DE
    engine = get_local_engine(lang)
    print(f"Local Orpheus → lang={lang} voice={voice}")

    SPEECH_FILE.unlink(missing_ok=True)
    sample_rate, samples = engine.tts(s, voice_id=voice)
    audio = np.asarray(samples).squeeze()
    if audio.size == 0:
        raise RuntimeError("local Orpheus returned empty audio")
    write_wav_mono_i16(SPEECH_FILE, sample_rate, audio)
    try:
        play_and_cleanup(SPEECH_FILE)
    except Exception as play_err:
        print(f"Local audio saved but play failed ({play_err}); keeping {DELETE_AFTER_S}s")
        cleanup_speech(SPEECH_FILE, DELETE_AFTER_S)


def preflight_groq(*, timeout_s: float = PREFLIGHT_TIMEOUT_S) -> tuple[bool, str]:
    """Check API key and that Groq is reachable (cheap ``models.list`` call).

    Returns
    -------
    ok, reason
        ``(True, "ok")`` or ``(False, human-readable reason)``.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key or not api_key.strip():
        return False, "GROQ_API_KEY not set"
    try:
        client = Groq(api_key=api_key.strip(), timeout=timeout_s)
        client.models.list()
    except Exception as e:
        return False, f"unreachable: {type(e).__name__}: {e}"
    return True, "ok"


def speak_groq(s: str) -> None:
    """Synthesize via Groq Orpheus API, play, record usage, cleanup."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    client = Groq(api_key=api_key, timeout=API_TIMEOUT_S)
    print(f"Groq → {ORPHEUS_VOICE}")
    response = client.audio.speech.create(
        model=ORPHEUS_MODEL,
        voice=ORPHEUS_VOICE,
        response_format="wav",
        input=s,
    )
    SPEECH_FILE.write_bytes(response.read())
    record_usage(estimate_tokens(s))
    play_and_cleanup(SPEECH_FILE)


def list_say_voices() -> list[tuple[str, str]]:
    """Parse ``say -v ?`` into ``(voice_name, lang_REGION)`` pairs."""
    out = subprocess.check_output(["say", "-v", "?"], text=True)
    voices: list[tuple[str, str]] = []
    for line in out.strip().splitlines():
        m = re.match(r"^(.+?)\s+([a-z]{2}[_-][A-Z]{2})\s+#", line)
        if m:
            voices.append((m.group(1).strip(), m.group(2).replace("-", "_")))
    return voices


def say_voice_for(
    lang: str,
    voices: list[tuple[str, str]] | None = None,
) -> str | None:
    """Best installed macOS ``say`` voice for ``lang``, or ``None``."""
    if voices is None:
        voices = list_say_voices()
    installed = {name: code for name, code in voices}
    for name in SAY_PREFERRED.get(lang, []):
        if name in installed:
            return name
    for name, code in voices:
        base = name.split(" (")[0]
        if code.startswith(lang) and base not in SAY_SKIP and name not in SAY_SKIP:
            if any(x in name for x in ("Grandma", "Grandpa", "Superstar")):
                continue
            return name
    return None


def speak_say(s: str, reason: str) -> None:
    """Speak with macOS ``say`` and log why this fallback was used."""
    lang = lang_code(s)
    voice = say_voice_for(lang if lang in ("en", "de") else "en")
    print(f"macOS say fallback ({reason})")
    if voice:
        print(f"voice: {voice}")
        subprocess.run(["say", "-v", voice, s], check=True)
    else:
        subprocess.run(["say", s], check=True)


def speak(s: str) -> None:
    """Speak ``s``: Groq (if reachable), then local Orpheus EN/DE, then ``say``."""
    reasons: list[str] = []
    lang = lang_code(s)

    ok, why = preflight_groq()
    if not ok:
        reasons.append(f"groq skipped: {why}")
    else:
        limits_ok, limit_reason = fits_groq_limits(s)
        if not limits_ok:
            reasons.append(f"groq skipped: {limit_reason}")
        else:
            try:
                speak_groq(s)
                return
            except RateLimitError as e:
                reasons.append(f"groq rate limit: {e}")
            except APITimeoutError as e:
                reasons.append(f"groq timeout: {e}")
            except APIConnectionError as e:
                reasons.append(f"groq connection: {e}")
            except APIStatusError as e:
                reasons.append(f"groq status {e.status_code}")
            except Exception as e:
                reasons.append(f"groq {type(e).__name__}: {e}")

    if lang in ("en", "de"):
        try:
            if reasons:
                print(f"Trying local Orpheus ({'; '.join(reasons)})…")
            speak_local_orpheus(s, lang)
            return
        except Exception as e:
            reasons.append(f"local {type(e).__name__}: {e}")
    else:
        reasons.append(f"local unsupported lang '{lang}'")

    speak_say(s, "; ".join(reasons) if reasons else "all backends failed")


def cli(argv: list[str] | None = None) -> int:
    """Parse CLI args and speak. Returns process exit code."""
    parser = argparse.ArgumentParser(
        prog="speak",
        description="Groq-first Orpheus TTS (EN/DE local + macOS say fallbacks)",
    )
    parser.add_argument(
        "text",
        nargs="?",
        default=None,
        help="Text to speak",
    )
    parser.add_argument(
        "-f",
        "--file",
        type=Path,
        help="Read text from a UTF-8 file",
    )
    args = parser.parse_args(argv)

    if args.file is not None:
        payload = args.file.read_text(encoding="utf-8").strip()
    elif args.text is not None:
        payload = args.text
    else:
        print("No text to speak. Pass text or -f FILE.", file=sys.stderr)
        return 2

    if not payload:
        print("No text to speak.", file=sys.stderr)
        return 2

    speak(payload)
    if SPEECH_FILE.exists():
        time.sleep(DELETE_AFTER_S + 0.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
