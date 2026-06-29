"""Packaging stage — assembles the final upload-ready output folder.

Writes the text artifacts (metadata.json, description.txt, tags.txt, script.txt)
and a run summary via the injected ``StorageProvider``, ensures the assets/ and
logs/ directories exist, and records every artifact path in a ``GeneratedShort``
(the pipeline's return value). Media files (video/thumbnail/captions) were
written in place by earlier stages; only paths that exist are recorded.
"""

from __future__ import annotations

import json

from trend_intelligence.logging.setup import get_logger, log_duration

from ..domain.interfaces import PipelineStage, StorageProvider
from ..domain.models import GeneratedShort, Script, VideoMetadata


class Packager(PipelineStage):
    name = "packaging"

    def __init__(self, storage: StorageProvider) -> None:
        self._storage = storage
        self._logger = get_logger("shorts.packaging")

    def run(self, ctx) -> None:
        out = ctx.work_dir
        self._storage.ensure_dir(out)
        assets_dir = self._storage.ensure_dir(out / "assets")
        logs_dir = self._storage.ensure_dir(out / "logs")

        metadata_path = description_path = tags_path = script_path = None
        if ctx.metadata is not None:
            metadata_path = self._storage.write_text(
                out / "metadata.json", ctx.metadata.model_dump_json(indent=2)
            )
            description_path = self._storage.write_text(
                out / "description.txt", self._description(ctx.metadata)
            )
            tags_path = self._storage.write_text(
                out / "tags.txt", ", ".join(ctx.metadata.tags)
            )
        if ctx.script is not None:
            script_path = self._storage.write_text(
                out / "script.txt", self._script_text(ctx.script)
            )

        with log_duration(self._logger, "packaging"):
            self._storage.write_text(logs_dir / "summary.json", self._summary(ctx))

        ctx.package = GeneratedShort(
            output_dir=out,
            video_path=self._existing(
                ctx.rendered_video.path if ctx.rendered_video else None
            ),
            thumbnail_path=self._existing(
                ctx.thumbnail.path if ctx.thumbnail else None
            ),
            captions_path=self._existing(
                ctx.voice.subtitle_path if ctx.voice else None
            ),
            metadata_path=metadata_path,
            description_path=description_path,
            tags_path=tags_path,
            script_path=script_path,
            assets_dir=assets_dir,
            logs_dir=logs_dir,
            upload=ctx.upload_result,
        )
        self._logger.info("packaged", output_dir=str(out))

    # --- helpers --------------------------------------------------------- #
    def _existing(self, path):
        return path if path is not None and self._storage.exists(path) else None

    @staticmethod
    def _description(metadata: VideoMetadata) -> str:
        text = metadata.description.strip()
        hashtags = " ".join(metadata.hashtags)
        if hashtags and hashtags not in text:
            text = f"{text}\n\n{hashtags}"
        return text

    @staticmethod
    def _script_text(script: Script) -> str:
        parts = [f"HOOK\n{script.hook}", f"NARRATION\n{script.narration}"]
        if script.scenes:
            scene_lines = [
                f"{s.index + 1}. {s.narration}"
                + (f"  [text: {s.on_screen_text}]" if s.on_screen_text else "")
                + (
                    f"  [visual: {s.visual_instruction}]"
                    if s.visual_instruction
                    else ""
                )
                for s in script.scenes
            ]
            parts.append("SCENES\n" + "\n".join(scene_lines))
        if script.cta:
            parts.append(f"CTA\n{script.cta}")
        return "\n\n".join(parts) + "\n"

    @staticmethod
    def _summary(ctx) -> str:
        return json.dumps(
            {
                "title": ctx.brief.title,
                "metadata_title": ctx.metadata.title if ctx.metadata else None,
                "duration_seconds": (
                    ctx.rendered_video.duration_seconds if ctx.rendered_video else None
                ),
                "scene_count": len(ctx.scene_plan.scenes) if ctx.scene_plan else 0,
                "validation_ok": ctx.validation.ok if ctx.validation else None,
                "validation_issues": (
                    len(ctx.validation.issues) if ctx.validation else 0
                ),
            },
            indent=2,
        )
