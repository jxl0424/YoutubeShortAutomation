"""Trend Discovery & Intelligence Layer (Stage 1).

Discovers, aggregates, analyzes, scores and selects high-potential YouTube
Shorts topics. The downstream content pipeline depends only on the
:class:`~trend_intelligence.domain.models.SelectedTopic` contract.
"""

__version__ = "0.1.0"

from .pipeline import (
    TrendIntelligencePipeline,
    build_pipeline,
    query_from_config,
)

__all__ = [
    "__version__",
    "TrendIntelligencePipeline",
    "build_pipeline",
    "query_from_config",
]
