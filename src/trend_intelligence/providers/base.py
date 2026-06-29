"""Base trend provider implementing all cross-cutting concerns once.

Concrete providers implement only two methods — :meth:`_fetch_raw` (the
external call) and :meth:`_normalize` (raw → domain models). Everything else —
caching, retries with exponential backoff, rate limiting, timing, graceful
failure — is handled here via the template-method pattern so a single bad
provider can never crash a discovery run.
"""

from __future__ import annotations

import re
import time
from abc import abstractmethod
from collections.abc import Callable
from typing import Any, ClassVar

from pydantic import ValidationError
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config.settings import HttpConfig, ProviderConfig
from ..domain.exceptions import RateLimitError
from ..domain.interfaces import TrendCache, TrendProvider
from ..domain.models import Trend, TrendProviderResult, TrendQuery, TrendSource
from ..logging.setup import get_logger

_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "by", "at", "as", "it", "this", "that",
    "from", "how", "why", "what", "new", "your", "you",
}


def extract_keywords(text: str, limit: int = 6) -> list[str]:
    """Cheap keyword extraction shared by providers lacking native keywords."""
    words = (w.lower() for w in _WORD_RE.findall(text))
    kept = [w for w in words if len(w) > 2 and w not in _STOPWORDS]
    return list(dict.fromkeys(kept))[:limit]  # order-preserving unique


class RateLimiter:
    """Enforces a minimum interval between successive calls."""

    def __init__(
        self,
        min_interval: float,
        *,
        clock: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def acquire(self) -> None:
        if self.min_interval <= 0:
            return
        if self._last is not None:
            wait = self.min_interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()


class BaseTrendProvider(TrendProvider):
    """Template-method base class for every trend provider."""

    #: Exceptions worth retrying (transient). Subclasses may extend this.
    RETRYABLE_EXCEPTIONS: ClassVar[tuple[type[BaseException], ...]] = (
        RateLimitError,
        ConnectionError,
        TimeoutError,
    )

    def __init__(
        self,
        config: ProviderConfig,
        cache: TrendCache,
        *,
        http: HttpConfig | None = None,
        cache_ttl: int = 3600,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._config = config
        self._cache = cache
        self._http = http or HttpConfig()
        self._cache_ttl = cache_ttl
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        self._logger = get_logger(f"providers.{self.source.value}")
        min_interval = float(config.options.get("min_interval_seconds", 0) or 0)
        self._rate_limiter = RateLimiter(
            min_interval, clock=self._clock, sleep=self._sleep
        )

    # --- TrendProvider API ---------------------------------------------- #
    @property
    def is_enabled(self) -> bool:
        return self._config.enabled

    def discover(self, query: TrendQuery) -> TrendProviderResult:
        if not self.is_enabled:
            return TrendProviderResult.failure(self.source, "provider is disabled")

        cache_key = self._cache_key(query)
        cached = self._cache.get(self.source.value, cache_key)
        if cached is not None:
            try:
                result = TrendProviderResult.model_validate(cached)
                self._logger.info(
                    "cache_hit", provider=self.source.value, count=result.count
                )
                return result
            except ValidationError:
                self._cache.invalidate(self.source.value, cache_key)

        start = time.perf_counter()
        try:
            raw = self._retrying_fetch(query)
            trends = self._postprocess(self._normalize(raw, query), query)
            elapsed = round((time.perf_counter() - start) * 1000, 2)
            result = TrendProviderResult(
                provider=self.source,
                trends=trends,
                execution_time_ms=elapsed,
                success=True,
            )
            self._cache.set(
                self.source.value,
                cache_key,
                result.model_dump(mode="json"),
                ttl=self._cache_ttl,
            )
            self._logger.info(
                "provider_discovered",
                provider=self.source.value,
                count=len(trends),
                duration_ms=elapsed,
            )
            return result
        except Exception as exc:  # graceful degradation — never raise
            elapsed = round((time.perf_counter() - start) * 1000, 2)
            self._logger.error(
                "provider_failed",
                provider=self.source.value,
                error=str(exc),
                duration_ms=elapsed,
            )
            return TrendProviderResult.failure(
                self.source, str(exc), execution_time_ms=elapsed
            )

    # --- abstract hooks -------------------------------------------------- #
    @abstractmethod
    def _fetch_raw(self, query: TrendQuery) -> Any:
        """Perform the external call; may raise (retried per policy)."""

    @abstractmethod
    def _normalize(self, raw: Any, query: TrendQuery) -> list[Trend]:
        """Convert the raw provider payload into domain ``Trend`` objects."""

    # --- shared machinery ------------------------------------------------ #
    def _retrying_fetch(self, query: TrendQuery) -> Any:
        retryer = Retrying(
            stop=stop_after_attempt(self._config.max_retries + 1),
            wait=wait_exponential(
                multiplier=self._http.backoff_factor,
                max=self._http.backoff_max_seconds,
            ),
            retry=retry_if_exception_type(self.RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=self._log_retry,
        )

        def _call() -> Any:
            self._rate_limiter.acquire()
            return self._fetch_raw(query)

        return retryer(_call)

    def _log_retry(self, retry_state: Any) -> None:
        self._logger.warning(
            "provider_retry",
            provider=self.source.value,
            attempt=retry_state.attempt_number,
            error=str(retry_state.outcome.exception()),
        )

    def _postprocess(
        self, trends: list[Trend], query: TrendQuery
    ) -> list[Trend]:
        """De-duplicate within the provider, sort by popularity, truncate."""
        unique: dict[str, Trend] = {}
        for trend in trends:
            unique.setdefault(trend.title.strip().lower(), trend)
        ordered = sorted(
            unique.values(), key=lambda t: t.popularity_score, reverse=True
        )
        limit = min(self._config.max_trends, query.max_trends_per_provider)
        return ordered[:limit]

    def _cache_key(self, query: TrendQuery) -> str:
        categories = ",".join(sorted(c.value for c in query.categories))
        return "|".join(
            [
                self.source.value,
                query.region,
                query.language,
                categories,
                str(query.max_trends_per_provider),
            ]
        )
