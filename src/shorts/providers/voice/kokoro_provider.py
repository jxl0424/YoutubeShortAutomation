"""Kokoro voice provider — local, offline neural TTS (no API key).

Runs the Apache-2.0 Kokoro-82M model via ``kokoro-onnx`` (ONNX runtime, no
PyTorch). The model + voice files are downloaded once and referenced by path.

Unlike edge-tts, Kokoro does not emit word-boundary events, so subtitle cues are
estimated by spreading the narration words across the measured audio duration
(weighted by word length). ``kokoro_onnx`` is imported lazily and the synth call
is injectable so tests never load the ~310 MB model.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from trend_intelligence.logging.setup import get_logger

from ...domain.exceptions import VoiceError
from ...domain.interfaces import VoiceProvider
from ...domain.models import VoiceResult
from .subtitles import TimedWord, cues_to_srt, group_words_into_cues

# (text, voice, speed, lang) -> (float samples, sample_rate)
SynthFn = Callable[[str, str, float, str], tuple[Any, int]]


class KokoroVoiceProvider(VoiceProvider):
    name = "kokoro"

    def __init__(
        self,
        *,
        model_path: str,
        voices_path: str,
        synth: SynthFn | None = None,
    ) -> None:
        self._model_path = model_path
        self._voices_path = voices_path
        self._synth = synth
        self._model: Any = None  # lazy-loaded Kokoro instance
        self._logger = get_logger("shorts.voice.kokoro")

    def synthesize(
        self,
        *,
        text: str,
        output_dir: Path,
        voice: str,
        language: str,
        rate: str | None = None,
    ) -> VoiceResult:
        if not text.strip():
            raise VoiceError("cannot synthesize empty text")
        output_dir.mkdir(parents=True, exist_ok=True)

        speed = self._rate_to_speed(rate)
        lang = "en-gb" if voice.startswith(("bf_", "bm_")) else "en-us"
        try:
            samples, sample_rate = self._run_synth(text, voice, speed, lang)
        except Exception as exc:
            raise VoiceError(f"kokoro synthesis failed: {exc}") from exc

        audio_path = self._write_mp3(samples, sample_rate, output_dir)

        duration = len(samples) / sample_rate
        words = self._estimate_word_times(text, duration)
        cues = group_words_into_cues(words)
        subtitle_path = output_dir / "captions.srt"
        subtitle_path.write_text(cues_to_srt(cues), encoding="utf-8")

        return VoiceResult(
            audio_path=audio_path,
            subtitle_path=subtitle_path,
            duration_seconds=duration,
            cues=cues,
        )

    # --- synthesis ------------------------------------------------------- #
    def _run_synth(
        self, text: str, voice: str, speed: float, lang: str
    ) -> tuple[Any, int]:
        if self._synth is not None:
            return self._synth(text, voice, speed, lang)
        return self._load().create(text, voice=voice, speed=speed, lang=lang)

    def _load(self) -> Any:
        if self._model is None:
            if not Path(self._model_path).exists():
                raise VoiceError(
                    f"kokoro model not found at {self._model_path} — download "
                    "kokoro-v1.0.onnx and voices-v1.0.bin into models/kokoro/"
                )
            from kokoro_onnx import Kokoro

            self._model = Kokoro(self._model_path, self._voices_path)
        return self._model

    @staticmethod
    def _write_mp3(samples: Any, sample_rate: int, output_dir: Path) -> Path:
        import imageio_ffmpeg
        import soundfile as sf

        wav_path = output_dir / "_narration.wav"
        sf.write(str(wav_path), samples, sample_rate)
        audio_path = output_dir / "narration.mp3"
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run(
            [ffmpeg, "-y", "-i", str(wav_path), "-b:a", "128k", str(audio_path)],
            check=True,
            capture_output=True,
        )
        wav_path.unlink(missing_ok=True)
        return audio_path

    # --- helpers --------------------------------------------------------- #
    @staticmethod
    def _rate_to_speed(rate: str | None) -> float:
        # Map an edge-tts-style percentage ("+10%") to a Kokoro speed multiplier.
        if not rate:
            return 1.0
        try:
            pct = float(rate.strip().rstrip("%"))
        except ValueError:
            return 1.0
        return max(0.5, min(2.0, 1.0 + pct / 100))

    @staticmethod
    def _estimate_word_times(text: str, duration: float) -> list[TimedWord]:
        words = text.split()
        if not words:
            return []
        weights = [max(1, len(w)) for w in words]
        total = sum(weights)
        timed: list[TimedWord] = []
        start = 0.0
        for word, weight in zip(words, weights, strict=True):
            span = duration * weight / total
            timed.append((start, start + span, word))
            start += span
        return timed
