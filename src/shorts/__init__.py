"""Stage 2 — AI YouTube Shorts generation pipeline.

Consumes a Stage 1 ``SelectedTopic`` and produces an upload-ready package. The
pipeline depends only on the ``TopicBrief`` adapter, never on Stage 1 internals.
"""

__version__ = "0.1.0"

from .config.settings import ShortsConfig
from .domain.brief import TopicBrief
from .pipeline import PipelineContext, ShortsPipeline

__all__ = [
    "__version__",
    "ShortsConfig",
    "TopicBrief",
    "PipelineContext",
    "ShortsPipeline",
]
