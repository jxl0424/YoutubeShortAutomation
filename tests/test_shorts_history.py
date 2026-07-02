"""Tests for the cross-run topic history (duplicate protection)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from shorts.history import TopicHistory


def _store(tmp_path):
    return tmp_path / "state" / "history.json"


def test_fresh_store_has_no_duplicates(tmp_path):
    history = TopicHistory(_store(tmp_path))
    assert history.is_duplicate("Anything", ["any"]) is False


def test_recorded_title_matches_normalized(tmp_path):
    history = TopicHistory(_store(tmp_path))
    history.record("PlayStation Ends Physical Discs!", ["playstation", "discs"])

    reloaded = TopicHistory(_store(tmp_path))
    # Case and punctuation differences still match.
    assert reloaded.is_duplicate("playstation ends physical discs") is True
    assert reloaded.is_duplicate("A different topic entirely", ["other"]) is False


def test_keyword_overlap_triggers_duplicate(tmp_path):
    history = TopicHistory(_store(tmp_path))
    history.record("Sony kills game discs", ["sony", "playstation", "discs", "2028"])

    reloaded = TopicHistory(_store(tmp_path))
    # Different title, 3/4 shared keywords (jaccard 0.6) -> duplicate.
    assert (
        reloaded.is_duplicate(
            "Physical media ends on consoles",
            ["sony", "playstation", "discs", "digital"],
        )
        is True
    )
    # Only 1/7 shared -> not a duplicate.
    assert (
        reloaded.is_duplicate("AI chip breakthrough", ["ai", "chip", "nvidia", "sony"])
        is False
    )


def test_entries_expire_after_lookback(tmp_path):
    path = _store(tmp_path)
    path.parent.mkdir(parents=True)
    old = (datetime.now(UTC) - timedelta(days=15)).isoformat()
    path.write_text(
        json.dumps([{"title": "Old topic", "keywords": ["old"], "selected_at": old}]),
        encoding="utf-8",
    )
    history = TopicHistory(path)
    assert history.is_duplicate("Old topic", ["old"]) is False


def test_record_prunes_expired_entries(tmp_path):
    path = _store(tmp_path)
    path.parent.mkdir(parents=True)
    old = (datetime.now(UTC) - timedelta(days=15)).isoformat()
    path.write_text(
        json.dumps([{"title": "Old topic", "keywords": [], "selected_at": old}]),
        encoding="utf-8",
    )
    TopicHistory(path).record("New topic", ["new"], video_url="https://x/y")

    entries = json.loads(path.read_text(encoding="utf-8"))
    assert [e["title"] for e in entries] == ["New topic"]
    assert entries[0]["video_url"] == "https://x/y"


def test_unreadable_store_never_raises(tmp_path):
    path = _store(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    history = TopicHistory(path)  # must not raise
    assert history.is_duplicate("Anything") is False
    history.record("Anything", [])  # store recovers on next write
    assert TopicHistory(path).is_duplicate("Anything") is True
