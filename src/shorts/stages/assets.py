"""Asset collection stage.

For each planned scene, fetches one visual asset into ``work_dir/assets/``.
Providers are tried in order, preferring those that satisfy the scene's planned
visual type, falling back to any other provider (e.g. generated image when stock
video is unavailable). A scene that no provider can satisfy raises ``VisualError``
(the pipeline can't render without visuals).
"""

from __future__ import annotations

from collections.abc import Sequence

from trend_intelligence.logging.setup import get_logger, log_duration

from ..domain.exceptions import VisualError
from ..domain.interfaces import PipelineStage, VisualProvider
from ..domain.models import Scene, VisualAsset


class AssetCollector(PipelineStage):
    name = "asset_collection"

    def __init__(
        self,
        providers: Sequence[VisualProvider],
        *,
        max_retries: int = 0,
        backoff_factor: float = 1.0,
        sleep=None,
    ) -> None:
        import time

        self._providers = list(providers)
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor
        self._sleep = sleep or time.sleep
        self._logger = get_logger("shorts.assets")

    def run(self, ctx) -> None:
        if ctx.scene_plan is None:
            raise VisualError("asset collection requires a scene plan")
        if not self._providers:
            raise VisualError("no visual providers are configured")

        assets_dir = ctx.work_dir / "assets"
        collected: list[VisualAsset] = []
        with log_duration(self._logger, "asset_collection"):
            for scene in ctx.scene_plan.scenes:
                collected.append(self._collect_for_scene(scene, assets_dir))

        ctx.assets = collected
        self._logger.info("assets_collected", count=len(collected))

    def _collect_for_scene(self, scene: Scene, output_dir) -> VisualAsset:
        # Prefer providers that satisfy the scene's planned visual type.
        ordered = sorted(
            self._providers,
            key=lambda p: 0 if p.supports(scene.visual_type) else 1,
        )
        last_error: Exception | None = None
        for provider in ordered:
            for attempt in range(self._max_retries + 1):
                try:
                    asset = provider.fetch(scene, output_dir)
                    self._logger.info(
                        "asset_fetched",
                        scene=scene.index,
                        provider=provider.name,
                        type=asset.visual_type.value,
                    )
                    return asset
                except Exception as exc:
                    last_error = exc
                    self._logger.warning(
                        "asset_provider_failed",
                        scene=scene.index,
                        provider=provider.name,
                        attempt=attempt + 1,
                        error=str(exc),
                    )
                    if attempt < self._max_retries:
                        self._sleep(self._backoff_factor * (2**attempt))
        raise VisualError(f"no provider could supply scene {scene.index}: {last_error}")
