import uuid
import requests
import os
from dotenv import load_dotenv
import shutil
import uvicorn
import fastapi
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
from fastapi import HTTPException, Query, FastAPI, File, UploadFile, status, Depends, Header, Request, Response, BackgroundTasks
from pydantic import BaseModel
from datetime import datetime, timedelta
import datetime as dt
from sqlalchemy.orm import Session, joinedload, contains_eager
from sqlalchemy import select, asc, desc, or_
import time
from typing import Dict, List, Optional
from datetime import datetime
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from data import club_data, event_data
import database, models, schemas, utils

models.Base.metadata.create_all(bind=database.engine)

load_dotenv()

VALID_API_KEY = os.getenv("API_SECRET_KEY")
NEXTJS_URL = os.getenv("NEXTJS_APP_URL", "http://localhost:3000")
REVALIDATION_TOKEN = os.getenv("REVALIDATION_TOKEN")

# request limiter
limiter = Limiter(key_func=get_remote_address)

#create api
api = FastAPI()

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

api.mount("/static", StaticFiles(directory="uploads"), name="static")

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}

# helper
def get_week_range(ref_date_str: str):
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
            print(f"✅ Revalidation triggered for: {tags}")
        else:
            print(f"⚠️ Revalidation failed: {response.text}")
            
    except Exception as e:
        print(f"❌ Error triggering revalidation: {e}")

@api.get("/health")
async def health_check():
    return {"status": "healthy"}

# main page request to get events
@api.get("/events/weekly", response_model=schemas.MultiEventResponse)
@limiter.limit("10/minute") # Only 10 requests allowed per IP per minute
async def weekly_events(
    request: Request,  
    response: Response,
    date: str = Query(..., description="Any date within the desired week (YYYY-MM-DD)"), 
    db: Session = Depends(database.get_db), 
    token: str = Depends(verify_api_key),
):
    
    try:
        week_beginning, week_end = get_week_range(date)
    
        get_weekly_events_query = (select(models.Event)
                                    .join(models.Event.owner)
                                    .options(contains_eager(models.Event.owner))
                                    .where(models.Event.date >= week_beginning.date())
                                    .where(models.Event.date < week_end.date())
                                    .order_by(models.Event.date.asc())
                                )
        result = db.execute(get_weekly_events_query)
    
        db_events = result.scalars().unique().all()

        data_to_send = []
        
        for event in db_events:
            
            event_dto = schemas.EventResponse(
                # 1. Flattened Fields (Manual)
                club_name=event.owner.club_name if event.owner else "Unknown",
                
                # 2. Direct Fields (Pydantic maps these automatically)
                id=str(event.id),
                club_id=str(event.club_id),
                title=event.title,
                description=event.description,
                date=event.date, # Pydantic handles date -> string conversion
                start_time=event.start_time,
                end_time=event.end_time,
                duration=event.duration,
                location_type=event.location_type,
                location=event.location,
                cover_image=event.cover_image,
                
                # 3. Defaults/Computed
                is_registration_open=event.is_registration_open,
                registration_link=event.registration_link,
                capacity=event.capacity if hasattr(event, 'capacity') else None
            )
            data_to_send.append(event_dto)

        # ✅ Correct Return Type: MultiEventResponse (for lists)
        return schemas.MultiEventResponse(success=True, data=data_to_send)

    except Exception as e:
        print(f"❌ CRITICAL ERROR in weekly_events: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error. Please contact support.")


# get single event
@api.get("/events/{event_id}", response_model=schemas.SingleEventResponse)
async def handle_events(event_id: str, db: Session = Depends(database.get_db)):

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
                

        event_complex = schemas.EventResponse(
            id=str(event.id),
            title=str(event.title),
            description=str(event.description),
            
            # Club Info (Fetched via joinedload)
            club_id=str(event.club_id),
            club_name=event.owner.club_name if event.owner else "Unknown Club",
            
            # Time
            date=event.date,
            start_time=str(event.start_time),
            end_time=str(event.end_time),
            duration=float(event.duration),
            
            # Location
            location_type=str(event.location_type),
            location=str(event.location),
            
            # Visuals & Details
            cover_image=str(event.cover_image),
            tags=list(event.tags), 
            is_registration_open=event.is_registration_open,
            registration_link=event.registration_link,
            capacity=event.capacity
        )

        return schemas.SingleEventResponse(success=True, data=event_complex)
            
    except HTTPException as he: # re-raise
        raise he
    
    except Exception as e:
        print("exception: ", e)
        raise HTTPException(400, detail=f"Exception occured in handle events: {str(e)}")
    
    

