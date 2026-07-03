"""Pre-publish QA gate.

Runs deterministic quality checks on the finished package right before upload and
decides the privacy the short publishes with. A passing report publishes at the
configured privacy (``upload.privacy``, e.g. public); a failing one downgrades to
``upload.qa_fail_privacy`` (private by default) so a bad render lands in a
manual-review queue instead of going public.

Unlike ``AssetValidator``, this gate never raises on a failed check — a failure is
a routing decision, not a pipeline abort. It only raises ``QAError`` when the
artifacts it needs to inspect are missing (which would itself be a pipeline bug).
"""

from __future__ import annotations

from trend_intelligence.logging.setup import get_logger, log_duration

from ..domain.exceptions import QAError
from ..domain.interfaces import PipelineStage
from ..domain.models import QAReport

# Sanity bounds for a Short (module constants, like cli.py's dedupe gate). A good
# render for this channel sits well inside these; the checks catch broken output.
_MIN_SECONDS = 8.0
_MAX_SECONDS = 90.0
_MIN_TITLE_WORDS = 3
_MIN_DESCRIPTION_CHARS = 20
_MIN_TAGS = 3


class PrePublishQA(PipelineStage):
    name = "pre_publish_qa"

    def __init__(self) -> None:
        self._logger = get_logger("shorts.qa")

    def is_enabled(self, config) -> bool:
        # QA only matters when the run intends to upload.
        return config.upload.enabled

    def run(self, ctx) -> None:
        if ctx.package is None:
            raise QAError("QA requires a packaged short")
        if ctx.metadata is None:
            raise QAError("QA requires metadata")
        if ctx.rendered_video is None:
            raise QAError("QA requires a rendered video")

        with log_duration(self._logger, "pre_publish_qa"):
            report = self._check(ctx)

        ctx.qa_report = report
        upload = ctx.config.upload
        if report.ok:
            ctx.publish_privacy = upload.privacy
            self._logger.info("qa_passed", privacy=upload.privacy)
        else:
            ctx.publish_privacy = upload.qa_fail_privacy
            self._logger.warning(
                "qa_failed_downgrade",
                privacy=upload.qa_fail_privacy,
                issues=report.issues,
            )

    def _check(self, ctx) -> QAReport:
        pkg = ctx.package
        video = ctx.rendered_video
        meta = ctx.metadata
        validation = ctx.config.validation
        max_title = ctx.config.metadata.max_title_length
        issues: list[str] = []

        # 1. Video file present and non-empty.
        if pkg.video_path is None or not pkg.video_path.exists():
            issues.append("video file is missing")
        elif pkg.video_path.stat().st_size == 0:
            issues.append("video file is empty")

        # 2. Duration within Short bounds.
        if not (_MIN_SECONDS <= video.duration_seconds <= _MAX_SECONDS):
            issues.append(
                f"duration {video.duration_seconds:.1f}s outside "
                f"[{_MIN_SECONDS:.0f}, {_MAX_SECONDS:.0f}]s"
            )

        # 3. Portrait orientation at or above the resolution floor.
        if video.width >= video.height:
            issues.append(
                f"video is {video.width}x{video.height} (not portrait)"
            )
        if video.width < validation.min_width or video.height < validation.min_height:
            issues.append(
                f"video is {video.width}x{video.height}, below "
                f"{validation.min_width}x{validation.min_height}"
            )

        # 4. Captions present and non-empty.
        if pkg.captions_path is None or not pkg.captions_path.exists():
            issues.append("captions file is missing")
        elif pkg.captions_path.stat().st_size == 0:
            issues.append("captions file is empty")

        # 5. Thumbnail present.
        if pkg.thumbnail_path is None or not pkg.thumbnail_path.exists():
            issues.append("thumbnail is missing")

        # 6. Title present, within the platform cap, and not a bare fragment.
        title = meta.title.strip()
        if not title:
            issues.append("title is empty")
        else:
            if len(title) > max_title:
                issues.append(f"title is {len(title)} chars, over {max_title}")
            if len(title.split()) < _MIN_TITLE_WORDS:
                issues.append(
                    f"title has fewer than {_MIN_TITLE_WORDS} words: {title!r}"
                )

        # 7. Description and tags substantial enough to publish.
        if len(meta.description.strip()) < _MIN_DESCRIPTION_CHARS:
            issues.append(
                f"description under {_MIN_DESCRIPTION_CHARS} characters"
            )
        if len(meta.tags) < _MIN_TAGS:
            issues.append(f"fewer than {_MIN_TAGS} tags")

        return QAReport(ok=not issues, issues=issues)
