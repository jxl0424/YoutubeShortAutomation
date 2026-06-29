"""edge-tts voice provider — credential-free TTS producing MP3 + SRT.

Uses Microsoft Edge's online TTS via the ``edge-tts`` package (no API key). Word
boundary events give us timing for subtitles. ``edge_tts`` is imported lazily so
the module loads even where it isn't installed, and tests inject a fake provider.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from trend_intelligence.logging.setup import get_logger

from ...domain.exceptions import VoiceError
from ...domain.interfaces import VoiceProvider
from ...domain.models import VoiceResult
from .subtitles import TimedWord, cues_to_srt, group_words_into_cues


class EdgeTTSVoiceProvider(VoiceProvider):
    name = "edge_tts"

    def __init__(self) -> None:
        self._logger = get_logger("shorts.voice.edge_tts")

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

        try:
            words, audio = asyncio.run(self._stream(text, voice, rate))
        except Exception as exc:  # network / TTS failure
            raise VoiceError(f"edge-tts synthesis failed: {exc}") from exc

        audio_path = output_dir / "narration.mp3"
        audio_path.write_bytes(audio)

        cues = group_words_into_cues(words)
        subtitle_path = output_dir / "captions.srt"
        subtitle_path.write_text(cues_to_srt(cues), encoding="utf-8")

        duration = words[-1][1] if words else 0.0
        return VoiceResult(
            audio_path=audio_path,
            subtitle_path=subtitle_path,
            duration_seconds=duration,
            cues=cues,
        )

    async def _stream(
        self, text: str, voice: str, rate: str | None
    ) -> tuple[list[TimedWord], bytes]:
        import edge_tts

        # edge-tts defaults to sentence-level boundaries; request word-level so
        # we can build fine-grained subtitle cues.
        kwargs: dict[str, str] = {"voice": voice, "boundary": "WordBoundary"}
        if rate:
            kwargs["rate"] = rate
        communicate = edge_tts.Communicate(text, **kwargs)

        audio = bytearray()
        words: list[TimedWord] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 10_000_000  # 100-ns ticks → seconds
                duration = chunk["duration"] / 10_000_000
                words.append((start, start + duration, chunk["text"]))
        return words, bytes(audio)
