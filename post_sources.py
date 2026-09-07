"""Expose the canonical source separately, including for previously published posts."""
import re


def source_details(candidates, body):
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