# get single club
@api.get("/clubs/{club_id}", response_model=schemas.ClubApiResponse)
async def handle_club(club_id: str, db: Session = Depends(database.get_db)):

    try:
        query = (
            select(models.User)
            .where(models.User.id == club_id)
        )
    
        club = db.execute(query).scalars().first()
    
        if not club:
            raise HTTPException(404, detail=f"No event found with id {club_id}")
        
        club_data = schemas.ClubResponse(
            id = str(club.id),
            slug = club.slug,
            club_name= club.club_name,
            email = club.email,
            description= club.description,
            logo_url= club.logo_url,
            banner_url= club.banner_url,
            is_verified=bool(club.is_verified),
            role=str(club.role),
            rejection_reason=str(club.rejection_reason)
        )
        
        return schemas.ClubApiResponse(success=True, data=club_data)
            
    except Exception as e:
        print("exception: ", e)
        raise HTTPException(status_code=500, detail=f"Error occured in handle club: {str(e)}")
    

    
# get club's events
@api.get("/clubs/{club_id}/events", response_model=schemas.MultiEventResponse)
async def handle_club_events(club_id: str, db: Session = Depends(database.get_db)):

    try:
        query = (
            select(models.Event)
            .options(joinedload(models.Event.owner))
            .where(models.Event.club_id == club_id)
        )
    
        result = db.execute(query).scalars().unique().all()
    
        if not result:
            raise HTTPException(status_code=404, detail="No event found")
        
        clubs_events = []
        for event in result:
    
            event_to_return = schemas.EventResponse(
                id = str(event.id),
                title = str(event.title),
                description= str(event.description),
                club_id=str(event.club_id),
                club_name=event.owner.club_name if event.owner else "Unknown Club",
                
                # Time
                date=event.date,
                start_time=str(event.start_time),
                end_time=str(event.end_time),
                duration=float(event.duration),
                
                # Location
                location_type=str(event.location_type),
                location=str(event.location),
                
                # Visuals & Details
                cover_image=str(event.cover_image),
                tags=list(event.tags), 
                is_registration_open=event.is_registration_open,
                registration_link=event.registration_link,
                capacity=event.capacity
            )
            clubs_events.append(event_to_return)
    
        return schemas.MultiEventResponse(success=True, data=clubs_events)

    except Exception as e:
        print("Exception: ", e)
        raise HTTPException(400, detail=f"Exception occured in handle club events: {str(e)}")

@api.post("/upload")
async def upload_image(file: UploadFile = File(...)):
    try:
        # 1. Safety Check: Does the file have a name?
        if not file.filename:
            raise HTTPException(status_code=400, detail="File must have a name")

        # 2. Safety Check: Is it an allowed image type?
        # Get extension, lowercase it to match 'JPG' and 'jpg'
        file_extension = file.filename.split(".")[-1].lower()
        
        if file_extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")

        # 3. Generate unique name
        unique_filename = f"{uuid.uuid4()}.{file_extension}"
        file_location = f"uploads/{unique_filename}"
        
        # 4. Save the file
        with open(file_location, "wb+") as file_object:
            shutil.copyfileobj(file.file, file_object)
            
        return {"url": f"http://localhost:4444/static/{unique_filename}"}
        
    except HTTPException as he:
        raise he # Re-raise HTTP exceptions (like thedayEvents 400s above)
    except Exception as e:
        print(f"Upload Error: {e}")
        raise HTTPException(status_code=500, detail="Image upload failed server-side")


