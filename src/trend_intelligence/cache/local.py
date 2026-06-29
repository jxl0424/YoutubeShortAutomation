"""Local filesystem cache (JSON files).

Each namespace maps to a subdirectory; each key to a SHA-256-named file holding
``{"expires_at": <epoch|null>, "value": <json>}``. Values must be
JSON-serializable — callers serialize Pydantic models via ``model_dump(mode="json")``
before caching. The design is intentionally storage-agnostic so a Redis or
database backend can implement the same :class:`TrendCache` interface later.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..domain.exceptions import CacheError
from ..logging.setup import get_logger
from .base import TrendCache

_logger = get_logger("cache.local")
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_namespace(namespace: str) -> str:
    cleaned = _UNSAFE.sub("_", namespace).strip("_")
    return cleaned or "default"


class LocalFileCache(TrendCache):
    """File-backed implementation of :class:`TrendCache`."""

    def __init__(
        self,
        directory: str | Path,
        *,
        default_ttl: int = 3600,
        enabled: bool = True,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.directory = Path(directory)
        self.default_ttl = default_ttl
        self.enabled = enabled
        self._clock = clock

    # --- internals ------------------------------------------------------- #
    def _namespace_dir(self, namespace: str) -> Path:
        path = self.directory / _safe_namespace(namespace)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _path(self, namespace: str, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return self._namespace_dir(namespace) / f"{digest}.json"

    # --- TrendCache API -------------------------------------------------- #
    def get(self, namespace: str, key: str) -> Any | None:
        if not self.enabled:
            return None
        path = self._path(namespace, key)
        if not path.exists():
            _logger.debug("cache_miss", namespace=namespace, key=key)
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            _logger.warning("cache_read_error", namespace=namespace, error=str(exc))
            return None

        expires_at = payload.get("expires_at")
        if expires_at is not None and self._clock() >= expires_at:
            _logger.debug("cache_expired", namespace=namespace, key=key)
            self._unlink(path)
            return None

        _logger.debug("cache_hit", namespace=namespace, key=key)
        return payload.get("value")

    def set(self, namespace: str, key: str, value: Any, ttl: int | None = None) -> None:
        if not self.enabled:
            return
        ttl = self.default_ttl if ttl is None else ttl
        expires_at = None if ttl <= 0 else self._clock() + ttl
        path = self._path(namespace, key)
        try:
            path.write_text(
                json.dumps({"expires_at": expires_at, "value": value}),
                encoding="utf-8",
            )
        except (TypeError, ValueError, OSError) as exc:
            raise CacheError(
                f"Failed to write cache for {namespace}/{key}: {exc}"
            ) from exc

    def invalidate(self, namespace: str, key: str | None = None) -> None:
        if key is None:
            ns_dir = self.directory / _safe_namespace(namespace)
            if ns_dir.exists():
                for file in ns_dir.glob("*.json"):
                    self._unlink(file)
        else:
            self._unlink(self._path(namespace, key))

    @staticmethod
    def _unlink(path: Path) -> None:
        try:
            path.unlink()
        except OSError:
            pass
