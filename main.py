from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import wave
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from groq import APIConnectionError, APIStatusError, APITimeoutError, Groq, RateLimitError
from langdetect import detect

from local_orpheus import LocalOrpheus

load_dotenv()

ROOT = Path(__file__).resolve().parent
SPEECH_FILE = ROOT / "speech.wav"
USAGE_FILE = ROOT / ".groq_usage.json"

# --- Local Orpheus (default) ---
# EN OSS voices: tara, leah, jess, leo, dan, mia, zac, zoe  (no Groq "troy")
LOCAL_VOICE_EN = "leo"
LOCAL_VOICE_DE = "leo"  # DE weights + same tag format; male-leaning
N_GPU_LAYERS = -1
N_CTX = 2048

# --- Groq optional fallback ---
ORPHEUS_MODEL = "canopylabs/orpheus-v1-english"
ORPHEUS_VOICE = "troy"
ORPHEUS_MAX_CHARS = 200
ORPHEUS_RPM = 10
ORPHEUS_RPD = 100
ORPHEUS_TPM = 1200
ORPHEUS_TPD = 3600
API_TIMEOUT_S = 30.0
DELETE_AFTER_S = 10.0

text = "Karim Khan, Chefankläger am Internationalen Strafgerichtshof, sieht sich mit schweren Vorwürfen konfrontiert. Nun verliert er sein Amt."
# text = "Hello, I'm speaking English and can help you with your questions."

SAY_PREFERRED = {
    "en": ["Samantha", "Daniel"],
    "de": ["Anna", "Reed (Deutsch (Deutschland))", "Eddy (Deutsch (Deutschland))"],
}
SAY_SKIP = {
    "Albert", "Bad News", "Bahh", "Bells", "Boing", "Bubbles", "Cellos",
    "Wobble", "Fred", "Good News", "Jester", "Junior", "Kathy", "Organ",
    "Superstar", "Ralph", "Trinoids", "Whisper", "Zarvox", "Grandma", "Grandpa",
}

# Only one heavy model resident at a time (saves RAM on M-series)
_engine: LocalOrpheus | None = None
_engine_lang: str | None = None


