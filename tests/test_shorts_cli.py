"""Tests for the Stage 2 CLI (shorts.cli)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from shorts import cli
from shorts.domain.exceptions import ShortsPipelineError
from shorts.domain.models import GeneratedShort
from shorts.history import TopicHistory
from trend_intelligence.domain.exceptions import TrendIntelligenceError
from trend_intelligence.domain.models import (
    AggregatedTrend,
    ContentCategory,
    RankedTrend,
    ScoreBreakdown,
    SelectedTopic,
    TrendSource,
)


@pytest.fixture(autouse=True)
def history_store(tmp_path, monkeypatch):
    """Point the CLI's TopicHistory at a per-test file, never the real .state/."""
    path = tmp_path / "state" / "history.json"
    monkeypatch.setattr(cli, "TopicHistory", lambda p=path: TopicHistory(p))
    return path


def _ranked(cluster: str, title: str, keywords: list[str], rank: int) -> RankedTrend:
    aggregated = AggregatedTrend(
        cluster_id=cluster,
        canonical_title=title,
        keywords=keywords,
        categories=[ContentCategory.TECHNOLOGY],
        sources=[TrendSource.HACKER_NEWS],
        source_count=1,
        popularity_score=0.8,
    )
    return RankedTrend(
        aggregated_trend=aggregated,
        analysis=None,
        score_breakdown=ScoreBreakdown(total=0.7),
        final_score=0.7,
        rank=rank,
    )


def _selected(*, with_alternative: bool = False) -> SelectedTopic:
    alternatives = (
        [_ranked("c2", "Quantum computing milestone", ["quantum", "computing"], 2)]
        if with_alternative
        else []
    )
    return SelectedTopic(
        title="This AI Chip Changes Everything",
        ranked_trend=_ranked("c1", "AI breakthrough", ["ai", "chip"], 1),
        selection_reason="highest score",
        score=0.65,
        alternatives=alternatives,
    )


def _short(tmp_path: Path) -> GeneratedShort:
    out = tmp_path / "pkg"
    return GeneratedShort(
        output_dir=out,
        video_path=out / "video.mp4",
        thumbnail_path=out / "thumbnail.png",
    )


class _FakePipeline:
    def __init__(self, result: GeneratedShort | None = None, error=None):
        self.result = result
        self.error = error
        self.calls: list[tuple[SelectedTopic, Path | None]] = []

    def generate(self, topic, *, work_dir=None):
        self.calls.append((topic, work_dir))
        if self.error is not None:
            raise self.error
        return self.result


def _topic_file(tmp_path: Path) -> Path:
    path = tmp_path / "topic.json"
    path.write_text(_selected().model_dump_json(), encoding="utf-8")
    return path


def _patch_discovery(monkeypatch, *, topic=None, error=None):
    """Stub the Stage 1 names imported by shorts.cli; returns the captured state."""
    state = SimpleNamespace(config=SimpleNamespace(llm=SimpleNamespace(provider="x")))

    def _run(query, override_title=None):
        state.query = query
        state.override = override_title
        if error is not None:
            raise error
        return topic

    monkeypatch.setattr(
        cli, "AppConfig", SimpleNamespace(load=lambda path: state.config)
    )
    monkeypatch.setattr(cli, "query_from_config", lambda config: "QUERY")
    monkeypatch.setattr(
        cli, "build_discovery_pipeline", lambda config: SimpleNamespace(run=_run)
    )
    return state


def test_topic_json_skips_discovery(tmp_path, monkeypatch, capsys):
    fake = _FakePipeline(result=_short(tmp_path))
    monkeypatch.setattr(cli, "build_pipeline", lambda config: fake)

    rc = cli.main(["--topic-json", str(_topic_file(tmp_path))])

    assert rc == 0
    topic, work_dir = fake.calls[0]
    assert topic.title == "This AI Chip Changes Everything"
    assert work_dir is None
    out = capsys.readouterr()
    assert "GENERATED SHORT: This AI Chip Changes Everything" in out.out
    assert "video.mp4" in out.out
    assert "Upload     : skipped" in out.out
    assert "Generating short" in out.err


