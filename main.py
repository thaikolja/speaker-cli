"""speak — Orpheus TTS CLI with selectable backends.

Default priority (``SPEAK_ENGINE=auto``): Groq → local Orpheus (EN/DE) → macOS
``say``. Force a single backend with ``SPEAK_ENGINE=groq|local|say``.

Environment Variables
    ---------------------
    * ``GROQ_API_KEY`` — required for Groq (and for ``auto`` when using cloud).
    * ``SPEAK_ENGINE`` / ``SPEAKER_ENGINE`` — ``auto`` | ``groq`` | ``local`` | ``say``.
    * ``SPEAK_SPEED`` / ``ORPHEUS_SPEED`` — playback rate (client-side).
    * Loaded from the process env, then ``.env`` files (see :func:`load_env_files`).

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

ROOT = Path(__file__).resolve().parent
SPEECH_FILE = ROOT / "speech.wav"
USAGE_FILE = ROOT / ".groq_usage.json"
CONFIG_ENV = Path.home() / ".config" / "speaker" / ".env"
HOME_ENV = Path.home() / ".speaker.env"


def env_file_candidates() -> list[Path]:
    """``.env`` paths checked for secrets (first match wins per key).

    Order: ``SPEAKER_ENV`` (if set), cwd ``.env``, ``~/.config/speaker/.env``,
    ``~/.speaker.env``. Process environment always wins over files.
    """
    paths: list[Path] = []
    custom = os.environ.get("SPEAKER_ENV")
    if custom:
        paths.append(Path(custom).expanduser())
    paths.append(Path.cwd() / ".env")
    paths.append(CONFIG_ENV)
    paths.append(HOME_ENV)
    return paths


def load_env_files() -> list[Path]:
    """Load known ``.env`` files without overriding existing process env vars."""
    loaded: list[Path] = []
    for path in env_file_candidates():
        try:
            if path.is_file():
                load_dotenv(path, override=False)
                loaded.append(path)
        except OSError:
            continue
    return loaded


load_env_files()

# Local Orpheus — EN tags: tara, leah, jess, leo, dan, mia, zac, zoe (no "troy")
LOCAL_VOICE_EN = "leo"
LOCAL_VOICE_DE = "leo"
N_GPU_LAYERS = -1
N_CTX = 2048

# Groq fallback — https://console.groq.com/docs/rate-limits
# https://console.groq.com/docs/text-to-speech/orpheus
ORPHEUS_MODEL = "canopylabs/orpheus-v1-english"
ORPHEUS_VOICE = "troy"
ORPHEUS_SPEED = 1.0  # speaking rate; override with SPEAK_SPEED or ORPHEUS_SPEED env
ORPHEUS_SPEED_MIN = 0.5
ORPHEUS_SPEED_MAX = 3.0
ORPHEUS_MAX_CHARS = 200
ORPHEUS_RPM = 10
ORPHEUS_RPD = 100
ORPHEUS_TPM = 1200
ORPHEUS_TPD = 3600
API_TIMEOUT_S = 30.0
PREFLIGHT_TIMEOUT_S = 5.0
DELETE_AFTER_S = 10.0

# Backend selection: auto | groq | local | say (see :func:`speak_engine`)
DEFAULT_SPEAK_ENGINE = "auto"
SPEAK_ENGINES = frozenset({"auto", "groq", "local", "say"})
_SPEAK_ENGINE_ALIASES = {
    "auto": "auto",
    "default": "auto",
    "fallback": "auto",
    "groq": "groq",
    "cloud": "groq",
    "api": "groq",
    "local": "local",
    "orpheus": "local",
    "say": "say",
    "macos": "say",
    "macos_say": "say",
    "mac": "say",
}

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


def scale_wav_speed(path: Path, speed: float) -> None:
    """Rewrite ``path`` so playback duration is shorter/longer by ``speed``.

    Groq Orpheus ignores the API ``speed`` field; we change the WAV frame rate
    instead (faster → higher pitch). ``speed`` of ``1.0`` is a no-op.
    """
    if speed <= 0:
        raise ValueError(f"speed must be positive, got {speed}")
    if abs(speed - 1.0) < 1e-3:
        return
    with wave.open(str(path), "rb") as wf:
        nchannels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    new_rate = max(1, round(framerate * speed))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(nchannels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(new_rate)
        wf.writeframes(frames)


def play_wav(path: Path, *, speed: float = 1.0) -> None:
    """Play a WAV via ``afplay`` (retries), then ``ffplay`` if needed.

    ``speed`` is applied with ``afplay -r`` when not ``1.0`` (and as a filter for
    ffplay). Prefer :func:`scale_wav_speed` on the file when you need the WAV
    itself to reflect the rate.
    """
    path = path.resolve()
    last_err: Exception | None = None
    afplay_cmd = ["afplay"]
    if abs(speed - 1.0) >= 1e-3:
        afplay_cmd.extend(["-r", f"{speed:g}"])
    afplay_cmd.append(str(path))
    for _ in range(3):
        try:
            subprocess.run(afplay_cmd, check=True)
            return
        except Exception as e:
            last_err = e
            time.sleep(0.3)
    try:
        ffplay_cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]
        if abs(speed - 1.0) >= 1e-3:
            # atempo accepts 0.5-2.0 per filter; chain if needed is overkill here
            tempo = max(0.5, min(2.0, speed))
            ffplay_cmd.extend(["-af", f"atempo={tempo:g}"])
        ffplay_cmd.append(str(path))
        subprocess.run(ffplay_cmd, check=True)
        return
    except Exception:
        pass
    raise RuntimeError(f"playback failed: {last_err}")


def play_and_cleanup(path: Path = SPEECH_FILE, *, speed: float = 1.0) -> None:
    """Play ``path`` then schedule delayed deletion."""
    play_wav(path, speed=speed)
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
    speed = groq_speech_speed()
    scale_wav_speed(SPEECH_FILE, speed)
    try:
        play_and_cleanup(SPEECH_FILE, speed=1.0)
    except Exception as play_err:
        print(f"Local audio saved but play failed ({play_err}); keeping {DELETE_AFTER_S}s")
        cleanup_speech(SPEECH_FILE, DELETE_AFTER_S)


def groq_api_key() -> str | None:
    """Return stripped ``GROQ_API_KEY`` from the environment, or ``None``."""
    key = os.environ.get("GROQ_API_KEY")
    if key is None:
        return None
    key = key.strip().strip("'\"")
    return key or None


def groq_speech_speed() -> float:
    """Speaking rate for Groq TTS (``SPEAK_SPEED`` / ``ORPHEUS_SPEED``, else default).

    Clamped to :data:`ORPHEUS_SPEED_MIN` … :data:`ORPHEUS_SPEED_MAX`.
    """
    raw = os.environ.get("SPEAK_SPEED") or os.environ.get("ORPHEUS_SPEED")
    if raw is None or not str(raw).strip():
        return float(ORPHEUS_SPEED)
    try:
        speed = float(str(raw).strip().strip("'\""))
    except ValueError:
        return float(ORPHEUS_SPEED)
    return max(ORPHEUS_SPEED_MIN, min(ORPHEUS_SPEED_MAX, speed))


def speak_engine() -> str:
    """Return the configured backend: ``auto``, ``groq``, ``local``, or ``say``.

    Reads ``SPEAK_ENGINE`` or ``SPEAKER_ENGINE``. Unknown values fall back to
    ``auto`` with a stderr warning.
    """
    load_env_files()
    raw = os.environ.get("SPEAK_ENGINE") or os.environ.get("SPEAKER_ENGINE")
    if raw is None or not str(raw).strip():
        return DEFAULT_SPEAK_ENGINE
    key = str(raw).strip().strip("'\"").lower().replace("-", "_").replace(" ", "_")
    engine = _SPEAK_ENGINE_ALIASES.get(key)
    if engine is None:
        print(
            f"Unknown SPEAK_ENGINE={raw!r}; use auto|groq|local|say. Using auto.",
            file=sys.stderr,
        )
        return DEFAULT_SPEAK_ENGINE
    return engine


def preflight_groq(*, timeout_s: float = PREFLIGHT_TIMEOUT_S) -> tuple[bool, str]:
    """Check API key and that Groq is reachable (cheap ``models.list`` call).

    Returns
    -------
    ok, reason
        ``(True, "ok")`` or ``(False, human-readable reason)``.
    """
    # Reload so a cwd ``.env`` is seen even if the process started elsewhere.
    load_env_files()
    api_key = groq_api_key()
    if not api_key:
        return (
            False,
            f"GROQ_API_KEY not set (export it, or put it in {CONFIG_ENV} or ./.env)",
        )
    try:
        client = Groq(api_key=api_key, timeout=timeout_s)
        client.models.list()
    except Exception as e:
        return False, f"unreachable: {type(e).__name__}: {e}"
    return True, "ok"


def speak_groq(s: str) -> None:
    """Synthesize via Groq Orpheus API, play, record usage, cleanup."""
    api_key = groq_api_key()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    client = Groq(api_key=api_key, timeout=API_TIMEOUT_S)
    speed = groq_speech_speed()
    print(f"Groq → {ORPHEUS_VOICE} @ {speed:g}x")
    # Orpheus does not honor API ``speed``; we rescale the WAV after download.
    response = client.audio.speech.create(
        model=ORPHEUS_MODEL,
        voice=ORPHEUS_VOICE,
        response_format="wav",
        input=s,
    )
    SPEECH_FILE.write_bytes(response.read())
    scale_wav_speed(SPEECH_FILE, speed)
    record_usage(estimate_tokens(s))
    play_and_cleanup(SPEECH_FILE, speed=1.0)


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


def speak_say(s: str, reason: str = "") -> None:
    """Speak with macOS ``say``. ``reason`` is logged when non-empty."""
    lang = lang_code(s)
    voice = say_voice_for(lang if lang in ("en", "de") else "en")
    if reason:
        print(f"macOS say ({reason})")
    else:
        print("macOS say")
    if voice:
        print(f"voice: {voice}")
        subprocess.run(["say", "-v", voice, s], check=True)
    else:
        subprocess.run(["say", s], check=True)


def _try_groq(s: str, *, forced: bool) -> tuple[bool, str]:
    """Attempt Groq TTS. Returns ``(True, "")`` on success, else ``(False, reason)``."""
    ok, why = preflight_groq()
    if not ok:
        return False, why
    limits_ok, limit_reason = fits_groq_limits(s)
    if not limits_ok:
        return False, limit_reason
    try:
        speak_groq(s)
        return True, ""
    except RateLimitError as e:
        msg = f"rate limit: {e}"
    except APITimeoutError as e:
        msg = f"timeout: {e}"
    except APIConnectionError as e:
        msg = f"connection: {e}"
    except APIStatusError as e:
        msg = f"status {e.status_code}"
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
    if forced:
        raise RuntimeError(f"SPEAK_ENGINE=groq failed: {msg}") from None
    return False, msg


def _try_local(s: str, lang: str, *, forced: bool, prior: str = "") -> tuple[bool, str]:
    """Attempt local Orpheus. Returns ``(True, "")`` on success, else ``(False, reason)``."""
    if lang not in ("en", "de"):
        msg = f"unsupported lang '{lang}'"
        if forced:
            raise RuntimeError(f"SPEAK_ENGINE=local failed: {msg}")
        return False, msg
    try:
        if prior:
            print(f"Trying local Orpheus ({prior})…")
        speak_local_orpheus(s, lang)
        return True, ""
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        if forced:
            raise RuntimeError(f"SPEAK_ENGINE=local failed: {msg}") from e
        return False, msg


def speak(s: str) -> None:
    """Speak ``s`` using ``SPEAK_ENGINE`` (``auto`` | ``groq`` | ``local`` | ``say``)."""
    engine = speak_engine()
    lang = lang_code(s)

    if engine == "groq":
        ok, why = _try_groq(s, forced=True)
        if not ok:
            raise RuntimeError(f"SPEAK_ENGINE=groq failed: {why}")
        return

    if engine == "local":
        _try_local(s, lang, forced=True)
        return

    if engine == "say":
        speak_say(s, "SPEAK_ENGINE=say")
        return

    # auto: groq → local → say
    reasons: list[str] = []
    ok, why = _try_groq(s, forced=False)
    if ok:
        return
    reasons.append(f"groq skipped: {why}")

    ok, why = _try_local(s, lang, forced=False, prior="; ".join(reasons))
    if ok:
        return
    reasons.append(f"local {why}")

    speak_say(s, "; ".join(reasons) if reasons else "all backends failed")


def cli(argv: list[str] | None = None) -> int:
    """Parse CLI args and speak. Returns process exit code."""
    parser = argparse.ArgumentParser(
        prog="speak",
        description=(
            "TTS via Groq / local Orpheus / macOS say (set SPEAK_ENGINE=auto|groq|local|say)"
        ),
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
