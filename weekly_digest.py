"""
Weekly Digest Email Script

Run this as a cron job (e.g., every Monday at 8 AM):
    0 8 * * 1 cd /app && python weekly_digest.py

Requires SMTP env vars:
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM_EMAIL
    FRONTEND_URL (for links in the email)
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import select
from database import SessionLocal
import models

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


def get_upcoming_events(db, days=7):
    """Get events happening in the next N days."""
    today = datetime.now().date()
    end_date = today + timedelta(days=days)

    query = (
        select(models.Event)
        .where(models.Event.date >= today)
        .where(models.Event.date <= end_date)
        .order_by(models.Event.date.asc())
    )
    return db.execute(query).scalars().all()


def get_active_subscribers(db):
    """Get all active subscribers."""
    query = select(models.Subscription).where(models.Subscription.is_active == True)
    return db.execute(query).scalars().all()


def filter_events_for_subscriber(events, subscriber):
    """Filter events based on subscriber preferences (uses ClubSubscription relationship)."""
    sub_club_ids = set(
        cs.club_id for cs in subscriber.club_subscriptions if cs.is_active
    )
    sub_categories = set(
        cs.category.value if hasattr(cs.category, 'value') else cs.category
        for cs in subscriber.category_subscriptions if cs.is_active
    )

    # If no preferences set, send all events
    if not sub_club_ids and not sub_categories:
        return events

    filtered = []
    for event in events:
        event_tags = set(
            t.strip().lower() for t in event.tags.split(",") if t.strip()
        ) if event.tags else set()

        # Match by club
        if sub_club_ids and event.club_id in sub_club_ids:
            filtered.append(event)
            continue

        # Match by category/tag overlap
        if sub_categories and sub_categories & event_tags:
            filtered.append(event)
            continue

    return filtered


def build_email_html(events, unsubscribe_token):
    """Build the HTML email body."""
    unsubscribe_url = f"{FRONTEND_URL}/unsubscribe/{unsubscribe_token}"

    if not events:
        return f"""
        <html><body style="font-family: Arial, sans-serif; color: #333;">
        <h2>This Week at Campus</h2>
        <p>No upcoming events this week. Check back soon!</p>
        <hr>
        <p style="font-size: 12px; color: #888;">
            <a href="{unsubscribe_url}">Unsubscribe</a>
        </p>
        </body></html>
        """

    event_rows = ""
    for e in events:
        event_url = f"{FRONTEND_URL}/events/{e.id}"
        event_rows += f"""
        <tr>
            <td style="padding: 12px; border-bottom: 1px solid #eee;">
                <a href="{event_url}" style="font-size: 16px; font-weight: bold; color: #1a73e8; text-decoration: none;">
                    {e.title}
                </a>
                <br>
                <span style="color: #666; font-size: 14px;">
                    {e.date.strftime('%A, %B %d')} &middot; {e.start_time} - {e.end_time}
                    &middot; {e.location}
                </span>
            </td>
        </tr>
        """

    return f"""
    <html><body style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto;">
    <h2>This Week at Campus</h2>
    <p>Here are the upcoming events for this week:</p>
    <table style="width: 100%; border-collapse: collapse;">
        {event_rows}
    </table>
    <br>
    <a href="{FRONTEND_URL}/events"
       style="display: inline-block; padding: 10px 20px; background: #1a73e8; color: white; text-decoration: none; border-radius: 4px;">
        View All Events
    </a>
    <hr style="margin-top: 30px;">
    <p style="font-size: 12px; color: #888;">
        You are receiving this because you subscribed to event updates.
        <a href="{unsubscribe_url}">Unsubscribe</a>
    </p>
    </body></html>
    """


def send_email(to_email, subject, html_body):
    """Send an email via SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM_EMAIL
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM_EMAIL, to_email, msg.as_string())


def run_digest():
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD, SMTP_FROM_EMAIL]):
        logger.error("SMTP not configured. Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD, SMTP_FROM_EMAIL")
        return

    db = SessionLocal()
    try:
        events = get_upcoming_events(db)
        subscribers = get_active_subscribers(db)

        logger.info(f"Found {len(events)} upcoming events, {len(subscribers)} active subscribers")

        sent = 0
        failed = 0

        for sub in subscribers:
            relevant_events = filter_events_for_subscriber(events, sub)
            html = build_email_html(relevant_events, sub.token)
            subject = f"This Week at Campus - {len(relevant_events)} upcoming events"

            try:
                send_email(sub.email, subject, html)
                sent += 1
                logger.info(f"Sent digest to {sub.email} ({len(relevant_events)} events)")
            except Exception as e:
                failed += 1
                logger.error(f"Failed to send to {sub.email}: {e}")

        logger.info(f"Digest complete: {sent} sent, {failed} failed")

    finally:
        db.close()


if __name__ == "__main__":
    run_digest()
