"""Transactional metric history for all ORM publishing and interaction paths."""
import datetime as dt
import hashlib

from sqlalchemy import event, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import models as m


def insert_once(connection, table, values):
    insert = pg_insert if connection.dialect.name == "postgresql" else sqlite_insert
    return connection.execute(insert(table).values(**values).on_conflict_do_nothing()).rowcount == 1


def email_hash(email):
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def initialize(engine):
    with engine.begin() as connection:
        insert_once(connection, m.MetricCoverage.__table__, {"name": "site_visitors", "started_at": dt.datetime.utcnow()})
        if insert_once(connection, m.MetricCoverage.__table__, {"name": "history", "started_at": dt.datetime.utcnow()}):
            # Do not misreport old subscribers' reactivations as new subscriptions.
            for email in connection.execute(select(m.Subscription.email)).scalars():
                insert_once(connection, m.MetricSubscriber.__table__, {"email_hash": email_hash(email)})


def record(connection, kind, *, at=None, **values):
    connection.execute(m.MetricRecord.__table__.insert().values(
        kind=kind, occurred_at=at or dt.datetime.utcnow(), **values))


def activation(connection, target):
    now = dt.datetime.utcnow()
    subject = email_hash(target.email)
    if insert_once(connection, m.MetricSubscriber.__table__, {"email_hash": subject, "first_activated_at": now}):
        record(connection, "newSubscribers", at=now, subject=subject)


def inserted(mapper, connection, target):
    if isinstance(target, m.Event):
        role = connection.execute(select(m.User.role).where(m.User.id == target.club_id)).scalar()
        record(connection, "publishedEvents", event_id=target.id,
               club_id=target.club_id if role == m.UserRole.CLUB else None)
    elif isinstance(target, (m.EventView, m.EventLike)):
        visitor = (target.visitor_id or "").strip()
        if visitor and visitor.lower() != "unknown":
            record(connection, "eventViews" if isinstance(target, m.EventView) else "newLikes",
                   at=target.created_at, event_id=target.event_id, subject=visitor)
    elif isinstance(target, m.User) and target.role == m.UserRole.CLUB:
        record(connection, "newClubs", subject=target.id)
    elif isinstance(target, m.Subscription) and target.is_active:
        activation(connection, target)
    elif isinstance(target, m.Suggestion):
        record(connection, "newSuggestions", at=target.created_at, subject=target.id)
        if target.status == "approved":
            record(connection, "approvedSuggestions", at=target.reviewed_at, subject=target.id)


def updating(mapper, connection, target):
    # Read the persisted previous state before UPDATE, including expired attributes.
    if isinstance(target, m.Subscription):
        old = connection.execute(select(m.Subscription.is_active).where(m.Subscription.id == target.id)).scalar()
        if old is True and target.is_active is False:
            record(connection, "unsubscribes", subject=email_hash(target.email))
        elif old is False and target.is_active is True:
            activation(connection, target)
    elif isinstance(target, m.Suggestion) and target.status == "approved":
        old = connection.execute(select(m.Suggestion.status).where(m.Suggestion.id == target.id)).scalar()
        if old != "approved":
            record(connection, "approvedSuggestions", at=target.reviewed_at, subject=target.id)


def install():
    for model in (m.Event, m.EventView, m.EventLike, m.User, m.Subscription, m.Suggestion):
        if not event.contains(model, "after_insert", inserted):
            event.listen(model, "after_insert", inserted)
    for model in (m.Subscription, m.Suggestion):
        if not event.contains(model, "before_update", updating):
            event.listen(model, "before_update", updating)
