"""speak — Orpheus TTS CLI with selectable backends and JSON config.

Default priority (``engine=auto``), by language:

* **English:** Groq → local Orpheus → macOS ``say``
* **German:** macOS ``say`` (native) → local Orpheus → Groq

Force one backend for all languages with ``engine=groq|local|say``.

Defaults live in ``config.json`` (see :func:`config_paths`). CLI flags override
the loaded config; all flags are optional.

CLI::

    speak "Hello world"
    speak "Guten Tag"
    speak -f notes.txt --engine groq --speed 1.25
    speak --help
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from copy import deepcopy
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from groq import APIConnectionError, APIStatusError, APITimeoutError, Groq, RateLimitError

if TYPE_CHECKING:
    from local_orpheus import LocalOrpheus

ROOT = Path(__file__).resolve().parent
CONFIG_DIR = Path.home() / ".config" / "speak"
CACHE_DIR = Path.home() / ".cache" / "speak"

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


@dataclass
class Settings:
    """All runtime defaults (config.json + CLI overrides)."""

    engine: str = "auto"
    speed: float = 1.0
    speed_min: float = 0.5
    speed_max: float = 3.0

    groq_api_key: str = ""
    groq_model: str = "canopylabs/orpheus-v1-english"
    groq_voice: str = "troy"
    groq_max_chars: int = 200
    groq_rpm: int = 10
    groq_rpd: int = 100
    groq_tpm: int = 1200
    groq_tpd: int = 3600
    api_timeout_s: float = 30.0
    preflight_timeout_s: float = 5.0

    local_voice_en: str = "leo"
    local_voice_de: str = "leo"
    n_gpu_layers: int = -1
    n_ctx: int = 2048

    say_voice: str = ""  # empty = auto-pick from preferred lists

    delete_after_s: float = 10.0
    speech_file: str = str(CACHE_DIR / "speech.wav")
    usage_file: str = str(CACHE_DIR / "groq_usage.json")

    def normalize(self) -> Settings:
        """Clamp / alias fields; return self."""
        self.engine = normalize_engine(self.engine)
        self.speed = max(self.speed_min, min(self.speed_max, float(self.speed)))
        self.groq_api_key = (self.groq_api_key or "").strip().strip("'\"")
        self.say_voice = (self.say_voice or "").strip()
        self.speech_file = str(Path(self.speech_file).expanduser())
        self.usage_file = str(Path(self.usage_file).expanduser())
        return self

    def speech_path(self) -> Path:
        return Path(self.speech_file)

    def usage_path(self) -> Path:
        return Path(self.usage_file)


# Module defaults / test aliases (mirror Settings field defaults)
DEFAULT_SETTINGS = Settings()
ORPHEUS_SPEED = DEFAULT_SETTINGS.speed
ORPHEUS_SPEED_MIN = DEFAULT_SETTINGS.speed_min
ORPHEUS_SPEED_MAX = DEFAULT_SETTINGS.speed_max
ORPHEUS_MAX_CHARS = DEFAULT_SETTINGS.groq_max_chars
ORPHEUS_RPM = DEFAULT_SETTINGS.groq_rpm
ORPHEUS_RPD = DEFAULT_SETTINGS.groq_rpd
ORPHEUS_TPM = DEFAULT_SETTINGS.groq_tpm
ORPHEUS_TPD = DEFAULT_SETTINGS.groq_tpd
ORPHEUS_MODEL = DEFAULT_SETTINGS.groq_model
ORPHEUS_VOICE = DEFAULT_SETTINGS.groq_voice
DELETE_AFTER_S = DEFAULT_SETTINGS.delete_after_s
API_TIMEOUT_S = DEFAULT_SETTINGS.api_timeout_s
PREFLIGHT_TIMEOUT_S = DEFAULT_SETTINGS.preflight_timeout_s
DEFAULT_SPEAK_ENGINE = DEFAULT_SETTINGS.engine

_settings = Settings()
_engine: LocalOrpheus | None = None
_engine_lang: str | None = None


def get_settings() -> Settings:
    """Return the active settings object."""
    return _settings


def set_settings(settings: Settings) -> None:
    """Replace active settings (used by CLI and tests)."""
    global _settings
    _settings = settings.normalize()


def normalize_engine(raw: str) -> str:
    """Map engine aliases to ``auto|groq|local|say``."""
    key = str(raw or "auto").strip().strip("'\"").lower().replace("-", "_").replace(" ", "_")
    engine = _SPEAK_ENGINE_ALIASES.get(key)
    if engine is None:
        print(
            f"Unknown engine={raw!r}; use auto|groq|local|say. Using auto.",
            file=sys.stderr,
        )
        return "auto"
    return engine


def config_paths(explicit: Path | None = None) -> list[Path]:
    """Candidate ``config.json`` paths (first existing file wins when loading)."""
    paths: list[Path] = []
    if explicit is not None:
        paths.append(explicit.expanduser())
    env_path = os.environ.get("SPEAK_CONFIG")
    if env_path:
        paths.append(Path(env_path).expanduser())
    paths.append(Path.cwd() / "config.json")
    paths.append(CONFIG_DIR / "config.json")
    # Legacy location from earlier builds
    paths.append(Path.home() / ".config" / "speaker" / "config.json")
    return paths


def default_settings_dict() -> dict[str, Any]:
    """JSON-serializable default config."""
    return asdict(Settings())


def load_config_file(path: Path) -> dict[str, Any]:
    """Load a JSON object from ``path``; empty dict on missing/invalid."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"Warning: could not read config {path}: {e}", file=sys.stderr)
        return {}
    if not isinstance(data, dict):
        print(f"Warning: config {path} is not a JSON object; ignoring", file=sys.stderr)
        return {}
    return data