@api.post("/signup", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(user: schemas.UserCreate, db: Session = Depends(database.get_db)):
    
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
    
    return new_user

@api.post("/login", response_model=schemas.Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(), 
    db: Session = Depends(database.get_db)
):
    # 1. Find the user
    # Note: OAuth2PasswordRequestForm expects 'username', but we treat it as 'email'
    user = db.query(models.User).filter_by(email = form_data.username).first()
    
    # 2. Verify User and Password
    if not user or not utils.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 3. Create Token
    access_token = utils.create_access_token(data={"sub": user.email})
    
    # 4. Return it
    return {"access_token": access_token, "token_type": "bearer"}


# posting an event (IMPORTANT NOTE: when an event is created (with mock up auth), it doesnt show up as expected in calendar, maybe its about auth or admin)
@api.post("/events", response_model=schemas.SingleEventResponse)
async def create_event(
    event_in: schemas.EventCreate, 
    bg_tasks: BackgroundTasks,
    db: Session = Depends(database.get_db)
):
    
    # 1. Fetch the Club trying to post
    # (In a real app, this comes from the JWT Token. Here we look up the ID sent in the body)
    club = db.query(models.User).filter(models.User.id == event_in.club_id).first()
    
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    # 2. ✅ CHECK: Block Event Creation if Unverified
    if not bool(club.is_verified) and str(club.role) != "admin":
        raise HTTPException(
            status_code=403, 
            detail="Your club is not verified yet. You cannot post events."
        )
    

    # 1. Generate a Slug (Title + Date)
    raw_slug = f"{event_in.title} {event_in.date}"
    slug = models.generate_slug(raw_slug)

    # 2. Create the DB Object
    # We unpack (**dict) the Pydantic model, but we need to exclude 
    # fields that don't match the DB column names exactly if we mapped them differently
    
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
        tags=list(event_in.tags), 
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
        created_event = schemas.EventResponse(
            id=str(db_event.id),
            title=str(db_event.title),
            description=str(db_event.description),
            club_id=str(db_event.club_id),
            club_name=db_event.owner.club_name if db_event.owner else "Loading...",
            date=db_event.date,
            start_time=str(db_event.start_time),
            end_time=str(db_event.end_time),
            duration=db_event.duration,
            location_type=str(db_event.location_type),
            location=str(db_event.location),
            cover_image=str(db_event.cover_image),
            tags=list(db_event.tags), 
            is_registration_open=db_event.is_registration_open,
            registration_link=db_event.registration_link,
            capacity=db_event.capacity
        )

        bg_tasks.add_task(revalidate_frontend, ["events"])

        return schemas.SingleEventResponse(success=True, data=created_event)
        
    except Exception as e:
        db.rollback()
        print(f"Error creating event: {e}")
        raise HTTPException(status_code=500, detail="Could not create event")

# get all clubs for the admin page and club list
@api.get("/all_clubs", response_model=schemas.AllClubsResponse)
async def get_all_clubs(db: Session = Depends(database.get_db)):

    try:
        query = (
            select(models.User)
        )

        result = db.execute(query).scalars().all()

        if not result:
            raise HTTPException(status_code=404, detail="No club found")
        
        clubs_to_return = []
        for club in result:
            club_to_add = schemas.ClubResponse(
                id=str(club.id),
                slug=club.slug,
                club_name=club.club_name,
                email=club.email,
                description=club.description,
                logo_url=club.logo_url,
                banner_url=club.banner_url,
                is_verified=bool(club.is_verified),
                role=str(club.role),
                rejection_reason=str(club.rejection_reason)
            )

            clubs_to_return.append(club_to_add)

        return schemas.AllClubsResponse(success=True, data=clubs_to_return)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting all clubs: {e}")

# club update (profile update) by admin or club owner
@api.patch("/clubs/{club_id}", response_model=schemas.ClubApiResponse)
async def update_club(
    club_id: str, 
    club_update: schemas.ClubUpdate, 
    bg_tasks: BackgroundTasks,
    db: Session = Depends(database.get_db)
):
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

    # 3. Commit to Database
    try:
        db.commit()
        db.refresh(club) # Reloads the object with new data from DB

        bg_tasks.add_task(revalidate_frontend, ["clubs", "events"])
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update club: {str(e)}")

    # 4. Return the updated club (formatted for the response schema)
    return schemas.ClubApiResponse(
        success=True,
        data=schemas.ClubResponse(
            id=str(club.id),
            slug=club.slug,
            email=club.email,
            club_name=club.club_name,
            description=club.description,
            logo_url=club.logo_url,
            banner_url=club.banner_url,
            is_verified=bool(club.is_verified),
            role=str(club.role),
            rejection_reason=str(club.rejection_reason)
        )
    )

# get all clubs for admin
@api.get("/admin/clubs", response_model=schemas.AllClubsResponse)
async def get_all_clubs_admin(
    status: Optional[str] = None, # Optional filter: 'verified', 'pending'
    db: Session = Depends(database.get_db)
):
    """
    Fetches ALL clubs (including unverified ones) for the Admin Dashboard.
    """
    query = select(models.User).where(models.User.role == "club")
    
    if status == 'verified':
        query = query.where(models.User.is_verified == True)
    elif status == 'pending':
        query = query.where(models.User.is_verified == False)
        
    query = query.order_by(
        asc(models.User.is_verified), 
        asc(models.User.club_name)
    )

    clubs = db.execute(query).scalars().all()
    clubs_to_return = []
    for club in clubs:
        c = schemas.ClubResponse(
            id=str(club.id),
            slug=club.slug,
            email=club.email,
            club_name=club.club_name,
            description=club.description,
            logo_url=club.logo_url,
            banner_url=club.banner_url,
            is_verified=bool(club.is_verified),
            role=str(club.role),
            rejection_reason=str(club.rejection_reason)
        )
        clubs_to_return.append(c)
    print(clubs_to_return)
    return schemas.AllClubsResponse(success=True, data=clubs_to_return)


# 1. ADMIN: SET CLUB STATUS
@api.patch("/admin/clubs/{club_id}/status", response_model=schemas.ClubApiResponse)
async def set_club_verification(
    club_id: str,
    status_update: schemas.ClubStatusUpdate,
    bg_tasks: BackgroundTasks,
    db: Session = Depends(database.get_db)
):
    """
    Admin endpoint to Verify or Reject a club.
    """
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
        data=schemas.ClubResponse(
            id=str(club.id),
            slug=club.slug,
            email=club.email,
            
            # Pass snake_case args; CamelModel handles "clubName", "logoUrl", etc.
            club_name=club.club_name,
            description=club.description,
            logo_url=club.logo_url,
            banner_url=club.banner_url,
            
            is_verified=club.is_verified,
            role=club.role,
            rejection_reason=club.rejection_reason
        )
    )


