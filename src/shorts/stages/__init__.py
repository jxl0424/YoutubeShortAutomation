"""Pipeline stages — each an independent, replaceable step."""

from .assets import AssetCollector
from .metadata import MetadataGenerator
from .script import ScriptGenerator
from .visual_planning import VisualPlanner
from .voice import VoiceGenerator

__all__ = [
    "AssetCollector",
    "MetadataGenerator",
    "ScriptGenerator",
    "VisualPlanner",
    "VoiceGenerator",
]