def estimate_tokens(s: str) -> int:
    return max(1, (len(s) + 3) // 4)


def load_usage() -> list[dict]:
    if not USAGE_FILE.is_file():
        return []
    try:
        data = json.loads(USAGE_FILE.read_text())
        cutoff = time.time() - 86400
        return [e for e in data.get("events", []) if e.get("ts", 0) >= cutoff]
    except (json.JSONDecodeError, OSError):
        return []


def save_usage(events: list[dict]) -> None:
    cutoff = time.time() - 86400
    events = [e for e in events if e.get("ts", 0) >= cutoff]
    USAGE_FILE.write_text(json.dumps({"events": events}, indent=2))


def record_usage(tokens: int) -> None:
    events = load_usage()
    events.append({"ts": time.time(), "tokens": tokens})
    save_usage(events)


def fits_groq_limits(s: str) -> tuple[bool, str]:
    if len(s) > ORPHEUS_MAX_CHARS:
        return False, f"input {len(s)} chars > {ORPHEUS_MAX_CHARS} max"
    tokens = estimate_tokens(s)
    now = time.time()
    events = load_usage()
    last_min = [e for e in events if e["ts"] >= now - 60]
    if len(last_min) >= ORPHEUS_RPM:
        return False, f"RPM {len(last_min)}/{ORPHEUS_RPM}"
    if len(events) >= ORPHEUS_RPD:
        return False, f"RPD {len(events)}/{ORPHEUS_RPD}"
    tpm = sum(e["tokens"] for e in last_min)
    tpd = sum(e["tokens"] for e in events)
    if tpm + tokens > ORPHEUS_TPM:
        return False, f"TPM {tpm}+{tokens} > {ORPHEUS_TPM}"
    if tpd + tokens > ORPHEUS_TPD:
        return False, f"TPD {tpd}+{tokens} > {ORPHEUS_TPD}"
    return True, "ok"


def cleanup_speech(path: Path = SPEECH_FILE, delay_s: float = DELETE_AFTER_S) -> None:
    def _delete() -> None:
        if delay_s > 0:
            time.sleep(delay_s)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    if delay_s <= 0:
        path.unlink(missing_ok=True)
        return
    threading.Thread(target=_delete, daemon=True).start()


def write_wav_mono_i16(path: Path, sample_rate: int, audio: np.ndarray) -> None:
    audio = np.ascontiguousarray(np.asarray(audio).squeeze(), dtype=np.int16)
    if audio.ndim != 1:
        audio = audio.reshape(-1)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(audio.tobytes())


def play_wav(path: Path) -> None:
    path = path.resolve()
    last_err: Exception | None = None
    for _ in range(3):
        try:
            subprocess.run(["afplay", str(path)], check=True)
            return
        except Exception as e:
            last_err = e
            time.sleep(0.3)
    # Fallback player
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
    play_wav(path)
    cleanup_speech(path, DELETE_AFTER_S)


def lang_code(s: str) -> str:
    try:
        code = detect(s)
    except Exception:
        code = "en"
    if code.startswith("de"):
        return "de"
    if code.startswith("en"):
        return "en"
    return code


def get_local_engine(lang: str) -> LocalOrpheus:
    global _engine, _engine_lang
    if lang not in ("en", "de"):
        raise ValueError(f"local Orpheus only supports en/de, got {lang}")
    if _engine is not None and _engine_lang == lang:
        return _engine
    # Drop previous language model to free Metal/RAM
    _engine = None
    _engine_lang = None
    _engine = LocalOrpheus(lang=lang, n_gpu_layers=N_GPU_LAYERS, n_ctx=N_CTX, verbose=False)
    _engine_lang = lang
    return _engine


def speak_local_orpheus(s: str, lang: str) -> None:
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


def speak_groq(s: str) -> None:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")
    client = Groq(api_key=api_key, timeout=API_TIMEOUT_S)
    print(f"Groq fallback → {ORPHEUS_VOICE}")
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
    out = subprocess.check_output(["say", "-v", "?"], text=True)
    voices: list[tuple[str, str]] = []
    for line in out.strip().splitlines():
        m = re.match(r"^(.+?)\s+([a-z]{2}[_-][A-Z]{2})\s+#", line)
        if m:
            voices.append((m.group(1).strip(), m.group(2).replace("-", "_")))
    return voices


def say_voice_for(lang: str) -> str | None:
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
    lang = lang_code(s)
    voice = say_voice_for(lang if lang in ("en", "de") else "en")
    print(f"macOS say fallback ({reason})")
    if voice:
        print(f"voice: {voice}")
        subprocess.run(["say", "-v", voice, s], check=True)
    else:
        subprocess.run(["say", s], check=True)


def speak_groq_or_say(s: str, why_local_failed: str) -> None:
    ok, reason = fits_groq_limits(s)
    if not ok:
        speak_say(s, f"after local fail ({why_local_failed}); groq skipped: {reason}")
        return
    try:
        print(f"Local Orpheus failed ({why_local_failed}); trying Groq…")
        speak_groq(s)
    except RateLimitError as e:
        speak_say(s, f"API rate limit: {e}")
    except APITimeoutError as e:
        speak_say(s, f"API timeout: {e}")
    except APIConnectionError as e:
        speak_say(s, f"API connection: {e}")
    except APIStatusError as e:
        speak_say(s, f"API status {e.status_code}")
    except Exception as e:
        speak_say(s, f"API error: {type(e).__name__}: {e}")


def speak(s: str) -> None:
    lang = lang_code(s)
    if lang not in ("en", "de"):
        speak_groq_or_say(s, f"unsupported lang '{lang}' for local Orpheus")
        return

    try:
        speak_local_orpheus(s, lang)
    except Exception as e:
        speak_groq_or_say(s, f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    speak(text)
    if SPEECH_FILE.exists():
        time.sleep(DELETE_AFTER_S + 0.5)
