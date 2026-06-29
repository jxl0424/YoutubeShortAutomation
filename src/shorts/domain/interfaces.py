"""Provider and stage interfaces for the Shorts pipeline (Stage 2).

Every external service is abstracted behind one of these ports; business logic
(the stages) depends only on the abstractions. The ``LLMProvider`` interface is
*reused* from Stage 1 — script and metadata generation need exactly the same
structured-output contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

# Reuse Stage 1's LLM abstraction rather than redefining it.
from trend_intelligence.domain.interfaces import LLMProvider

from .models import (
    GeneratedShort,
    Scene,
    UploadResult,
    VideoMetadata,
    VisualAsset,
    VisualType,
    VoiceResult,
)

if TYPE_CHECKING:
    from ..config.settings import ShortsConfig
    from ..pipeline import PipelineContext

__all__ = [
    "LLMProvider",
    "VoiceProvider",
    "VisualProvider",
    "StorageProvider",
    "UploadProvider",
    "PipelineStage",
]


class VoiceProvider(ABC):
    """Text-to-speech. Default impl is edge-tts; future: ElevenLabs, Azure, GCP."""

    name: ClassVar[str]

    @abstractmethod
    def synthesize(
        self,
        *,
        text: str,
        output_dir: Path,
        voice: str,
        language: str,
        rate: str | None = None,
    ) -> VoiceResult:
        """Produce narration audio (and optional subtitles) for ``text``."""


class VisualProvider(ABC):
    """Supplies a visual asset for a scene (stock footage or generated image)."""

    name: ClassVar[str]
    #: Which visual types this provider can satisfy.
    provides: ClassVar[set[VisualType]]

    def supports(self, visual_type: VisualType) -> bool:
        return visual_type in self.provides

    @abstractmethod
    def fetch(self, scene: Scene, output_dir: Path) -> VisualAsset:
        """Return a local asset satisfying the scene's visual requirements."""


class StorageProvider(ABC):
    """File storage abstraction (local now; cloud/object storage later)."""

    @abstractmethod
    def ensure_dir(self, path: Path) -> Path: ...

    @abstractmethod
    def write_text(self, path: Path, text: str) -> Path: ...

    @abstractmethod
    def write_bytes(self, path: Path, data: bytes) -> Path: ...

    @abstractmethod
    def exists(self, path: Path) -> bool: ...


class UploadProvider(ABC):
    """Publishes the finished package to a destination platform."""

    name: ClassVar[str]

    @abstractmethod
    def upload(self, package: GeneratedShort, metadata: VideoMetadata) -> UploadResult:
        """Upload the package; must be no-op-safe when uploads are disabled."""


class PipelineStage(ABC):
    """One independent, replaceable step of the generation pipeline.

    A stage reads from and writes to the shared :class:`PipelineContext`.
    Optional stages override :meth:`is_enabled` to self-gate via configuration.
    """

    name: ClassVar[str]

    def is_enabled(self, config: ShortsConfig) -> bool:  # noqa: ARG002
        return True

    @abstractmethod
    def run(self, ctx: PipelineContext) -> None: ...
