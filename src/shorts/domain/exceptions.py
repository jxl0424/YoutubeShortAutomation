"""Exception hierarchy for the Shorts generation pipeline (Stage 2).

Mirrors Stage 1's style: a narrow, typed hierarchy so each stage can fail with
an actionable, attributable error.
"""

from __future__ import annotations


class ShortsError(Exception):
    """Base class for all Stage 2 errors."""


class ShortsConfigurationError(ShortsError):
    """Stage 2 configuration is missing or invalid."""


class StageError(ShortsError):
    """A pipeline stage failed."""


class ScriptGenerationError(StageError):
    """The script could not be generated."""


class MetadataError(StageError):
    """Metadata generation failed."""


class VoiceError(StageError):
    """Voice synthesis failed."""


class VisualPlanningError(StageError):
    """The scene plan could not be built."""


class VisualError(StageError):
    """Asset collection/generation failed."""


class AssetValidationError(StageError):
    """Collected assets failed validation."""


class RenderError(StageError):
    """Video assembly/rendering failed."""


class QAError(StageError):
    """The pre-publish QA gate could not run (missing artifacts)."""


class UploadError(StageError):
    """Upload to the destination platform failed."""


class ReportError(ShortsError):
    """The channel analytics report could not be produced."""


class ShortsPipelineError(ShortsError):
    """Wraps a stage failure with the offending stage name."""

    def __init__(self, stage: str, message: str) -> None:
        self.stage = stage
        self.message = message
        super().__init__(f"[{stage}] {message}")
