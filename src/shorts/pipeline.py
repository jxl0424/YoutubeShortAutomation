"""Composition root for the Shorts generation pipeline (Stage 2).

Runs an ordered list of independent :class:`PipelineStage` objects over a shared
:class:`PipelineContext`:

    enrichment → script → metadata → voice → visual planning → asset collection
    → validation → assembly → thumbnail → packaging → upload

Stages are injected, so any stage can be added, removed, reordered or replaced
without touching this orchestrator. The single input is Stage 1's
``SelectedTopic`` (flattened to a ``TopicBrief`` at the boundary); the single
output is a ``GeneratedShort``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from trend_intelligence.domain.models import SelectedTopic
from trend_intelligence.logging.setup import get_logger, log_duration

from .config.settings import ShortsConfig
from .domain.brief import TopicBrief
from .domain.exceptions import ShortsPipelineError
from .domain.interfaces import PipelineStage
from .domain.models import (
    AssetValidationReport,
    GeneratedShort,
    RenderedVideo,
    ScenePlan,
    Script,
    ThumbnailResult,
    TopicResearch,
    UploadResult,
    VideoMetadata,
    VisualAsset,
    VoiceResult,
)


@dataclass
class PipelineContext:
    """Mutable state shared by every stage. Stages fill in their own field."""

    brief: TopicBrief
    config: ShortsConfig
    work_dir: Path
    research: TopicResearch | None = None
    script: Script | None = None
    metadata: VideoMetadata | None = None
    scene_plan: ScenePlan | None = None
    voice: VoiceResult | None = None
    assets: list[VisualAsset] = field(default_factory=list)
    validation: AssetValidationReport | None = None
    rendered_video: RenderedVideo | None = None
    thumbnail: ThumbnailResult | None = None
    package: GeneratedShort | None = None
    upload_result: UploadResult | None = None


class ShortsPipeline:
    """Runs the staged generation workflow."""

    def __init__(
        self,
        stages: Sequence[PipelineStage],
        config: ShortsConfig,
    ) -> None:
        self._stages = list(stages)
        self._config = config
        self._logger = get_logger("shorts.pipeline")

    def generate(
        self,
        selected_topic: SelectedTopic,
        *,
        work_dir: Path | None = None,
    ) -> GeneratedShort:
        brief = TopicBrief.from_selected_topic(selected_topic)
        run_dir = Path(work_dir) if work_dir else self._default_work_dir(brief)
        ctx = PipelineContext(brief=brief, config=self._config, work_dir=run_dir)

        with log_duration(self._logger, "shorts_pipeline", title=brief.title):
            for stage in self._stages:
                if not stage.is_enabled(self._config):
                    self._logger.info("stage_skipped", stage=stage.name)
                    continue
                try:
                    with log_duration(self._logger, "stage", stage=stage.name):
                        stage.run(ctx)
                except ShortsPipelineError:
                    raise
                except Exception as exc:
                    self._logger.error("stage_failed", stage=stage.name, error=str(exc))
                    raise ShortsPipelineError(stage.name, str(exc)) from exc

        if ctx.package is None:
            raise ShortsPipelineError(
                "packaging", "pipeline completed without producing a package"
            )
        self._logger.info(
            "shorts_done",
            title=brief.title,
            output_dir=str(ctx.package.output_dir),
        )
        return ctx.package

    def _default_work_dir(self, brief: TopicBrief) -> Path:
        slug = re.sub(r"[^a-z0-9]+", "-", brief.title.lower()).strip("-")[:50]
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        return (
            Path(self._config.packaging.output_dir) / f"{slug or 'short'}-{timestamp}"
        )
