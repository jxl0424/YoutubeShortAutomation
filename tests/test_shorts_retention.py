"""Tests for local output pruning."""

from __future__ import annotations

from shorts.config.settings import ShortsConfig
from shorts.retention import prune_output


def _make_run(output_dir, name, *, assets_bytes=1000):
    run = output_dir / name
    (run / "assets").mkdir(parents=True)
    (run / "assets" / "scene_00.mp4").write_bytes(b"a" * assets_bytes)
    (run / "video.mp4").write_bytes(b"deliverable")
    return run


def _config(tmp_path, *, keep_runs=2, enabled=True):
    config = ShortsConfig()
    config.packaging.output_dir = str(tmp_path / "output")
    config.retention.enabled = enabled
    config.retention.keep_runs = keep_runs
    return config


def test_prunes_old_assets_keeps_newest_and_deliverable(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    # Names sort chronologically; newest last.
    for name in ["short-20260701", "short-20260702", "short-20260703"]:
        _make_run(out, name)

    stats = prune_output(_config(tmp_path, keep_runs=2))

    assert stats.runs_pruned == 1
    assert stats.bytes_freed == 1000
    # Oldest lost its assets/ but kept the deliverable.
    assert not (out / "short-20260701" / "assets").exists()
    assert (out / "short-20260701" / "video.mp4").exists()
    # Newest two fully intact.
    assert (out / "short-20260702" / "assets").exists()
    assert (out / "short-20260703" / "assets").exists()


def test_noop_when_fewer_than_keep_runs(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    _make_run(out, "short-20260701")
    stats = prune_output(_config(tmp_path, keep_runs=5))
    assert stats.runs_pruned == 0
    assert (out / "short-20260701" / "assets").exists()


def test_missing_output_dir_is_safe(tmp_path):
    stats = prune_output(_config(tmp_path, keep_runs=2))
    assert stats.runs_pruned == 0


def test_run_without_assets_is_skipped(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    _make_run(out, "short-20260703")
    _make_run(out, "short-20260702")
    # Oldest run already has no assets/ (e.g. pruned before).
    old = out / "short-20260701"
    old.mkdir()
    (old / "video.mp4").write_bytes(b"x")

    stats = prune_output(_config(tmp_path, keep_runs=2))
    assert stats.runs_pruned == 0  # nothing left to prune on the old one