def settings_from_mapping(data: dict[str, Any], base: Settings | None = None) -> Settings:
    """Merge known keys from ``data`` into a Settings copy."""
    s = deepcopy(base) if base is not None else Settings()
    known = {f.name for f in fields(Settings)}
    for key, value in data.items():
        if key in known:
            setattr(s, key, value)
    return s.normalize()


def load_settings(explicit_config: Path | None = None) -> Settings:
    """Load Settings from the first existing config path (or built-in defaults)."""
    settings = Settings()
    for path in config_paths(explicit_config):
        if path.is_file():
            settings = settings_from_mapping(load_config_file(path), settings)
            break
    return settings.normalize()


def ensure_parent(path: Path) -> None:
    """Create parent directory for ``path`` if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)


def estimate_tokens(s: str) -> int:
    """Rough token estimate for Groq pre-checks (~4 characters per token)."""
    return max(1, (len(s) + 3) // 4)


def load_usage(path: Path | None = None) -> list[dict]:
    """Load Groq usage events, dropping entries older than 24 hours."""
    p = path if path is not None else get_settings().usage_path()
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text())
        cutoff = time.time() - 86400
        return [e for e in data.get("events", []) if e.get("ts", 0) >= cutoff]
    except (json.JSONDecodeError, OSError):
        return []


def save_usage(events: list[dict], path: Path | None = None) -> None:
    """Persist usage events after pruning anything older than 24 hours."""
    p = path if path is not None else get_settings().usage_path()
    cutoff = time.time() - 86400
    events = [e for e in events if e.get("ts", 0) >= cutoff]
    ensure_parent(p)
    p.write_text(json.dumps({"events": events}, indent=2))


def record_usage(tokens: int, path: Path | None = None) -> None:
    """Append one successful Groq call to the usage ledger."""
    p = path if path is not None else get_settings().usage_path()
    events = load_usage(p)
    events.append({"ts": time.time(), "tokens": tokens})
    save_usage(events, p)


def fits_groq_limits(
    s: str,
    *,
    usage_path: Path | None = None,
    max_chars: int | None = None,
    rpm: int | None = None,
    rpd: int | None = None,
    tpm: int | None = None,
    tpd: int | None = None,
    now: float | None = None,
) -> tuple[bool, str]:
    """Whether ``s`` may be sent to Groq under char and rate limits."""
    cfg = get_settings()
    max_chars = cfg.groq_max_chars if max_chars is None else max_chars
    rpm = cfg.groq_rpm if rpm is None else rpm
    rpd = cfg.groq_rpd if rpd is None else rpd
    tpm = cfg.groq_tpm if tpm is None else tpm
    tpd = cfg.groq_tpd if tpd is None else tpd
    usage = usage_path if usage_path is not None else cfg.usage_path()

    if len(s) > max_chars:
        return False, f"input {len(s)} chars > {max_chars} max"
    tokens = estimate_tokens(s)
    ts = time.time() if now is None else now
    events = load_usage(usage)
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


def cleanup_speech(path: Path | None = None, delay_s: float | None = None) -> None:
    """Delete ``path`` now (``delay_s <= 0``) or after ``delay_s`` seconds."""
    cfg = get_settings()
    target = path if path is not None else cfg.speech_path()
    wait = cfg.delete_after_s if delay_s is None else delay_s

    def _delete() -> None:
        if wait > 0:
            time.sleep(wait)
        with contextlib.suppress(OSError):
            target.unlink(missing_ok=True)

    if wait <= 0:
        target.unlink(missing_ok=True)
        return
    threading.Thread(target=_delete, daemon=True).start()


def write_wav_mono_i16(path: Path, sample_rate: int, audio: np.ndarray) -> None:
    """Write mono 16-bit PCM WAV (e.g. for ``afplay``)."""
    audio = np.ascontiguousarray(np.asarray(audio).squeeze(), dtype=np.int16)
    if audio.ndim != 1:
        audio = audio.reshape(-1)
    ensure_parent(path)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(audio.tobytes())


def atempo_filter_chain(speed: float) -> str:
    """Build an ffmpeg ``atempo`` chain (each stage must be in ``[0.5, 2.0]``)."""
    if speed <= 0:
        raise ValueError(f"speed must be positive, got {speed}")
    factors: list[float] = []
    remaining = float(speed)
    while remaining > 2.0 + 1e-9:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5 - 1e-9:
        factors.append(0.5)
        remaining /= 0.5
    factors.append(remaining)
    return ",".join(f"atempo={f:.6g}" for f in factors)


def time_stretch_mono(samples: np.ndarray, speed: float, *, frame_length: int = 1024) -> np.ndarray:
    """Pitch-preserving time stretch (WSOLA). ``speed`` > 1 → faster / shorter."""
    x = np.ascontiguousarray(samples, dtype=np.float64).reshape(-1)
    n = int(x.size)
    if n == 0 or abs(speed - 1.0) < 1e-3:
        return x
    if speed <= 0:
        raise ValueError(f"speed must be positive, got {speed}")

    frame = min(frame_length, max(64, n // 2))
    if frame % 2:
        frame += 1
    hop_s = max(1, frame // 2)
    hop_a = max(1, round(hop_s * speed))
    tol = max(0, min(hop_s, frame // 4))
    window = np.hanning(frame)

    out_len = max(frame, round(n / speed) + frame)
    y = np.zeros(out_len + frame, dtype=np.float64)
    wsum = np.zeros_like(y)

    def grab(start: int) -> np.ndarray:
        end = start + frame
        if start < 0:
            return np.zeros(frame, dtype=np.float64)
        if end <= n:
            return x[start:end].copy()
        if start >= n:
            return np.zeros(frame, dtype=np.float64)
        part = x[start:n]
        return np.pad(part, (0, frame - part.size))

    src = 0
    dst = 0
    prev = grab(0)
    y[dst : dst + frame] += prev * window
    wsum[dst : dst + frame] += window
    src = hop_a
    dst = hop_s

    while dst + frame < len(y) and src < n:
        ideal = src
        lo = max(0, ideal - tol)
        hi = min(max(0, n - frame), ideal + tol)
        best = ideal if ideal <= n - frame else max(0, n - frame)
        if hi >= lo and n >= frame:
            ref = prev[hop_s:]
            best_score = -np.inf
            for cand in range(lo, hi + 1):
                seg = x[cand : cand + ref.size]
                if seg.size != ref.size:
                    continue
                score = float(np.dot(seg, ref))
                if score > best_score:
                    best_score = score
                    best = cand
        frame_data = grab(best)
        y[dst : dst + frame] += frame_data * window
        wsum[dst : dst + frame] += window
        prev = frame_data
        src = best + hop_a
        dst += hop_s

    nz = wsum > 1e-8
    y[nz] /= wsum[nz]
    target = max(1, round(n / speed))
    return y[:target]


def _scale_wav_speed_ffmpeg(path: Path, speed: float) -> bool:
    """Pitch-preserving tempo via ffmpeg ``atempo``. Returns True on success."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    filt = atempo_filter_chain(speed)
    tmp_path = Path()
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-filter:a",
                filt,
                str(tmp_path),
            ],
            check=True,
            capture_output=True,
        )
        tmp_path.replace(path)
        return True
    except (OSError, subprocess.CalledProcessError):
        with contextlib.suppress(OSError):
            tmp_path.unlink(missing_ok=True)
        return False
    finally:
        with contextlib.suppress(OSError):
            if tmp_path.is_file():
                tmp_path.unlink(missing_ok=True)


