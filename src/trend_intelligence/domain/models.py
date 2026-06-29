"""Strongly-typed domain models shared across every stage of the pipeline.

These Pydantic models are the *only* contract between stages. Raw provider
payloads must be normalized into these models inside the provider layer and
never leak outside it. All scores are normalized to the range ``0.0 - 1.0``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utcnow() -> datetime:
    """Timezone-aware current time (UTC). Centralized for easy testing."""
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
class TrendSource(str, Enum):
    """Where a trend was discovered. Adding a value here is the only change
    required to register a new provider category."""

    GOOGLE_TRENDS = "google_trends"
    REDDIT = "reddit"
    YOUTUBE = "youtube"
    NEWS_RSS = "news_rss"
    # Future sources — present so models validate before providers are built.
    TIKTOK = "tiktok"
    TWITTER = "twitter"
    INSTAGRAM = "instagram"
    EXPLODING_TOPICS = "exploding_topics"
    PRODUCT_HUNT = "product_hunt"
    HACKER_NEWS = "hacker_news"
    GITHUB_TRENDING = "github_trending"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


class ContentCategory(str, Enum):
    TECHNOLOGY = "technology"
    SCIENCE = "science"
    ENTERTAINMENT = "entertainment"
    GAMING = "gaming"
    SPORTS = "sports"
    NEWS = "news"
    BUSINESS = "business"
    HEALTH = "health"
    EDUCATION = "education"
    LIFESTYLE = "lifestyle"
    FINANCE = "finance"
    POLITICS = "politics"
    OTHER = "other"


class SafetyFlag(str, Enum):
    MISINFORMATION = "misinformation"
    VIOLENCE = "violence"
    ADULT = "adult"
    HATE = "hate"
    MEDICAL = "medical"
    FINANCIAL_ADVICE = "financial_advice"
    POLITICAL = "political"
    COPYRIGHT = "copyright"
    SENSITIVE = "sensitive"


# --------------------------------------------------------------------------- #
# Base config
# --------------------------------------------------------------------------- #
class _Model(BaseModel):
    """Shared base — forbids unknown fields to catch contract drift early."""

    model_config = ConfigDict(extra="forbid", validate_assignment=False)


# --------------------------------------------------------------------------- #
# Pipeline input
# --------------------------------------------------------------------------- #
class TrendQuery(_Model):
    """Parameters that drive a discovery run."""

    region: str = "US"
    language: str = "en"
    categories: list[ContentCategory] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    max_trends_per_provider: int = Field(default=20, ge=1)


# --------------------------------------------------------------------------- #
# Discovery stage
# --------------------------------------------------------------------------- #
class Trend(_Model):
    """A single normalized trend produced by one provider."""

    title: str
    keywords: list[str] = Field(default_factory=list)
    category: ContentCategory = ContentCategory.OTHER
    source: TrendSource
    source_url: str | None = None
    popularity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    engagement_score: float = Field(default=0.0, ge=0.0, le=1.0)
    growth_score: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    discovered_at: datetime = Field(default_factory=utcnow)
    language: str = "en"
    region: str = "US"
    # Normalized provider-specific extras (NOT the raw response).
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def _non_empty_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be empty")
        return v


class TrendProviderResult(_Model):
    """Envelope returned by every provider — success *or* failure, never raised
    to the pipeline so one bad provider cannot break a run."""

    provider: TrendSource
    trends: list[Trend] = Field(default_factory=list)
    fetched_at: datetime = Field(default_factory=utcnow)
    execution_time_ms: float = Field(default=0.0, ge=0.0)
    success: bool = True
    error: str | None = None

    @property
    def count(self) -> int:
        return len(self.trends)

    @classmethod
    def failure(
        cls,
        provider: TrendSource,
        error: str,
        execution_time_ms: float = 0.0,
    ) -> TrendProviderResult:
        return cls(
            provider=provider,
            success=False,
            error=error,
            execution_time_ms=execution_time_ms,
        )


# --------------------------------------------------------------------------- #
# Aggregation stage
# --------------------------------------------------------------------------- #
class AggregatedTrend(_Model):
    """A cluster of near-duplicate trends merged across providers, with source
    attribution preserved."""

    cluster_id: str
    canonical_title: str
    aliases: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    categories: list[ContentCategory] = Field(default_factory=list)
    sources: list[TrendSource] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    member_trends: list[Trend] = Field(default_factory=list)
    popularity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    engagement_score: float = Field(default=0.0, ge=0.0, le=1.0)
    growth_score: float = Field(default=0.0, ge=0.0, le=1.0)
    source_count: int = Field(default=0, ge=0)
    first_seen: datetime = Field(default_factory=utcnow)
    last_seen: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- #
# Intelligence stage (LLM output — structured JSON only)
# --------------------------------------------------------------------------- #
class TrendAnalysis(_Model):
    """Structured result of the LLM analysis for one aggregated trend."""

    cluster_id: str
    keep: bool = True
    refined_title: str
    emerging_theme: str | None = None
    estimated_audience_interest: float = Field(default=0.5, ge=0.0, le=1.0)
    video_angles: list[str] = Field(default_factory=list)
    hooks: list[str] = Field(default_factory=list)
    target_audience: str | None = None
    recommended_category: ContentCategory = ContentCategory.OTHER
    is_safe: bool = True
    safety_flags: list[SafetyFlag] = Field(default_factory=list)
    educational_value: float = Field(default=0.5, ge=0.0, le=1.0)
    entertainment_value: float = Field(default=0.5, ge=0.0, le=1.0)
    visual_potential: float = Field(default=0.5, ge=0.0, le=1.0)
    ai_confidence: float = Field(default=0.5, ge=0.0, le=1.0)


# --------------------------------------------------------------------------- #
# Scoring stage
# --------------------------------------------------------------------------- #
class ScoreBreakdown(_Model):
    """Per-factor contributions plus the combined total — kept for transparency
    and logging."""

    factors: dict[str, float] = Field(default_factory=dict)
    total: float = Field(default=0.0, ge=0.0, le=1.0)


class RankedTrend(_Model):
    """An aggregated trend with its analysis and final score/rank."""

    aggregated_trend: AggregatedTrend
    analysis: TrendAnalysis | None = None
    score_breakdown: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    final_score: float = Field(default=0.0, ge=0.0, le=1.0)
    rank: int = Field(default=0, ge=0)


# --------------------------------------------------------------------------- #
# Selection stage — the stable contract handed to Stage 2
# --------------------------------------------------------------------------- #
class SelectedTopic(_Model):
    """Final output of Stage 1. Stage 2 depends only on this model."""

    title: str
    ranked_trend: RankedTrend
    selection_reason: str
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    alternatives: list[RankedTrend] = Field(default_factory=list)
    manual_override: bool = False
    selected_at: datetime = Field(default_factory=utcnow)
