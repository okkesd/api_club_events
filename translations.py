"""Azure text translation and persistent, description-versioned event cache."""

import hashlib
import os
import re

import requests
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import Event, EventTranslation


def translate_description(description: str, target_language: str) -> str:
    key = os.getenv("AZURE_KEY", "").strip()
    region = os.getenv("AZURE_REGION", "").strip()
    if not key or not region:
        raise HTTPException(503, detail="Translation service is not configured")

    # Translate nonblank lines in one batch, retaining all original line breaks.
    parts = re.split(r"(\r\n|\r|\n)", description)
    positions = [i for i in range(0, len(parts), 2) if parts[i].strip()]
    if not positions:
        raise HTTPException(422, detail="Event description is empty")
    if len(positions) > 1000 or len(description.encode("utf-16-le")) // 2 > 50000:
        raise HTTPException(422, detail="Event description exceeds translation limits")

    try:
        response = requests.post(
            "https://api.cognitive.microsofttranslator.com/translate",
            params={"api-version": "3.0", "to": target_language, "textType": "plain"},
            headers={
                "Ocp-Apim-Subscription-Key": key,
                "Ocp-Apim-Subscription-Region": region,
                "Content-Type": "application/json; charset=UTF-8",
            },
            json=[{"Text": parts[i]} for i in positions],
            timeout=(5, 30),
            allow_redirects=False,
        )
    except (requests.Timeout, requests.ConnectionError):
        raise HTTPException(503, detail="Translation service is unavailable") from None
    except requests.RequestException:
        raise HTTPException(502, detail="Translation service request failed") from None

    try:
        payload = response.json()
    except ValueError:
        payload = None

    error = payload.get("error") if isinstance(payload, dict) else None
    error_code = str(error.get("code")) if isinstance(error, dict) else ""
    if response.status_code == 429 or (response.status_code == 403 and error_code == "403001"):
        raise HTTPException(429, detail="Translation quota exceeded; please try again later")
    if response.status_code in (408, 503, 504):
        raise HTTPException(503, detail="Translation service is unavailable")
    if response.status_code != 200:
        raise HTTPException(502, detail="Translation service request failed")

    if not isinstance(payload, list) or len(payload) != len(positions):
        raise HTTPException(502, detail="Invalid translation service response")
    for position, item in zip(positions, payload):
        results = item.get("translations") if isinstance(item, dict) else None
        if not isinstance(results, list) or len(results) != 1:
            raise HTTPException(502, detail="Invalid translation service response")
        result = results[0]
        if (
            not isinstance(result, dict)
            or result.get("to") != target_language
            or not isinstance(result.get("text"), str)
            or not result["text"].strip()
        ):
            raise HTTPException(502, detail="Invalid translation service response")
        parts[position] = result["text"]
    return "".join(parts)


def get_event_translation(db: Session, event_id: str, target_language: str) -> str:
    source = db.execute(select(Event.description).where(Event.id == event_id)).one_or_none()
    if source is None:
        raise HTTPException(404, detail="Event not found")
    description = source[0]
    if not description or not description.strip():
        raise HTTPException(422, detail="Event description is empty")

    description_hash = hashlib.sha256(description.encode("utf-8")).hexdigest()
    cached_query = select(EventTranslation).where(
        EventTranslation.event_id == event_id,
        EventTranslation.target_language == target_language,
        EventTranslation.description_hash == description_hash,
    )
    cached = db.execute(cached_query).scalar_one_or_none()
    if cached is not None:
        return cached.description

    # Release the read transaction before waiting for the external service.
    db.rollback()
    translated = translate_description(description, target_language)
    current = db.execute(select(Event.description).where(Event.id == event_id)).one_or_none()
    if current is None:
        raise HTTPException(404, detail="Event not found")
    if current[0] != description:
        raise HTTPException(503, detail="Event description changed; please try again")
    db.add(EventTranslation(
        event_id=event_id, target_language=target_language,
        description_hash=description_hash, description=translated,
    ))
    try:
        db.commit()
    except IntegrityError:
        # Another worker may have saved this version while Azure was responding.
        db.rollback()
        cached = db.execute(cached_query).scalar_one_or_none()
        if cached is not None:
            return cached.description
        if db.execute(select(Event.id).where(Event.id == event_id)).scalar_one_or_none() is None:
            raise HTTPException(404, detail="Event not found")
        raise
    return translated
