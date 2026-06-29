"""LLM provider interface. Lives in the domain layer; re-exported here so all
LLM adapters and callers import from one place."""

from __future__ import annotations

from ...domain.interfaces import LLMProvider

__all__ = ["LLMProvider"]
