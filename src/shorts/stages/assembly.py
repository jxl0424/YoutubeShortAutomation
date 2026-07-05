"""Video assembly stage.

Builds a renderer-agnostic ``RenderRequest`` from the scene plan, collected
assets and synthesized voice, then delegates to the injected ``VideoRenderer``.
The renderer does the heavy lifting; this stage just wires the pieces, so the
engine (MoviePy today) can be swapped without touching pipeline logic.
"""

from __future__ import annotations

from pathlib import Path

from trend_intelligence.logging.setup import get_logger, log_duration

from ..domain.exceptions import RenderError
from ..domain.interfaces import PipelineStage, VideoRenderer
from ..domain.models import RenderRequest, RenderScene


class VideoAssembler(PipelineStage):
    name = "video_assembly"

    def __init__(self, renderer: VideoRenderer) -> None:
        self._renderer = renderer
        self._logger = get_logger("shorts.assembly")

    def run(self, ctx) -> None:
        if ctx.scene_plan is None or not ctx.assets:
            raise RenderError("assembly requires a scene plan and collected assets")
        if ctx.voice is None:
            raise RenderError("assembly requires synthesized narration audio")

        video_cfg = ctx.config.video
        asset_by_scene = {a.scene_index: a for a in ctx.assets}

        scenes: list[RenderScene] = []
        for scene in ctx.scene_plan.scenes:
            asset = asset_by_scene.get(scene.index)
            if asset is None:
                raise RenderError(f"scene {scene.index} has no collected asset")
            scenes.append(
                RenderScene(
                    asset_path=asset.path,
                    visual_type=asset.visual_type,
                    duration_seconds=scene.duration_seconds,
                    on_screen_text=scene.on_screen_text,
                )
            )

        music = ctx.config.video.music
        subtitles = video_cfg.subtitles
        request = RenderRequest(
            output_path=ctx.work_dir / "video.mp4",
            width=video_cfg.width,
            height=video_cfg.height,
            fps=video_cfg.fps,
            bitrate=video_cfg.bitrate,
            audio_path=ctx.voice.audio_path,
            scenes=scenes,
            subtitle_path=ctx.voice.subtitle_path,
            ken_burns=video_cfg.ken_burns,
            transitions=video_cfg.transitions,
            scene_text=video_cfg.scene_text,
            burn_subtitles=subtitles.enabled,
            subtitle_font=subtitles.font,
            subtitle_font_size=subtitles.font_size,
            subtitle_color=subtitles.color,
            subtitle_position=subtitles.position,
            subtitle_highlight_color=subtitles.highlight_color,
            caption_cues=ctx.voice.cues,
            music_path=self._music_path(music),
            music_volume=music.volume,
        )

        with log_duration(self._logger, "video_assembly", scenes=len(scenes)):
            rendered = self._renderer.render(request)

        ctx.rendered_video = rendered
        self._logger.info(
            "video_assembled",
            path=str(rendered.path),
            duration=rendered.duration_seconds,
        )

    @staticmethod
    def _music_path(music) -> Path | None:
        """Resolve the configured music track (relative paths = project root)."""
        if not (music.enabled and music.path):
            return None
        path = Path(music.path)
        if not path.is_absolute():
            from ..config.settings import PROJECT_ROOT

            path = PROJECT_ROOT / path
        return path
