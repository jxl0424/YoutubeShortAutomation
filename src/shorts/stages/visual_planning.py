"""Visual planning stage.

Turns the script (and the synthesized voice timing) into a structured
``ScenePlan``: one timed :class:`Scene` per script scene, with a visual type and
a concrete ``visual_query`` the asset stage can act on. Scene durations are
distributed across the narration so the visuals span the audio timeline (the
audio remains the master track at assembly time).
"""

from __future__ import annotations

from trend_intelligence.logging.setup import get_logger, log_duration

from ..config.settings import VisualPlanningConfig
from ..domain.exceptions import VisualPlanningError
from ..domain.interfaces import PipelineStage
from ..domain.models import Scene, ScenePlan

# (narration, on_screen_text, visual_instruction)
_SceneSource = tuple[str, str | None, str | None]


class VisualPlanner(PipelineStage):
    name = "visual_planning"

    def __init__(self) -> None:
        self._logger = get_logger("shorts.visual_planning")

    def run(self, ctx) -> None:
        script = ctx.script
        if script is None:
            raise VisualPlanningError("visual planning requires a generated script")

        config = ctx.config.visual_planning
        total_seconds = (
            ctx.voice.duration_seconds
            if ctx.voice is not None and ctx.voice.duration_seconds > 0
            else self._estimate_duration(script.narration, config)
        )

        with log_duration(self._logger, "visual_planning"):
            scenes = self._plan(ctx, config, total_seconds)

        ctx.scene_plan = ScenePlan(
            scenes=scenes,
            total_duration_seconds=round(sum(s.duration_seconds for s in scenes), 3),
        )
        self._logger.info(
            "visual_planned",
            scenes=len(scenes),
            total_seconds=ctx.scene_plan.total_duration_seconds,
        )

    def _estimate_duration(self, narration: str, config: VisualPlanningConfig) -> float:
        words = max(1, len(narration.split()))
        return words / config.words_per_second

    def _plan(self, ctx, config: VisualPlanningConfig, total: float) -> list[Scene]:
        script = ctx.script
        if script.scenes:
            sources: list[_SceneSource] = [
                (s.narration, s.on_screen_text, s.visual_instruction)
                for s in script.scenes
            ]
        else:
            # No scene breakdown — treat the whole narration as one scene.
            sources = [(script.narration, script.caption_text, None)]

        weights = [max(1, len(narration.split())) for narration, _, _ in sources]
        total_words = sum(weights)

        scenes: list[Scene] = []
        for index, ((narration, on_screen, instruction), weight) in enumerate(
            zip(sources, weights, strict=True)
        ):
            duration = max(0.1, total * (weight / total_words))
            scenes.append(
                Scene(
                    index=index,
                    narration=narration,
                    duration_seconds=round(duration, 3),
                    visual_type=config.default_visual_type,
                    visual_query=self._visual_query(ctx, instruction, index),
                    on_screen_text=on_screen,
                )
            )
        return scenes

    @staticmethod
    def _visual_query(ctx, instruction: str | None, index: int) -> str:
        if instruction and instruction.strip():
            return instruction.strip()
        suggestions = ctx.brief.visual_suggestions
        if index < len(suggestions) and suggestions[index].strip():
            return suggestions[index].strip()
        if ctx.brief.keywords:
            return " ".join(ctx.brief.keywords)
        return ctx.brief.title
