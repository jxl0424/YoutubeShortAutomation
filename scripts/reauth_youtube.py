#!/usr/bin/env python
"""Mint a fresh, durable YouTube upload OAuth token (offline + forced consent).

Runs ONLY the OAuth flow — no pipeline, no rendering — so re-authing takes a few
seconds. Unlike the inline flow in
``src/shorts/providers/upload/youtube.py``, this passes ``prompt="consent"`` so
Google always returns a *refresh* token (without it, re-authing an already-
consented account can hand back a token with no refresh_token, which then dies in
~1 hour). Publish the OAuth consent screen to "In production" first so the
refresh token doesn't expire after 7 days.

Usage (from the repo root, with the venv):
    .venv/Scripts/python.exe scripts/reauth_youtube.py

Reads the client-secrets path from ``YOUTUBE_CLIENT_SECRETS`` (or falls back to
.secrets/client_secrets.json) and writes the token to .secrets/youtube_token.json
(override with ``YOUTUBE_TOKEN_PATH``). Paste that file's contents into the
``YOUTUBE_TOKEN_JSON`` GitHub Actions secret afterwards.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Must match _SCOPES in src/shorts/providers/upload/youtube.py.
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CLIENT_SECRETS = ROOT / ".secrets" / "client_secrets.json"
DEFAULT_TOKEN_PATH = ROOT / ".secrets" / "youtube_token.json"


def main() -> int:
    load_dotenv()

    client_secrets = Path(
        os.getenv("YOUTUBE_CLIENT_SECRETS") or DEFAULT_CLIENT_SECRETS
    )
    token_path = Path(os.getenv("YOUTUBE_TOKEN_PATH") or DEFAULT_TOKEN_PATH)

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
            "Install the 'youtube' extra first: "
            'pip install -e ".[youtube]"',
            file=sys.stderr,
        )
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), SCOPES)
    # offline + consent => Google always returns a durable refresh token.
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
        "YOUTUBE_TOKEN_JSON GitHub Actions secret, then re-run the workflow."
    )
    return 0 if has_refresh else 1


if __name__ == "__main__":
    raise SystemExit(main())
