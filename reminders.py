"""Event reminder registration and read-only admin listing. No email delivery."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Query, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import database
import models

LOCAL_TZ = ZoneInfo("Europe/Istanbul")


def now_local():
    return datetime.now(LOCAL_TZ)


def event_start(event):
    return datetime.combine(event.date, time.fromisoformat(event.start_time), LOCAL_TZ)


class ReminderRequest(BaseModel):
    email: EmailStr


def build_router(verify_api_key, limiter, require_admin):
    router = APIRouter()

    @router.post("/events/{event_id}/reminders")
    @limiter.limit("10/minute")
    def register_reminder(event_id: str, payload: ReminderRequest, request: Request,
                          token=Depends(verify_api_key), db: Session = Depends(database.get_db)):
        event = db.get(models.Event, event_id)
        if event is None:
            raise HTTPException(404, "Event not found")
        try:
            start = event_start(event)
        except (TypeError, ValueError):
            raise HTTPException(422, "Event start time is invalid")
        if start <= now_local():
            raise HTTPException(400, "Event has already started")
        email = str(payload.email).lower()
        existing = select(models.EventReminder.id).where(
            models.EventReminder.event_id == event_id, models.EventReminder.email == email)
        if db.scalar(existing) is None:
            db.add(models.EventReminder(event_id=event_id, email=email))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                if db.scalar(existing) is None:
                    raise
        return {"success": True}

    @router.get("/admin/reminders")
    def list_reminders(response: Response, page: int = Query(1, ge=1),
                       page_size: int = Query(20, ge=1, le=100),
                       current_user=Depends(require_admin), token=Depends(verify_api_key),
                       db: Session = Depends(database.get_db)):
        response.headers["Cache-Control"] = "private, no-store"
        total = db.scalar(select(func.count()).select_from(models.EventReminder))
        rows = db.execute(select(models.EventReminder, models.Event).join(models.Event)
                          .order_by(models.EventReminder.created_at.desc(), models.EventReminder.id)
                          .offset((page - 1) * page_size).limit(page_size)).all()
        return {"success": True, "data": [reminder_record(r, e) for r, e in rows],
                "pagination": {"page": page, "pageSize": page_size, "total": total,
                               "totalPages": (total + page_size - 1) // page_size}}

    return router



def reminder_record(reminder, event, now=None):
    now = now or now_local()
    try:
        start = event_start(event)
        # Late registrations become due as soon as they are recorded.
        created = reminder.created_at.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)
        due = max(start - timedelta(hours=24), created)
    except (TypeError, ValueError):
        start = due = None
    display_status = reminder.status
    if display_status == "pending":
        if start is None:
            display_status = "invalid_time"
        elif start <= now:
            display_status = "expired"
        elif due > now:
            display_status = "upcoming"
        else:
            display_status = "waiting"
    return {"id": reminder.id, "email": reminder.email, "eventId": event.id,
            "eventTitle": event.title, "eventStart": start.isoformat() if start else None,
            "dueAt": due.isoformat() if due else None, "status": reminder.status,
            "displayStatus": display_status,
            "sentAt": reminder.sent_at.replace(tzinfo=timezone.utc).isoformat() if reminder.sent_at else None,
            "createdAt": reminder.created_at.replace(tzinfo=timezone.utc).isoformat()}
