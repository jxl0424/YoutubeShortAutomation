"""Storage providers — file persistence behind the ``StorageProvider`` interface.

Only a local-filesystem backend exists today; the interface lets a cloud/object
backend drop in later without touching the packaging stage.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from ..config.settings import PackagingConfig
from ..domain.interfaces import StorageProvider


class LocalStorageProvider(StorageProvider):
    name: ClassVar[str] = "local"

    def ensure_dir(self, path: Path) -> Path:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_text(self, path: Path, text: str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_bytes(self, path: Path, data: bytes) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def exists(self, path: Path) -> bool:
        return Path(path).exists()


def build_storage(config: PackagingConfig | None = None) -> StorageProvider:
    # Only the local backend exists; config reserved for future backend selection.
    return LocalStorageProvider()
