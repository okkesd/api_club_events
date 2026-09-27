"""Stable event categories and account-independent organizer defaults."""
from enum import Enum
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

import database
import models


class EventCategory(str, Enum):
    ARTS_CULTURE = 'arts_culture'
    SPORTS_NATURE = 'sports_nature'
    SCIENCE_TECHNOLOGY = 'science_technology'
    CAREER_ENTREPRENEURSHIP = 'career_entrepreneurship'
    SOCIETY_THOUGHT = 'society_thought'
    SOCIAL_HOBBIES = 'social_hobbies'
    OTHER = 'other'


def effective_category(event):
    if event.category:
        return event.category
    if event.organizer_profile and event.organizer_profile.category:
        return event.organizer_profile.category
    # A named external organizer must not inherit its admin publisher's category.
    if event.owner and (not event.organizer_instagram or
                       (event.owner.ig_username or '').lower() == event.organizer_instagram.lower()):
        return (event.owner.organizer_profile.category if event.owner.organizer_profile else None) or event.owner.category
    return None


class CategoryUpdate(BaseModel):
    category: EventCategory | None


def build_router(require_admin, verify_api_key, revalidate):
    router = APIRouter(dependencies=[Depends(verify_api_key), Depends(require_admin)])

    @router.get('/admin/organizer-categories')
    def list_categories(db: Session = Depends(database.get_db)):
        profiles = {p.username: p.category for p in db.scalars(select(models.OrganizerCategory))}
        for handle in db.scalars(select(models.Event.organizer_instagram).distinct()):
            if handle:
                profiles.setdefault(handle.strip().lstrip('@').lower(), None)
        for handle in db.scalars(select(models.User.ig_username).where(models.User.ig_username.is_not(None))):
            profiles.setdefault(handle.strip().lstrip('@').lower(), None)
        return {'success': True, 'data': [{'username': name, 'category': profiles[name]}
                                         for name in sorted(profiles)]}

    @router.put('/admin/organizer-categories/{username}')
    def set_category(username: str, payload: CategoryUpdate, db: Session = Depends(database.get_db)):
        username = username.strip().lstrip('@').lower()
        if not re.fullmatch(r'[a-z0-9_.]{1,30}', username):
            raise HTTPException(422, 'Invalid Instagram username')
        # Atomic upsert also handles simultaneous admin edits.
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        insert = pg_insert if db.bind.dialect.name == 'postgresql' else sqlite_insert
        stmt = insert(models.OrganizerCategory).values(username=username, category=payload.category)
        db.execute(stmt.on_conflict_do_update(index_elements=['username'], set_={'category': payload.category}))
        db.commit()
        revalidate(['events', 'clubs'])
        return {'success': True}

    return router
