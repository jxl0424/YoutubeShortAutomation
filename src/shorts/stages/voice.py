"""Voice generation stage.

Synthesizes the script narration into an MP3 plus an SRT subtitle file via the
configured :class:`VoiceProvider`, storing the result on the context.
"""

from __future__ import annotations

from trend_intelligence.logging.setup import get_logger, log_duration

from ..domain.exceptions import VoiceError
from ..domain.interfaces import PipelineStage, VoiceProvider


class VoiceGenerator(PipelineStage):
    name = "voice_generation"

    def __init__(self, provider: VoiceProvider) -> None:
        self._provider = provider
        self._logger = get_logger("shorts.voice")

    def run(self, ctx) -> None:
        if ctx.script is None:
            raise VoiceError("voice generation requires a generated script")

        voice_cfg = ctx.config.voice
        with log_duration(
            self._logger, "voice_generation", provider=self._provider.name
        ):
            result = self._provider.synthesize(
                text=ctx.script.narration,
                output_dir=ctx.work_dir,
                voice=voice_cfg.voice,
                language=voice_cfg.language,
                rate=voice_cfg.rate,
            )

        ctx.voice = result
        self._logger.info(
            "voice_generated",
            duration_seconds=round(result.duration_seconds, 2),
            cues=len(result.cues),
        )
