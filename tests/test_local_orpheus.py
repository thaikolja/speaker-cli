from __future__ import annotations

import pytest

from local_orpheus import CUSTOM_TOKEN_PREFIX, DEFAULT_VOICE, LANG_TO_REPO, LocalOrpheus


def test_lang_repos_only_en_de() -> None:
    assert set(LANG_TO_REPO) == {"en", "de"}


def test_default_voices() -> None:
    assert DEFAULT_VOICE["en"] == "leo"
    assert DEFAULT_VOICE["de"] == "leo"


def test_unsupported_lang_raises() -> None:
    with pytest.raises(ValueError, match="unsupported lang"):
        LocalOrpheus(lang="fr")


def test_token_to_id_parses_custom_token() -> None:
    # Bypass __init__ model download
    obj = object.__new__(LocalOrpheus)
    token = f"{CUSTOM_TOKEN_PREFIX}10>"
    assert obj._token_to_id(token, 0) == 0
    # index % 7 == 1 → subtract 4096
    assert obj._token_to_id(f"{CUSTOM_TOKEN_PREFIX}4110>", 1) == 4110 - 10 - 4096


def test_token_to_id_invalid() -> None:
    obj = object.__new__(LocalOrpheus)
    assert obj._token_to_id("nope", 0) is None
    assert obj._token_to_id(f"{CUSTOM_TOKEN_PREFIX}abc>", 0) is None


def test_convert_to_audio_too_short() -> None:
    obj = object.__new__(LocalOrpheus)
    assert obj._convert_to_audio([1, 2, 3]) is None
