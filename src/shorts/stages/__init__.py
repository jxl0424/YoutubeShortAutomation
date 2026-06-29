"""Pipeline stages — each an independent, replaceable step."""

from .metadata import MetadataGenerator
from .script import ScriptGenerator

__all__ = ["MetadataGenerator", "ScriptGenerator"]
