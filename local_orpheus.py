"""Local Orpheus TTS via llama.cpp (Metal) and SNAC audio decode.

Loads quantized Orpheus GGUF weights from Hugging Face, generates tokens with
llama-cpp-python, and decodes SNAC codebook tokens to 24 kHz mono PCM.

Supported languages: ``en``, ``de``.

Example::

    engine = LocalOrpheus(lang="en")
    sample_rate, samples = engine.tts("Hello world", voice_id="leo")
"""

from __future__ import annotations

import os
import platform
from collections.abc import Generator, Iterator
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import onnxruntime
from huggingface_hub import hf_hub_download
from numpy.typing import NDArray

if TYPE_CHECKING:
    from llama_cpp import CreateCompletionStreamResponse

# Suppress verbose ONNX Runtime / CoreML provider scan logs.
# Set SPEAKER_ORT_VERBOSE=1 to see them again for debugging.
if not os.environ.get("SPEAKER_ORT_VERBOSE"):
    onnxruntime.set_default_logger_severity(3)

# Default SNAC decode to CPU to avoid macOS CoreAnalytics "Context leak" spam.
# Set SPEAKER_USE_COREML=1 to try the CoreML execution provider anyway.
_USE_COREML = os.environ.get("SPEAKER_USE_COREML") == "1"

LANG_TO_REPO = {
    "en": "isaiahbjork/orpheus-3b-0.1-ft-Q4_K_M-GGUF",
    "de": "freddyaboulton/3b-de-ft-research_release-Q4_K_M-GGUF",
}

# EN tags: tara, leah, jess, leo, dan, mia, zac, zoe. DE uses the same format.
DEFAULT_VOICE = {"en": "leo", "de": "leo"}

CUSTOM_TOKEN_PREFIX = "<custom_token_"


def _import_llama() -> Any:
    """Import ``Llama`` only when local inference is used (optional Metal wheel)."""
    try:
        from llama_cpp import Llama
    except ImportError as e:
        raise RuntimeError(
            "llama-cpp-python is required for local Orpheus. "
            "On macOS Apple Silicon run ./scripts/install_metal.sh "
            "(or install Metal llama-cpp-python into this environment). "
            "Without it, use GROQ_API_KEY or macOS say."
        ) from e
    return Llama


