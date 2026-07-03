"""Data models that connect the Shorts generation stages (Stage 2).

These strongly-typed Pydantic models are the only contract passed between
stages. Each stage reads what it needs from the shared pipeline context and
writes a typed result, so stages stay independent and replaceable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
class VisualType(str, Enum):
    STOCK_VIDEO = "stock_video"
    STOCK_IMAGE = "stock_image"
    GENERATED_IMAGE = "generated_image"
    COLOR_CARD = "color_card"
    AI_VIDEO = "ai_video"  # future


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


# --------------------------------------------------------------------------- #
# Enrichment (optional)
# --------------------------------------------------------------------------- #
class TopicResearch(_Model):
    facts: list[str] = Field(default_factory=list)
    statistics: list[str] = Field(default_factory=list)
    terminology: list[str] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)
    context: str | None = None


# --------------------------------------------------------------------------- #
# Script
# --------------------------------------------------------------------------- #
class ScriptScene(_Model):
    index: int = Field(ge=0)
    narration: str
    on_screen_text: str | None = None
    visual_instruction: str | None = None


class Script(_Model):
    hook: str
    narration: str  # full narration, ~60-90 words
    scenes: list[ScriptScene] = Field(default_factory=list)
    caption_text: str | None = None
    cta: str | None = None
    word_count: int = Field(default=0, ge=0)


# --------------------------------------------------------------------------- #
# Metadata
# --------------------------------------------------------------------------- #
class VideoMetadata(_Model):
    title: str
    description: str
    tags: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    category: str | None = None
    language: str = "en"


# --------------------------------------------------------------------------- #
# Visual planning
# --------------------------------------------------------------------------- #
class Scene(_Model):
    index: int = Field(ge=0)
    narration: str
    duration_seconds: float = Field(gt=0)
    visual_type: VisualType
    visual_query: str
    on_screen_text: str | None = None


class ScenePlan(_Model):
    scenes: list[Scene] = Field(default_factory=list)
    total_duration_seconds: float = Field(default=0.0, ge=0)


# --------------------------------------------------------------------------- #
# Voice
# --------------------------------------------------------------------------- #
class CaptionCue(_Model):
    index: int = Field(ge=0)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    text: str


class VoiceResult(_Model):
    audio_path: Path
    subtitle_path: Path | None = None
    duration_seconds: float = Field(default=0.0, ge=0)
    cues: list[CaptionCue] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Visual assets + validation
# --------------------------------------------------------------------------- #
class VisualAsset(_Model):
    scene_index: int = Field(ge=0)
    visual_type: VisualType
    path: Path
    source: str  # provider name
    source_url: str | None = None
    width: int = Field(default=0, ge=0)
    height: int = Field(default=0, ge=0)
    duration_seconds: float | None = None
    license: str | None = None


class AssetIssue(_Model):
    code: str
    message: str
    scene_index: int | None = None
    severity: Severity = Severity.ERROR


class AssetValidationReport(_Model):
    ok: bool = True
    issues: list[AssetIssue] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Render request (renderer input) + outputs
# --------------------------------------------------------------------------- #
class RenderScene(_Model):
    """One timed visual segment for the renderer."""

    asset_path: Path
    visual_type: VisualType
    duration_seconds: float = Field(gt=0)
    on_screen_text: str | None = None


class RenderRequest(_Model):
    """Everything the renderer needs — decouples the renderer from the pipeline."""

    output_path: Path
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: int = Field(gt=0)
    bitrate: str
    audio_path: Path
    scenes: list[RenderScene] = Field(default_factory=list)
    subtitle_path: Path | None = None
    ken_burns: bool = True
    transitions: bool = True
    burn_subtitles: bool = True
    # Big per-scene keyword overlays rendered from RenderScene.on_screen_text
    # (distinct from the bottom narration captions).
    scene_text: bool = True
    # Subtitle styling, renderer-agnostic: size is in output-video pixels,
    # color is a common name or #RRGGBB, position is bottom | center | top.
    subtitle_font: str = "Arial"
    subtitle_font_size: int = Field(default=96, gt=0)
    subtitle_color: str = "white"
    subtitle_position: str = "bottom"
    music_path: Path | None = None
    music_volume: float = Field(default=0.15, ge=0.0, le=1.0)


class RenderedVideo(_Model):
    path: Path
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: int = Field(gt=0)
    duration_seconds: float = Field(default=0.0, ge=0)
    bitrate: str | None = None


class ThumbnailRequest(_Model):
    output_path: Path
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    title: str
    background_path: Path | None = None
    branding: str | None = None
    title_overlay: bool = True


class ThumbnailResult(_Model):
    path: Path
    width: int = Field(gt=0)
    height: int = Field(gt=0)


# --------------------------------------------------------------------------- #
# Pre-publish QA
# --------------------------------------------------------------------------- #
class QAReport(_Model):
    """Result of the deterministic pre-publish quality gate.

    A binary gate: any failed check drops ``ok`` to False and the offending
    checks are listed in ``issues``. A failing report downgrades the upload's
    privacy (to a review queue) rather than aborting the pipeline.
    """

    ok: bool = True
    issues: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Upload + final package
# --------------------------------------------------------------------------- #
class UploadResult(_Model):
    uploaded: bool = False
    video_id: str | None = None
    url: str | None = None
    status: str = "skipped"


class GeneratedShort(_Model):
    """The final upload-ready package — paths to every produced artifact."""

    output_dir: Path
    video_path: Path | None = None
    thumbnail_path: Path | None = None
    captions_path: Path | None = None
    metadata_path: Path | None = None
    description_path: Path | None = None
    tags_path: Path | None = None
    script_path: Path | None = None
    assets_dir: Path | None = None
    logs_dir: Path | None = None
    upload: UploadResult | None = None
    created_at: datetime = Field(default_factory=utcnow)
