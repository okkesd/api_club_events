"""Validated suggestion input and camelCase API contracts."""
import datetime as dt
import re
from typing import Literal
from pydantic import ConfigDict, EmailStr, Field, HttpUrl, field_validator
from schemas import CamelModel
from models import AnnouncementCategory, LocationType


class Content(CamelModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=10000)
    date: dt.date | None = None
    start_time: str | None = None
    end_time: str | None = None
    location: str | None = Field(None, max_length=500)
    organizer: str | None = Field(None, max_length=500)
    link: HttpUrl | None = Field(None, max_length=2048)
    category: AnnouncementCategory | None = None
    expires_at: dt.date | None = None

    @field_validator("*", mode="before")
    @classmethod
    def strip_text(cls, value):
        return (value.strip() or None) if isinstance(value, str) else value

    @field_validator("date", "expires_at", mode="before")
    @classmethod
    def strict_date(cls, value):
        if value is not None and not isinstance(value, dt.date):
            if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError("Use YYYY-MM-DD")
        return value

    @field_validator("start_time", "end_time")
    @classmethod
    def valid_time(cls, value):
        if value is not None and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("Use HH:MM (00:00–23:59)")
        return value


class Submission(Content):
    kind: Literal["event", "announcement"]
    email: EmailStr | None = None


class Edit(Content):
    kind: Literal["event", "announcement"] | None = None

    @field_validator("kind")
    @classmethod
    def nonnull_kind(cls, value):
        if value is None:
            raise ValueError("kind cannot be null")
        return value


class Review(Submission):
    id: str
    status: Literal["pending", "approved", "rejected"]
    image_url: str | None
    created_at: dt.datetime
    updated_at: dt.datetime
    reviewed_at: dt.datetime | None
    reviewed_by: str | None
    rejection_reason: str | None
    created_event_id: str | None
    created_announcement_id: str | None


class Approve(CamelModel):
    model_config = ConfigDict(extra="forbid")
    club_id: str | None = None
    publish_as_admin: bool = False
    location_type: LocationType = LocationType.ON_CAMPUS


class Reject(CamelModel):
    rejection_reason: str | None = Field(None, max_length=2000)


class Extract(CamelModel):
    model_config = ConfigDict(extra="forbid")
    image: str = Field(max_length=7 * 1024 * 1024)
    kind: Literal["event", "announcement"]
