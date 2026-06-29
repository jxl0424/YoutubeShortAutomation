"""Asset validation stage.

Checks collected assets before rendering and produces an actionable
``AssetValidationReport``. ERROR-level issues stop the pipeline (you can't render
a broken set of assets); WARNING-level issues (e.g. duplicates) are logged but
allowed. Uses the dimensions the providers already recorded, so no media probe
is needed.
"""

from __future__ import annotations

import hashlib

from trend_intelligence.logging.setup import get_logger, log_duration

from ..domain.exceptions import AssetValidationError
from ..domain.interfaces import PipelineStage
from ..domain.models import (
    AssetIssue,
    AssetValidationReport,
    Scene,
    Severity,
    VisualAsset,
)


class AssetValidator(PipelineStage):
    name = "asset_validation"

    def __init__(self) -> None:
        self._logger = get_logger("shorts.validation")

    def run(self, ctx) -> None:
        if ctx.scene_plan is None:
            raise AssetValidationError("validation requires a scene plan")

        with log_duration(self._logger, "asset_validation"):
            report = self._validate(ctx)

        ctx.validation = report
        errors = [i for i in report.issues if i.severity is Severity.ERROR]
        warnings = [i for i in report.issues if i.severity is Severity.WARNING]
        self._logger.info(
            "assets_validated",
            ok=report.ok,
            errors=len(errors),
            warnings=len(warnings),
        )
        if not report.ok:
            summary = "; ".join(i.message for i in errors)
            raise AssetValidationError(f"asset validation failed: {summary}")

    def _validate(self, ctx) -> AssetValidationReport:
        config = ctx.config.validation
        scenes: list[Scene] = list(ctx.scene_plan.scenes)
        assets: list[VisualAsset] = list(ctx.assets)
        scene_by_index = {s.index: s for s in scenes}
        asset_by_index = {a.scene_index: a for a in assets}
        issues: list[AssetIssue] = []

        # 1. Coverage — every scene must have an asset.
        for scene in scenes:
            if scene.index not in asset_by_index:
                issues.append(
                    AssetIssue(
                        code="missing_asset",
                        message=f"scene {scene.index} has no asset",
                        scene_index=scene.index,
                        severity=Severity.ERROR,
                    )
                )

        # 2. Per-asset checks.
        seen_hashes: dict[str, int] = {}
        for asset in assets:
            if not asset.path.exists():
                issues.append(
                    AssetIssue(
                        code="missing_file",
                        message=f"file not found: {asset.path}",
                        scene_index=asset.scene_index,
                        severity=Severity.ERROR,
                    )
                )
                continue
            data = asset.path.read_bytes()
            if not data:
                issues.append(
                    AssetIssue(
                        code="empty_file",
                        message=f"empty file: {asset.path}",
                        scene_index=asset.scene_index,
                        severity=Severity.ERROR,
                    )
                )
                continue

            issues.extend(self._check_dimensions(asset, config))
            issues.extend(self._check_timing(asset, scene_by_index))

            digest = hashlib.sha256(data).hexdigest()
            if digest in seen_hashes and not config.allow_duplicates:
                issues.append(
                    AssetIssue(
                        code="duplicate_visual",
                        message=(
                            f"scene {asset.scene_index} duplicates scene "
                            f"{seen_hashes[digest]}"
                        ),
                        scene_index=asset.scene_index,
                        severity=Severity.WARNING,
                    )
                )
            else:
                seen_hashes[digest] = asset.scene_index

        ok = not any(i.severity is Severity.ERROR for i in issues)
        return AssetValidationReport(ok=ok, issues=issues)

    @staticmethod
    def _check_dimensions(asset: VisualAsset, config) -> list[AssetIssue]:
        if asset.width <= 0 or asset.height <= 0:
            return [
                AssetIssue(
                    code="unknown_dimensions",
                    message=f"scene {asset.scene_index} asset has unknown dimensions",
                    scene_index=asset.scene_index,
                    severity=Severity.WARNING,
                )
            ]
        issues: list[AssetIssue] = []
        if asset.width < config.min_width or asset.height < config.min_height:
            issues.append(
                AssetIssue(
                    code="low_resolution",
                    message=(
                        f"scene {asset.scene_index} is {asset.width}x{asset.height}, "
                        f"below {config.min_width}x{config.min_height}"
                    ),
                    scene_index=asset.scene_index,
                    severity=Severity.ERROR,
                )
            )
        if asset.width > asset.height:
            issues.append(
                AssetIssue(
                    code="wrong_orientation",
                    message=f"scene {asset.scene_index} is landscape, expected portrait",
                    scene_index=asset.scene_index,
                    severity=Severity.ERROR,
                )
            )
        return issues

    @staticmethod
    def _check_timing(asset: VisualAsset, scene_by_index) -> list[AssetIssue]:
        scene = scene_by_index.get(asset.scene_index)
        if (
            scene is not None
            and asset.duration_seconds is not None
            and asset.duration_seconds < scene.duration_seconds - 0.01
        ):
            return [
                AssetIssue(
                    code="short_asset",
                    message=(
                        f"scene {asset.scene_index} asset is "
                        f"{asset.duration_seconds:.1f}s < scene "
                        f"{scene.duration_seconds:.1f}s (will loop)"
                    ),
                    scene_index=asset.scene_index,
                    severity=Severity.WARNING,
                )
            ]
        return []
