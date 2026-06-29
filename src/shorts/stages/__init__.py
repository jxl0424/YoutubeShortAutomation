"""Pipeline stages — each an independent, replaceable step."""

from .assembly import VideoAssembler
from .assets import AssetCollector
from .metadata import MetadataGenerator
from .script import ScriptGenerator
from .thumbnail import ThumbnailGenerator
from .validation import AssetValidator
from .visual_planning import VisualPlanner
from .voice import VoiceGenerator

__all__ = [
    "AssetCollector",
    "AssetValidator",
    "MetadataGenerator",
    "ScriptGenerator",
    "ThumbnailGenerator",
    "VideoAssembler",
    "VisualPlanner",
    "VoiceGenerator",
]
