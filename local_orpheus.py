"""Local Orpheus TTS via llama.cpp (Metal) + SNAC decoder."""

from __future__ import annotations

import platform
from collections.abc import Generator, Iterator
from typing import cast

import numpy as np
import onnxruntime
from huggingface_hub import hf_hub_download
from llama_cpp import CreateCompletionStreamResponse, Llama
from numpy.typing import NDArray

LANG_TO_REPO = {
    "en": "isaiahbjork/orpheus-3b-0.1-ft-Q4_K_M-GGUF",
    "de": "freddyaboulton/3b-de-ft-research_release-Q4_K_M-GGUF",
}

# Public finetune voice tags (EN). DE research model accepts the same prompt format;
# "leo"/"dan" still produce usable DE speech on the DE weights.
DEFAULT_VOICE = {"en": "leo", "de": "leo"}

CUSTOM_TOKEN_PREFIX = "<custom_token_"


class LocalOrpheus:
    def __init__(
        self, lang: str = "en", n_gpu_layers: int = -1, n_ctx: int = 2048, verbose: bool = False
    ):
        if lang not in LANG_TO_REPO:
            raise ValueError(f"unsupported lang {lang!r}; want en|de")
        self.lang = lang
        self.voice_default = DEFAULT_VOICE[lang]

        repo_id = LANG_TO_REPO[lang]
        filename = repo_id.split("/")[-1].lower().replace("-gguf", ".gguf")
        print(f"Loading local Orpheus ({lang}) from {repo_id} …")
        model_path = hf_hub_download(repo_id=repo_id, filename=filename)

        # Apple Silicon: full Metal offload
        if platform.system() == "Darwin" and platform.machine() == "arm64" and n_gpu_layers == 0:
            n_gpu_layers = -1

        self._llm = Llama(
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
        providers = [
            p
            for p in ("CoreMLExecutionProvider", "CPUExecutionProvider")
            if p in onnxruntime.get_available_providers()
        ]
        if not providers:
            providers = ["CPUExecutionProvider"]
        self._snac = onnxruntime.InferenceSession(snac_path, providers=providers)

    def _token_to_id(self, token_text: str, index: int) -> int | None:
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
        voice = voice_id or self.voice_default
        chunks: list[np.ndarray] = []
        for audio_bytes in self._decode(self._token_gen(text, voice)):
            chunks.append(np.frombuffer(audio_bytes, dtype=np.int16))
        if not chunks:
            return 24_000, np.zeros(0, dtype=np.int16)
        return 24_000, np.concatenate(chunks)
