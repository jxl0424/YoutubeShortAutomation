#!/usr/bin/env python
"""Thin wrapper so the pipeline can be run as a script.

Equivalent to ``python -m trend_intelligence.cli`` (or the installed
``trend-discovery`` console command).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running directly from a checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trend_intelligence.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
