#!/usr/bin/env bash
# Build llama-cpp-python with Apple Metal for local Orpheus on M-series Macs.
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
