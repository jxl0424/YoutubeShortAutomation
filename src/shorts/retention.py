"""Local output pruning.

Reclaims disk by deleting the re-downloadable ``assets/`` footage of old runs.
The newest ``keep_runs`` folders are kept fully intact; older runs lose only
their ``assets/`` subfolder (~85% of a run's size) — the small deliverable
(video.mp4, thumbnail, metadata) stays local. Deliberately non-destructive to
the deliverable: it only ever removes a directory literally named ``assets``.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from trend_intelligence.logging.setup import get_logger

from .config.settings import PROJECT_ROOT, ShortsConfig

_logger = get_logger("shorts.retention")


@dataclass
class PruneStats:
    runs_pruned: int = 0
    bytes_freed: int = 0


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def prune_output(config: ShortsConfig) -> PruneStats:
    """Delete the ``assets/`` of runs older than the newest ``keep_runs``."""
    output_dir = Path(config.packaging.output_dir)
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir
    if not output_dir.is_dir():
        return PruneStats()

    # Newest first (name embeds a sortable -YYYYMMDD-HHMMSS timestamp; fall back
    # to mtime so a non-standard folder name still orders sanely).
    runs = sorted(
        (p for p in output_dir.iterdir() if p.is_dir()),
        key=lambda p: (p.name, p.stat().st_mtime),
        reverse=True,
    )

    stats = PruneStats()
    for run in runs[config.retention.keep_runs :]:
        assets = run / "assets"
        if not assets.is_dir():
            continue
        freed = _dir_size(assets)
        shutil.rmtree(assets)
        stats.runs_pruned += 1
        stats.bytes_freed += freed

    if stats.runs_pruned:
        _logger.info(
            "output_pruned",
            runs_pruned=stats.runs_pruned,
            mb_freed=round(stats.bytes_freed / 1_048_576, 1),
            kept=config.retention.keep_runs,
        )
    return stats
