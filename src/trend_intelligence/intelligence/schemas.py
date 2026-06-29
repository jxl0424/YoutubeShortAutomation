"""LLM input/output schemas.

The LLM is asked to return a *batch* of analyses in one structured response. We
tolerate extra keys from the model (``extra="ignore"``) for robustness, then the
analyzer re-validates each item into the strict domain :class:`TrendAnalysis`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..domain.models import TrendAnalysis


class LLMTrendAnalysis(TrendAnalysis):
    """Lenient view of TrendAnalysis used only for parsing LLM output."""

    model_config = ConfigDict(extra="ignore")


class TrendAnalysisBatch(BaseModel):
    """Top-level structured object the LLM must return."""

    model_config = ConfigDict(extra="ignore")

    analyses: list[LLMTrendAnalysis] = Field(default_factory=list)
