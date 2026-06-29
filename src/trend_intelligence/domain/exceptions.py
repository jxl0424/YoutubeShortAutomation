"""Exception hierarchy for the Trend Intelligence module.

A narrow, typed hierarchy lets each layer react appropriately: providers wrap
external failures so the pipeline can degrade gracefully instead of crashing.
"""

from __future__ import annotations


class TrendIntelligenceError(Exception):
    """Base class for all errors raised by this module."""


# --- Provider layer ------------------------------------------------------- #
class ProviderError(TrendIntelligenceError):
    """A provider failed to discover trends."""

    def __init__(self, provider: str, message: str) -> None:
        self.provider = provider
        self.message = message
        super().__init__(f"[{provider}] {message}")


class RateLimitError(ProviderError):
    """Provider signalled rate limiting; eligible for backoff/retry."""


class InvalidResponseError(ProviderError):
    """Provider returned a response that could not be parsed/normalized."""


class ProviderAuthError(ProviderError):
    """Provider authentication failed or credentials are missing."""


# --- Cache layer ---------------------------------------------------------- #
class CacheError(TrendIntelligenceError):
    """A cache read/write operation failed."""


# --- LLM / intelligence layer --------------------------------------------- #
class LLMError(TrendIntelligenceError):
    """The LLM provider failed to produce a usable response."""


class InvalidLLMResponseError(LLMError):
    """The LLM response could not be parsed into the expected schema."""


# --- Selection ------------------------------------------------------------ #
class SelectionError(TrendIntelligenceError):
    """No suitable topic could be selected."""


# --- Configuration -------------------------------------------------------- #
class ConfigurationError(TrendIntelligenceError):
    """Configuration is missing or invalid."""