class LocalOrpheus:
    """Run Orpheus TTS locally with llama.cpp and an ONNX SNAC decoder.

    Parameters
    ----------
    lang :
        ``en`` or ``de`` (keys of :data:`LANG_TO_REPO`).
    n_gpu_layers :
        Layers to offload; ``-1`` = all. On Apple Silicon, ``0`` becomes ``-1``.
    n_ctx :
        Context length in tokens.
    verbose :
        Forwarded to :class:`llama_cpp.Llama`.

    Raises
    ------
    ValueError
        If ``lang`` is not supported.
    """

    def __init__(
        self,
        lang: str = "en",
        n_gpu_layers: int = -1,
        n_ctx: int = 2048,
        verbose: bool = False,
    ) -> None:
        if lang not in LANG_TO_REPO:
            raise ValueError(f"unsupported lang {lang!r}; want en|de")
        self.lang = lang
        self.voice_default = DEFAULT_VOICE[lang]

        repo_id = LANG_TO_REPO[lang]
        filename = repo_id.split("/")[-1].lower().replace("-gguf", ".gguf")
        print(f"Loading local Orpheus ({lang}) from {repo_id} …")
        model_path = hf_hub_download(repo_id=repo_id, filename=filename)

        if platform.system() == "Darwin" and platform.machine() == "arm64" and n_gpu_layers == 0:
            n_gpu_layers = -1

        llama_cls = _import_llama()
        self._llm = llama_cls(
            model_path=model_path,
            n_ctx=n_ctx,
            verbose=verbose,
            n_gpu_layers=n_gpu_layers,
            n_threads=0,
            n_batch=512,
        )

        snac_path = hf_hub_download(
            "onnx-community/snac_24khz-ONNX",
            subfolder="onnx",
            filename="decoder_model.onnx",
        )
        if _USE_COREML:
            providers = [
                p
                for p in ("CoreMLExecutionProvider", "CPUExecutionProvider")
                if p in onnxruntime.get_available_providers()
            ]
        else:
            providers = ["CPUExecutionProvider"]
        if not providers:
            providers = ["CPUExecutionProvider"]
        self._snac = onnxruntime.InferenceSession(snac_path, providers=providers)

    def _token_to_id(self, token_text: str, index: int) -> int | None:
        """Parse a stream fragment into a raw SNAC codebook index, or ``None``.

        The returned integer is the de-offset codebook value and may be
        non-positive; callers must filter (see :meth:`_decode`).
        """
        token_string = token_text.strip()
        last = token_string.rfind(CUSTOM_TOKEN_PREFIX)
        if last == -1:
            return None
        last_token = token_string[last:]
        if last_token.startswith(CUSTOM_TOKEN_PREFIX) and last_token.endswith(">"):
            try:
                number_str = last_token[len(CUSTOM_TOKEN_PREFIX) : -1]
                return int(number_str) - 10 - ((index % 7) * 4096)
            except ValueError:
                return None
        return None

    def _convert_to_audio(self, multiframe: list[int]) -> bytes | None:
        """Decode SNAC codes to raw int16 PCM bytes, or ``None`` if invalid."""
        if len(multiframe) < 28:
            return None
        num_frames = len(multiframe) // 7
        frame = multiframe[: num_frames * 7]
        codes_0: list[int] = []
        codes_1: list[int] = []
        codes_2: list[int] = []
        for j in range(num_frames):
            i = 7 * j
            codes_0.append(frame[i])
            codes_1.extend([frame[i + 1], frame[i + 4]])
            codes_2.extend([frame[i + 2], frame[i + 3], frame[i + 5], frame[i + 6]])

        c0 = np.expand_dims(np.array(codes_0, dtype=np.int64), 0)
        c1 = np.expand_dims(np.array(codes_1, dtype=np.int64), 0)
        c2 = np.expand_dims(np.array(codes_2, dtype=np.int64), 0)
        if (
            np.any(c0 < 0)
            or np.any(c0 > 4096)
            or np.any(c1 < 0)
            or np.any(c1 > 4096)
            or np.any(c2 < 0)
            or np.any(c2 > 4096)
        ):
            return None

        names = [x.name for x in self._snac.get_inputs()]
        audio_hat = self._snac.run(None, dict(zip(names, [c0, c1, c2], strict=True)))[0]
        audio_np = audio_hat[:, :, 2048:4096]
        out = (audio_np * 32767).astype(np.int16).tobytes()
        return bytes(out)

    def _decode(self, token_gen: Generator[str, None, None]) -> Generator[bytes, None, None]:
        """Yield PCM chunks from streamed LLM text tokens."""
        buffer: list[int] = []
        count = 0
        for token_text in token_gen:
            token = self._token_to_id(token_text, count)
            if token is not None and token > 0:
                buffer.append(token)
                count += 1
                if count % 7 == 0 and count > 27:
                    audio = self._convert_to_audio(buffer[-28:])
                    if audio is not None:
                        yield audio

    def _token_gen(
        self, text: str, voice_id: str, max_tokens: int = 2048
    ) -> Generator[str, None, None]:
        """Stream llama.cpp completion fragments for an Orpheus TTS prompt."""
        prompt = f"<|audio|>{voice_id}: {text}<|eot_id|><custom_token_4>"
        stream = self._llm(
            prompt,
            max_tokens=max_tokens,
            stream=True,
            temperature=0.8,
            top_p=0.95,
            top_k=40,
            min_p=0.05,
            repeat_penalty=1.1,
        )
        for token in cast(Iterator[CreateCompletionStreamResponse], stream):
            yield token["choices"][0]["text"]

    def tts(self, text: str, voice_id: str | None = None) -> tuple[int, NDArray[np.int16]]:
        """Synthesize ``text`` to mono int16 PCM at 24 kHz.

        Parameters
        ----------
        text :
            Text to speak.
        voice_id :
            Speaker tag; defaults to :attr:`voice_default`.

        Returns
        -------
        sample_rate :
            Always ``24000``.
        samples :
            Mono int16 waveform (empty if nothing was decoded).
        """
        voice = voice_id or self.voice_default
        chunks: list[np.ndarray] = []
        for audio_bytes in self._decode(self._token_gen(text, voice)):
            chunks.append(np.frombuffer(audio_bytes, dtype=np.int16))
        if not chunks:
            return 24_000, np.zeros(0, dtype=np.int16)
        return 24_000, np.concatenate(chunks)
