from __future__ import annotations

import json
import time
import wave
from pathlib import Path

import numpy as np
import pytest

import main


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test gets a clean Settings pointing at tmp paths."""
    s = main.Settings(
        speech_file=str(tmp_path / "speech.wav"),
        usage_file=str(tmp_path / "usage.json"),
        groq_api_key="",
        engine="auto",
        speed=1.0,
    )
    main.set_settings(s)
    # Avoid picking up the developer's real config.json during CLI tests.
    monkeypatch.setattr(
        main,
        "load_settings",
        lambda explicit_config=None: main.Settings(
            speech_file=str(tmp_path / "speech.wav"),
            usage_file=str(tmp_path / "usage.json"),
        ),
    )


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


def test_lang_code_short_hello_is_english() -> None:
    # langdetect alone often returns nl/fi for "hello"
    assert main.lang_code("hello") == "en"
    assert main.lang_code("Hello") == "en"
    assert main.local_lang("hello") == "en"


def test_lang_code_umlaut_is_german() -> None:
    assert main.lang_code("Schön") == "de"


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


def test_say_voice_forced_from_settings() -> None:
    s = main.get_settings()
    s.say_voice = "Zarvox"
    main.set_settings(s)
    assert main.say_voice_for("en", [("Samantha", "en_US")]) == "Zarvox"


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


def test_cli_no_args() -> None:
    assert main.cli([]) == 2


def test_cli_text_arg(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(main, "speak", lambda s: seen.append(s))
    assert main.cli(["Hello there"]) == 0
    assert seen == ["Hello there"]


def test_cli_help_lists_flags() -> None:
    with pytest.raises(SystemExit) as ei:
        main.cli(["--help"])
    assert ei.value.code == 0


def test_cli_write_config(tmp_path: Path) -> None:
    out = tmp_path / "cfg.json"
    assert main.cli(["--write-config", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["engine"] == "auto"
    assert data["groq_voice"] == "troy"
    assert "speed" in data


def test_cli_engine_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def capture(_s: str) -> None:
        seen.append(main.get_settings().engine)

    monkeypatch.setattr(main, "speak", capture)
    assert main.cli(["--engine", "say", "hi there friend"]) == 0
    assert seen == ["say"]


def test_settings_from_config_file(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"engine": "local", "speed": 1.5, "groq_api_key": "gsk_x"}))
    s = main.settings_from_mapping(main.load_config_file(cfg))
    assert s.engine == "local"
    assert s.speed == 1.5
    assert s.groq_api_key == "gsk_x"


def test_load_settings_reads_explicit_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "my.json"
    cfg.write_text(json.dumps({"engine": "groq", "groq_voice": "hannah"}))
    # Bypass autouse stub: call implementation with only this candidate.
    monkeypatch.setattr(main, "config_paths", lambda explicit=None: [cfg])
    s = main.Settings()
    for path in main.config_paths():
        if path.is_file():
            s = main.settings_from_mapping(main.load_config_file(path), s)
            break
    assert s.engine == "groq"
    assert s.groq_voice == "hannah"


def test_preflight_groq_missing_key() -> None:
    main.set_settings(main.Settings(groq_api_key=""))
    ok, reason = main.preflight_groq()
    assert ok is False
    assert "groq_api_key" in reason


def test_groq_api_key_from_settings() -> None:
    main.set_settings(main.Settings(groq_api_key="  gsk_from_cfg  "))
    assert main.groq_api_key() == "gsk_from_cfg"


def test_groq_api_key_env_overrides_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    main.set_settings(main.Settings(groq_api_key="gsk_cfg"))
    monkeypatch.setenv("GROQ_API_KEY", "gsk_env")
    assert main.groq_api_key() == "gsk_env"


def test_groq_speech_speed_clamped() -> None:
    main.set_settings(main.Settings(speed=9.0, speed_min=0.5, speed_max=3.0))
    assert main.groq_speech_speed() == 3.0
    main.set_settings(main.Settings(speed=0.1, speed_min=0.5, speed_max=3.0))
    assert main.groq_speech_speed() == 0.5


def test_scale_wav_speed_shortens_keeps_rate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "_scale_wav_speed_ffmpeg", lambda _p, _s: False)
    path = tmp_path / "t.wav"
    audio = (np.sin(np.linspace(0, 40 * np.pi, 24_000)) * 10000).astype(np.int16)
    main.write_wav_mono_i16(path, 24_000, audio)
    main.scale_wav_speed(path, 2.0)
    with wave.open(str(path), "rb") as wf:
        assert wf.getframerate() == 24_000
        assert 8_000 <= wf.getnframes() <= 16_000


def test_scale_wav_speed_noop_at_one(tmp_path: Path) -> None:
    path = tmp_path / "t.wav"
    main.write_wav_mono_i16(path, 16_000, np.zeros(100, dtype=np.int16))
    main.scale_wav_speed(path, 1.0)
    with wave.open(str(path), "rb") as wf:
        assert wf.getframerate() == 16_000
        assert wf.getnframes() == 100


def test_atempo_filter_chain_splits_above_two() -> None:
    assert main.atempo_filter_chain(3.0) == "atempo=2,atempo=1.5"


def test_time_stretch_mono_faster_is_shorter() -> None:
    x = np.sin(np.linspace(0, 20 * np.pi, 8000))
    y = main.time_stretch_mono(x, 2.0)
    assert len(y) < len(x) * 0.7
    assert len(y) > len(x) * 0.3


def test_preflight_groq_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    main.set_settings(main.Settings(groq_api_key="gsk_test"))

    class Boom:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        @property
        def models(self) -> object:
            raise ConnectionError("offline")

    monkeypatch.setattr(main, "Groq", Boom)
    ok, reason = main.preflight_groq(timeout_s=0.1)
    assert ok is False
    assert "unreachable" in reason


def test_preflight_groq_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    main.set_settings(main.Settings(groq_api_key="gsk_test"))

    class Models:
        def list(self) -> list[str]:
            return ["ok"]

    class Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.models = Models()

    monkeypatch.setattr(main, "Groq", Client)
    ok, reason = main.preflight_groq()
    assert ok is True
    assert reason == "ok"


def test_normalize_engine_aliases() -> None:
    assert main.normalize_engine("macos") == "say"
    assert main.normalize_engine("cloud") == "groq"
    assert main.normalize_engine("orpheus") == "local"


def test_speak_english_auto_prefers_groq(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    main.set_settings(main.Settings(engine="auto", groq_api_key="x"))
    monkeypatch.setattr(main, "local_lang", lambda _s: "en")
    monkeypatch.setattr(main, "preflight_groq", lambda **_k: (True, "ok"))
    monkeypatch.setattr(main, "fits_groq_limits", lambda _s, **_k: (True, "ok"))
    monkeypatch.setattr(main, "speak_groq", lambda _s: order.append("groq"))
    monkeypatch.setattr(main, "speak_local_orpheus", lambda _s, _l: order.append("local"))
    monkeypatch.setattr(main, "speak_say", lambda _s, _r="": order.append("say"))
    main.speak("Hello friend, how are you today?")
    assert order == ["groq"]


def test_speak_german_auto_prefers_local(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    langs: list[str] = []
    main.set_settings(main.Settings(engine="auto", groq_api_key="x"))
    monkeypatch.setattr(main, "local_lang", lambda _s: "de")
    monkeypatch.setattr(main, "speak_groq", lambda _s: order.append("groq"))

    def local(_s: str, lang: str) -> None:
        langs.append(lang)
        order.append("local")

    monkeypatch.setattr(main, "speak_local_orpheus", local)
    monkeypatch.setattr(main, "speak_say", lambda _s, _r="": order.append("say"))
    main.speak("Guten Tag, wie geht es Ihnen heute?")
    assert order == ["local"]
    assert langs == ["de"]


def test_speak_local_when_preflight_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    main.set_settings(main.Settings(engine="auto"))
    monkeypatch.setattr(main, "local_lang", lambda _s: "en")
    monkeypatch.setattr(main, "preflight_groq", lambda **_k: (False, "no key"))
    monkeypatch.setattr(main, "speak_groq", lambda _s: order.append("groq"))
    monkeypatch.setattr(main, "speak_local_orpheus", lambda _s, _l: order.append("local"))
    monkeypatch.setattr(main, "speak_say", lambda _s, _r="": order.append("say"))
    main.speak("Hello friend, how are you today?")
    assert order == ["local"]


def test_speak_local_then_say_when_groq_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    main.set_settings(main.Settings(engine="auto", groq_api_key="x"))
    monkeypatch.setattr(main, "local_lang", lambda _s: "en")
    monkeypatch.setattr(main, "preflight_groq", lambda **_k: (True, "ok"))
    monkeypatch.setattr(main, "fits_groq_limits", lambda _s, **_k: (True, "ok"))

    def boom(_s: str) -> None:
        order.append("groq")
        raise RuntimeError("api down")

    def local_fail(_s: str, _l: str) -> None:
        order.append("local")
        raise RuntimeError("no metal")

    monkeypatch.setattr(main, "speak_groq", boom)
    monkeypatch.setattr(main, "speak_local_orpheus", local_fail)
    monkeypatch.setattr(main, "speak_say", lambda _s, _r="": order.append("say"))
    main.speak("Hello friend, how are you today?")
    assert order == ["groq", "local", "say"]


def test_speak_maps_unsupported_lang_to_en_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    langs: list[str] = []
    main.set_settings(main.Settings(engine="auto"))
    monkeypatch.setattr(main, "local_lang", lambda _s: "en")  # fr mapped to en upstream
    monkeypatch.setattr(main, "preflight_groq", lambda **_k: (False, "no key"))

    def local(_s: str, lang: str) -> None:
        langs.append(lang)
        order.append("local")

    monkeypatch.setattr(main, "speak_local_orpheus", local)
    monkeypatch.setattr(main, "speak_say", lambda _s, _r="": order.append("say"))
    main.speak("Bonjour tout le monde aujourd'hui")
    assert order == ["local"]
    assert langs == ["en"]


def test_speak_engine_forced_say(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    main.set_settings(main.Settings(engine="say"))
    monkeypatch.setattr(main, "speak_groq", lambda _s: order.append("groq"))
    monkeypatch.setattr(main, "speak_local_orpheus", lambda _s, _l: order.append("local"))
    monkeypatch.setattr(main, "speak_say", lambda _s, _r="": order.append("say"))
    main.speak("Hello friend, how are you today?")
    assert order == ["say"]


def test_speak_engine_forced_local(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    main.set_settings(main.Settings(engine="local"))
    monkeypatch.setattr(main, "lang_code", lambda _s: "en")
    monkeypatch.setattr(main, "speak_groq", lambda _s: order.append("groq"))
    monkeypatch.setattr(main, "speak_local_orpheus", lambda _s, _l: order.append("local"))
    monkeypatch.setattr(main, "speak_say", lambda _s, _r="": order.append("say"))
    main.speak("Hello friend, how are you today?")
    assert order == ["local"]


def test_speak_engine_forced_groq_no_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    main.set_settings(main.Settings(engine="groq"))
    monkeypatch.setattr(main, "preflight_groq", lambda **_k: (False, "no key"))
    monkeypatch.setattr(main, "speak_local_orpheus", lambda _s, _l: order.append("local"))
    monkeypatch.setattr(main, "speak_say", lambda _s, _r="": order.append("say"))
    with pytest.raises(RuntimeError, match="engine=groq"):
        main.speak("Hello friend, how are you today?")
    assert order == []
