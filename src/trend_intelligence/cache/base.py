"""Cache abstraction. The interface lives in the domain layer; this re-exports
it so cache implementations and callers import from one place."""

from __future__ import annotations

from ..domain.interfaces import TrendCache

__all__ = ["TrendCache"]