def scale_wav_speed(path: Path, speed: float) -> None:
    """Rewrite ``path`` to play at ``speed`` without changing pitch."""
    if speed <= 0:
        raise ValueError(f"speed must be positive, got {speed}")
    if abs(speed - 1.0) < 1e-3:
        return
    if _scale_wav_speed_ffmpeg(path, speed):
        return

    with wave.open(str(path), "rb") as wf:
        nchannels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)

    if sampwidth != 2:
        new_rate = max(1, round(framerate * speed))
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(nchannels)
            wf.setsampwidth(sampwidth)
            wf.setframerate(new_rate)
            wf.writeframes(raw)
        return

    samples = np.frombuffer(raw, dtype=np.int16)
    if nchannels > 1:
        multi = samples.reshape(-1, nchannels)
        channels = [time_stretch_mono(multi[:, ch], speed) for ch in range(nchannels)]
        length = min(len(ch) for ch in channels)
        out = np.stack([ch[:length] for ch in channels], axis=1)
        out_i16 = np.clip(np.rint(out), -32768, 32767).astype(np.int16)
        pcm = out_i16.reshape(-1).tobytes()
    else:
        mono = time_stretch_mono(samples, speed)
        out_i16 = np.clip(np.rint(mono), -32768, 32767).astype(np.int16)
        pcm = out_i16.tobytes()

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(nchannels)
        wf.setsampwidth(2)
        wf.setframerate(framerate)
        wf.writeframes(pcm)


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


