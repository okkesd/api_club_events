"""Read GSÜ's public calendar and detail pages into the existing review inbox."""
from dataclasses import dataclass
from datetime import datetime
import json
import logging
import re
import time
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import requests
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import models
import schemas
import scraped_auto_approval
from post_sources import GSU_SOURCE, is_gsu_event_url

BASE = "https://gsu.edu.tr"
LIST_URL = BASE + "/tr/duyurular/kategori/etkinlik"
FALLBACK_DESCRIPTION = "Okul etkinliğidir."
log = logging.getLogger(__name__)


class GSUImportError(ValueError):
    """Curated diagnostic text that is safe to write to the server journal."""


@dataclass
class SchoolEvent:
    source_id: str
    url: str
    title: str
    start: datetime
    end: datetime | None
    location: str | None
    description: str
    original_description: str
    image_url: str | None


def calendar_entries(html):
    match = re.search(r"\bconst\s+cdata\s*=\s*(\[.*?\])\s*;", html, re.S)
    if not match:
        raise GSUImportError("GSÜ calendar structure changed")
    try:
        entries = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise GSUImportError("GSÜ calendar contains invalid JSON") from exc
    if not isinstance(entries, list):
        raise GSUImportError("Invalid GSÜ calendar")
    return entries


def parse_detail(html, url):
    if not is_gsu_event_url(url):
        raise GSUImportError("Invalid GSÜ event URL")
    soup = BeautifulSoup(html, "html.parser")
    title = soup.select_one(".post-title")
    content = soup.select_one(".post-excerpt")
    info = soup.select_one(".bq-event-detail")
    if not title or not content or not info:
        raise GSUImportError("GSÜ detail structure changed")
    values = {}
    for label in info.select("strong"):
        name = label.get_text(" ", strip=True).rstrip(":")
        values[name] = label.parent.get_text(" ", strip=True).split(":", 1)[-1].strip()

    def timestamp(name):
        value = values.get(name)
        try:
            return datetime.strptime(value, "%d.%m.%Y %H.%M") if value else None
        except ValueError as exc:
            raise GSUImportError("GSÜ detail datetime format is invalid") from exc

    start = timestamp("Başlangıç Tarihi ve Saati")
    end = timestamp("Bitiş Tarihi ve Saati")
    if not start or not title.get_text(strip=True):
        raise GSUImportError("Missing GSÜ title or start datetime")
    if end and end <= start:
        raise GSUImportError("Invalid GSÜ end datetime")

    image_url = None
    for image in content.select("img"):
        candidate = urljoin(url, image.get("src") or image.get("data-src") or "")
        parsed = urlsplit(candidate)
        if (parsed.scheme == "https" and parsed.netloc in ("gsu.edu.tr", "dosya2.gsu.edu.tr")
                and parsed.path.startswith("/event/")):
            image_url = candidate
            break
    # Restrict description to the article; exclude metadata, images and site navigation.
    for node in content.select(".bq-event-detail, script, style, iframe, form, img"):
        node.decompose()
    for anchor in content.select("a[href]"):
        href = urljoin(url, anchor["href"])
        text = anchor.get_text(" ", strip=True)
        if urlsplit(href).scheme in ("http", "https") and href != text:
            anchor.replace_with(f"{text} ({href})")
    paragraphs = [re.sub(r"\s+([,.;:!?])", r"\1", node.get_text(" ", strip=True)) for node in content.children
                  if getattr(node, "name", None)]
    original = "\n\n".join(p for p in paragraphs if p).strip()
    description = original or FALLBACK_DESCRIPTION
    if len(description) > 5000:
        description = description[:4950].rsplit(" ", 1)[0] + "\n\nDevamı kaynak bağlantısında."
    return SchoolEvent(url.rsplit("/", 1)[-1], url, title.get_text(" ", strip=True),
        start, end, values.get("Yer") or None, description, original, image_url)


def fetch_html(session, url):
    response = session.get(url, timeout=15, allow_redirects=False)
    response.raise_for_status()
    if response.status_code != 200:
        raise GSUImportError("Unexpected redirect from GSÜ")
    response.encoding = "utf-8"
    return response.text


def import_gsu_events(db, publisher, limit=10, session=None, now=None):
    """Import upcoming events only; repeat runs retain prior approvals/rejections.

    `publisher` is an existing admin used for internal ownership. No school login or
    Instagram account is invented. Public presentation comes from source provenance.
    """
    if publisher.role != models.UserRole.ADMIN:
        raise GSUImportError("School imports require an admin owner")
    now = now or datetime.now(ZoneInfo("Europe/Istanbul")).replace(tzinfo=None)
    limit = min(max(limit, 1), 20)
    imported = skipped = 0
    ids = []
    own_session = session is None
    session = session or requests.Session()
    try:
        if own_session:
            session.headers.update({"User-Agent": "Evenements-GSU-Events/1.0"})
        entries = calendar_entries(fetch_html(session, LIST_URL))
        upcoming = []
        for entry in entries:
            url = urljoin(BASE, entry.get("url", ""))
            if not is_gsu_event_url(url):
                continue
            try:
                start = datetime.fromisoformat(entry["start"])
            except (ValueError, TypeError, KeyError) as exc:
                raise GSUImportError("GSÜ calendar start datetime is missing or invalid") from exc
            if start.tzinfo:
                start = start.astimezone(ZoneInfo("Europe/Istanbul")).replace(tzinfo=None)
            if start.date() >= now.date():
                upcoming.append((start, url))
        for _, url in sorted(set(upcoming)):
            source_id = url.rsplit("/", 1)[-1]
            existing = db.scalar(select(models.ScrapedEvent).where(
                models.ScrapedEvent.source == GSU_SOURCE,
                models.ScrapedEvent.source_event_id == source_id))
            if existing:
                skipped += 1
                ids.append(existing.id)
                continue
            if imported >= limit:
                break
            time.sleep(0.5)
            event = parse_detail(fetch_html(session, url), url)
            if event.start.date() < now.date():
                skipped += 1
                continue
            row = models.ScrapedEvent(source=GSU_SOURCE, source_event_id=source_id,
                club_username="gsu_website", post_shortcode=source_id,
                post_url=url, post_caption=event.original_description,
                post_image_url=event.image_url, kind="event", title=event.title,
                date=event.start, end_date=event.end, location=event.location,
                description=event.description, confidence=1.0, club_id=publisher.id,
                organizer_instagram=None, status=models.ScrapedEventStatus.PENDING)
            try:
                with db.begin_nested():
                    db.add(row)
                    db.flush()
                db.commit()
            except IntegrityError:
                # The existing source+id constraint protects concurrent imports.
                db.rollback()
                existing = db.scalar(select(models.ScrapedEvent).where(
                    models.ScrapedEvent.source == GSU_SOURCE,
                    models.ScrapedEvent.source_event_id == source_id))
                if not existing:
                    raise
                skipped += 1
                ids.append(existing.id)
                continue
            imported += 1
            ids.append(row.id)
        # Reuse completeness approval; this source does not invoke Jev.
        scraped_auto_approval.approve_complete_events(db, ids)
        return schemas.ScrapedEventImportStats(imported=imported, skipped=skipped,
            matched_clubs=0)
    finally:
        if own_session:
            session.close()
