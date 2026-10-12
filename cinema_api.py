"""Read-only cinema API, isolated from every school event endpoint."""
from datetime import datetime, timedelta
from hashlib import sha256
import unicodedata

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

import database
import models
import schemas


def film_id(title):
    """Stable film page shared by identical titles across venues and sessions."""
    normalized = " ".join(unicodedata.normalize("NFKC", title).casefold().split())
    return sha256(normalized.encode("utf-8")).hexdigest()


class ScreeningResponse(schemas.CamelModel):
    id: str
    film_id: str
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


class FilmResponse(schemas.CamelModel):
    id: str
    title: str
    description: str
    image_url: str | None
    source_url: str
    screenings: list[ScreeningResponse]


class FilmDetailResponse(schemas.ApiResponse):
    data: FilmResponse


def screening_response(row):
    return ScreeningResponse.model_validate({
        field: film_id(row.title) if field == "film_id" else getattr(row, field)
        for field in ScreeningResponse.model_fields
    })


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
        return ScreeningsResponse(success=True, data=[screening_response(row) for row in rows],
            pagination=schemas.PaginationMeta(page=page, page_size=page_size,
                total=total, total_pages=(total + page_size - 1) // page_size))

    @api.get("/films/{movie_id}", response_model=FilmDetailResponse)
    def film(movie_id: str, db: Session = Depends(database.get_db)):
        # Match distinct titles first, then load only this film's sessions.
        # No schema migration or re-scrape is needed for previously imported films.
        titles = [title for title in db.scalars(select(models.CinemaScreening.title).distinct())
                  if film_id(title) == movie_id]
        if not titles:
            raise HTTPException(404, "Film not found")
        rows = db.scalars(select(models.CinemaScreening).where(
            models.CinemaScreening.title.in_(titles)).order_by(
                models.CinemaScreening.starts_at, models.CinemaScreening.venue,
                models.CinemaScreening.id)).all()
        active = [row for row in rows if row.is_active]
        representative = next((row for row in reversed(active or rows) if row.description), rows[-1])
        return FilmDetailResponse(success=True, data=FilmResponse(
            id=movie_id, title=representative.title, description=representative.description,
            image_url=next((row.image_url for row in reversed(active or rows) if row.image_url), None),
            source_url=representative.source_url,
            screenings=[screening_response(row) for row in active]))

    return api
