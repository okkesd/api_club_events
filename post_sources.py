"""Expose the canonical source separately, including for previously published posts."""
import re
from urllib.parse import urlsplit

GSU_SOURCE = "gsu_website"
GSU_NAME = "Galatasaray Üniversitesi"


def is_gsu_event_url(url):
    try:
        parsed = urlsplit(url or "")
        return (parsed.scheme == "https" and parsed.netloc == "gsu.edu.tr"
                and bool(re.fullmatch(r"/tr/guncel/etkinlik/[a-zA-Z0-9-]+/[a-f0-9]{8}", parsed.path))
                and not parsed.query and not parsed.fragment)
    except ValueError:
        return False


def is_gsu_source(row):
    return row.source == GSU_SOURCE and is_gsu_event_url(row.post_url)


def organizer_name(candidates):
    return GSU_NAME if any(is_gsu_source(row) for row in candidates) else None


def source_details(candidates, body):
    school = next((row for row in candidates if is_gsu_source(row)), None)
    if school:
        return school.post_url, body
    source = next((row for row in candidates if row.source == "instagram"
                   and re.fullmatch(r"[A-Za-z0-9_-]+", row.post_shortcode or "")), None)
    if source is None:
        return None, body
    url = f"https://www.instagram.com/p/{source.post_shortcode}/"
    handle = source.club_username.strip().lstrip("@").lower()
    cleaned = "\n".join(
        line for line in (body or "").splitlines()
        if line.strip() != url and not (
            line.strip().startswith("Kaynak: ") and (
                line.strip() == f"Kaynak: @{handle}" or line.strip().endswith(f"(@{handle})")
            )
        )
    ).strip()
    return url, cleaned
