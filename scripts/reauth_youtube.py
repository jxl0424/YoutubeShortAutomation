#!/usr/bin/env python
"""Mint a fresh, durable YouTube OAuth token (offline + forced consent).

Runs ONLY the OAuth flow — no pipeline, no rendering — so re-authing takes a few
seconds. Unlike the inline flows in the providers, this passes
``prompt="consent"`` so Google always returns a *refresh* token (without it,
re-authing an already-consented account can hand back a token with no
refresh_token, which then dies in ~1 hour). Publish the OAuth consent screen to
"In production" first so the refresh token doesn't expire after 7 days.

Two independent tokens, selected with ``--scopes``:

* ``upload`` (default) — the narrow ``youtube.upload`` scope used to publish.
* ``report`` — the two READ-ONLY scopes the weekly report needs. Kept separate
  so the upload token's narrow scope stays untouched. Needs the YouTube
  Analytics API enabled in the same Google Cloud project.

Usage (from the repo root, with the venv):
    .venv/Scripts/python.exe scripts/reauth_youtube.py
    .venv/Scripts/python.exe scripts/reauth_youtube.py --scopes report

Reads the client-secrets path from ``YOUTUBE_CLIENT_SECRETS`` (or falls back to
.secrets/client_secrets.json). Paste the written file's contents into the
GitHub Actions secret the script names when it finishes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Must match _SCOPES in the matching provider: upload ->
# src/shorts/providers/upload/youtube.py, report ->
# src/shorts/analytics/provider.py.
SCOPE_SETS = {
    "upload": {
        "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
        "token_name": "youtube_token.json",
        "secret": "YOUTUBE_TOKEN_JSON",
    },
    "report": {
        "scopes": [
            "https://www.googleapis.com/auth/youtube.readonly",
            "https://www.googleapis.com/auth/yt-analytics.readonly",
        ],
        "token_name": "youtube_report_token.json",
        "secret": "YOUTUBE_REPORT_TOKEN_JSON",
    },
}

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CLIENT_SECRETS = ROOT / ".secrets" / "client_secrets.json"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mint a durable YouTube OAuth token (upload or report)."
    )
    parser.add_argument(
        "--scopes",
        choices=sorted(SCOPE_SETS),
        default="upload",
        help="Which token to mint (default: upload)",
    )
    parser.add_argument("--token-path", help="Override where the token is written")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    load_dotenv()

    scope_set = SCOPE_SETS[args.scopes]
    scopes = scope_set["scopes"]

    client_secrets = Path(os.getenv("YOUTUBE_CLIENT_SECRETS") or DEFAULT_CLIENT_SECRETS)
    if args.token_path:
        token_path = Path(args.token_path)
    else:
        # YOUTUBE_TOKEN_PATH predates --scopes and means the *upload* token;
        # honouring it for the report token would overwrite the wrong file.
        override = os.getenv("YOUTUBE_TOKEN_PATH") if args.scopes == "upload" else None
        token_path = Path(override or ROOT / ".secrets" / scope_set["token_name"])

    if not client_secrets.exists():
        print(
            f"Client secrets not found at {client_secrets}.\n"
            "Set YOUTUBE_CLIENT_SECRETS or place the file at "
            f"{DEFAULT_CLIENT_SECRETS}.",
            file=sys.stderr,
        )
        return 1

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print(
            "Install the 'youtube' extra first: pip install -e \".[youtube]\"",
            file=sys.stderr,
        )
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), scopes)
    # offline + consent => Google always returns a durable refresh token.
    print(f"Requesting the '{args.scopes}' scopes: {', '.join(scopes)}")
    print("Opening a browser for Google consent... approve the account.")
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")

    has_refresh = bool(getattr(creds, "refresh_token", None))
    print(f"\nToken written to {token_path}")
    if has_refresh:
        print("refresh_token: PRESENT  ->  this token can refresh indefinitely.")
    else:
        print(
            "refresh_token: MISSING  ->  NOT durable. Revoke the app's access at\n"
            "https://myaccount.google.com/permissions and run this script again.",
            file=sys.stderr,
        )

    # Sanity-check what we actually wrote (never prints secret values).
    data = json.loads(token_path.read_text(encoding="utf-8"))
    print(
        "Contains keys:",
        ", ".join(k for k in ("refresh_token", "token", "client_id") if data.get(k)),
    )
    print(
        "\nNext: copy the FULL contents of the file above into the "
        f"{scope_set['secret']} GitHub Actions secret, then re-run the workflow."
    )
    return 0 if has_refresh else 1


if __name__ == "__main__":
    raise SystemExit(main())
