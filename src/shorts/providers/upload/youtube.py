"""YouTube upload provider (YouTube Data API v3).

Uploads the rendered video and sets the thumbnail. OAuth runs once (browser
consent) and caches a token. google-api-python-client / google-auth-oauthlib are
lazy-imported and installed via the optional ``youtube`` extra; the API client
is injectable so tests never touch Google.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from trend_intelligence.logging.setup import get_logger

from ...domain.exceptions import UploadError
from ...domain.interfaces import UploadProvider
from ...domain.models import GeneratedShort, UploadResult, VideoMetadata

_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


class YouTubeUploadProvider(UploadProvider):
    name: ClassVar[str] = "youtube"

    def __init__(
        self,
        *,
        client_secrets_path: str | None = None,
        token_path: str = ".secrets/youtube_token.json",
        privacy: str = "private",
        category_id: str = "22",
        contains_synthetic_media: bool = True,
        made_for_kids: bool = False,
        build_service: Callable[[], Any] | None = None,
        media_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self._client_secrets_path = client_secrets_path
        self._token_path = Path(token_path)
        self._privacy = privacy
        self._category_id = category_id
        self._contains_synthetic_media = contains_synthetic_media
        self._made_for_kids = made_for_kids
        self._build_service = build_service
        self._media_factory = media_factory or self._default_media
        self._logger = get_logger("shorts.upload")

    def _default_media(self, path: str) -> Any:
        from googleapiclient.http import MediaFileUpload

        return MediaFileUpload(path, resumable=True)

    def _service(self) -> Any:
        if self._build_service is not None:
            return self._build_service()
        if (
            not self._client_secrets_path
            or not Path(self._client_secrets_path).exists()
        ):
            raise UploadError(
                "YouTube client secrets not found (set YOUTUBE_CLIENT_SECRETS)"
            )
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise UploadError(
                "install the 'youtube' extra for upload support: pip install -e '.[youtube]'"
            ) from exc

        creds = None
        if self._token_path.exists():
            creds = Credentials.from_authorized_user_file(
                str(self._token_path), _SCOPES
            )
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self._client_secrets_path, _SCOPES
                )
                creds = flow.run_local_server(port=0)
            self._token_path.parent.mkdir(parents=True, exist_ok=True)
            self._token_path.write_text(creds.to_json(), encoding="utf-8")
        return build("youtube", "v3", credentials=creds)

    def upload(
        self,
        package: GeneratedShort,
        metadata: VideoMetadata,
        *,
        privacy: str | None = None,
    ) -> UploadResult:
        if package.video_path is None or not Path(package.video_path).exists():
            raise UploadError("no rendered video to upload")

        service = self._service()
        description = metadata.description
        if metadata.hashtags:
            description = f"{description}\n\n{' '.join(metadata.hashtags)}"
        body = {
            "snippet": {
                "title": metadata.title[:100],
                "description": description,
                "tags": metadata.tags,
                "categoryId": self._category_id,
            },
            "status": {
                "privacyStatus": privacy or self._privacy,
                "selfDeclaredMadeForKids": self._made_for_kids,
                "containsSyntheticMedia": self._contains_synthetic_media,
            },
        }

        try:
            request = service.videos().insert(
                part="snippet,status",
                body=body,
                media_body=self._media_factory(str(package.video_path)),
            )
            response = request.execute()
        except UploadError:
            raise
        except Exception as exc:
            raise UploadError(f"youtube upload failed: {exc}") from exc

        video_id = response.get("id")
        status = (response.get("status") or {}).get("uploadStatus", "uploaded")

        if package.thumbnail_path and Path(package.thumbnail_path).exists():
            try:
                service.thumbnails().set(
                    videoId=video_id,
                    media_body=self._media_factory(str(package.thumbnail_path)),
                ).execute()
            except Exception as exc:
                self._logger.warning("thumbnail_upload_failed", error=str(exc))

        self._logger.info(
            "uploaded",
            video_id=video_id,
            status=status,
            privacy=privacy or self._privacy,
        )
        return UploadResult(
            uploaded=True,
            video_id=video_id,
            # The /shorts/ URL: youtu.be/<id> opens the regular watch player
            # even for Shorts, which reads as "it didn't upload as a Short".
            url=f"https://www.youtube.com/shorts/{video_id}" if video_id else None,
            status=status,
        )
