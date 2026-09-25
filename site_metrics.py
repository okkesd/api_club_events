"""Record browser visits independently of event detail requests."""
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

import database
import models
from metrics_tracking import insert_once


def build_router(verify_api_key):
    router = APIRouter()

    @router.post("/metrics/site-visit")
    def site_visit(visitor: str = Header(..., alias="X-Visitor-Id"),
                   token=Depends(verify_api_key), db: Session = Depends(database.get_db)):
        try:
            visitor_id = UUID(visitor)
            if visitor_id.version != 4:
                raise ValueError("Expected a browser UUID")
        except ValueError:
            raise HTTPException(422, "Valid visitor UUID required")
        # The primary key + ON CONFLICT also deduplicate concurrent tabs/requests.
        insert_once(db.connection(), models.SiteVisitor.__table__, {"visitor_id": str(visitor_id)})
        db.commit()
        return {"success": True}

    return router
