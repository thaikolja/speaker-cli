from __future__ import annotations

import json
import time
import wave
from pathlib import Path

import numpy as np
import pytest

import main


def test_estimate_tokens_minimum() -> None:
    assert main.estimate_tokens("") == 1
    assert main.estimate_tokens("a") == 1


def test_estimate_tokens_scales_with_length() -> None:
    assert main.estimate_tokens("abcd") == 1
    assert main.estimate_tokens("abcdefgh") == 2
    assert main.estimate_tokens("x" * 200) == 50


def test_fits_groq_limits_rejects_long_input(tmp_path: Path) -> None:
    usage = tmp_path / "usage.json"
    ok, reason = main.fits_groq_limits("x" * 201, usage_path=usage, max_chars=200)
    assert ok is False
    assert "chars" in reason


def test_fits_groq_limits_ok_empty_usage(tmp_path: Path) -> None:
    usage = tmp_path / "usage.json"
    ok, reason = main.fits_groq_limits("hello world", usage_path=usage)
    assert ok is True
    assert reason == "ok"


def test_fits_groq_limits_rpm(tmp_path: Path) -> None:
    usage = tmp_path / "usage.json"
    now = time.time()
    events = [{"ts": now - 10, "tokens": 1} for _ in range(10)]
    usage.write_text(json.dumps({"events": events}))
    ok, reason = main.fits_groq_limits("hi", usage_path=usage, rpm=10, now=now)
    assert ok is False
    assert "RPM" in reason


def test_fits_groq_limits_tpm(tmp_path: Path) -> None:
    usage = tmp_path / "usage.json"
    now = time.time()
    usage.write_text(json.dumps({"events": [{"ts": now - 5, "tokens": 1190}]}))
    # long string → many tokens; 1190 + tokens > 1200
    ok, reason = main.fits_groq_limits(
        "x" * 80,
        usage_path=usage,
        tpm=1200,
        now=now,
    )
    assert ok is False
    assert "TPM" in reason


def test_record_and_load_usage(tmp_path: Path) -> None:
    usage = tmp_path / "usage.json"
    main.record_usage(42, path=usage)
    events = main.load_usage(usage)
    assert len(events) == 1
    assert events[0]["tokens"] == 42


def test_load_usage_corrupt_file(tmp_path: Path) -> None:
    usage = tmp_path / "usage.json"
    usage.write_text("not-json{")
    assert main.load_usage(usage) == []


def test_lang_code_english() -> None:
    assert main.lang_code("Hello, how are you doing today my friend?") == "en"


def test_lang_code_german() -> None:
    assert main.lang_code("Guten Tag, wie geht es Ihnen heute? Das Wetter ist schön.") == "de"


def test_write_wav_mono_i16(tmp_path: Path) -> None:
    path = tmp_path / "out.wav"
    audio = np.array([0, 1000, -1000, 0], dtype=np.int16)
    main.write_wav_mono_i16(path, 24_000, audio)
    with wave.open(str(path), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 24_000
        assert wf.getnframes() == 4


def test_write_wav_squeezes_2d(tmp_path: Path) -> None:
    path = tmp_path / "out.wav"
    audio = np.zeros((1, 8), dtype=np.int16)
    main.write_wav_mono_i16(path, 16_000, audio)
    with wave.open(str(path), "rb") as wf:
        assert wf.getnframes() == 8


def test_say_voice_for_prefers_samantha() -> None:
    voices = [
        ("Albert", "en_US"),
        ("Samantha", "en_US"),
        ("Anna", "de_DE"),
    ]
    assert main.say_voice_for("en", voices) == "Samantha"
    assert main.say_voice_for("de", voices) == "Anna"


def test_say_voice_for_skips_novelty() -> None:
    voices = [
        ("Albert", "en_US"),
        ("Fred", "en_US"),
        ("Daniel", "en_GB"),
    ]
    assert main.say_voice_for("en", voices) == "Daniel"


def test_say_voice_for_none() -> None:
    assert main.say_voice_for("en", []) is None


def test_cleanup_speech_immediate(tmp_path: Path) -> None:
    path = tmp_path / "speech.wav"
    path.write_bytes(b"x")
    main.cleanup_speech(path, delay_s=0)
    assert not path.exists()


def test_cleanup_speech_delayed(tmp_path: Path) -> None:
    path = tmp_path / "speech.wav"
    path.write_bytes(b"x")
    main.cleanup_speech(path, delay_s=0.2)
    assert path.exists()
    time.sleep(0.5)
    assert not path.exists()


def test_cli_empty_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_text("   \n")
    monkeypatch.setattr(main, "speak", lambda _s: None)
    assert main.cli(["-f", str(empty)]) == 2


def test_cli_text_arg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[str] = []
    monkeypatch.setattr(main, "speak", lambda s: seen.append(s))
    monkeypatch.setattr(main, "SPEECH_FILE", tmp_path / "missing.wav")
    assert main.cli(["Hello there"]) == 0
    assert seen == ["Hello there"]
