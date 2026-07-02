"""Cross-run topic history for duplicate protection.

A daily scheduled run can rediscover the same trend for days, so the CLI
consults this small JSON store before generating: a recently-posted topic makes
it re-select an alternative (or no-op for the day) instead of uploading a
near-identical short.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from trend_intelligence.logging.setup import get_logger

from .config.settings import PROJECT_ROOT

DEFAULT_HISTORY_PATH = PROJECT_ROOT / ".state" / "topic_history.json"
LOOKBACK_DAYS = 14
KEYWORD_OVERLAP_THRESHOLD = 0.6


def _normalize(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _keyword_set(keywords: list[str] | None) -> set[str]:
    return {k.strip().lower() for k in keywords or [] if k.strip()}


class TopicHistory:
    """Remembers what was generated recently; entries expire after the lookback."""

    def __init__(self, path: Path | str = DEFAULT_HISTORY_PATH) -> None:
        self._path = Path(path)
        self._logger = get_logger("shorts.history")
        self._entries = self._load()

    def _load(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # An unreadable history must never block a run; worst case is one
            # repeated topic, which the user reviews before publishing anyway.
            self._logger.warning("history_unreadable", error=str(exc))
            return []
        return data if isinstance(data, list) else []

    def _recent(self) -> list[dict]:
        cutoff = datetime.now(UTC) - timedelta(days=LOOKBACK_DAYS)
        recent = []
        for entry in self._entries:
            try:
                when = datetime.fromisoformat(entry["selected_at"])
            except (KeyError, TypeError, ValueError):
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            if when >= cutoff:
                recent.append(entry)
        return recent

    def is_duplicate(self, title: str, keywords: list[str] | None = None) -> bool:
        normalized = _normalize(title)
        words = _keyword_set(keywords)
        for entry in self._recent():
            if _normalize(entry.get("title", "")) == normalized:
                return True
            past = _keyword_set(entry.get("keywords"))
            if words and past:
                overlap = len(words & past) / len(words | past)
                if overlap >= KEYWORD_OVERLAP_THRESHOLD:
                    return True
        return False

    def record(
        self,
        title: str,
        keywords: list[str] | None = None,
        video_url: str | None = None,
    ) -> None:
        self._entries = self._recent()  # prune expired entries on write
        self._entries.append(
            {
                "title": title,
                "keywords": list(keywords or []),
                "selected_at": datetime.now(UTC).isoformat(),
                "video_url": video_url,
            }
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._entries, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self._logger.info("history_recorded", title=title, entries=len(self._entries))
