"""Typed containers for the weekly report (mirrors shorts.domain.models style)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChannelSnapshot(_Model):
    """Lifetime totals from the Data API ``channels.list`` statistics."""

    title: str = ""
    subscribers: int = 0
    total_views: int = 0
    video_count: int = 0


class WeekMetrics(_Model):
    """One week of channel metrics from the Analytics API."""

    start: date
    end: date
    views: int = 0
    watch_minutes: int = 0
    average_view_duration_seconds: float = 0.0
    average_view_percentage: float = 0.0
    subscribers_gained: int = 0
    subscribers_lost: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0

    @property
    def net_subscribers(self) -> int:
        return self.subscribers_gained - self.subscribers_lost


class VideoStat(_Model):
    """Per-video performance within the report week."""

    video_id: str
    title: str = ""
    views: int = 0
    average_view_percentage: float = 0.0
    likes: int = 0


class WeeklyReport(_Model):
    """Everything the renderer needs, already fetched."""

    channel: ChannelSnapshot
    this_week: WeekMetrics
    last_week: WeekMetrics
    top_videos: list[VideoStat] = Field(default_factory=list)
