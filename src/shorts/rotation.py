"""Cross-run media rotation for the narrator voice and background music.

A daily run that always used the same voice + track would make the channel sound
identical every day. This small JSON store remembers the last voice and track so
the CLI can pick a different one each run (never repeating back-to-back), the way
[TopicHistory][shorts.history] remembers recently-posted topics.
"""

from __future__ import annotations

import json
import random
from collections.abc import Sequence
from pathlib import Path

from trend_intelligence.logging.setup import get_logger

from .config.settings import PROJECT_ROOT

DEFAULT_ROTATION_PATH = PROJECT_ROOT / ".state" / "rotation.json"
_AUDIO_SUFFIXES = {".mp3", ".m4a", ".wav", ".ogg"}


def list_music_tracks(directory: str | None) -> list[Path]:
    """Audio files in ``directory`` (relative paths resolve against the repo).

    Non-audio files (e.g. the README) are excluded by suffix, so the music
    folder can hold docs alongside tracks. Missing/unset dir -> no tracks.
    """
    if not directory:
        return []
    root = Path(directory)
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    if not root.is_dir():
        return []
    return sorted(
        p for p in root.iterdir() if p.suffix.lower() in _AUDIO_SUFFIXES and p.is_file()
    )


class MediaRotation:
    """Remembers the last pick per key so the next run can differ from it."""

    def __init__(self, path: Path | str = DEFAULT_ROTATION_PATH) -> None:
        self._path = Path(path)
        self._logger = get_logger("shorts.rotation")
        self._state = self._load()

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # An unreadable state file must never block a run; worst case is one
            # repeated voice/track, which is harmless.
            self._logger.warning("rotation_unreadable", error=str(exc))
            return {}
        return data if isinstance(data, dict) else {}

    def choose(self, key: str, options: Sequence[str]) -> str:
        """Pick a random option for ``key``, avoiding the previous run's pick."""
        if not options:
            raise ValueError("choose requires at least one option")
        last = self._state.get(key)
        pool = [o for o in options if o != last] or list(options)
        picked = random.choice(pool)
        self._state[key] = picked
        self._save()
        return picked

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._state, indent=2, ensure_ascii=False), encoding="utf-8"
        )
