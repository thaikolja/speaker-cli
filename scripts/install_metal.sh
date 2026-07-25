#!/usr/bin/env bash
#
# install_metal.sh — llama-cpp-python with Apple Metal for local Orpheus
#
# Purpose: enable Metal-backed GGUF inference used by local_orpheus.py.
# Run after each fresh `uv sync --extra dev` on macOS (not in the lockfile).
#
# Usage:
#   ./scripts/install_metal.sh
#   make install-metal
#
# Exit: 0 success; 1 not Darwin or install failure.
#

set -euo pipefail

cd "$(dirname "$0")/.."

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "Metal install is for macOS only." >&2
    exit 1
fi

export CMAKE_ARGS="-DGGML_METAL=on"
uv pip install llama-cpp-python --no-cache
uv pip install "onnxruntime>=1.27" "huggingface-hub>=0.20" "numpy>=2.0"
python -c "import llama_cpp; print('OK', llama_cpp.__file__)"
echo "Metal llama-cpp-python installed."
