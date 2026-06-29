"""Domain layer: models and interfaces with no outward dependencies."""

from .exceptions import (
    CacheError,
    ConfigurationError,
    InvalidLLMResponseError,
    InvalidResponseError,
    LLMError,
    ProviderAuthError,
    ProviderError,
    RateLimitError,
    SelectionError,
    TrendIntelligenceError,
)
from .interfaces import (
    LLMProvider,
    ScoringStrategy,
    SelectionStrategy,
    TrendCache,
    TrendProvider,
)
from .models import (
    AggregatedTrend,
    ContentCategory,
    RankedTrend,
    SafetyFlag,
    ScoreBreakdown,
    SelectedTopic,
    Trend,
    TrendAnalysis,
    TrendProviderResult,
    TrendQuery,
    TrendSource,
    utcnow,
)

__all__ = [
    # models
    "AggregatedTrend",
    "ContentCategory",
    "RankedTrend",
    "SafetyFlag",
    "ScoreBreakdown",
    "SelectedTopic",
    "Trend",
    "TrendAnalysis",
    "TrendProviderResult",
    "TrendQuery",
    "TrendSource",
    "utcnow",
    # interfaces
    "LLMProvider",
    "ScoringStrategy",
    "SelectionStrategy",
    "TrendCache",
    "TrendProvider",
    # exceptions
    "CacheError",
    "ConfigurationError",
    "InvalidLLMResponseError",
    "InvalidResponseError",
    "LLMError",
    "ProviderAuthError",
    "ProviderError",
    "RateLimitError",
    "SelectionError",
    "TrendIntelligenceError",
]
