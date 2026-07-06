"""Tests for cross-run media rotation (narrator voice + BGM)."""

from __future__ import annotations

import json

from shorts.rotation import MediaRotation, list_music_tracks


def test_choose_avoids_last_used(tmp_path):
    rot = MediaRotation(tmp_path / "rotation.json")
    # With two options, the pick must alternate away from the last one.
    first = rot.choose("voice", ["a", "b"])
    for _ in range(5):
        nxt = rot.choose("voice", ["a", "b"])
        assert nxt != first
        first = nxt


def test_choose_single_option_returns_it(tmp_path):
    rot = MediaRotation(tmp_path / "rotation.json")
    assert rot.choose("music", ["only.mp3"]) == "only.mp3"
    assert rot.choose("music", ["only.mp3"]) == "only.mp3"  # no crash on repeat


def test_choice_persists_across_instances(tmp_path):
    path = tmp_path / "rotation.json"
    # Each fresh instance reads the prior pick off disk and avoids it (3 options
    # leave 2 in the pool, so a different pick is always available).
    picked = MediaRotation(path).choose("voice", ["x", "y", "z"])
    for _ in range(5):
        nxt = MediaRotation(path).choose("voice", ["x", "y", "z"])
        assert nxt != picked
        picked = nxt


def test_unreadable_state_does_not_raise(tmp_path):
    path = tmp_path / "rotation.json"
    path.write_text("{ not valid json", encoding="utf-8")
    # Malformed state is treated as empty rather than blocking the run.
    assert MediaRotation(path).choose("voice", ["a"]) == "a"


def test_choose_writes_state_file(tmp_path):
    path = tmp_path / "rotation.json"
    MediaRotation(path).choose("voice", ["solo"])
    assert json.loads(path.read_text(encoding="utf-8"))["voice"] == "solo"


def test_list_music_tracks_filters_and_sorts(tmp_path):
    (tmp_path / "b.mp3").write_bytes(b"x")
    (tmp_path / "a.wav").write_bytes(b"x")
    (tmp_path / "README.md").write_text("docs")  # excluded by suffix
    (tmp_path / "notes.txt").write_text("x")  # excluded by suffix
    tracks = list_music_tracks(str(tmp_path))
    assert [t.name for t in tracks] == ["a.wav", "b.mp3"]


def test_list_music_tracks_missing_or_unset(tmp_path):
    assert list_music_tracks(None) == []
    assert list_music_tracks(str(tmp_path / "nope")) == []
