"""Application configuration.

Configuration is loaded from a YAML file (``config/default.yaml`` by default)
and layered with environment variables for *secrets only*. Nothing in normal
operation requires code changes — providers, weights, cache, LLM, region and
language are all driven from YAML.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..domain.exceptions import ConfigurationError
from ..domain.models import ContentCategory

# src/trend_intelligence/config/settings.py -> project root is 3 levels up.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "default.yaml"


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderConfig(_Section):
    enabled: bool = False
    max_trends: int = Field(default=20, ge=1)
    timeout_seconds: float = Field(default=10.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    api_key_env: str | None = None
    api_key: str | None = None  # populated from env at load time
    # Provider-specific, free-form settings (feed URLs, subreddits, etc.).
    options: dict[str, Any] = Field(default_factory=dict)


class CacheConfig(_Section):
    backend: str = "local"
    directory: str = ".cache/trends"
    default_ttl_seconds: int = Field(default=3600, ge=0)
    enabled: bool = True
    ttl_overrides: dict[str, int] = Field(default_factory=dict)

    def ttl_for(self, namespace: str) -> int:
        return self.ttl_overrides.get(namespace, self.default_ttl_seconds)


class LLMConfig(_Section):
    provider: str = "nvidia_nim"
    base_url: str = "https://integrate.api.nvidia.com/v1"
    model: str = "meta/llama-3.1-70b-instruct"
    api_key_env: str = "NVIDIA_API_KEY"
    api_key: str | None = None  # populated from env at load time
    temperature: float = Field(default=0.4, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=1)
    timeout_seconds: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=3, ge=0)


class ScoringWeights(_Section):
    search_popularity: float = 0.11
    growth_rate: float = 0.09
    recent_activity: float = 0.06
    engagement: float = 0.12
    competition: float = 0.06
    freshness: float = 0.05
    news_relevance: float = 0.04
    uniqueness: float = 0.06
    visual_potential: float = 0.08
    educational_value: float = 0.06
    entertainment_value: float = 0.07
    estimated_virality: float = 0.10
    ai_confidence: float = 0.10

    def as_mapping(self) -> dict[str, float]:
        return self.model_dump()


class SelectionConfig(_Section):
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)
    require_monetization_safe: bool = True
    max_alternatives: int = Field(default=5, ge=0)
    evergreen_bonus: float = Field(default=0.0, ge=0.0, le=1.0)


class HttpConfig(_Section):
    timeout_seconds: float = Field(default=10.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    backoff_factor: float = Field(default=0.5, ge=0.0)
    backoff_max_seconds: float = Field(default=30.0, gt=0)


class AggregationConfig(_Section):
    # Titles whose token similarity meets this threshold are clustered together.
    similarity_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    # Popularity boost per extra corroborating source (cross-source agreement).
    cross_source_bonus: float = Field(default=0.08, ge=0.0, le=1.0)
    # Cap on the number of aggregated trends returned (strongest first).
    max_aggregated: int = Field(default=50, ge=1)
    # Minimum token length considered when comparing titles.
    min_token_length: int = Field(default=3, ge=1)


class AppConfig(BaseModel):
    """Root configuration object for the whole module."""

    model_config = ConfigDict(extra="forbid")

    region: str = "US"
    language: str = "en"
    categories: list[ContentCategory] = Field(default_factory=list)
    max_trends_per_provider: int = Field(default=20, ge=1)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    scoring: ScoringWeights = Field(default_factory=ScoringWeights)
    selection: SelectionConfig = Field(default_factory=SelectionConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    aggregation: AggregationConfig = Field(default_factory=AggregationConfig)

    # --- loading --------------------------------------------------------- #
    @classmethod
    def load(
        cls,
        path: str | Path | None = None,
        *,
        load_env: bool = True,
    ) -> AppConfig:
        """Load configuration from YAML and resolve secrets from the environment."""
        if load_env:
            load_dotenv()

        config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
        if not config_path.exists():
            raise ConfigurationError(f"Config file not found: {config_path}")

        try:
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigurationError(f"Invalid YAML in {config_path}: {exc}") from exc

        if not isinstance(raw, dict):
            raise ConfigurationError(
                f"Config root must be a mapping, got {type(raw).__name__}"
            )

        try:
            config = cls.model_validate(raw)
        except ValidationError as exc:
            raise ConfigurationError(f"Invalid configuration: {exc}") from exc

        config._resolve_secrets()
        return config

    def _resolve_secrets(self) -> None:
        """Pull secret values from environment variables (never from YAML)."""
        if self.llm.api_key is None and self.llm.api_key_env:
            self.llm.api_key = os.getenv(self.llm.api_key_env)
        for provider in self.providers.values():
            if provider.api_key is None and provider.api_key_env:
                provider.api_key = os.getenv(provider.api_key_env)

    # --- helpers --------------------------------------------------------- #
    def enabled_providers(self) -> dict[str, ProviderConfig]:
        return {name: cfg for name, cfg in self.providers.items() if cfg.enabled}