def play_and_cleanup(path: Path | None = None) -> None:
    """Play ``path`` then schedule delayed deletion."""
    target = path if path is not None else get_settings().speech_path()
    play_wav(target)
    cleanup_speech(target)


def lang_code(s: str) -> str:
    """Return ``de``, ``en``, or another langdetect code for long non-EN/DE text.

    Short / low-confidence strings default to ``en`` — ``langdetect`` often
    mislabels words like ``hello`` as Dutch/Finnish/etc.
    """
    text = (s or "").strip()
    if not text:
        return "en"
    # Strong orthographic cue for German
    if re.search(r"[äöüÄÖÜß]", text):
        return "de"
    try:
        from langdetect import detect_langs

        ranked = detect_langs(text)
    except Exception:
        return "en"
    if not ranked:
        return "en"

    en_p = sum(p.prob for p in ranked if str(p.lang).startswith("en"))
    de_p = sum(p.prob for p in ranked if str(p.lang).startswith("de"))

    if de_p >= 0.55 and de_p >= en_p:
        return "de"
    if en_p >= 0.55:
        return "en"

    # Unreliable short input → default English (local/Groq EN path)
    if len(text) < 48:
        return "de" if de_p > en_p + 0.15 else "en"

    top = str(ranked[0].lang).split("-")[0]
    if top.startswith("de"):
        return "de"
    if top.startswith("en"):
        return "en"
    return top


def local_lang(s: str) -> str:
    """Language for local Orpheus: always ``en`` or ``de``."""
    lang = lang_code(s)
    if lang in ("en", "de"):
        return lang
    print(f"Local Orpheus: unsupported lang {lang!r}, using en", file=sys.stderr)
    return "en"