def test_json_output_is_pure_json_on_stdout(tmp_path, monkeypatch, capsys):
    fake = _FakePipeline(result=_short(tmp_path))
    monkeypatch.setattr(cli, "build_pipeline", lambda config: fake)

    rc = cli.main(["--topic-json", str(_topic_file(tmp_path)), "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["video_path"].endswith("video.mp4")


def test_work_dir_is_forwarded(tmp_path, monkeypatch):
    fake = _FakePipeline(result=_short(tmp_path))
    monkeypatch.setattr(cli, "build_pipeline", lambda config: fake)

    rc = cli.main(
        [
            "--topic-json",
            str(_topic_file(tmp_path)),
            "--work-dir",
            str(tmp_path / "run"),
        ]
    )

    assert rc == 0
    assert fake.calls[0][1] == tmp_path / "run"


def test_missing_topic_file_fails(tmp_path, capsys):
    rc = cli.main(["--topic-json", str(tmp_path / "nope.json")])
    assert rc == 1
    assert "Could not load topic" in capsys.readouterr().err


def test_invalid_topic_json_fails(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('{"title": "no ranked trend"}', encoding="utf-8")
    rc = cli.main(["--topic-json", str(bad)])
    assert rc == 1
    assert "Could not load topic" in capsys.readouterr().err


def test_missing_config_fails(tmp_path, capsys):
    rc = cli.main(["--config", str(tmp_path / "nope.yaml")])
    assert rc == 1
    assert "Configuration error" in capsys.readouterr().err


def test_discovery_path_runs_stage1(tmp_path, monkeypatch, capsys):
    fake = _FakePipeline(result=_short(tmp_path))
    monkeypatch.setattr(cli, "build_pipeline", lambda config: fake)
    state = _patch_discovery(monkeypatch, topic=_selected())

    rc = cli.main(["--mock-llm", "--override", "My Topic"])

    assert rc == 0
    assert state.config.llm.provider == "mock"
    assert state.override == "My Topic"
    assert state.query == "QUERY"
    assert fake.calls[0][0].title == "This AI Chip Changes Everything"


def test_discovery_failure_fails(tmp_path, monkeypatch, capsys):
    _patch_discovery(monkeypatch, error=TrendIntelligenceError("no trends"))
    rc = cli.main([])
    assert rc == 1
    assert "No topic could be selected: no trends" in capsys.readouterr().err


def test_generation_failure_fails(tmp_path, monkeypatch, capsys):
    fake = _FakePipeline(error=ShortsPipelineError("voice", "tts down"))
    monkeypatch.setattr(cli, "build_pipeline", lambda config: fake)

    rc = cli.main(["--topic-json", str(_topic_file(tmp_path))])

    assert rc == 1
    assert "Generation failed: [voice] tts down" in capsys.readouterr().err


# --- duplicate protection ---------------------------------------------------- #
def _seed(history_store, *records):
    history = TopicHistory(history_store)
    for title, keywords in records:
        history.record(title, keywords)


def test_dedupe_reselects_alternative(tmp_path, monkeypatch, capsys, history_store):
    _seed(history_store, ("This AI Chip Changes Everything", ["ai", "chip"]))
    fake = _FakePipeline(result=_short(tmp_path))
    monkeypatch.setattr(cli, "build_pipeline", lambda config: fake)
    _patch_discovery(monkeypatch, topic=_selected(with_alternative=True))

    rc = cli.main([])

    assert rc == 0
    assert fake.calls[0][0].title == "Quantum computing milestone"
    assert "using alternative" in capsys.readouterr().err


def test_dedupe_all_duplicates_is_successful_noop(
    tmp_path, monkeypatch, capsys, history_store
):
    _seed(
        history_store,
        ("This AI Chip Changes Everything", ["ai", "chip"]),
        ("Quantum computing milestone", ["quantum", "computing"]),
    )
    fake = _FakePipeline(result=_short(tmp_path))
    monkeypatch.setattr(cli, "build_pipeline", lambda config: fake)
    _patch_discovery(monkeypatch, topic=_selected(with_alternative=True))

    rc = cli.main([])

    assert rc == 0
    assert fake.calls == []  # pipeline never ran
    assert "Nothing new to post" in capsys.readouterr().err


def test_allow_repeat_bypasses_dedupe(tmp_path, monkeypatch, history_store):
    _seed(history_store, ("This AI Chip Changes Everything", ["ai", "chip"]))
    fake = _FakePipeline(result=_short(tmp_path))
    monkeypatch.setattr(cli, "build_pipeline", lambda config: fake)
    _patch_discovery(monkeypatch, topic=_selected())

    rc = cli.main(["--allow-repeat"])

    assert rc == 0
    assert fake.calls[0][0].title == "This AI Chip Changes Everything"


def test_topic_json_skips_dedupe_but_records(tmp_path, monkeypatch, history_store):
    _seed(history_store, ("This AI Chip Changes Everything", ["ai", "chip"]))
    fake = _FakePipeline(result=_short(tmp_path))
    monkeypatch.setattr(cli, "build_pipeline", lambda config: fake)

    rc = cli.main(["--topic-json", str(_topic_file(tmp_path))])

    assert rc == 0
    assert len(fake.calls) == 1  # generated despite being in history


def test_history_recorded_after_success(tmp_path, monkeypatch, history_store):
    fake = _FakePipeline(result=_short(tmp_path))
    monkeypatch.setattr(cli, "build_pipeline", lambda config: fake)
    _patch_discovery(monkeypatch, topic=_selected())

    rc = cli.main([])

    assert rc == 0
    entries = json.loads(history_store.read_text(encoding="utf-8"))
    assert entries[0]["title"] == "This AI Chip Changes Everything"
    assert entries[0]["keywords"] == ["ai", "chip"]
