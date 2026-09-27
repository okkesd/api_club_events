"""Public sidebar statistics, independent of event-list filters."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

import database
import models
from event_categories import EventCategory, effective_category

LOCAL_TZ = ZoneInfo("Europe/Istanbul")


def now_local():
    return datetime.now(LOCAL_TZ)


class HighlightEvent(BaseModel):
    id: str
    title: str
    date: date
    startTime: str
    likes: int
    coverImage: str | None
    location: str
    category: EventCategory | None


class HighlightsData(BaseModel):
    timezone: str
    weekStart: date
    weekEnd: date
    weeklyEventCount: int
    popularEvents: list[HighlightEvent]
    nextEvent: HighlightEvent | None


class HighlightsResponse(BaseModel):
    success: bool
    data: HighlightsData


def event_card(event):
    return HighlightEvent(id=event.id, title=event.title, date=event.date,
                          startTime=event.start_time, likes=event.likes or 0,
                          coverImage=event.cover_image, location=event.location, category=effective_category(event))


def highlights(db, now=None):
    now = (now or now_local()).astimezone(LOCAL_TZ)
    first = now.date() - timedelta(days=now.weekday())
    end = first + timedelta(days=7)
    e = models.Event
    week = (e.date >= first, e.date < end)
    total = db.scalar(select(func.count()).select_from(e).where(*week))
    popular = db.scalars(select(e).where(*week, e.likes > 0)
                         .order_by(e.likes.desc(), e.date, e.start_time, e.id).limit(3)).all()
    # Event start times are stored as zero-padded HH:MM local time.
    upcoming = or_(e.date > now.date(),
                   (e.date == now.date()) & (e.start_time > now.strftime("%H:%M")))
    next_event = db.scalars(select(e).where(upcoming)
                           .order_by(e.date, e.start_time, e.id).limit(1)).first()
    return HighlightsData(timezone="Europe/Istanbul", weekStart=first,
                          weekEnd=end - timedelta(days=1), weeklyEventCount=total,
                          popularEvents=[event_card(row) for row in popular],
                          nextEvent=event_card(next_event) if next_event else None)


def build_router(verify_api_key):
    router = APIRouter()

    @router.get("/events/highlights", response_model=HighlightsResponse)
    def get_highlights(response: Response, token=Depends(verify_api_key),
                       db: Session = Depends(database.get_db)):
        response.headers["Cache-Control"] = "no-store"
        return HighlightsResponse(success=True, data=highlights(db))

    return router
