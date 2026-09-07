import uuid
import requests
import os
from pathlib import Path
import secrets
from dotenv import load_dotenv
import shutil
import uvicorn
import fastapi
import logging
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
from fastapi import HTTPException, Query, FastAPI, File, UploadFile, status, Depends, Header, Request, Response, BackgroundTasks
from pydantic import BaseModel
from datetime import datetime, timedelta
import datetime as dt
from sqlalchemy.orm import Session, joinedload, contains_eager
from sqlalchemy import select, asc, desc, or_, insert, func
import math
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from data import club_data, event_data
import database, models, schemas, utils, storage
from ratelimit import client_ip

models.Base.metadata.create_all(bind=database.engine)

load_dotenv()

# trigger deploy again :( and againn last time

VALID_API_KEY = os.getenv("API_SECRET_KEY")
NEXTJS_URL = os.getenv("NEXTJS_APP_URL", "http://localhost:3000")
REVALIDATION_TOKEN = os.getenv("REVALIDATION_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# request limiter — keyed on the real client, not the proxy in front of us (see ratelimit.py)
limiter = Limiter(key_func=client_ip)

#create api
api = FastAPI() # deploy trigger one more, another

# add limiter
api.state.limiter = limiter
api.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler) # type: ignore

# middlewares
origins = [
    os.getenv("FRONTEND_URL", "http://localhost:3000"),
]

api.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


# A 422 tells the caller which field failed but leaves no trace server-side, which makes
# "the form won't save" reports impossible to diagnose. Log the offending fields and body.
@api.exception_handler(RequestValidationError)
async def log_validation_error(request: Request, exc: RequestValidationError):
    fields = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
    logger.warning(
        "422 %s %s — %s | body=%s",
        request.method, request.url.path, "; ".join(fields), exc.body,
    )
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})


MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
ALLOWED_CONTENT_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp"
}

# helper
def get_week_range(ref_date_str: str) -> Tuple[datetime, datetime]:
    try:
        # Parse the input string "2026-01-18"
        dt = datetime.strptime(ref_date_str, "%Y-%m-%d")
        
        # Calculate Monday (0 = Monday, 6 = Sunday)
        start_of_week = dt - timedelta(days=dt.weekday())
        
        # Calculate next Monday (End of week non-inclusive)
        end_of_week = start_of_week + timedelta(days=7)
        
        return start_of_week, end_of_week
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

# helper
async def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key != VALID_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")


# helper
def require_admin(current_user: models.User = Depends(utils.get_current_user)) -> models.User:
    # role comes back as the UserRole enum member; str() would give "UserRole.ADMIN"
    if current_user.role != models.UserRole.ADMIN.value:
        raise HTTPException(status_code=403, detail="Admin only")
    return current_user


# helper
def revalidate_frontend(tags: list[str]):
    """
    Tells Next.js to purge cache for a list of tags.
    Usage: revalidate_frontend(["events", "clubs"])
    """
    if not tags: 
        return

    # Join tags into a comma-separated string: "events,clubs"
    tag_str = ",".join(tags)
    
    try:
        # We send the list of tags as a query param
        url = f"{NEXTJS_URL}/api/revalidate?tags={tag_str}&secret={REVALIDATION_TOKEN}"
        
        # 1. Fire and Forget (don't wait too long)
        response = requests.post(url, timeout=2) 
        
        if response.status_code == 200:
            logger.info(f"✅ Revalidation triggered for: {tags}")
        else:
            logger.info(f"⚠️ Revalidation failed: {response.text}")
            
    except Exception as e:
        logger.info(f"❌ Error triggering revalidation: {e}")

# helper — extract visitor ID from X-Visitor-Id header (no IP fallback)
def get_visitor_id(request: Request) -> Optional[str]:
    visitor = request.headers.get("x-visitor-id")
    if visitor and visitor != "unknown":
        return visitor
    return None

# helper
def map_event_to_response(event: models.Event, has_liked: bool = False) -> schemas.EventResponse:
    """Convert Event model to EventResponse schema."""
    return schemas.EventResponse(
        id=str(event.id),
        club_id=str(event.club_id),
        club_name=event.owner.club_name if event.owner else "Unknown",
        title=event.title,
        description=event.description,
        date=event.date,
        start_time=event.start_time,
        end_time=event.end_time,
        duration=event.duration,
        location_type=event.location_type,
        location=event.location,
        cover_image=event.cover_image,
        tags=[t.strip() for t in event.tags.split(",") if t.strip()] if event.tags else [],
        is_registration_open=event.is_registration_open,
        registration_link=event.registration_link,
        capacity=int(event.capacity) if event.capacity else None,
        likes=int(event.likes),
        view_count=int(event.view_count),
        has_liked=has_liked,
    )

# helper
def map_club_to_response(club: models.User) -> schemas.ClubResponse:
    """Convert Event model to ClubResponse schema."""
    return schemas.ClubResponse(
            id = str(club.id),
            club_name= club.club_name,
            email = club.email,
            description= club.description,
            logo_url= club.logo_url,
            banner_url= club.banner_url,
            is_verified=bool(club.is_verified),
            role=str(club.role),
            rejection_reason=str(club.rejection_reason),
            ig_username=club.ig_username,
        )


# helper
def paginate(page: int, page_size: int, total: Optional[int]) -> schemas.PaginationMeta:
    total = total or 0
    return schemas.PaginationMeta(
        page=page,
        page_size=page_size,
        total=total,
        total_pages=math.ceil(total / page_size) if page_size > 0 else 0,
    )


@api.get("/health")
async def health_check():
    return {"status": "healthy"}

