"""Command-line entry point for Stage 2.

Runs Stage 1 trend discovery, then generates an upload-ready Short from the
selected topic. Use ``--topic-json`` to reuse a topic saved with
``trend-discovery --json`` instead of re-running discovery.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from trend_intelligence.config.settings import AppConfig
from trend_intelligence.domain.exceptions import TrendIntelligenceError
from trend_intelligence.domain.models import SelectedTopic
from trend_intelligence.logging.setup import configure_logging
from trend_intelligence.pipeline import build_pipeline as build_discovery_pipeline
from trend_intelligence.pipeline import query_from_config

from .config.settings import ShortsConfig
from .domain.exceptions import ShortsError
from .domain.models import GeneratedShort
from .pipeline import build_pipeline


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="shorts-generate",
        description="Generate an upload-ready YouTube Short from a trending topic.",
    )
    parser.add_argument(
        "--config", help="Path to the Stage 2 config YAML (default: config/shorts.yaml)"
    )
    parser.add_argument(
        "--stage1-config",
        help="Path to the Stage 1 config YAML (default: config/default.yaml)",
    )
    parser.add_argument(
        "--topic-json",
        help="Load the topic from a JSON file (saved via `trend-discovery --json`) "
        "instead of running discovery",
    )
    parser.add_argument("--override", help="Manually select a topic by title")
    parser.add_argument(
        "--mock-llm",
        action="store_true",
        help="Use the offline mock LLM for discovery",
    )
    parser.add_argument(
        "--work-dir",
        help="Directory for the generated package (default: output/<slug>-<timestamp>)",
    )
    parser.add_argument(
        "--json", action="store_true", help="Print the generated package as JSON"
    )
    parser.add_argument("--log-level", default="WARNING", help="Logging level")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    configure_logging(args.log_level, json_logs=True)

    try:
        config = ShortsConfig.load(args.config)
    except ShortsError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    if args.topic_json:
        try:
            topic = _load_topic(Path(args.topic_json))
        except (OSError, ValueError) as exc:
            print(
                f"Could not load topic from {args.topic_json}: {exc}", file=sys.stderr
            )
            return 1
    else:
        try:
            topic = _discover_topic(args)
        except TrendIntelligenceError as exc:
            print(f"No topic could be selected: {exc}", file=sys.stderr)
            return 1

    # Progress goes to stderr so stdout stays clean for --json.
    print(f"Topic: {topic.title}  (score {topic.score:.3f})", file=sys.stderr)
    print("Generating short... (this can take a few minutes)", file=sys.stderr)

    work_dir = Path(args.work_dir) if args.work_dir else None
    try:
        short = build_pipeline(config).generate(topic, work_dir=work_dir)
    except ShortsError as exc:
        print(f"Generation failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(short.model_dump_json(indent=2))
    else:
        _print_short(short, topic.title)
    return 0


def _load_topic(path: Path) -> SelectedTopic:
    # pydantic ValidationError subclasses ValueError, so the caller's
    # (OSError, ValueError) handler covers bad JSON and bad shapes alike.
    return SelectedTopic.model_validate_json(path.read_text(encoding="utf-8"))


def _discover_topic(args: argparse.Namespace) -> SelectedTopic:
    config = AppConfig.load(args.stage1_config)
    if args.mock_llm:
        config.llm.provider = "mock"
    pipeline = build_discovery_pipeline(config)
    return pipeline.run(query_from_config(config), override_title=args.override)


def _print_short(short: GeneratedShort, title: str) -> None:
    print("=" * 64)
    print(f"GENERATED SHORT: {title}")
    print("=" * 64)
    print(f"Output dir : {short.output_dir}")
    rows = [
        ("Video", short.video_path),
        ("Thumbnail", short.thumbnail_path),
        ("Captions", short.captions_path),
        ("Metadata", short.metadata_path),
        ("Script", short.script_path),
    ]
    for label, path in rows:
        if path is not None:
            print(f"{label:<11}: {path}")
    if short.upload is not None and short.upload.uploaded:
        print(f"{'Upload':<11}: {short.upload.url or short.upload.video_id}")
    else:
        print(f"{'Upload':<11}: skipped")


if __name__ == "__main__":  # python -m shorts.cli
    raise SystemExit(main())
