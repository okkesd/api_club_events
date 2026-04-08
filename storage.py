import io
import os
import logging
from typing import Optional

import requests
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
STORAGE_BUCKET = os.getenv("STORAGE_BUCKET", "event-images")

MAX_IMAGE_WIDTH = 1920
IMAGE_QUALITY = 85


def compress_image(content: bytes, max_width: int = MAX_IMAGE_WIDTH, quality: int = IMAGE_QUALITY) -> tuple[bytes, str]:
    """Compress and resize image to WebP format. Returns (bytes, extension)."""
    img = Image.open(io.BytesIO(content))

    # Convert RGBA/P to RGB (WebP supports alpha, but RGB is smaller)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    # Resize if wider than max_width, maintaining aspect ratio
    if img.width > max_width:
        ratio = max_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((max_width, new_height), Image.LANCZOS)

    buffer = io.BytesIO()
    img.save(buffer, format="WEBP", quality=quality)
    buffer.seek(0)

    return buffer.getvalue(), "webp"


def upload_to_supabase(file_bytes: bytes, filename: str, content_type: str) -> str:
    """Upload file to Supabase Storage and return public URL."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")

    url = f"{SUPABASE_URL}/storage/v1/object/{STORAGE_BUCKET}/{filename}"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Content-Type": content_type,
        "x-upsert": "true",
    }

    response = requests.post(url, headers=headers, data=file_bytes, timeout=30)

    if response.status_code not in (200, 201):
        logger.error(f"Supabase Storage upload failed: {response.text}")
        raise Exception(f"Storage upload failed with status {response.status_code}")

    return f"{SUPABASE_URL}/storage/v1/object/public/{STORAGE_BUCKET}/{filename}"


def delete_from_supabase(file_url: str) -> bool:
    """Delete file from Supabase Storage given its public URL."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return False

    # Extract filename from public URL
    prefix = f"{SUPABASE_URL}/storage/v1/object/public/{STORAGE_BUCKET}/"
    if not file_url.startswith(prefix):
        logger.info(f"Not a Supabase Storage URL, skipping: {file_url}")
        return False

    filename = file_url[len(prefix):]

    url = f"{SUPABASE_URL}/storage/v1/object/{STORAGE_BUCKET}"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Content-Type": "application/json",
    }

    response = requests.delete(url, headers=headers, json={"prefixes": [filename]}, timeout=10)

    if response.status_code in (200, 201):
        logger.info(f"Deleted from Supabase Storage: {filename}")
        return True

    logger.error(f"Failed to delete from storage: {response.text}")
    return False


def list_storage_files(prefix: str = "", limit: int = 1000, offset: int = 0) -> list[dict]:
    """List files in the Supabase Storage bucket."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return []

    url = f"{SUPABASE_URL}/storage/v1/object/list/{STORAGE_BUCKET}"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Content-Type": "application/json",
    }
    body = {"prefix": prefix, "limit": limit, "offset": offset}

    response = requests.post(url, headers=headers, json=body, timeout=30)
    if response.status_code == 200:
        return response.json()
    logger.error(f"Failed to list storage files: {response.text}")
    return []


def cleanup_orphaned_images(db_session) -> dict:
    """Delete images from storage that aren't referenced by any event, announcement, or user."""
    from models import Event, Announcement, User

    # Collect all referenced image URLs from the database
    referenced_urls = set()

    for url, in db_session.query(Event.cover_image).filter(Event.cover_image.isnot(None)).all():
        referenced_urls.add(url)
    for url, in db_session.query(Announcement.cover_image).filter(Announcement.cover_image.isnot(None)).all():
        referenced_urls.add(url)
    for url, in db_session.query(User.logo_url).filter(User.logo_url.isnot(None)).all():
        referenced_urls.add(url)

    # Extract just the filenames from referenced URLs
    public_prefix = f"{SUPABASE_URL}/storage/v1/object/public/{STORAGE_BUCKET}/"
    referenced_filenames = set()
    for url in referenced_urls:
        if url.startswith(public_prefix):
            referenced_filenames.add(url[len(public_prefix):])

    # List all files in storage
    storage_files = list_storage_files()
    filenames_in_storage = [f["name"] for f in storage_files if f.get("name")]

    # Find orphans
    orphans = [f for f in filenames_in_storage if f not in referenced_filenames]

    deleted = 0
    for filename in orphans:
        full_url = f"{public_prefix}{filename}"
        if delete_from_supabase(full_url):
            deleted += 1

    logger.info(f"Storage cleanup: {deleted}/{len(orphans)} orphaned images deleted, {len(filenames_in_storage) - len(orphans)} in use")
    return {"total_in_storage": len(filenames_in_storage), "orphans_found": len(orphans), "deleted": deleted}
