"""Publish complete scraped events through the existing approval transaction."""
import logging

import event_verification
import models
import schemas

log = logging.getLogger(__name__)


def completeness_errors(db, row):
    errors = event_verification.mandatory_errors(row, event_verification.snapshot(db, row))
    if (event_verification.status_value(row) != "pending"
            or row.created_event_id or row.created_announcement_id):
        errors.append("not_pending")
    return errors


def approve_complete_events(db, ids):
    """A failure leaves the committed candidate available for manual review."""
    for scraped_id in ids:
        try:
            row = db.get(models.ScrapedEvent, scraped_id)
            if row is None or completeness_errors(db, row):
                continue
            from main import publish_scraped_event, revalidate_frontend
            publish_scraped_event(db, scraped_id, schemas.ScrapedEventApprove(),
                                 current_user=None, auto_approve_complete=True)
            revalidate_frontend(["events"])
        except Exception as exc:
            db.rollback()
            log.warning("Complete scraped event approval deferred for %s (%s)",
                        scraped_id, type(exc).__name__)
