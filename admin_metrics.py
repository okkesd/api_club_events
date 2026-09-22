"""Admin-only aggregates over complete Istanbul calendar days."""
import datetime as dt
import logging
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

import database
import models as m

ZONE = ZoneInfo("Europe/Istanbul")
KINDS = ("publishedEvents", "eventViews", "newLikes", "newSubscribers", "unsubscribes",
         "newClubs", "newSuggestions", "approvedSuggestions")
METRICS = ("scheduledEvents", "publishedEvents", "eventViews", "averageViewsPerEvent",
           "uniqueVisitors", "newLikes", "newSubscribers", "unsubscribes", "activeClubs",
           "newClubs", "newSuggestions", "approvedSuggestions")
DAILY = ("publishedEvents", "eventViews", "newLikes", "newSubscribers")


def midnight(day):
    return dt.datetime.combine(day, dt.time(), ZONE).astimezone(dt.timezone.utc).replace(tzinfo=None)


def count(db, model, *conditions):
    return db.scalar(select(func.count()).select_from(model).where(*conditions))


def period_data(db, first, end, coverage):
    start_utc, end_utc = midnight(first), midnight(end)
    result = dict.fromkeys(METRICS)
    result["scheduledEvents"] = count(db, m.Event, m.Event.date >= first, m.Event.date < end)
    dates = [first + dt.timedelta(days=i) for i in range((end - first).days)]
    daily = [{"date": day.isoformat(), **dict.fromkeys(DAILY)} for day in dates]
    if coverage is None or coverage > start_utc:
        # Partial history is not a measured zero, even on individually covered days.
        return result, daily, None

    r = m.MetricRecord
    bounds = (r.occurred_at >= start_utc, r.occurred_at < end_utc)
    grouped = dict(db.execute(select(r.kind, func.count()).where(*bounds).group_by(r.kind)).all())
    for kind in KINDS:
        result[kind] = grouped.get(kind, 0)
    for kind in ("newSubscribers", "unsubscribes", "newClubs", "newSuggestions", "approvedSuggestions"):
        result[kind] = db.scalar(select(func.count(func.distinct(r.subject))).where(*bounds, r.kind == kind))
    unique_events, visitors = db.execute(select(func.count(func.distinct(r.event_id)), func.count(func.distinct(r.subject)))
        .where(*bounds, r.kind == "eventViews")).one()
    result["uniqueVisitors"] = visitors
    result["averageViewsPerEvent"] = result["eventViews"] / unique_events if unique_events else 0
    result["activeClubs"] = db.scalar(select(func.count(func.distinct(r.club_id))).where(*bounds, r.kind == "publishedEvents"))

    likes = select(r.event_id, r.subject, func.min(r.occurred_at).label("first_at")).where(
        *bounds, r.kind == "newLikes").group_by(r.event_id, r.subject).subquery()
    result["newLikes"] = db.scalar(select(func.count()).select_from(likes))

    def day_column(column):
        return case(*[( (column >= midnight(day)) & (column < midnight(day + dt.timedelta(days=1))), day.isoformat()) for day in dates])

    for kind in DAILY:
        if kind == "newLikes":
            day = day_column(likes.c.first_at)
            rows = db.execute(select(day, func.count()).select_from(likes).group_by(day))
        else:
            day = day_column(r.occurred_at)
            rows = db.execute(select(day, func.count()).where(*bounds, r.kind == kind).group_by(day))
        values = dict(rows.all())
        for row in daily:
            row[kind] = values.get(row["date"], 0)

    views = select(r.event_id, func.count().label("views")).where(*bounds, r.kind == "eventViews").group_by(r.event_id).subquery()
    like_counts = select(likes.c.event_id, func.count().label("likes")).group_by(likes.c.event_id).subquery()
    top = db.execute(select(m.Event.id, m.Event.title, views.c.views, func.coalesce(like_counts.c.likes, 0).label("likes"))
        .join(views, views.c.event_id == m.Event.id).outerjoin(like_counts, like_counts.c.event_id == m.Event.id)
        .order_by(views.c.views.desc(), m.Event.id.asc()).limit(5)).mappings().all()
    return result, daily, [dict(row) for row in top]


def calculate(db, days=7, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    end = now.astimezone(ZONE).date()
    first, previous = end - dt.timedelta(days=days), end - dt.timedelta(days=days * 2)
    coverage = db.scalar(select(m.MetricCoverage.started_at).where(m.MetricCoverage.name == "history"))
    current, daily, top = period_data(db, first, end, coverage)
    before, _, _ = period_data(db, previous, first, coverage)
    return {
        "period": {"from": first.isoformat(), "to": (end - dt.timedelta(days=1)).isoformat(),
                   "previousFrom": previous.isoformat(), "previousTo": (first - dt.timedelta(days=1)).isoformat(),
                   "timezone": "Europe/Istanbul"},
        "generatedAt": now.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "metrics": {key: {"current": current[key], "previous": before[key]} for key in METRICS},
        "totals": {
            "activeSubscribers": db.scalar(select(func.count(func.distinct(func.lower(func.trim(m.Subscription.email)))))
                .where(m.Subscription.is_active.is_(True))),
            "pendingClubs": count(db, m.User, m.User.role == m.UserRole.CLUB, m.User.is_verified.is_(False)),
            "pendingSuggestions": count(db, m.Suggestion, m.Suggestion.status == "pending"),
            "pendingScrapedEvents": count(db, m.ScrapedEvent, m.ScrapedEvent.status == m.ScrapedEventStatus.PENDING,
                                          m.ScrapedEvent.source == "instagram", m.ScrapedEvent.kind == "event"),
        },
        "daily": daily, "topEvents": top if top is not None else [],
    }


def build_router(require_admin, verify_api_key):
    router = APIRouter()

    @router.get("/admin/metrics")
    def metrics(days: int = Query(7, ge=7, le=7), admin=Depends(require_admin),
                token=Depends(verify_api_key), db: Session = Depends(database.get_db)):
        try:
            return JSONResponse({"success": True, "data": calculate(db, days)},
                                headers={"Cache-Control": "private, no-store"})
        except Exception:
            db.rollback()
            logging.getLogger(__name__).exception("Failed to calculate admin metrics")
            raise HTTPException(500, "Could not calculate metrics")

    return router
