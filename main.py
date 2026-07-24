from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from dotenv import load_dotenv
from groq import APIConnectionError, APIStatusError, APITimeoutError, Groq, RateLimitError
from langdetect import detect

load_dotenv()

ROOT = Path(__file__).resolve().parent
SPEECH_FILE = ROOT / "speech.wav"
USAGE_FILE = ROOT / ".groq_usage.json"

# Free-plan limits for canopylabs/orpheus-v1-english
# https://console.groq.com/docs/rate-limits
# https://console.groq.com/docs/text-to-speech/orpheus
ORPHEUS_MODEL = "canopylabs/orpheus-v1-english"
ORPHEUS_VOICE = "troy"
ORPHEUS_MAX_CHARS = 200
ORPHEUS_RPM = 10
ORPHEUS_RPD = 100
ORPHEUS_TPM = 1200
ORPHEUS_TPD = 3600
API_TIMEOUT_S = 30.0
DELETE_AFTER_S = 10.0

text = "Er soll eine Mitarbeiterin intim berührt und ihr seine Zunge ins Ohr gesteckt haben: Karim Khan, Chefankläger am Internationalen Strafgerichtshof, sieht sich mit schweren Vorwürfen konfrontiert. Nun verliert er sein Amt."
# text = "Hello, I'm speaking English and can help you with your questions."

PREFERRED: dict[str, list[str]] = {
    "en": ["Samantha", "Daniel", "Karen", "Moira"],
    "de": [
        "Yannick",
        "Markus",
        "Petra",
        "Anna",
        "Reed (Deutsch (Deutschland))",
        "Eddy (Deutsch (Deutschland))",
    ],
    "fr": ["Thomas", "Amélie", "Audrey"],
    "es": ["Jorge", "Juan", "Monica"],
    "it": ["Luca", "Alice"],
    "ja": ["Otoya", "Kyoko"],
    "zh": ["Tingting"],
    "nl": ["Xander", "Ellen"],
    "pt": ["Felipe", "Luciana"],
    "ru": ["Yuri", "Milena"],
}

SKIP = {
    "Albert", "Bad News", "Bahh", "Bells", "Boing", "Bubbles", "Cellos",
    "Wobble", "Fred", "Good News", "Jester", "Junior", "Kathy", "Organ",
    "Superstar", "Ralph", "Trinoids", "Whisper", "Zarvox",
    "Grandma", "Grandpa",
}


def estimate_tokens(s: str) -> int:
    return max(1, (len(s) + 3) // 4)


def load_usage() -> list[dict]:
    if not USAGE_FILE.is_file():
        return []
    try:
        data = json.loads(USAGE_FILE.read_text())
        events = data.get("events", [])
        cutoff = time.time() - 86400
        return [e for e in events if e.get("ts", 0) >= cutoff]
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


def fits_limits(s: str) -> tuple[bool, str]:
    if len(s) > ORPHEUS_MAX_CHARS:
        return False, f"input {len(s)} chars > {ORPHEUS_MAX_CHARS} max"

    tokens = estimate_tokens(s)
    now = time.time()
    events = load_usage()
    last_min = [e for e in events if e["ts"] >= now - 60]
    last_day = events

    rpm = len(last_min)
    rpd = len(last_day)
    tpm = sum(e["tokens"] for e in last_min)
    tpd = sum(e["tokens"] for e in last_day)

    if rpm >= ORPHEUS_RPM:
        return False, f"RPM {rpm}/{ORPHEUS_RPM}"
    if rpd >= ORPHEUS_RPD:
        return False, f"RPD {rpd}/{ORPHEUS_RPD}"
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

    # Non-blocking cleanup so speak() can return; for CLI we block briefly after play
    import threading

    threading.Thread(target=_delete, daemon=True).start()


def speak_groq(s: str) -> None:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    client = Groq(api_key=api_key, timeout=API_TIMEOUT_S)
    print(f"Groq {ORPHEUS_VOICE} → {ORPHEUS_MODEL}")
    response = client.audio.speech.create(
        model=ORPHEUS_MODEL,
        voice=ORPHEUS_VOICE,
        response_format="wav",
        input=s,
    )
    content = response.read()
    SPEECH_FILE.write_bytes(content)
    record_usage(estimate_tokens(s))
    subprocess.run(["afplay", str(SPEECH_FILE)], check=True)
    cleanup_speech(SPEECH_FILE, DELETE_AFTER_S)


def list_say_voices() -> list[tuple[str, str]]:
    out = subprocess.check_output(["say", "-v", "?"], text=True)
    voices: list[tuple[str, str]] = []
    for line in out.strip().splitlines():
        m = re.match(r"^(.+?)\s+([a-z]{2}[_-][A-Z]{2})\s+#", line)
        if m:
            voices.append((m.group(1).strip(), m.group(2).replace("-", "_")))
    return voices


def voice_for(lang: str, voices: list[tuple[str, str]]) -> str | None:
    installed = {name: code for name, code in voices}
    for name in PREFERRED.get(lang, []):
        if name in installed:
            return name
    for name, code in voices:
        base = name.split(" (")[0]
        if code.startswith(lang) and base not in SKIP and name not in SKIP:
            if any(s in name for s in ("Grandma", "Grandpa", "Superstar")):
                continue
            return name
    return None


def speak_local(s: str, reason: str) -> None:
    voices = list_say_voices()
    lang = detect(s)
    voice = voice_for(lang, voices)
    print(f"Local fallback ({reason})")
    if voice:
        print(f"Detected language: {lang} → voice: {voice}")
        subprocess.run(["say", "-v", voice, s], check=True)
    else:
        print(f"Detected language: {lang} → system default")
        subprocess.run(["say", s], check=True)


def speak(s: str) -> None:
    ok, reason = fits_limits(s)
    if not ok:
        speak_local(s, reason)
        return

    try:
        speak_groq(s)
    except RateLimitError as e:
        speak_local(s, f"API rate limit: {e}")
    except APITimeoutError as e:
        speak_local(s, f"API timeout: {e}")
    except APIConnectionError as e:
        speak_local(s, f"API connection: {e}")
    except APIStatusError as e:
        speak_local(s, f"API status {e.status_code}: {e}")
    except Exception as e:
        speak_local(s, f"API error: {type(e).__name__}: {e}")


if __name__ == "__main__":
    speak(text)
    # Keep process alive briefly so delayed file delete can run
    if SPEECH_FILE.exists():
        time.sleep(DELETE_AFTER_S + 0.5)
