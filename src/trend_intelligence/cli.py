"""Command-line entry point for Stage 1.

Runs the full pipeline and prints the selected topic with its scoring breakdown.
Use ``--mock-llm`` to run without contacting the NVIDIA NIM API.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .config.settings import AppConfig
from .domain.exceptions import TrendIntelligenceError
from .domain.models import SelectedTopic
from .logging.setup import configure_logging
from .pipeline import build_pipeline, query_from_config


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="trend-discovery",
        description="Discover, rank and select a YouTube Shorts topic.",
    )
    parser.add_argument("--config", help="Path to a config YAML (default: config/default.yaml)")
    parser.add_argument("--region", help="Override region (e.g. US)")
    parser.add_argument("--language", help="Override language (e.g. en)")
    parser.add_argument("--max", type=int, help="Max trends per provider")
    parser.add_argument("--override", help="Manually select a topic by title")
    parser.add_argument(
        "--mock-llm", action="store_true", help="Use the offline mock LLM"
    )
    parser.add_argument(
        "--json", action="store_true", help="Print the selected topic as JSON"
    )
    parser.add_argument("--log-level", default="WARNING", help="Logging level")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    configure_logging(args.log_level, json_logs=True)

    config = AppConfig.load(args.config)
    if args.region:
        config.region = args.region
    if args.language:
        config.language = args.language
    if args.mock_llm:
        config.llm.provider = "mock"

    pipeline = build_pipeline(config)
    query = query_from_config(config, max_trends=args.max)

    try:
        topic = pipeline.run(query, override_title=args.override)
    except TrendIntelligenceError as exc:
        print(f"No topic could be selected: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(topic.model_dump_json(indent=2))
    else:
        _print_topic(topic)
    return 0


def _print_topic(topic: SelectedTopic) -> None:
    ranked = topic.ranked_trend
    agg = ranked.aggregated_trend
    analysis = ranked.analysis

    print("=" * 64)
    print(f"SELECTED TOPIC: {topic.title}")
    print("=" * 64)
    print(f"Score        : {topic.score:.3f}  (rank #{ranked.rank})")
    print(f"Reason       : {topic.selection_reason}")
    print(f"Sources      : {', '.join(s.value for s in agg.sources)}")
    if analysis is not None:
        print(f"Category     : {analysis.recommended_category.value}")
        if analysis.target_audience:
            print(f"Audience     : {analysis.target_audience}")
        if analysis.hooks:
            print(f"Hook         : {analysis.hooks[0]}")
        if analysis.video_angles:
            print(f"Angle        : {analysis.video_angles[0]}")
        if analysis.safety_flags:
            flags = ", ".join(f.value for f in analysis.safety_flags)
            print(f"Safety flags : {flags}")

    top = sorted(ranked.score_breakdown.factors.items(), key=lambda kv: -kv[1])[:5]
    print("Top factors  : " + ", ".join(f"{k}={v:.3f}" for k, v in top))

    if topic.alternatives:
        print("\nAlternatives:")
        for alt in topic.alternatives:
            title = (
                alt.analysis.refined_title
                if alt.analysis
                else alt.aggregated_trend.canonical_title
            )
            print(f"  #{alt.rank}  {alt.final_score:.3f}  {title}")


if __name__ == "__main__":  # python -m trend_intelligence.cli
    raise SystemExit(main())
