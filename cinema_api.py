"""Read-only cinema API, isolated from every school event endpoint."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

import database
import models
import schemas


class ScreeningResponse(schemas.CamelModel):
    id: str
    title: str
    venue: str
    starts_at: datetime
    ends_at: datetime | None
    description: str
    image_url: str | None
    source_url: str
    ticket_url: str | None
    auditorium: str | None
    last_seen_at: datetime


class ScreeningsResponse(schemas.ApiResponse):
    data: list[ScreeningResponse]
    pagination: schemas.PaginationMeta


def router(verify_api_key):
    api = APIRouter(prefix="/sinefil", dependencies=[Depends(verify_api_key)])

    @api.get("/screenings", response_model=ScreeningsResponse)
    def screenings(week: str, page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=100),
                   db: Session = Depends(database.get_db)):
        try:
            start = datetime.strptime(week, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(422, "week must be YYYY-MM-DD")
        start -= timedelta(days=start.weekday())
        query = select(models.CinemaScreening).where(models.CinemaScreening.is_active.is_(True),
            models.CinemaScreening.starts_at >= start,
            models.CinemaScreening.starts_at < start + timedelta(days=7))
        total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = db.scalars(query.order_by(models.CinemaScreening.starts_at,
            models.CinemaScreening.venue, models.CinemaScreening.id)
            .offset((page - 1) * page_size).limit(page_size)).all()
        return ScreeningsResponse(success=True, data=[ScreeningResponse.model_validate(row) for row in rows],
            pagination=schemas.PaginationMeta(page=page, page_size=page_size,
                total=total, total_pages=(total + page_size - 1) // page_size))

    return api
