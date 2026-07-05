"""Stage 2 configuration.

Loaded from ``config/shorts.yaml`` (separate from Stage 1's config), with secrets
resolved from environment variables only. Follows the same pydantic-settings
conventions as Stage 1 so nothing requires code changes to retune behaviour.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..domain.exceptions import ShortsConfigurationError
from ..domain.models import VisualType

# src/shorts/config/settings.py -> project root is 3 levels up.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "shorts.yaml"


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EnrichmentConfig(_Section):
    enabled: bool = False
    max_facts: int = Field(default=5, ge=0)


class ScriptConfig(_Section):
    provider: str = "gemini_flash"
    fallback_providers: list[str] = Field(
        default_factory=lambda: ["groq", "openrouter"]
    )
    model: str = "gemini-2.0-flash"
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1)
    # Free-tier endpoints (e.g. NVIDIA NIM llama-70b) can take >30s to produce a
    # full script, so this is deliberately generous.
    timeout_seconds: float = Field(default=120.0, gt=0)
    # Bounds for the LLM's own length choice (content-driven, biased short).
    min_words: int = Field(default=40, ge=1)
    max_words: int = Field(default=160, ge=1)
    include_cta: bool = True
    api_key_env: str = "GEMINI_API_KEY"
    api_key: str | None = None


class MetadataConfig(_Section):
    max_title_length: int = Field(default=100, ge=1)
    max_tags: int = Field(default=15, ge=0)
    hashtag_count: int = Field(default=5, ge=0)


class VoiceConfig(_Section):
    provider: str = "edge_tts"
    voice: str = "en-US-AriaNeural"
    # Note: current providers derive language from the voice name (e.g. Kokoro's
    # bf_/bm_ prefixes -> en-gb); this field is a forward-looking interface param.
    language: str = "en"
    rate: str = "+0%"
    # Local Kokoro model files (only used when provider == "kokoro").
    kokoro_model_path: str = "models/kokoro/kokoro-v1.0.onnx"
    kokoro_voices_path: str = "models/kokoro/voices-v1.0.bin"


class VisualPlanningConfig(_Section):
    # Scene durations are purely proportional to narration word counts (see
    # VisualPlanner._plan); there is deliberately no per-scene min/max clamp.
    words_per_second: float = Field(default=2.5, gt=0)
    default_visual_type: VisualType = VisualType.STOCK_VIDEO


class StockConfig(_Section):
    pexels_api_key_env: str = "PEXELS_API_KEY"
    pexels_api_key: str | None = None
    pixabay_api_key_env: str = "PIXABAY_API_KEY"
    pixabay_api_key: str | None = None


class GeneratedImageConfig(_Section):
    provider: str = "pollinations"  # credential-free default
    model: str | None = "flux"  # higher-quality Pollinations model
    style: str | None = (
        "cinematic, photorealistic, vivid color, dramatic lighting, "
        "vertical composition"
    )
    api_key_env: str | None = None
    api_key: str | None = None


class AssetsConfig(_Section):
    providers: list[str] = Field(default_factory=lambda: ["pexels", "pollinations"])
    stock: StockConfig = Field(default_factory=StockConfig)
    generated: GeneratedImageConfig = Field(default_factory=GeneratedImageConfig)


class ValidationConfig(_Section):
    min_width: int = Field(default=720, ge=1)
    min_height: int = Field(default=1280, ge=1)
    allow_duplicates: bool = False


class SubtitleConfig(_Section):
    enabled: bool = True
    font: str = "Arial"
    # In output-video pixels (96 ≈ 5% of a 1920-tall frame — Shorts-sized).
    font_size: int = Field(default=96, ge=1)
    color: str = "white"  # common name or #RRGGBB
    position: str = "bottom"  # bottom | center | top
    # Karaoke highlight for the currently-spoken word (brand yellow).
    highlight_color: str = "#FFC400"  # common name or #RRGGBB


class MusicConfig(_Section):
    enabled: bool = False
    path: str | None = None
    volume: float = Field(default=0.15, ge=0.0, le=1.0)


class VideoConfig(_Section):
    width: int = Field(default=1080, ge=1)
    height: int = Field(default=1920, ge=1)
    fps: int = Field(default=30, ge=1)
    bitrate: str = "8M"
    ken_burns: bool = True
    transitions: bool = True
    # Per-scene keyword overlays from the script's on_screen_text.
    scene_text: bool = True
    template: str = "default"
    subtitles: SubtitleConfig = Field(default_factory=SubtitleConfig)
    music: MusicConfig = Field(default_factory=MusicConfig)


class ThumbnailConfig(_Section):
    enabled: bool = True
    template: str = "default"
    title_overlay: bool = True
    branding: str | None = None


class PackagingConfig(_Section):
    output_dir: str = "output"


class UploadConfig(_Section):
    enabled: bool = False
    # Privacy a QA-passing short publishes with (the shipped yaml opts into
    # "public"); a QA failure downgrades to ``qa_fail_privacy`` for review.
    privacy: str = "private"
    qa_fail_privacy: str = "private"
    category_id: str = "22"
    # Self-declared YouTube status flags (see the Data API `videos.insert`
    # `status` block). Age restriction is deliberately absent: `ytRating` is
    # read-only in the API and can only be self-applied manually in Studio.
    contains_synthetic_media: bool = True
    made_for_kids: bool = False
    client_secrets_env: str = "YOUTUBE_CLIENT_SECRETS"
    token_path: str = ".secrets/youtube_token.json"


class ArchiveConfig(_Section):
    """Mirror finished shorts to S3-compatible object storage (e.g. Cloudflare
    R2). Off by default — needs a bucket and the three credential env vars. The
    raw ``assets/`` footage is skipped unless ``include_assets`` (it is large
    and re-downloadable)."""

    enabled: bool = False
    bucket: str = ""
    prefix: str = "shorts"
    include_assets: bool = False
    endpoint_url_env: str = "R2_ENDPOINT_URL"
    access_key_id_env: str = "R2_ACCESS_KEY_ID"
    secret_access_key_env: str = "R2_SECRET_ACCESS_KEY"


class RetentionConfig(_Section):
    """Prune old local runs to reclaim disk. Off by default (destructive). The
    newest ``keep_runs`` folders are kept intact; older runs lose only their
    re-downloadable ``assets/`` — the small deliverable stays local."""

    enabled: bool = False
    keep_runs: int = Field(default=5, ge=1)


class ReportConfig(_Section):
    """Weekly channel-growth report (``shorts-report``).

    Read-only YouTube access with its own OAuth token so the upload token's
    narrow ``youtube.upload`` scope stays untouched.
    """

    output_dir: str = "reports"
    top_videos: int = Field(default=5, ge=1)
    client_secrets_env: str = "YOUTUBE_CLIENT_SECRETS"
    token_path: str = ".secrets/youtube_report_token.json"


class HttpConfig(_Section):
    timeout_seconds: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    backoff_factor: float = Field(default=0.5, ge=0.0)
    backoff_max_seconds: float = Field(default=30.0, gt=0)


class ShortsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str = "en"
    enrichment: EnrichmentConfig = Field(default_factory=EnrichmentConfig)
    script: ScriptConfig = Field(default_factory=ScriptConfig)
    metadata: MetadataConfig = Field(default_factory=MetadataConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    visual_planning: VisualPlanningConfig = Field(default_factory=VisualPlanningConfig)
    assets: AssetsConfig = Field(default_factory=AssetsConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    video: VideoConfig = Field(default_factory=VideoConfig)
    thumbnail: ThumbnailConfig = Field(default_factory=ThumbnailConfig)
    packaging: PackagingConfig = Field(default_factory=PackagingConfig)
    upload: UploadConfig = Field(default_factory=UploadConfig)
    archive: ArchiveConfig = Field(default_factory=ArchiveConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)

    @classmethod
    def load(
        cls,
        path: str | Path | None = None,
        *,
        load_env: bool = True,
    ) -> ShortsConfig:
        if load_env:
            load_dotenv()

        config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
        if not config_path.exists():
            raise ShortsConfigurationError(f"Config file not found: {config_path}")

        try:
            raw: Any = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ShortsConfigurationError(
                f"Invalid YAML in {config_path}: {exc}"
            ) from exc
        if not isinstance(raw, dict):
            raise ShortsConfigurationError(
                f"Config root must be a mapping, got {type(raw).__name__}"
            )

        try:
            config = cls.model_validate(raw)
        except ValidationError as exc:
            raise ShortsConfigurationError(f"Invalid configuration: {exc}") from exc

        config._resolve_secrets()
        return config

    def _resolve_secrets(self) -> None:
        if self.script.api_key is None and self.script.api_key_env:
            self.script.api_key = os.getenv(self.script.api_key_env)
        stock = self.assets.stock
        if stock.pexels_api_key is None:
            stock.pexels_api_key = os.getenv(stock.pexels_api_key_env)
        if stock.pixabay_api_key is None:
            stock.pixabay_api_key = os.getenv(stock.pixabay_api_key_env)
        generated = self.assets.generated
        if generated.api_key is None and generated.api_key_env:
            generated.api_key = os.getenv(generated.api_key_env)
