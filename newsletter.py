"""Subscription cancellation shared by the API and newsletter delivery checks."""
from fastapi import HTTPException
import models


def find_subscription(db, token):
    sub = db.query(models.Subscription).filter(models.Subscription.token == token).first()
    if sub:
        return sub
    sub = db.query(models.ClubSubscription).filter(models.ClubSubscription.token == token).first()
    if not sub:
        raise HTTPException(404, detail="Subscription not found")
    return sub


def unsubscribe_by_token(db, token):
    sub = find_subscription(db, token)
    sub.is_active = False
    if isinstance(sub, models.Subscription):
        for preference in [*sub.club_subscriptions, *sub.category_subscriptions]:
            preference.is_active = False
        message = "Unsubscribed from all"
    else:
        message = "Unsubscribed from club"
    db.commit()
    return {"success": True, "message": message}