def get_local_engine(lang: str) -> LocalOrpheus:
    """Return a cached :class:`LocalOrpheus` for ``lang`` (one model resident)."""
    global _engine, _engine_lang
    from local_orpheus import LocalOrpheus as _LocalOrpheus

    cfg = get_settings()
    if lang not in ("en", "de"):
        raise ValueError(f"local Orpheus only supports en/de, got {lang}")
    if _engine is not None and _engine_lang == lang:
        return _engine
    _engine = None
    _engine_lang = None
    _engine = _LocalOrpheus(
        lang=lang,
        n_gpu_layers=cfg.n_gpu_layers,
        n_ctx=cfg.n_ctx,
        verbose=False,
    )
    _engine_lang = lang
    return _engine


def speak_local_orpheus(s: str, lang: str) -> None:
    """Synthesize with local Orpheus, play, and schedule WAV cleanup."""
    cfg = get_settings()
    voice = cfg.local_voice_en if lang == "en" else cfg.local_voice_de
    engine = get_local_engine(lang)
    speech = cfg.speech_path()
    print(f"Local Orpheus → lang={lang} voice={voice}")

    speech.unlink(missing_ok=True)
    sample_rate, samples = engine.tts(s, voice_id=voice)
    audio = np.asarray(samples).squeeze()
    if audio.size == 0:
        raise RuntimeError("local Orpheus returned empty audio")
    write_wav_mono_i16(speech, sample_rate, audio)
    scale_wav_speed(speech, cfg.speed)
    try:
        play_and_cleanup(speech)
    except Exception as play_err:
        print(f"Local audio saved but play failed ({play_err}); keeping {cfg.delete_after_s}s")
        cleanup_speech(speech)


