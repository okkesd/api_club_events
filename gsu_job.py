"""Daily GSÜ import entry point, executed inside the running backend container."""
import logging
import os
import traceback

from sqlalchemy import select, func

import database
import models
import gsu_import
import scraped_auto_approval
from post_sources import GSU_SOURCE

log = logging.getLogger(__name__)


def run(db):
    email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    if not email:
        raise gsu_import.GSUImportError("ADMIN_EMAIL is missing from the backend container")
    publisher = db.scalar(select(models.User).where(
        func.lower(models.User.email) == email,
        models.User.role == models.UserRole.ADMIN))
    if publisher is None:
        raise gsu_import.GSUImportError("ADMIN_EMAIL does not match an existing admin account in the configured database")
    log.info("GSÜ daily import started")
    stats = gsu_import.import_gsu_events(db, publisher, limit=20)
    pending = db.scalars(select(models.ScrapedEvent).where(
        models.ScrapedEvent.source == GSU_SOURCE,
        models.ScrapedEvent.status == models.ScrapedEventStatus.PENDING)).all()
    failed_publications = sum(not scraped_auto_approval.completeness_errors(db, row) for row in pending)
    log.info("GSÜ daily import finished: imported=%d skipped=%d pending=%d publication_failures=%d",
        stats.imported, stats.skipped, len(pending), failed_publications)
    if failed_publications:
        raise RuntimeError("Complete GSÜ records remain pending; inspect publication errors")
    return stats


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        # Initializes the existing schema/migrations and shared publishing helpers.
        # Running in the backend container uses its current image and environment.
        import main as backend  # noqa: F401
        with database.SessionLocal() as db:
            run(db)
    except Exception as exc:
        # Curated importer errors contain no credentials or raw response data.
        if isinstance(exc, gsu_import.GSUImportError):
            log.error("GSÜ daily import failed: %s", exc)
        else:
            # Show the failing code location, without arbitrary exception text,
            # source lines or local variables that could contain credentials.
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            log.error("GSÜ daily import failed (%s) at %s:%d (%s)",
                type(exc).__name__, os.path.basename(frame.filename), frame.lineno, frame.name)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