# 2. CLUB: UPDATE EVENT
@api.patch("/events/{event_id}", response_model=schemas.SingleEventResponse)
async def update_event(
    event_id: str,
    event_update: schemas.EventUpdate,
    bg_tasks: BackgroundTasks,
    db: Session = Depends(database.get_db)
):
    # 1. Find Event
    db_event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not db_event:
        raise HTTPException(status_code=404, detail="Event not found")

    # 2. Get the Club (Owner)
    club = db.query(models.User).filter(models.User.id == db_event.club_id).first()

    if not club:
        raise HTTPException(status_code=500, detail="Event owner not found.")
    
    # 3. Permission Check
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
        db_event.registration_link = event_update.registration_link
    if event_update.capacity is not None: 
        db_event.capacity = event_update.capacity

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
        data=schemas.EventResponse(
            id=str(db_event.id),
            
            # Flatten club_name from the relationship
            club_id=str(db_event.club_id),
            club_name=club.club_name,
            
            title=db_event.title,
            description=db_event.description,
            date=db_event.date,
            start_time=db_event.start_time,
            end_time=db_event.end_time,
            duration=db_event.duration,
            location_type=db_event.location_type,
            location=db_event.location,
            cover_image=db_event.cover_image,
            tags=list(db_event.tags), 
            
            # ✅ FIX: Use the actual values from DB (or updated values)
            is_registration_open=db_event.is_registration_open,
            registration_link=db_event.registration_link,
            capacity=int(db_event.capacity) if db_event.capacity else None
        )
    )

@api.get("/clubs", response_model=schemas.AllClubsResponse)
async def get_all_clubs_user(
    search: Optional[str] = None, 
    db: Session = Depends(database.get_db)
):
    """
    Public directory of all verified clubs.
    """
    query = db.query(models.User).filter(
        models.User.role == "club",
        models.User.is_verified == True
    )

    if search:
        search_fmt = f"%{search}%"
        query = query.filter(
            or_(
                models.User.club_name.ilike(search_fmt),
                models.User.description.ilike(search_fmt)
            )
        )
    
    # Sort alphabetically
    query = query.order_by(models.User.club_name.asc())
    
    clubs = query.all()

    clubs_to_return = []

    for cl in clubs:
        clubs_to_return.append(schemas.ClubResponse(
            id=str(cl.id),
            slug=cl.slug,
            email=cl.email,
            
            # Pass snake_case args; CamelModel handles "clubName", "logoUrl", etc.
            club_name=cl.club_name,
            description=cl.description,
            logo_url=cl.logo_url,
            banner_url=cl.banner_url,
            
            is_verified=cl.is_verified,
            role=cl.role,
            rejection_reason=cl.rejection_reason
        ))

    return schemas.AllClubsResponse(success=True, data=clubs_to_return)


if __name__ == "__main__":

    port = int(os.getenv("BACKEND_PORT", 4444))
    environment = os.getenv("ENVIRONMENT", "development")

    uvicorn.run(
        "main:api",
        host="0.0.0.0",
        port=port,
        reload=(environment == "development")  # Only reload in dev mode
    )