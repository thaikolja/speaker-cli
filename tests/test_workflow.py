"""Language-aware backend chain, directions, and Groq helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import main


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = main.Settings(
        speech_file=str(tmp_path / "speech.wav"),
        usage_file=str(tmp_path / "usage.json"),
        engine="auto",
    )
    main.set_settings(s)
    monkeypatch.setattr(
        main,
        "load_settings",
        lambda explicit_config=None: main.Settings(
            speech_file=str(tmp_path / "speech.wav"),
            usage_file=str(tmp_path / "usage.json"),
        ),
    )


def test_auto_order_by_language() -> None:
    assert main.auto_order("en") == ["groq", "local", "say"]
    assert main.auto_order("ar") == ["groq", "say"]
    assert main.auto_order("de") == ["local", "say"]
    assert main.auto_order("fr") == ["say"]


def test_sanitize_direction() -> None:
    assert main.sanitize_direction("[Cheerful]") == "cheerful"
    assert main.sanitize_direction("  whisper  ") == "whisper"
    assert main.sanitize_direction("!!!") == ""
    assert main.sanitize_direction("a" * 50) == "a" * 30


def test_groq_model_and_voice_derive_from_lang() -> None:
    main.set_settings(main.Settings(groq_model="", groq_voice=""))
    assert main.groq_model_for("en") == "canopylabs/orpheus-v1-english"
    assert main.groq_model_for("ar") == "canopylabs/orpheus-arabic-saudi"
    assert main.groq_voice_for("en") == "troy"
    assert main.groq_voice_for("ar") == "fahad"


def test_groq_model_override() -> None:
    main.set_settings(main.Settings(groq_model="custom/model", groq_voice="hannah"))
    assert main.groq_model_for("en") == "custom/model"
    assert main.groq_voice_for("ar") == "hannah"


def test_groq_direction_english_only() -> None:
    main.set_settings(main.Settings(groq_direction="cheerful"))
    assert main.groq_direction_for("en") == "cheerful"
    assert main.groq_direction_for("ar") == ""
    assert main.groq_input("hi", "en") == "[cheerful] hi"
    assert main.groq_input("hi", "ar") == "hi"


def test_speak_arabic_auto_prefers_groq(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    main.set_settings(main.Settings(engine="auto", groq_api_key="x"))
    monkeypatch.setattr(main, "lang_code", lambda _s: "ar")
    monkeypatch.setattr(main, "local_lang", lambda _s: "en")
    monkeypatch.setattr(main, "preflight_groq", lambda **_k: (True, "ok"))
    monkeypatch.setattr(main, "fits_groq_limits", lambda _s, **_k: (True, "ok"))
    monkeypatch.setattr(main, "speak_groq", lambda _s, _l: order.append("groq"))
    monkeypatch.setattr(main, "speak_local_orpheus", lambda _s, _l: order.append("local"))
    monkeypatch.setattr(main, "speak_say", lambda _s, _r="": order.append("say"))
    main.speak("مرحبا")
    assert order == ["groq"]


def test_speak_german_skips_groq(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    main.set_settings(main.Settings(engine="auto", groq_api_key="x"))
    monkeypatch.setattr(main, "lang_code", lambda _s: "de")
    monkeypatch.setattr(main, "local_lang", lambda _s: "de")
    monkeypatch.setattr(main, "speak_groq", lambda _s, _l: order.append("groq"))
    monkeypatch.setattr(main, "speak_local_orpheus", lambda _s, _l: order.append("local"))
    monkeypatch.setattr(main, "speak_say", lambda _s, _r="": order.append("say"))
    main.speak("Guten Tag, wie geht es Ihnen heute?")
    assert order == ["local"]
    assert "groq" not in order


def test_try_groq_rejects_unsupported_lang_forced() -> None:
    main.set_settings(main.Settings(engine="groq", groq_api_key="x"))
    with pytest.raises(RuntimeError, match="no Groq model"):
        main._try_groq("Hallo", "de", forced=True)


def test_try_groq_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    from groq import RateLimitError

    main.set_settings(main.Settings(groq_api_key="x"))
    monkeypatch.setattr(main, "preflight_groq", lambda **_k: (True, "ok"))
    monkeypatch.setattr(main, "fits_groq_limits", lambda _s, **_k: (True, "ok"))

    def boom(_s: str, _l: str) -> None:
        raise RateLimitError(message="slow down", response=MagicMock(), body=None)

    monkeypatch.setattr(main, "speak_groq", boom)
    ok, why = main._try_groq("hi", "en", forced=False)
    assert ok is False
    assert "rate limit" in why


def test_speak_groq_writes_wav_and_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    speech = tmp_path / "out.wav"
    usage = tmp_path / "usage.json"
    main.set_settings(
        main.Settings(
            speech_file=str(speech),
            usage_file=str(usage),
            groq_api_key="gsk_test",
            groq_direction="cheerful",
            speed=1.0,
        )
    )

    # Minimal valid-ish WAV header + silence (not full RIFF validation).
    fake_wav = b"RIFF" + b"\x00" * 40

    class Resp:
        def read(self) -> bytes:
            return fake_wav

    class Speech:
        def create(self, **kwargs: object) -> Resp:
            assert kwargs["model"] == "canopylabs/orpheus-v1-english"
            assert kwargs["voice"] == "troy"
            assert kwargs["input"] == "[cheerful] Hello there friend"
            assert kwargs["response_format"] == "wav"
            return Resp()

    class Audio:
        def __init__(self) -> None:
            self.speech = Speech()

    class Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.audio = Audio()

    played: list[Path] = []
    monkeypatch.setattr(main, "Groq", Client)
    monkeypatch.setattr(main, "scale_wav_speed", lambda _p, _s: None)
    monkeypatch.setattr(main, "play_and_cleanup", lambda p=None: played.append(p or speech))

    main.speak_groq("Hello there friend", "en")
    assert speech.is_file()
    assert speech.read_bytes() == fake_wav
    assert played == [speech]
    events = main.load_usage(usage)
    assert len(events) == 1


def test_cli_direction_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def capture(_s: str) -> None:
        seen.append(main.get_settings().groq_direction)

    monkeypatch.setattr(main, "speak", capture)
    assert main.cli(["-d", "whisper", "hi there friend"]) == 0
    assert seen == ["whisper"]


def test_cli_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_s: str) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(main, "speak", boom)
    monkeypatch.setattr(main, "cleanup_speech", lambda *a, **k: None)
    assert main.cli(["hi there friend"]) == 130


def test_load_usage_prunes_old_events(tmp_path: Path) -> None:
    import json
    import time

    usage = tmp_path / "usage.json"
    now = time.time()
    usage.write_text(
        json.dumps(
            {
                "events": [
                    {"ts": now - 90000, "tokens": 1},
                    {"ts": now - 10, "tokens": 2},
                ]
            }
        )
    )
    events = main.load_usage(usage)
    assert len(events) == 1
    assert events[0]["tokens"] == 2


def test_cli_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"engine": "say", "quiet": True}))
    seen: list[str] = []

    def capture(_s: str) -> None:
        seen.append(main.get_settings().engine)

    def load_cfg(explicit: Path | None = None) -> main.Settings:
        path = explicit or cfg
        return main.settings_from_mapping(main.load_config_file(path))

    monkeypatch.setattr(main, "speak", capture)
    monkeypatch.setattr(main, "load_settings", load_cfg)
    assert main.cli(["--config", str(cfg), "hello friend"]) == 0
    assert seen == ["say"]
