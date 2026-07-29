"""Opt-in integration tests (network / models / audio).

Run with::

    SPEAK_RUN_INTEGRATION=1 uv run pytest -m integration
"""

from __future__ import annotations

import os

import pytest

import main

pytestmark = pytest.mark.integration

_RUN = os.environ.get("SPEAK_RUN_INTEGRATION") == "1"


@pytest.mark.skipif(not _RUN, reason="set SPEAK_RUN_INTEGRATION=1")
def test_list_say_voices_on_macos() -> None:
    import sys

    if sys.platform != "darwin":
        pytest.skip("macOS only")
    voices = main.list_say_voices()
    assert isinstance(voices, list)


@pytest.mark.skipif(not _RUN, reason="set SPEAK_RUN_INTEGRATION=1")
def test_preflight_groq_live() -> None:
    if not os.environ.get("GROQ_API_KEY") and not main.get_settings().groq_api_key:
        pytest.skip("GROQ_API_KEY not set")
    ok, reason = main.preflight_groq(timeout_s=10.0)
    assert ok is True, reason