# main page request to get events
@api.get("/events/weekly", response_model=schemas.MultiEventResponse)
@limiter.limit("60/minute")  # a visitor paging through weeks makes several requests a minute
async def weekly_events(
    request: Request,
    response: Response,
    date: str = Query(..., description="Any date within the desired week (YYYY-MM-DD)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):

    try:
        week_beginning, week_end = get_week_range(date)

        base_filter = (
            select(models.Event)
            .where(models.Event.date >= week_beginning.date())
            .where(models.Event.date < week_end.date())
        )

        total = db.execute(select(func.count()).select_from(base_filter.subquery())).scalar()

        query = (
            base_filter
            .join(models.Event.owner)
            .options(contains_eager(models.Event.owner))
            .order_by(models.Event.date.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        db_events = db.execute(query).scalars().unique().all()

        # Resolve has_liked per event for this visitor
        visitor_id = get_visitor_id(request)
        liked_ids = set()
        if visitor_id:
            event_ids = [e.id for e in db_events]
            if event_ids:
                liked_rows = db.execute(
                    select(models.EventLike.event_id).where(
                        models.EventLike.event_id.in_(event_ids),
                        models.EventLike.visitor_id == visitor_id,
                    )
                ).scalars().all()
                liked_ids = set(liked_rows)

        data_to_send = [map_event_to_response(event, has_liked=event.id in liked_ids) for event in db_events]

        return schemas.MultiEventResponse(
            success=True, data=data_to_send, pagination=paginate(page, page_size, total)
        )

    except HTTPException as he:
        raise he

    except Exception as e:
        logger.info(f"❌ CRITICAL ERROR in weekly_events: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal Server Error. Please contact support.")


# browse/search events
@api.get("/events", response_model=schemas.MultiEventResponse)
async def browse_events(
    request: Request,
    search: Optional[str] = None,
    tag: Optional[str] = None,
    location_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    club_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_order: str = Query("desc"),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    try:
        base_query = select(models.Event)

        if search:
            search_fmt = f"%{search}%"
            base_query = base_query.where(
                or_(
                    models.Event.title.ilike(search_fmt),
                    models.Event.description.ilike(search_fmt),
                )
            )
        if tag:
            base_query = base_query.where(models.Event.tags.ilike(f"%{tag}%"))
        if location_type:
            base_query = base_query.where(models.Event.location_type == location_type)
        if club_id:
            base_query = base_query.where(models.Event.club_id == club_id)
        if date_from:
            base_query = base_query.where(models.Event.date >= date_from)
        if date_to:
            base_query = base_query.where(models.Event.date <= date_to)

        total = db.execute(select(func.count()).select_from(base_query.subquery())).scalar()

        order_clause = models.Event.date.asc() if sort_order == "asc" else models.Event.date.desc()

        query = (
            base_query
            .join(models.Event.owner)
            .options(contains_eager(models.Event.owner))
            .order_by(order_clause)
            .order_by(models.Event.date.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        db_events = db.execute(query).scalars().unique().all()

        visitor_id = get_visitor_id(request)
        liked_ids = set()
        if visitor_id:
            event_ids = [e.id for e in db_events]
            if event_ids:
                liked_rows = db.execute(
                    select(models.EventLike.event_id).where(
                        models.EventLike.event_id.in_(event_ids),
                        models.EventLike.visitor_id == visitor_id,
                    )
                ).scalars().all()
                liked_ids = set(liked_rows)

        data = [map_event_to_response(event, has_liked=event.id in liked_ids) for event in db_events]

        return schemas.MultiEventResponse(
            success=True, data=data, pagination=paginate(page, page_size, total)
        )

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.info(f"Error in browse_events: {e}")
        db.rollback()
        raise HTTPException(500, detail="Internal server error")


# get single event
@api.get("/events/{event_id}", response_model=schemas.SingleEventResponse)
async def handle_events(event_id: str, request: Request, db: Session = Depends(database.get_db), token: str = Depends(verify_api_key),):

    try:

        query = (
            select(models.Event)
            .options(joinedload(models.Event.owner))
            .where(models.Event.id == event_id)
        )

        res = db.execute(query)
        event = res.scalars().first()

        if not event:
            raise HTTPException(404, detail="Event not found")

        visitor_id = get_visitor_id(request)
        has_liked = False

        if visitor_id:
            # Deduplicated view count — only track when visitor is identified
            already_viewed = db.execute(
                select(models.EventView).where(
                    models.EventView.event_id == event_id,
                    models.EventView.visitor_id == visitor_id,
                )
            ).scalar()
            if not already_viewed:
                db.add(models.EventView(event_id=event_id, visitor_id=visitor_id))
                event.view_count += 1
                db.commit()

            # Check if this visitor has liked the event
            has_liked = db.execute(
                select(models.EventLike).where(
                    models.EventLike.event_id == event_id,
                    models.EventLike.visitor_id == visitor_id,
                )
            ).scalar() is not None

        event_complex = map_event_to_response(event, has_liked=has_liked)

        return schemas.SingleEventResponse(success=True, data=event_complex)
            
    except HTTPException as he: # re-raise
        raise he
    
    except Exception as e:
        logger.info("exception: %s", e)
        db.rollback()
        raise HTTPException(500, detail="Internal server error")
    

# get single club
@api.get("/clubs/{club_id}", response_model=schemas.ClubApiResponse)
async def handle_club(club_id: str, db: Session = Depends(database.get_db), token: str = Depends(verify_api_key),):

    try:
        query = (
            select(models.User)
            .where(models.User.id == club_id)
        )
    
        club = db.execute(query).scalars().first()
    
        if not club:
            raise HTTPException(404, detail=f"No club found with id {club_id}")
        
        club_data = map_club_to_response(club)
        
        return schemas.ClubApiResponse(success=True, data=club_data)
            
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.info("exception: %s", e)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error occured in handle club: {str(e)}")
    
    
# get club's events
@api.get("/clubs/{club_id}/events", response_model=schemas.MultiEventResponse)
async def handle_club_events(
    club_id: str,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(database.get_db),
):

    try:
        base_filter = select(models.Event).where(models.Event.club_id == club_id)
        total = db.execute(select(func.count()).select_from(base_filter.subquery())).scalar()

        query = (
            base_filter
            .options(joinedload(models.Event.owner))
            .order_by(models.Event.date.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = db.execute(query).scalars().unique().all()

        visitor_id = get_visitor_id(request)
        liked_ids = set()
        if visitor_id:
            event_ids = [e.id for e in result]
            if event_ids:
                liked_rows = db.execute(
                    select(models.EventLike.event_id).where(
                        models.EventLike.event_id.in_(event_ids),
                        models.EventLike.visitor_id == visitor_id,
                    )
                ).scalars().all()
                liked_ids = set(liked_rows)

        clubs_events = [map_event_to_response(event, has_liked=event.id in liked_ids) for event in result]

        return schemas.MultiEventResponse(
            success=True, data=clubs_events, pagination=paginate(page, page_size, total)
        )

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.info("Exception: %s", e)
        db.rollback()
        raise HTTPException(500, detail="Internal server error")

# image uploading , secured
@api.post("/upload")
@limiter.limit("10/minute")
async def upload_image(
    request: Request,
    file: UploadFile = File(...),
    current_user: models.User = Depends(utils.get_current_user),
    token: str = Depends(verify_api_key),
):
    try:
        if current_user.role not in ["club", "admin"]:
            raise HTTPException(status_code=403, detail="Uploading image is not allowed for the user")

        if file.content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(400, detail=f"Invalid content type. Not allowed. Allowed: {list(ALLOWED_CONTENT_TYPES.keys())}")

        # 1. Read and validate file size
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(413, detail=f"File too large. Maximum: {MAX_FILE_SIZE / 1024 / 1024}MB")

        # 2. Validate actual image
        try:
            from PIL import Image
            import io
            Image.open(io.BytesIO(content)).verify()
        except Exception:
            raise HTTPException(400, detail="Invalid image file")

        # 3. Compress and resize (converts to WebP)
        compressed_bytes, ext = storage.compress_image(content)

        # 4. Upload to Supabase Storage
        safe_filename = f"{secrets.token_urlsafe(16)}.{ext}"
        public_url = storage.upload_to_supabase(compressed_bytes, safe_filename, f"image/{ext}")

        logger.info(f"Image uploaded: {safe_filename} ({len(content)} -> {len(compressed_bytes)} bytes)")

        return {"success": True, "url": public_url}

    except HTTPException as he:
        raise he

    except Exception as e:
        logger.info(f"Upload Error: {e}")
        raise HTTPException(status_code=500, detail="Image upload failed server-side")


@api.post("/signup", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def create_user(request: Request, user: schemas.UserCreate, db: Session = Depends(database.get_db), token: str = Depends(verify_api_key),):
    
    try:

        # 1. Check if email already exists
        # We query the DB looking for a user with this email
        existing_user = db.query(models.User).filter_by(email=user.email).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="Email already registered")
        
        # 2. Hash the password
        hashed_pwd = utils.hash_password(user.password)
        
        # 3. Create the Database Object
        # We map the Pydantic data to the SQLAlchemy model
        new_user = models.User(
            email=user.email,
            hashed_password=hashed_pwd,
            club_name=user.club_name,
            description=user.description
        )
        
        # 4. Add & Commit
        db.add(new_user)
        db.commit()
        db.refresh(new_user) # Reloads the object with the generated ID
        
        return schemas.UserResponse(success=True, data=new_user) # Instead of returning this, we'd like to sign in user and login 
    
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.info("Exception occured in signup: %s", e)
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create user")

@api.post("/login", response_model=schemas.Token)
@limiter.limit("5/minute")
async def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    try:

        # 1. Find the user
        # Note: OAuth2PasswordRequestForm expects 'username', but we treat it as 'email'
        user = db.query(models.User).filter_by(email = form_data.username).first()
        
        # 2. Verify User and Password
        if not user or not utils.verify_password(form_data.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # 3. Create Token
        access_token = utils.create_access_token(data={"sub": user.id})
        
        # 4. Return it
        return {"access_token": access_token, "token_type": "bearer"}
    
    except HTTPException as he:
        raise he
    
    except Exception as e:
        logger.info("Exception occured in login: %s", e)
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal Server Error, failed to log in")

# after login, returns curent user
@api.get("/users/me", response_model=schemas.UserOut)
async def read_users_me(current_user: models.User = Depends(utils.get_current_user)):
    """
    Returns the currently logged-in user.
    The 'current_user' is injected automatically by checking the JWT token.
    """
    return current_user

# posting an event (IMPORTANT NOTE: when an event is created (with mock up auth), it doesnt show up as expected in calendar, maybe its about auth or admin)
@api.post("/events", response_model=schemas.SingleEventResponse)
async def create_event(
    event_in: schemas.EventCreate, 
    bg_tasks: BackgroundTasks,
    current_user: models.User = Depends(utils.get_current_user),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    logger.info(f"Current user's role: {current_user.role}")
    logger.info(event_in)
    if current_user.role not in ["club", "admin"]:
        raise HTTPException(status_code=403, detail="Posting event is not allowed for the user")
    
    if current_user.role == "club":
        if (current_user.id != event_in.club_id):
            raise HTTPException(status_code=403, detail="You cannot post events for other clubs")


    # 1. Fetch the Club trying to post
    # (In a real app, this comes from the JWT Token. Here we look up the ID sent in the body)
    club = db.query(models.User).filter(models.User.id == event_in.club_id).first()
    
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    # 2. ✅ CHECK: Block Event Creation if Unverified
    if not bool(club.is_verified) and str(club.role) != "admin":
        raise HTTPException(
            status_code=403, 
            detail="Your club is not verified yet. You cannot post events. Unverified"
        )
    

    # 1. Generate a Slug (Title + Date)
    raw_slug = f"{event_in.title} {event_in.date}"
    slug = models.generate_slug(raw_slug)

    # 2. Create the DB Object
    # We unpack (**dict) the Pydantic model, but we need to exclude 
    # fields that don't match the DB column names exactly if we mapped them differently

    tags_string = ",".join(event_in.tags) if event_in.tags else ""
    
    db_event = models.Event(
        slug=slug,
        title=event_in.title,
        description=event_in.description,
        club_id=event_in.club_id,
        date=event_in.date, # Convert Str -> Date
        start_time=event_in.start_time,
        end_time=event_in.end_time,
        duration=event_in.duration,
        location_type=event_in.location_type,
        location=event_in.location,
        cover_image=event_in.cover_image,
        tags=tags_string, 
        is_registration_open=event_in.is_registration_open,
        registration_link=event_in.registration_link,
        capacity=event_in.capacity
        # If your DB doesn't have 'tags' or 'registration' columns yet, 
        # you might need to skip these or add them to models.py first!
    )
    
    try:
        db.add(db_event)
        db.commit()
        db.refresh(db_event)
        
        # 3. Return the complex response (fetches club name automatically via relationship)
        # We re-query or just construct it manually to match the response schema
        created_event = map_event_to_response(db_event)

        bg_tasks.add_task(revalidate_frontend, ["events"])

        return schemas.SingleEventResponse(success=True, data=created_event)
        
    except Exception as e:
        db.rollback()
        logger.info(f"Error creating event: {e}")
        raise HTTPException(status_code=500, detail="Could not create event")

# get all clubs for the admin page and club list
@api.get("/all_clubs", response_model=schemas.AllClubsResponse)
async def get_all_clubs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):

    try:
        total = db.execute(select(func.count()).select_from(models.User)).scalar()

        result = db.execute(
            select(models.User).offset((page - 1) * page_size).limit(page_size)
        ).scalars().all()

        clubs_to_return = [map_club_to_response(club) for club in result]

        return schemas.AllClubsResponse(
            success=True, data=clubs_to_return, pagination=paginate(page, page_size, total)
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")

# club update (profile update) by admin or club owner
@api.patch("/clubs/{club_id}", response_model=schemas.ClubApiResponse)
async def update_club(
    club_id: str, 
    club_update: schemas.ClubUpdate, 
    bg_tasks: BackgroundTasks,
    current_user: models.User = Depends(utils.get_current_user),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    
    if current_user.role not in ["club", "admin"]:
        raise HTTPException(status_code=403, detail="Updating a club is not allowed for the user")
    
    # 1. Fetch the existing Club (User)
    query = select(models.User).where(models.User.id == club_id)
    club = db.execute(query).scalars().first()

    if not club:
        raise HTTPException(status_code=404, detail="Club not found")
    
    if not bool(club.is_verified) and str(club.role) != "admin":
        raise HTTPException(
            status_code=403, 
            detail="Unverified clubs cannot edit their public profile. Contact admin."
        )

    # 2. Update fields if they are provided in the request
    # We check if value is not None so we don't accidentally erase data
    if club_update.club_name is not None:
        club.club_name = club_update.club_name
        
    if club_update.email is not None:
        club.email = club_update.email
        
    if club_update.description is not None:
        club.description = club_update.description
        
    if club_update.logo_url is not None:
        club.logo_url = club_update.logo_url
        
    if club_update.banner_url is not None:
        club.banner_url = club_update.banner_url

    # Controls which scraped Instagram events attach to this club — admin decides.
    # Unlike the fields above, an explicit null here *clears* the handle (omit it to leave it alone).
    if "ig_username" in club_update.model_fields_set:
        if current_user.role != models.UserRole.ADMIN.value:
            raise HTTPException(status_code=403, detail="Only an admin can set the Instagram username")
        handle = (club_update.ig_username or "").lstrip("@").strip()
        club.ig_username = handle or None

    # 3. Commit to Database
    try:
        db.commit()
        db.refresh(club) # Reloads the object with new data from DB

        bg_tasks.add_task(revalidate_frontend, ["clubs", "events"])
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update club")

    # 4. Return the updated club (formatted for the response schema)
    return schemas.ClubApiResponse(
        success=True,
        data=map_club_to_response(club)
    )

# get all clubs for admin
@api.get("/admin/clubs", response_model=schemas.AllClubsResponse)
async def get_all_clubs_admin(
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: models.User = Depends(utils.get_current_user),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    """
    Fetches ALL clubs (including unverified ones) for the Admin Dashboard.
    """

    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Getting all clubs is not allowed for the user (club)")

    try:

        base_query = select(models.User).where(models.User.role == "club")

        if status == 'verified':
            base_query = base_query.where(models.User.is_verified == True)
        elif status == 'pending':
            base_query = base_query.where(models.User.is_verified == False)

        total = db.execute(select(func.count()).select_from(base_query.subquery())).scalar()

        query = base_query.order_by(
            asc(models.User.is_verified),
            asc(models.User.club_name)
        ).offset((page - 1) * page_size).limit(page_size)

        clubs = db.execute(query).scalars().all()
        clubs_to_return = [map_club_to_response(club) for club in clubs]

        return schemas.AllClubsResponse(
            success=True, data=clubs_to_return, pagination=paginate(page, page_size, total)
        )
    
    except Exception as e:
        logger.info("Exception occured in get all clubs admin: %s", e)
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


# 1. ADMIN: SET CLUB STATUS
@api.patch("/admin/clubs/{club_id}/status", response_model=schemas.ClubApiResponse)
async def set_club_verification(
    club_id: str,
    status_update: schemas.ClubStatusUpdate,
    bg_tasks: BackgroundTasks,
    current_user: models.User = Depends(utils.get_current_user),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    """
    Admin endpoint to Verify or Reject a club.
    """

    if current_user.role != "admin":
        raise HTTPException(status_code=401, detail="Changing club status is not allowed for the user")
    club = db.query(models.User).filter(models.User.id == club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")
        
    # Update Status
    club.is_verified = status_update.is_verified
    
    # Handle Rejection Reason
    if status_update.is_verified:
        # CLEANUP: If approved, clear any old rejection reasons (set to None or empty string)
        club.rejection_reason = None 
    else:
        # If rejected, require/store the reason
        club.rejection_reason = status_update.rejection_reason

    try:
        db.commit()
        db.refresh(club)
        bg_tasks.add_task(revalidate_frontend, ["clubs"])

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update verification status.")
    
    # Return using the Wrapper (ClubApiResponse) -> Data (ClubResponse)
    return schemas.ClubApiResponse(
        success=True,
        data=map_club_to_response(club)
    )


# 2. CLUB: UPDATE EVENT
@api.patch("/events/{event_id}", response_model=schemas.SingleEventResponse)
async def update_event(
    event_id: str,
    event_update: schemas.EventUpdate,
    bg_tasks: BackgroundTasks,
    current_user: models.User = Depends(utils.get_current_user),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    
    if current_user.role not in ["club", "admin"]:
        raise HTTPException(status_code=403, detail="Updating event is not allowed for user")

    # 1. Find Event
    db_event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not db_event:
        raise HTTPException(status_code=404, detail="Event not found")

    # 2. Ownership check — clubs can only update their own events
    if current_user.role == "club" and db_event.club_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only update your own events")

    # 3. Get the Club (Owner)
    club = db.query(models.User).filter(models.User.id == db_event.club_id).first()

    if not club:
        raise HTTPException(status_code=500, detail="Event owner not found.")

    # 4. Permission Check
    if not club.is_verified and club.role != "admin":
         raise HTTPException(status_code=403, detail="Unverified clubs cannot edit events.")

    # 4. Update Fields
    # Only update what is sent (Pydantic models exclude_unset=True is handled manually here for safety)
    
    if event_update.title is not None: db_event.title = event_update.title
    if event_update.description is not None: db_event.description = event_update.description
    if event_update.location is not None: db_event.location = event_update.location
    if event_update.location_type is not None: db_event.location_type = event_update.location_type
    if event_update.cover_image is not None: db_event.cover_image = event_update.cover_image
    
    # Time Logic
    if event_update.date is not None:
         # No need for strptime! Pydantic 'EventUpdate' schema already parsed this into a date object.
         db_event.date = event_update.date 
    
    if event_update.start_time is not None: db_event.start_time = event_update.start_time
    if event_update.end_time is not None: db_event.end_time = event_update.end_time
    if event_update.duration is not None: db_event.duration = event_update.duration

    # Registration Logic (Update these too!)
    if event_update.is_registration_open is not None: 
        db_event.is_registration_open = event_update.is_registration_open
    if event_update.registration_link is not None:
        # An empty field in the form arrives as "", which should clear the link, not store "".
        db_event.registration_link = event_update.registration_link or None
    if event_update.capacity is not None:
        # 0 is "no limit"; store it as NULL so responses and the DB agree on what empty means.
        db_event.capacity = event_update.capacity or None

    try:
        db.commit()
        db.refresh(db_event)

        bg_tasks.add_task(revalidate_frontend, ["events"])

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update event")

    # 5. Return (Map to Schema)
    return schemas.SingleEventResponse(
        success=True,
        data=map_event_to_response(db_event)
    )

# DELETE EVENT
@api.delete("/events/{event_id}", response_model=schemas.SingleEventResponse)
async def delete_event(
    event_id: str,
    bg_tasks: BackgroundTasks,
    current_user: models.User = Depends(utils.get_current_user),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    if current_user.role not in ["club", "admin"]:
        raise HTTPException(status_code=403, detail="Deleting event is not allowed for user")

    # 1. Find Event
    db_event = (
        db.query(models.Event)
        .options(joinedload(models.Event.owner))
        .filter(models.Event.id == event_id)
        .first()
    )
    if not db_event:
        raise HTTPException(status_code=404, detail="Event not found")

    # 2. Permission Check — clubs can only delete their own events
    if current_user.role == "club" and db_event.club_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only delete your own events")

    # 3. Build response before deletion (relationship data still available)
    event_response = map_event_to_response(db_event)

    # 4. Clean up cover image from Supabase Storage
    if db_event.cover_image:
        try:
            storage.delete_from_supabase(db_event.cover_image)
        except Exception:
            logger.info(f"Failed to delete image from storage: {db_event.cover_image}")

    # 5. Delete from DB
    try:
        db.delete(db_event)
        db.commit()
        bg_tasks.add_task(revalidate_frontend, ["events"])
    except Exception as e:
        db.rollback()
        logger.info(f"Error deleting event: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete event")

    return schemas.SingleEventResponse(success=True, data=event_response)


@api.get("/clubs", response_model=schemas.AllClubsResponse)
async def get_all_clubs_user(
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    """
    Public directory of all verified clubs.
    """

    try:

        base_query = select(models.User).where(
            models.User.role == "club",
            models.User.is_verified == True
        )

        if search:
            search_fmt = f"%{search}%"
            base_query = base_query.where(
                or_(
                    models.User.club_name.ilike(search_fmt),
                    models.User.description.ilike(search_fmt)
                )
            )

        total = db.execute(select(func.count()).select_from(base_query.subquery())).scalar()

        query = base_query.order_by(models.User.club_name.asc()).offset((page - 1) * page_size).limit(page_size)
        clubs = db.execute(query).scalars().all()

        clubs_to_return = [map_club_to_response(cl) for cl in clubs]

        return schemas.AllClubsResponse(
            success=True, data=clubs_to_return, pagination=paginate(page, page_size, total)
        )
    
    except Exception as e:
        logger.info("Exception occured in get all clubs user: %s", e)
        db.rollback()
        raise HTTPException(500, "Internal server error getting clubs")

@api.post("/event_like/{event_id}", response_model=schemas.EventLikeResponse)
async def handle_event_like(
    event_id: str,
    request: Request,
    bg_tasks: BackgroundTasks,
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    try:
        visitor_id = get_visitor_id(request)
        if not visitor_id:
            raise HTTPException(status_code=400, detail="Visitor ID required")

        event = db.execute(
            select(models.Event).where(models.Event.id == event_id)
        ).scalar()

        if not event:
            raise HTTPException(status_code=404, detail="Event not found")

        # Check if this visitor already liked this event
        existing_like = db.execute(
            select(models.EventLike).where(
                models.EventLike.event_id == event_id,
                models.EventLike.visitor_id == visitor_id,
            )
        ).scalar()

        if existing_like:
            # Unlike — remove the row and decrement
            db.delete(existing_like)
            event.likes = max(0, event.likes - 1)
            has_liked = False
        else:
            # Like — insert row and increment
            new_like = models.EventLike(event_id=event_id, visitor_id=visitor_id)
            db.add(new_like)
            event.likes += 1
            has_liked = True

        db.commit()
        db.refresh(event)
        logger.info(f"like toggle: event={event_id} visitor={visitor_id} liked={has_liked} total={event.likes}")

        bg_tasks.add_task(revalidate_frontend, ["events"])

        return schemas.EventLikeResponse(
            success=True, 
            data=schemas.EventLikeData(
                likes=int(event.likes), 
                has_liked=has_liked
            )
            )

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.info(f"Exception in handle_event_like for event {event_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal Server Error")


# ==================== ANNOUNCEMENTS ====================

def map_announcement_to_response(a: models.Announcement) -> schemas.AnnouncementResponse:
    return schemas.AnnouncementResponse(
        id=str(a.id),
        club_id=str(a.club_id),
        club_name=a.owner.club_name if a.owner else "Unknown",
        title=a.title,
        body=a.body,
        cover_image=a.cover_image,
        link=a.link,
        tags=list(a.tags.split(",")) if a.tags else [],
        category=a.category,
        is_pinned=bool(a.is_pinned),
        expires_at=a.expires_at,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


@api.get("/announcements", response_model=schemas.MultiAnnouncementResponse)
async def get_announcements(
    category: Optional[List[str]] = Query(None),
    club_id: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    include_expired: bool = False,
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    try:
        query = (
            select(models.Announcement)
            .join(models.Announcement.owner)
            .options(contains_eager(models.Announcement.owner))
        )

        if category:
            query = query.where(models.Announcement.category.in_(category))
        if club_id:
            query = query.where(models.Announcement.club_id == club_id)
        if tag:
            query = query.where(models.Announcement.tags.ilike(f"%{tag}%"))
        if search:
            search_fmt = f"%{search}%"
            query = query.where(
                or_(
                    models.Announcement.title.ilike(search_fmt),
                    models.Announcement.body.ilike(search_fmt),
                )
            )
        if not include_expired:
            query = query.where(
                or_(
                    models.Announcement.expires_at.is_(None),
                    models.Announcement.expires_at >= datetime.now().date(),
                )
            )

        # Pinned first, then newest
        query = query.order_by(
            models.Announcement.is_pinned.desc(),
            models.Announcement.created_at.desc(),
        )

        result = db.execute(query).scalars().unique().all()

        return schemas.MultiAnnouncementResponse(
            success=True,
            data=[map_announcement_to_response(a) for a in result],
        )

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.info(f"Error fetching announcements: {e}")
        db.rollback()
        raise HTTPException(500, detail="Internal server error")


# ==================== SUBSCRIPTIONS ====================

def _get_or_create_subscription(db: Session, email: str) -> models.Subscription:
    """Find existing subscription by email, or create a new one."""
    import secrets as sec
    sub = db.query(models.Subscription).filter(models.Subscription.email == email).first()
    if not sub:
        sub = models.Subscription(
            email=email,
            token=sec.token_urlsafe(32),
        )
        db.add(sub)
        db.flush()  # get the ID without committing
    return sub


def map_subscription_to_response(sub: models.Subscription) -> schemas.SubscriptionResponse:
    clubs = [
        schemas.ClubSubscriptionInfo(
            club_id=cs.club_id,
            club_name=cs.club.club_name if cs.club else "Unknown",
            is_active=cs.is_active,
        )
        for cs in sub.club_subscriptions
    ]
    categories = [
        schemas.CategorySubscriptionInfo(
            category=cat_sub.category.value if hasattr(cat_sub.category, 'value') else cat_sub.category,
            is_active=cat_sub.is_active,
        )
        for cat_sub in sub.category_subscriptions
    ]
    return schemas.SubscriptionResponse(
        id=str(sub.id),
        email=sub.email,
        clubs=clubs,
        categories=categories,
        is_active=sub.is_active,
        created_at=sub.created_at,
    )


@api.post("/subscribe", response_model=schemas.SingleSubscriptionResponse)
@limiter.limit("5/minute")
async def subscribe(
    request: Request,
    sub_in: schemas.SubscribeRequest,
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    """
    Public endpoint. Students subscribe with just their email.
    Optionally pass club_ids and/or categories.
    """
    import secrets as sec
    try:
        sub = _get_or_create_subscription(db, sub_in.email)

        # Create CategorySubscription rows for any requested categories
        for category in sub_in.categories:
            existing_cat = db.query(models.CategorySubscription).filter(
                models.CategorySubscription.subscription_id == sub.id,
                models.CategorySubscription.category == category,
            ).first()
            if not existing_cat:
                db.add(models.CategorySubscription(
                    subscription_id=sub.id,
                    category=category,
                ))
            elif not existing_cat.is_active:
                existing_cat.is_active = True

        sub.is_active = True

        # Create ClubSubscription rows for any requested club_ids
        for club_id in sub_in.club_ids:
            existing_cs = db.query(models.ClubSubscription).filter(
                models.ClubSubscription.subscription_id == sub.id,
                models.ClubSubscription.club_id == club_id,
            ).first()
            if not existing_cs:
                db.add(models.ClubSubscription(
                    subscription_id=sub.id,
                    club_id=club_id,
                    token=sec.token_urlsafe(32),
                ))
            elif not existing_cs.is_active:
                existing_cs.is_active = True

        db.commit()
        db.refresh(sub)

        return schemas.SingleSubscriptionResponse(
            success=True, data=map_subscription_to_response(sub)
        )

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.info(f"Error in subscribe: {e}")
        db.rollback()
        raise HTTPException(500, detail="Failed to subscribe")


@api.post("/clubs/{club_id}/subscribe", response_model=schemas.ClubSubscriptionToggleResponse)
async def toggle_club_subscription(
    club_id: str,
    req: schemas.ClubSubscribeRequest,
    db: Session = Depends(database.get_db),
):
    """Toggle subscription to a specific club by email."""
    import secrets as sec

    club = db.query(models.User).filter(models.User.id == club_id).first()
    if not club:
        raise HTTPException(404, "Club not found")

    sub = _get_or_create_subscription(db, req.email)

    # Check if a ClubSubscription already exists
    cs = db.query(models.ClubSubscription).filter(
        models.ClubSubscription.subscription_id == sub.id,
        models.ClubSubscription.club_id == club_id,
    ).first()

    if cs and cs.is_active:
        cs.is_active = False
        message = "Unsubscribed from club"
        is_subscribed = False
    elif cs:
        cs.is_active = True
        message = "Subscribed to club!"
        is_subscribed = True
    else:
        db.add(models.ClubSubscription(
            subscription_id=sub.id,
            club_id=club_id,
            token=sec.token_urlsafe(32),
        ))
        message = "Subscribed to club!"
        is_subscribed = True

    sub.is_active = True
    db.commit()

    return schemas.ClubSubscriptionToggleResponse(
        success=True, message=message, is_subscribed=is_subscribed
    )


@api.delete("/unsubscribe/{token}")
async def unsubscribe(
    token: str,
    db: Session = Depends(database.get_db),
):
    """
    Public endpoint. Unsubscribe via token (from email link).
    Works for both master tokens (deactivates everything) and per-club tokens.
    """
    # Check master token first
    sub = db.query(models.Subscription).filter(
        models.Subscription.token == token
    ).first()
    if sub:
        sub.is_active = False
        for cs in sub.club_subscriptions:
            cs.is_active = False
        db.commit()
        return {"success": True, "message": "Unsubscribed from all"}

    # Check per-club token
    cs = db.query(models.ClubSubscription).filter(
        models.ClubSubscription.token == token
    ).first()
    if cs:
        cs.is_active = False
        db.commit()
        return {"success": True, "message": "Unsubscribed from club"}

    raise HTTPException(404, detail="Subscription not found")


@api.get("/admin/subscriptions", response_model=schemas.MultiSubscriptionResponse)
async def get_subscriptions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: models.User = Depends(utils.get_current_user),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    """Admin-only: view all active subscriptions."""
    if current_user.role != "admin":
        raise HTTPException(403, detail="Admin only")

    try:
        base_query = select(models.Subscription).where(models.Subscription.is_active == True)
        total = db.execute(select(func.count()).select_from(base_query.subquery())).scalar()

        subs = db.execute(
            base_query.order_by(models.Subscription.created_at.desc())
            .offset((page - 1) * page_size).limit(page_size)
        ).scalars().all()

        return schemas.MultiSubscriptionResponse(
            success=True,
            data=[map_subscription_to_response(s) for s in subs],
            pagination=paginate(page, page_size, total),
        )

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.info(f"Error fetching subscriptions: {e}")
        db.rollback()
        raise HTTPException(500, detail="Internal server error")


@api.post("/admin/cleanup-storage")
async def cleanup_storage(
    current_user: models.User = Depends(utils.get_current_user),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    """Admin-only: delete orphaned images from Supabase Storage."""
    if current_user.role != "admin":
        raise HTTPException(403, detail="Admin only")

    result = storage.cleanup_orphaned_images(db)
    return {"success": True, **result}


@api.get("/announcements/{announcement_id}", response_model=schemas.SingleAnnouncementResponse)
async def get_announcement(
    announcement_id: str,
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    try:
        query = (
            select(models.Announcement)
            .options(joinedload(models.Announcement.owner))
            .where(models.Announcement.id == announcement_id)
        )
        a = db.execute(query).scalars().first()

        if not a:
            raise HTTPException(404, detail="Announcement not found")

        return schemas.SingleAnnouncementResponse(
            success=True, data=map_announcement_to_response(a)
        )

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.info(f"Error fetching announcement: {e}")
        db.rollback()
        raise HTTPException(500, detail="Internal server error")


@api.post("/announcements", response_model=schemas.SingleAnnouncementResponse)
async def create_announcement(
    announcement_in: schemas.AnnouncementCreate,
    bg_tasks: BackgroundTasks,
    current_user: models.User = Depends(utils.get_current_user),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    if current_user.role not in ["club", "admin"]:
        raise HTTPException(403, detail="Posting announcements is not allowed for this user")

    if current_user.role == "club" and current_user.id != announcement_in.club_id:
        raise HTTPException(403, detail="You cannot post announcements for other clubs")

    club = db.query(models.User).filter(models.User.id == announcement_in.club_id).first()
    if not club:
        raise HTTPException(404, detail="Club not found")

    if not bool(club.is_verified) and str(club.role) != "admin":
        raise HTTPException(403, detail="Unverified clubs cannot post announcements")

    slug = models.generate_slug(f"{announcement_in.title} {datetime.now().strftime('%Y%m%d%H%M')}")
    tags_string = ",".join(announcement_in.tags) if announcement_in.tags else ""

    # --- NEW: Enforce 14-day maximum expiration ---
    max_date = (datetime.utcnow() + timedelta(days=14)).date()
    final_expires_at = None
    
    if announcement_in.expires_at:
        # Pydantic usually parses this as a datetime.date object.
        # If your schema leaves it as a string, uncomment the line below:
        # incoming_date = datetime.strptime(announcement_in.expires_at, "%Y-%m-%d").date()
        incoming_date = announcement_in.expires_at 
        
        # Take whichever is sooner: their requested date, or our 14-day max
        final_expires_at = min(incoming_date, max_date)
    else:
        # Default to 7 days if they didn't provide one
        final_expires_at = (datetime.utcnow() + timedelta(days=7)).date()
    # ----------------------------------------------

    db_announcement = models.Announcement(
        slug=slug,
        title=announcement_in.title,
        body=announcement_in.body,
        cover_image=announcement_in.cover_image,
        link=announcement_in.link,
        tags=tags_string,
        category=announcement_in.category,
        is_pinned=announcement_in.is_pinned if current_user.role == "admin" else False,
        expires_at=final_expires_at, # <-- Use the safe calculated date here
        club_id=announcement_in.club_id,
    )

    try:
        db.add(db_announcement)
        db.commit()
        db.refresh(db_announcement)

        bg_tasks.add_task(revalidate_frontend, ["announcements"])

        return schemas.SingleAnnouncementResponse(
            success=True, data=map_announcement_to_response(db_announcement)
        )

    except Exception as e:
        db.rollback()
        logger.info(f"Error creating announcement: {e}")
        raise HTTPException(500, detail="Could not create announcement")


@api.patch("/announcements/{announcement_id}", response_model=schemas.SingleAnnouncementResponse)
async def update_announcement(
    announcement_id: str,
    update: schemas.AnnouncementUpdate,
    bg_tasks: BackgroundTasks,
    current_user: models.User = Depends(utils.get_current_user),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    if current_user.role not in ["club", "admin"]:
        raise HTTPException(403, detail="Updating announcements is not allowed for this user")

    db_a = db.query(models.Announcement).filter(models.Announcement.id == announcement_id).first()
    if not db_a:
        raise HTTPException(404, detail="Announcement not found")

    if current_user.role == "club" and db_a.club_id != current_user.id:
        raise HTTPException(403, detail="You can only update your own announcements")

    if update.title is not None: db_a.title = update.title
    if update.body is not None: db_a.body = update.body
    if update.cover_image is not None: db_a.cover_image = update.cover_image
    if update.link is not None: db_a.link = update.link
    if update.tags is not None: db_a.tags = ",".join(update.tags)
    if update.category is not None: db_a.category = update.category
    
    # --- NEW: Enforce 14-day limit on updates ---
    if update.expires_at is not None: 
        max_date = (datetime.utcnow() + timedelta(days=14)).date()
        incoming_date = update.expires_at # Again, assuming Pydantic casts to datetime.date
        db_a.expires_at = min(incoming_date, max_date)
    # --------------------------------------------

    # Only admin can pin
    if update.is_pinned is not None and current_user.role == "admin":
        db_a.is_pinned = update.is_pinned

    try:
        db.commit()
        db.refresh(db_a)
        bg_tasks.add_task(revalidate_frontend, ["announcements"])
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail="Failed to update announcement")

    return schemas.SingleAnnouncementResponse(
        success=True, data=map_announcement_to_response(db_a)
    )


@api.delete("/announcements/{announcement_id}", response_model=schemas.SingleAnnouncementResponse)
async def delete_announcement(
    announcement_id: str,
    bg_tasks: BackgroundTasks,
    current_user: models.User = Depends(utils.get_current_user),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    if current_user.role not in ["club", "admin"]:
        raise HTTPException(403, detail="Deleting announcements is not allowed for this user")

    db_a = (
        db.query(models.Announcement)
        .options(joinedload(models.Announcement.owner))
        .filter(models.Announcement.id == announcement_id)
        .first()
    )
    if not db_a:
        raise HTTPException(404, detail="Announcement not found")

    if current_user.role == "club" and db_a.club_id != current_user.id:
        raise HTTPException(403, detail="You can only delete your own announcements")

    response = map_announcement_to_response(db_a)

    # Clean up cover image from Supabase Storage
    if db_a.cover_image:
        try:
            storage.delete_from_supabase(db_a.cover_image)
        except Exception:
            logger.info(f"Failed to delete announcement image: {db_a.cover_image}")

    try:
        db.delete(db_a)
        db.commit()
        bg_tasks.add_task(revalidate_frontend, ["announcements"])
    except Exception as e:
        db.rollback()
        logger.info(f"Error deleting announcement: {e}")
        raise HTTPException(500, detail="Failed to delete announcement")

    return schemas.SingleAnnouncementResponse(success=True, data=response)


# ==================== CONTACT ====================

@api.post("/contact")
@limiter.limit("5/minute")
async def handle_contact(
    request: Request,
    response: Response,
    contact_data: schemas.ContactRequest,
    db: Session = Depends(database.get_db),
    #token: str = Depends(verify_api_key),
):
    try:
        query = insert(models.Contact).values(email=contact_data.email, message=contact_data.message, date=datetime.now())
        result = db.execute(query)
        db.commit()

        
        return {"success": True}
        

    except Exception as e:
        logger.info(f"Exception occured in handle_contact: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal Server Error, please try again later")

@api.get("/get_contacts")
async def get_contacts(
    user : models.User = Depends(utils.get_current_user),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    try:
        if user.role != "admin":
            raise HTTPException(status_code=403, detail="Forbidden, please don't try")

        now = datetime.now()
        a_month_ago = now - dt.timedelta(30)

        query = select(models.Contact).where(models.Contact.date > a_month_ago)
        result = db.execute(query).scalars().all()

        if not result:
            raise HTTPException(status_code=404, detail="No contact found")
        
        c_to_returns = []
        for c in result:
            c_to_returns.append(schemas.Contact(email=c.email, message=c.message, date=c.date))

        logger.info(c_to_returns)

        return schemas.ContactReturn(success=True, data=c_to_returns)

        
    except HTTPException as he:
        raise he

    except Exception as e:
        logger.info(f"Exception occured in get_contacts: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal Sever Error, please try again later")
    

if __name__ == "__main__":

    port = int(os.getenv("BACKEND_PORT", 4444))
    environment = os.getenv("ENVIRONMENT", "development")

    uvicorn.run(
        "main:api",
        host="0.0.0.0",
        port=port,
        reload=(environment == "development")  # Only reload in dev mode
    )


# ---------------------------------------------------------------------------
# Admin approval inbox: candidate events awaiting review before they go public.
# What fills the staging table is external — see pipeline_import.py where installed.
# ---------------------------------------------------------------------------

DEFAULT_DURATION_HOURS = 2.0
DEFAULT_LOCATION_TYPE = models.LocationType.ON_CAMPUS.value
# Instagram CDN URLs are signed and expire within days, so a published event must never
# point at one — the image is copied into our own storage at approval time.
MAX_REHOST_BYTES = 15 * 1024 * 1024


# --- helpers ---------------------------------------------------------------

def map_scraped_to_response(
    row: models.ScrapedEvent, club_is_remembered: bool = False
) -> schemas.ScrapedEventResponse:
    return schemas.ScrapedEventResponse(
        id=str(row.id),
        source=str(row.source),
        source_event_id=str(row.source_event_id),
        kind=str(row.kind or "event"),
        club_username=row.club_username,
        post_shortcode=row.post_shortcode,
        post_url=row.post_url,
        post_caption=row.post_caption,
        post_image_url=row.post_image_url,
        posted_at=row.posted_at,
        title=row.title,
        date=row.date,
        location=row.location,
        description=row.description,
        confidence=float(row.confidence or 0.0),
        category=row.category,
        link=row.link,
        expires_at=row.expires_at,
        status=_status(row),
        rejection_reason=row.rejection_reason,
        reviewed_at=row.reviewed_at,
        club_id=row.club_id,
        club_name=row.club.club_name if row.club else None,
        club_is_remembered=club_is_remembered,
        created_event_id=row.created_event_id,
        created_announcement_id=row.created_announcement_id,
        created_at=row.created_at,
    )


def _unique_slug(db: Session, base: str) -> str:
    slug = models.generate_slug(base) or "event"
    candidate, n = slug, 2
    while db.execute(select(models.Event.id).where(models.Event.slug == candidate)).first():
        candidate = f"{slug}-{n}"
        n += 1
    return candidate


def _unique_announcement_slug(db: Session, base: str) -> str:
    slug = models.generate_slug(base) or "announcement"
    candidate, n = slug, 2
    while db.execute(select(models.Announcement.id).where(models.Announcement.slug == candidate)).first():
        candidate = f"{slug}-{n}"
        n += 1
    return candidate


def _add_hours(hhmm: str, hours: float) -> str:
    h, m = map(int, hhmm.split(":"))
    total = (h * 60 + m + int(round(hours * 60))) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _status(row: models.ScrapedEvent) -> str:
    """Status comes back as the enum member or a plain string depending on the driver."""
    return getattr(row.status, "value", row.status)


def rehost_image(source_url: str, shortcode: str) -> Optional[str]:
    """Copy a source image into Supabase Storage and return the public URL.

    Returns None if anything goes wrong — approval must not fail because an image could
    not be fetched; the caller falls back to the original URL and logs it.
    """
    public_prefix = f"{storage.SUPABASE_URL}/storage/v1/object/public/{storage.STORAGE_BUCKET}/"
    if storage.SUPABASE_URL and source_url.startswith(public_prefix):
        return source_url
    try:
        r = requests.get(source_url, timeout=30, stream=True)
        r.raise_for_status()

        declared = r.headers.get("content-length")
        if declared and int(declared) > MAX_REHOST_BYTES:
            logger.info("scraped events: image too large to re-host (%s bytes)", declared)
            return None

        content = b""
        for chunk in r.iter_content(chunk_size=64 * 1024):
            content += chunk
            if len(content) > MAX_REHOST_BYTES:
                logger.info("scraped events: image exceeded %d bytes, aborting", MAX_REHOST_BYTES)
                return None

        compressed, ext = storage.compress_image(content)
        filename = f"scraped/{shortcode}-{uuid.uuid4().hex[:8]}.{ext}"
        return storage.upload_to_supabase(compressed, filename, f"image/{ext}")
    except Exception as e:
        logger.info("scraped events: could not re-host %s: %s", source_url, e)
        return None


def resolve_publisher(db: Session, club_username: str) -> Optional[models.User]:
    """Which user does this Instagram handle publish under?

    A remembered mapping (set by the admin in the panel) wins; otherwise fall back to a
    club that has declared the handle as its own. Returns None when the handle is unknown —
    the row then shows up unmatched and waits for the admin to choose.
    """
    mapping = (
        db.query(models.IgClubMapping)
        .filter(models.IgClubMapping.club_username == club_username)
        .first()
    )
    if mapping and mapping.user:
        return mapping.user
    return db.query(models.User).filter(models.User.ig_username == club_username).first()


def remember_publisher(db: Session, club_username: str, user_id: str) -> None:
    """Persist the admin's choice so the next post from this handle arrives pre-filled.

    Always overwritable — the admin can pick a different club on a later row and that
    becomes the new default. Does not commit; the caller owns the transaction.
    """
    mapping = (
        db.query(models.IgClubMapping)
        .filter(models.IgClubMapping.club_username == club_username)
        .first()
    )
    if mapping:
        if mapping.user_id != user_id:
            mapping.user_id = user_id
    else:
        db.add(models.IgClubMapping(club_username=club_username, user_id=user_id))


def _has_mapping(db: Session, club_username: str) -> bool:
    return (
        db.query(models.IgClubMapping.id)
        .filter(models.IgClubMapping.club_username == club_username)
        .first()
        is not None
    )


def _get_or_404(db: Session, scraped_id: str) -> models.ScrapedEvent:
    row = db.query(models.ScrapedEvent).filter(models.ScrapedEvent.id == scraped_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Scraped event not found")
    return row


# --- endpoints -------------------------------------------------------------

@api.post("/admin/scraped-events/import", response_model=schemas.ScrapedEventImportResponse)
async def import_scraped_events(
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    """Pull newly extracted events out of the pipeline DB into the approval inbox."""
    # The scraping pipeline is local-only: the module is absent on the deployed server, and
    # importing it lazily also keeps it free to import from this one.
    try:
        from pipeline_import import import_from_pipeline
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="The scraping pipeline is not installed on this server — run the importer locally",
        )

    try:
        stats = import_from_pipeline(db)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.info("Exception occured in import scraped events: %s", e)
        raise HTTPException(status_code=500, detail="Could not import scraped events")

    return schemas.ScrapedEventImportResponse(success=True, data=stats)


@api.get("/admin/scraped-events", response_model=schemas.MultiScrapedEventResponse)
async def list_scraped_events(
    status: str = Query("pending"),
    kind: Optional[str] = Query(None, description='"event" or "announcement"'),
    club_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    """Inbox listing. `status` accepts pending / approved / rejected / all."""
    valid = {s.value for s in models.ScrapedEventStatus} | {"all"}
    if status not in valid:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(valid)}")

    if kind and kind not in ("event", "announcement"):
        raise HTTPException(status_code=400, detail='kind must be "event" or "announcement"')

    base_query = select(models.ScrapedEvent)
    if status != "all":
        base_query = base_query.where(models.ScrapedEvent.status == status)
    if kind:
        base_query = base_query.where(models.ScrapedEvent.kind == kind)
    if club_id:
        base_query = base_query.where(models.ScrapedEvent.club_id == club_id)

    try:
        total = db.execute(select(func.count()).select_from(base_query.subquery())).scalar()
        query = (
            base_query.order_by(
                desc(models.ScrapedEvent.confidence), asc(models.ScrapedEvent.date)
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = db.execute(query).scalars().all()
    except Exception as e:
        db.rollback()
        logger.info("Exception occured in list scraped events: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")

    remembered = {
        m.club_username
        for m in db.query(models.IgClubMapping.club_username).all()
    }
    return schemas.MultiScrapedEventResponse(
        success=True,
        data=[
            map_scraped_to_response(r, r.club_username in remembered) for r in rows
        ],
        pagination=paginate(page, page_size, total),
    )


@api.get("/admin/scraped-events/{scraped_id}", response_model=schemas.SingleScrapedEventResponse)
async def get_scraped_event(
    scraped_id: str,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    row = _get_or_404(db, scraped_id)
    return schemas.SingleScrapedEventResponse(
        success=True, data=map_scraped_to_response(row, _has_mapping(db, row.club_username))
    )


@api.patch("/admin/scraped-events/{scraped_id}", response_model=schemas.SingleScrapedEventResponse)
async def update_scraped_event(
    scraped_id: str,
    payload: schemas.ScrapedEventUpdate,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    """Fix what the extractor got wrong (or attach the club) before approving."""
    row = _get_or_404(db, scraped_id)
    if _status(row) == models.ScrapedEventStatus.APPROVED.value:
        raise HTTPException(status_code=409, detail="Already approved — edit the published event instead")

    updates = payload.model_dump(exclude_unset=True)
    if "club_id" in updates and updates["club_id"] is not None:
        if not db.query(models.User).filter(models.User.id == updates["club_id"]).first():
            raise HTTPException(status_code=404, detail="Club not found")

    for field, value in updates.items():
        setattr(row, field, value)

    # Picking a club here teaches the mapping, so the next post from this handle arrives set.
    if updates.get("club_id"):
        remember_publisher(db, row.club_username, updates["club_id"])

    try:
        db.commit()
        db.refresh(row)
    except Exception as e:
        db.rollback()
        logger.info("Exception occured in update scraped event: %s", e)
        raise HTTPException(status_code=500, detail="Could not update scraped event")

    return schemas.SingleScrapedEventResponse(
        success=True, data=map_scraped_to_response(row, _has_mapping(db, row.club_username))
    )


@api.post("/admin/scraped-events/{scraped_id}/approve", response_model=schemas.SingleEventResponse)
async def approve_scraped_event(
    scraped_id: str,
    payload: schemas.ScrapedEventApprove,
    bg_tasks: BackgroundTasks,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    """Publish a staged event: creates the real Event and marks the staging row approved."""
    row = _get_or_404(db, scraped_id)
    if _status(row) == models.ScrapedEventStatus.APPROVED.value:
        raise HTTPException(status_code=409, detail="Scraped event already approved")
    if row.kind == "announcement":
        raise HTTPException(
            status_code=400,
            detail="This candidate is an announcement — approve it at "
                   "/admin/scraped-events/{id}/approve-announcement",
        )

    # publishAsAdmin covers handles whose club is not on the platform, or does not want
    # its name on the listing — the event goes out under the admin account instead.
    club_id = current_user.id if payload.publish_as_admin else (payload.club_id or row.club_id)
    if not club_id:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No club linked to @{row.club_username} — set clubId, or pass "
                "publishAsAdmin to publish it under the admin account"
            ),
        )
    club = db.query(models.User).filter(models.User.id == club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    # Date: admin override wins, else the extracted timestamp.
    event_date = payload.date or (row.date.date() if row.date else None)
    if not event_date:
        raise HTTPException(status_code=400, detail="No date on this event — set date before approving")

    title = payload.title or row.title
    if not title:
        raise HTTPException(status_code=400, detail="No title on this event — set title before approving")

    location = payload.location or row.location
    if not location:
        raise HTTPException(status_code=400, detail="No location on this event — set location before approving")

    # Time: the extractor only knows a timestamp, so fall back to its time-of-day.
    start_time = payload.start_time or (row.date.strftime("%H:%M") if row.date else "00:00")
    duration = payload.duration or DEFAULT_DURATION_HOURS
    end_time = payload.end_time or _add_hours(start_time, duration)

    location_type = payload.location_type or DEFAULT_LOCATION_TYPE
    if location_type not in {t.value for t in models.LocationType}:
        raise HTTPException(status_code=400, detail="Invalid locationType")

    # A custom cover typed by the admin is taken as-is; the scraped post image is copied
    # into our storage first, so the published event does not rot when the CDN link expires.
    if payload.cover_image:
        cover_image = payload.cover_image
    elif row.post_image_url:
        cover_image = rehost_image(row.post_image_url, row.post_shortcode) or row.post_image_url
        if cover_image == row.post_image_url:
            logger.info(
                "[%s] re-host failed — publishing with the source URL, which may expire",
                row.post_shortcode,
            )
    else:
        cover_image = None

    db_event = models.Event(
        slug=_unique_slug(db, f"{title} {event_date}"),
        title=title,
        description=payload.description or row.description or "",
        club_id=club.id,
        date=event_date,
        start_time=start_time,
        end_time=end_time,
        duration=duration,
        location_type=location_type,
        location=location,
        cover_image=cover_image,
        tags=",".join(payload.tags) if payload.tags else "",
        is_registration_open=payload.is_registration_open,
        registration_link=payload.registration_link,
        capacity=payload.capacity,
    )

    try:
        db.add(db_event)
        db.flush()

        # Remember the choice — including "publish as admin" — for this handle's next post.
        remember_publisher(db, row.club_username, club.id)

        row.status = models.ScrapedEventStatus.APPROVED
        row.club_id = club.id
        row.created_event_id = db_event.id
        row.reviewed_at = dt.datetime.utcnow()
        row.reviewed_by = current_user.id
        row.rejection_reason = None

        db.commit()
        db.refresh(db_event)
    except Exception as e:
        db.rollback()
        logger.info("Exception occured in approve scraped event: %s", e)
        raise HTTPException(status_code=500, detail="Could not publish event")

    bg_tasks.add_task(revalidate_frontend, ["events"])
    return schemas.SingleEventResponse(success=True, data=map_event_to_response(db_event))


@api.post("/admin/scraped-events/{scraped_id}/approve-announcement",
          response_model=schemas.SingleAnnouncementResponse)
async def approve_scraped_announcement(
    scraped_id: str,
    payload: schemas.ScrapedAnnouncementApprove,
    bg_tasks: BackgroundTasks,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    """Publish a staged announcement: creates the real Announcement and marks the row approved."""
    row = _get_or_404(db, scraped_id)
    if _status(row) == models.ScrapedEventStatus.APPROVED.value:
        raise HTTPException(status_code=409, detail="Scraped candidate already approved")
    if row.kind != "announcement":
        raise HTTPException(
            status_code=400,
            detail="This candidate is an event — approve it at "
                   "/admin/scraped-events/{id}/approve",
        )

    club_id = current_user.id if payload.publish_as_admin else (payload.club_id or row.club_id)
    if not club_id:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No club linked to @{row.club_username} — set clubId, or pass "
                "publishAsAdmin to publish it under the admin account"
            ),
        )
    club = db.query(models.User).filter(models.User.id == club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    title = payload.title or row.title
    if not title:
        raise HTTPException(status_code=400, detail="No title on this announcement — set title before approving")

    body = payload.body or row.description
    if not body:
        raise HTTPException(status_code=400, detail="No body on this announcement — set body before approving")

    category = payload.category or row.category or models.AnnouncementCategory.GENERAL.value
    if category not in {c.value for c in models.AnnouncementCategory}:
        raise HTTPException(status_code=400, detail="Invalid category")

    # Same reasoning as events: a custom cover is taken as-is, the post image is copied into
    # our storage so the published announcement does not rot when the CDN link expires.
    if payload.cover_image:
        cover_image = payload.cover_image
    elif row.post_image_url:
        cover_image = rehost_image(row.post_image_url, row.post_shortcode) or row.post_image_url
    else:
        cover_image = None

    db_announcement = models.Announcement(
        slug=_unique_announcement_slug(db, title),
        title=title,
        body=body,
        cover_image=cover_image,
        link=payload.link or row.link,
        tags=",".join(payload.tags) if payload.tags else "",
        category=category,
        is_pinned=payload.is_pinned,
        expires_at=payload.expires_at or row.expires_at,
        club_id=club.id,
    )

    try:
        db.add(db_announcement)
        db.flush()

        remember_publisher(db, row.club_username, club.id)
        row.status = models.ScrapedEventStatus.APPROVED
        row.club_id = club.id
        row.created_announcement_id = db_announcement.id
        row.reviewed_at = dt.datetime.utcnow()
        row.reviewed_by = current_user.id
        row.rejection_reason = None

        db.commit()
        db.refresh(db_announcement)
    except Exception as e:
        db.rollback()
        logger.info("Exception occured in approve scraped announcement: %s", e)
        raise HTTPException(status_code=500, detail="Could not publish announcement")

    bg_tasks.add_task(revalidate_frontend, ["announcements"])
    return schemas.SingleAnnouncementResponse(
        success=True, data=map_announcement_to_response(db_announcement)
    )


@api.post("/admin/scraped-events/{scraped_id}/reject", response_model=schemas.SingleScrapedEventResponse)
async def reject_scraped_event(
    scraped_id: str,
    payload: schemas.ScrapedEventReject,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    row = _get_or_404(db, scraped_id)
    if _status(row) == models.ScrapedEventStatus.APPROVED.value:
        raise HTTPException(status_code=409, detail="Already approved — delete the published event instead")

    row.status = models.ScrapedEventStatus.REJECTED
    row.rejection_reason = payload.rejection_reason
    row.reviewed_at = dt.datetime.utcnow()
    row.reviewed_by = current_user.id

    try:
        db.commit()
        db.refresh(row)
    except Exception as e:
        db.rollback()
        logger.info("Exception occured in reject scraped event: %s", e)
        raise HTTPException(status_code=500, detail="Could not reject scraped event")

    return schemas.SingleScrapedEventResponse(success=True, data=map_scraped_to_response(row))


@api.delete("/admin/scraped-events/{scraped_id}", response_model=schemas.ApiResponse)
async def delete_scraped_event(
    scraped_id: str,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    """Drop a staging row. The published event, if any, is left untouched."""
    row = _get_or_404(db, scraped_id)
    try:
        db.delete(row)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.info("Exception occured in delete scraped event: %s", e)
        raise HTTPException(status_code=500, detail="Could not delete scraped event")

    return schemas.ApiResponse(success=True)


# --- remembered handle → publisher mappings -------------------------------

@api.get("/admin/ig-club-mappings", response_model=schemas.MultiIgClubMappingResponse)
async def list_ig_club_mappings(
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    """Which Instagram handle publishes under which account, as learned from approvals."""
    rows = (
        db.query(models.IgClubMapping)
        .order_by(asc(models.IgClubMapping.club_username))
        .all()
    )
    return schemas.MultiIgClubMappingResponse(
        success=True,
        data=[
            schemas.IgClubMappingResponse(
                club_username=m.club_username,
                user_id=m.user_id,
                user_name=m.user.club_name if m.user else "(deleted)",
                is_admin=bool(m.user and m.user.role == models.UserRole.ADMIN.value),
                updated_at=m.updated_at,
            )
            for m in rows
        ],
    )


@api.delete("/admin/ig-club-mappings/{club_username}", response_model=schemas.ApiResponse)
async def delete_ig_club_mapping(
    club_username: str,
    current_user: models.User = Depends(require_admin),
    db: Session = Depends(database.get_db),
    token: str = Depends(verify_api_key),
):
    """Forget a handle's publisher. Already-staged rows keep whatever club they have."""
    mapping = (
        db.query(models.IgClubMapping)
        .filter(models.IgClubMapping.club_username == club_username.lstrip("@"))
        .first()
    )
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")

    try:
        db.delete(mapping)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.info("Exception occured in delete ig club mapping: %s", e)
        raise HTTPException(status_code=500, detail="Could not delete mapping")

    return schemas.ApiResponse(success=True)
