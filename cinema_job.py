"""Daily server import; --dry-run fetches calendars without opening the database."""
import argparse
from datetime import datetime, timedelta
import logging

from cinema_scraper import CalendarClient, VENUES, HORIZON_DAYS, ISTANBUL, scrape

log = logging.getLogger(__name__)


def sync_source(db, venue, screenings, now):
    import models
    from sqlalchemy import select

    existing = {row.source_id: row for row in db.scalars(select(models.CinemaScreening).where(
        models.CinemaScreening.source == venue.source)).all()}
    imported = updated = cancelled = 0
    seen = set()
    cutoff = (now + timedelta(days=HORIZON_DAYS)).replace(hour=0, minute=0, second=0, microsecond=0)
    for screening in screenings:
        seen.add(screening.source_id)
        row = existing.get(screening.source_id)
        if row is None:
            row = models.CinemaScreening(source=venue.source, source_id=screening.source_id)
            db.add(row)
            existing[screening.source_id] = row
            imported += 1
        else:
            updated += 1
        for field in ("title", "starts_at", "ends_at", "description", "image_url",
                      "source_url", "ticket_url", "auditorium"):
            setattr(row, field, getattr(screening, field))
        row.venue, row.is_active, row.last_seen_at = venue.name, True, now
    for source_id, row in existing.items():
        if (source_id not in seen and row.is_active and
                now <= row.starts_at < cutoff):
            row.is_active = False
            cancelled += 1
    db.commit()
    return imported, updated, cancelled


def run(db=None, client=None, now=None, dry_run=False):
    now = now or datetime.now(ISTANBUL).replace(tzinfo=None)
    own_client = client is None
    client = client or CalendarClient()
    failures = []
    try:
        for venue in VENUES:
            try:
                screenings = scrape(venue, client, now)
                if dry_run:
                    log.info("%s: upcoming_screenings=%d", venue.source, len(screenings))
                else:
                    imported, updated, cancelled = sync_source(db, venue, screenings, now)
                    log.info("%s: imported=%d updated=%d cancelled=%d", venue.source,
                             imported, updated, cancelled)
            except Exception as exc:
                if db is not None:
                    db.rollback()
                failures.append(venue.source)
                # Do not leak environment/connection details through exception messages.
                log.error("%s: import failed (%s); previous schedule retained",
                          venue.source, type(exc).__name__)
    finally:
        if own_client:
            client.close()
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.dry_run:
        return int(bool(run(dry_run=True)))
    try:
        import database
        import models
        models.CinemaScreening.__table__.create(database.engine, checkfirst=True)
        with database.SessionLocal() as db:
            return int(bool(run(db)))
    except Exception as exc:
        log.error("Cinema job failed (%s)", type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
