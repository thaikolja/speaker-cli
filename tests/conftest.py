"""Shared pytest setup.

``local_orpheus`` imports ``llama_cpp`` at module level, but llama-cpp-python is
only installed via ``scripts/install_metal.sh`` (not a hard package dependency).
Stub it early so unit tests run without the Metal wheel.
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock

# Insert before any test module imports main / local_orpheus.
if "llama_cpp" not in sys.modules:
    _llama_cpp = ModuleType("llama_cpp")
    _llama_cpp.Llama = MagicMock  # type: ignore[attr-defined]
    _llama_cpp.CreateCompletionStreamResponse = Any  # type: ignore[attr-defined]
    sys.modules["llama_cpp"] = _llama_cpp