def groq_api_key() -> str | None:
    """Return Groq API key from settings, or ``GROQ_API_KEY`` env as override."""
    env_key = os.environ.get("GROQ_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip().strip("'\"")
    key = get_settings().groq_api_key
    return key or None


def groq_speech_speed() -> float:
    """Active pitch-preserving tempo from settings."""
    cfg = get_settings()
    return max(cfg.speed_min, min(cfg.speed_max, float(cfg.speed)))


def speak_engine() -> str:
    """Return the active backend name."""
    return get_settings().engine


def preflight_groq(*, timeout_s: float | None = None) -> tuple[bool, str]:
    """Check API key and that Groq is reachable (cheap ``models.list`` call)."""
    cfg = get_settings()
    api_key = groq_api_key()
    if not api_key:
        return (
            False,
            f"groq_api_key not set (config.json or --groq-api-key; see {CONFIG_DIR / 'config.json'})",
        )
    wait = cfg.preflight_timeout_s if timeout_s is None else timeout_s
    try:
        client = Groq(api_key=api_key, timeout=wait)
        client.models.list()
    except Exception as e:
        return False, f"unreachable: {type(e).__name__}: {e}"
    return True, "ok"


def speak_groq(s: str) -> None:
    """Synthesize via Groq Orpheus API, play, record usage, cleanup."""
    cfg = get_settings()
    api_key = groq_api_key()
    if not api_key:
        raise RuntimeError("groq_api_key not set")

    client = Groq(api_key=api_key, timeout=cfg.api_timeout_s)
    speed = groq_speech_speed()
    speech = cfg.speech_path()
    print(f"Groq → {cfg.groq_voice} @ {speed:g}x")
    response = client.audio.speech.create(
        model=cfg.groq_model,
        voice=cfg.groq_voice,
        response_format="wav",
        input=s,
    )
    ensure_parent(speech)
    speech.write_bytes(response.read())
    scale_wav_speed(speech, speed)
    record_usage(estimate_tokens(s))
    play_and_cleanup(speech)


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
    forced = get_settings().say_voice
    if forced:
        return forced
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
    lang = local_lang(s)
    voice = say_voice_for(lang)
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
        raise RuntimeError(f"engine=groq failed: {msg}") from None
    return False, msg


def _try_local(s: str, lang: str, *, forced: bool, prior: str = "") -> tuple[bool, str]:
    """Attempt local Orpheus. Returns ``(True, "")`` on success, else ``(False, reason)``."""
    if lang not in ("en", "de"):
        msg = f"unsupported lang '{lang}'"
        if forced:
            raise RuntimeError(f"engine=local failed: {msg}")
        return False, msg
    try:
        if prior:
            print(f"Trying local Orpheus ({prior})…")
        speak_local_orpheus(s, lang)
        return True, ""
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        if forced:
            raise RuntimeError(f"engine=local failed: {msg}") from e
        return False, msg


def _try_say(s: str, *, reason: str = "", forced: bool = False) -> tuple[bool, str]:
    """Attempt macOS ``say``. Returns ``(True, "")`` on success."""
    try:
        speak_say(s, reason)
        return True, ""
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        if forced:
            raise RuntimeError(f"engine=say failed: {msg}") from e
        return False, msg


def _speak_chain(s: str, loc: str, order: list[str]) -> None:
    """Try backends in ``order`` (``groq`` | ``local`` | ``say``) until one works."""
    reasons: list[str] = []
    for backend in order:
        if backend == "groq":
            ok, why = _try_groq(s, forced=False)
            if ok:
                return
            reasons.append(f"groq skipped: {why}")
        elif backend == "local":
            prior = "; ".join(reasons)
            ok, why = _try_local(s, loc, forced=False, prior=prior)
            if ok:
                return
            reasons.append(f"local {why}")
        elif backend == "say":
            reason = "; ".join(reasons) if reasons else "primary"
            ok, why = _try_say(s, reason=reason, forced=False)
            if ok:
                return
            reasons.append(f"say {why}")
    raise RuntimeError("; ".join(reasons) if reasons else f"no backend succeeded for lang={loc}")


def speak(s: str) -> None:
    """Speak ``s`` using the active settings engine (language-aware when auto)."""
    engine = speak_engine()
    loc = local_lang(s)

    if engine == "groq":
        ok, why = _try_groq(s, forced=True)
        if not ok:
            raise RuntimeError(f"engine=groq failed: {why}")
        return

    if engine == "local":
        _try_local(s, loc, forced=True)
        return

    if engine == "say":
        _try_say(s, reason="engine=say", forced=True)
        return

    # auto: English prioritizes Groq; German prioritizes native macOS say.
    if loc == "de":
        _speak_chain(s, loc, ["say", "local", "groq"])
    else:
        _speak_chain(s, loc, ["groq", "local", "say"])


def build_parser(defaults: Settings) -> argparse.ArgumentParser:
    """Build CLI parser; defaults come from config / built-ins (shown in --help)."""
    parser = argparse.ArgumentParser(
        prog="speak",
        description=(
            "Text-to-speech: English prefers Groq, German prefers macOS say "
            f"(engine=auto). Defaults: {CONFIG_DIR / 'config.json'}."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("text", nargs="?", default=None, help="Text to speak")
    parser.add_argument("-f", "--file", type=Path, default=None, help="Read text from a UTF-8 file")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"Path to config.json (default search: cwd, {CONFIG_DIR / 'config.json'})",
    )

    parser.add_argument(
        "--engine",
        default=defaults.engine,
        choices=["auto", "groq", "local", "say"],
        help="TTS backend (auto: EN→Groq first, DE→macOS say first)",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=defaults.speed,
        help=f"Pitch-preserving tempo ({defaults.speed_min}-{defaults.speed_max})",
    )
    parser.add_argument(
        "--speed-min",
        type=float,
        default=defaults.speed_min,
        help="Minimum allowed speed",
    )
    parser.add_argument(
        "--speed-max",
        type=float,
        default=defaults.speed_max,
        help="Maximum allowed speed",
    )

    parser.add_argument(
        "--groq-api-key",
        default=None,
        help="Groq API key (default: groq_api_key from config.json; never shown here)",
    )
    parser.add_argument("--groq-model", default=defaults.groq_model, help="Groq TTS model id")
    parser.add_argument(
        "--groq-voice",
        default=defaults.groq_voice,
        help="Groq voice id (troy, hannah, austin, …)",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=defaults.groq_max_chars,
        dest="groq_max_chars",
        help="Groq max input characters",
    )
    parser.add_argument(
        "--rpm", type=int, default=defaults.groq_rpm, dest="groq_rpm", help="Groq RPM limit"
    )
    parser.add_argument(
        "--rpd", type=int, default=defaults.groq_rpd, dest="groq_rpd", help="Groq RPD limit"
    )
    parser.add_argument(
        "--tpm", type=int, default=defaults.groq_tpm, dest="groq_tpm", help="Groq TPM limit"
    )
    parser.add_argument(
        "--tpd", type=int, default=defaults.groq_tpd, dest="groq_tpd", help="Groq TPD limit"
    )
    parser.add_argument(
        "--api-timeout",
        type=float,
        default=defaults.api_timeout_s,
        dest="api_timeout_s",
        help="Groq TTS request timeout (seconds)",
    )
    parser.add_argument(
        "--preflight-timeout",
        type=float,
        default=defaults.preflight_timeout_s,
        dest="preflight_timeout_s",
        help="Groq reachability check timeout (seconds)",
    )

    parser.add_argument(
        "--local-voice-en",
        default=defaults.local_voice_en,
        help="Local Orpheus EN voice tag",
    )
    parser.add_argument(
        "--local-voice-de",
        default=defaults.local_voice_de,
        help="Local Orpheus DE voice tag",
    )
    parser.add_argument(
        "--n-gpu-layers",
        type=int,
        default=defaults.n_gpu_layers,
        help="llama.cpp GPU layers (-1 = all)",
    )
    parser.add_argument(
        "--n-ctx",
        type=int,
        default=defaults.n_ctx,
        help="llama.cpp context length",
    )

    parser.add_argument(
        "--say-voice",
        default=defaults.say_voice or None,
        help="Force macOS say voice name (empty = auto)",
    )
    parser.add_argument(
        "--delete-after",
        type=float,
        default=defaults.delete_after_s,
        dest="delete_after_s",
        help="Seconds before deleting speech.wav after play",
    )
    parser.add_argument(
        "--speech-file",
        default=defaults.speech_file,
        help="Path for temporary WAV output",
    )
    parser.add_argument(
        "--usage-file",
        default=defaults.usage_file,
        help="Path for Groq usage ledger JSON",
    )
    parser.add_argument(
        "--write-config",
        type=Path,
        default=None,
        metavar="PATH",
        help="Write full default config.json to PATH and exit",
    )
    return parser


def settings_from_args(base: Settings, args: argparse.Namespace) -> Settings:
    """Apply parsed CLI namespace onto ``base`` settings."""
    data = asdict(base)
    for name in fields(Settings):
        if hasattr(args, name.name):
            val = getattr(args, name.name)
            if val is not None:
                data[name.name] = val
    # argparse may pass None for optional string flags meant as empty
    if getattr(args, "groq_api_key", None) is not None:
        data["groq_api_key"] = args.groq_api_key or ""
    if getattr(args, "say_voice", None) is not None:
        data["say_voice"] = args.say_voice or ""
    return settings_from_mapping(data).normalize()


def cli(argv: list[str] | None = None) -> int:
    """Parse CLI args and speak. Returns process exit code."""
    argv_list = list(sys.argv[1:] if argv is None else argv)

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", type=Path, default=None)
    pre_args, _ = pre.parse_known_args(argv_list)

    base = load_settings(pre_args.config)
    parser = build_parser(base)
    args = parser.parse_args(argv_list)

    if args.write_config is not None:
        out = args.write_config.expanduser()
        ensure_parent(out)
        out.write_text(json.dumps(default_settings_dict(), indent=2) + "\n", encoding="utf-8")
        print(f"Wrote default config to {out}")
        return 0

    settings = settings_from_args(base, args)
    set_settings(settings)

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

    try:
        speak(payload)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    speech = get_settings().speech_path()
    if speech.exists():
        time.sleep(get_settings().delete_after_s + 0.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
