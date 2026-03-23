import io
import os
import logging
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
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
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
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }

    response = requests.delete(url, headers=headers, json={"prefixes": [filename]}, timeout=10)

    if response.status_code in (200, 201):
        logger.info(f"Deleted from Supabase Storage: {filename}")
        return True

    logger.error(f"Failed to delete from storage: {response.text}")
    return False
