"""Tests for Stage 2 connective data models."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from shorts.domain.models import (
    AssetIssue,
    AssetValidationReport,
    GeneratedShort,
    Scene,
    ScenePlan,
    Severity,
    VisualType,
)


def test_scene_requires_positive_duration():
    with pytest.raises(ValidationError):
        Scene(
            index=0,
            narration="hi",
            duration_seconds=0,
            visual_type=VisualType.STOCK_VIDEO,
            visual_query="city",
        )


def test_scene_plan_round_trip():
    plan = ScenePlan(
        scenes=[
            Scene(
                index=0,
                narration="Intro",
                duration_seconds=3.0,
                visual_type=VisualType.GENERATED_IMAGE,
                visual_query="sunrise",
            )
        ],
        total_duration_seconds=3.0,
    )
    restored = ScenePlan.model_validate_json(plan.model_dump_json())
    assert restored == plan
    assert restored.scenes[0].visual_type is VisualType.GENERATED_IMAGE


def test_generated_short_serializes_paths():
    short = GeneratedShort(
        output_dir=Path("output/run"), video_path=Path("output/run/video.mp4")
    )
    data = short.model_dump(mode="json")
    assert data["output_dir"] == "output/run" or data["output_dir"].endswith("run")
    assert short.upload is None


def test_validation_report_with_issue():
    report = AssetValidationReport(
        ok=False,
        issues=[AssetIssue(code="low_res", message="too small", scene_index=2)],
    )
    assert report.issues[0].severity is Severity.ERROR
    assert report.issues[0].scene_index == 2


def test_unknown_field_forbidden():
    with pytest.raises(ValidationError):
        AssetValidationReport(ok=True, bogus=1)
