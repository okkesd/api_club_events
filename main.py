import uuid
import os
import shutil
import uvicorn
import fastapi
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordRequestForm
from fastapi import HTTPException, Query, FastAPI, File, UploadFile, status, Depends
from pydantic import BaseModel
from datetime import datetime, timedelta
import datetime as dt
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select, asc, desc
import time
from typing import Dict, List
from datetime import datetime

from data import club_data, event_data
from custom_types import *
from app import database, models, schemas, utils

models.Base.metadata.create_all(bind=database.engine)

#create api
api = FastAPI()

# middlewares
origins = [
    "http://localhost:3000"
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
    

# main page request to get events
@api.get("/events/weekly", response_model=schemas.MainResponse)
async def weekly_events(date: str = Query(..., description="Any date within the desired week (YYYY-MM-DD)"), db: Session = Depends(database.get_db)): # obj: MainRequest

    try:
        week_beginning, week_end = get_week_range(date)
    
        get_weekly_events_query = (select(models.Event, models.User)
                                    .options(joinedload(models.Event.owner))
                                    .where(models.Event.date >= week_beginning.date())
                                    .where(models.Event.date < week_end.date())
                                )
        result = db.execute(get_weekly_events_query)
    
        db_events = result.scalars().unique().all()

        data_to_send = []
        
        for event in db_events:
            # 1. Attach the club_name to the event object so Pydantic can find it
            event_complex = schemas.EventDataComplex(
                id=event.id,
                title=event.title,
                description=event.description,
                
                # Error 1 Fix: Map club_id -> clubID
                clubID=event.club_id,
                
                # Error 2 Fix: Extract club_name from the relation -> clubName
                clubName=event.owner.club_name if event.owner else "Unknown Club", 
                
                # Error 3 Fix: Convert python date object -> string
                date=str(event.date),       
                
                # Error 4 Fix: Map start_time -> startTime
                startTime=event.start_time, 
                endTime=event.end_time,
                duration=event.duration,
                
                # Error 5 Fix: Map location_type -> locationType
                locationType=event.location_type,
                location=event.location,
                
                # Optional fields
                coverImage=event.cover_image,
                tags=[], # Default empty list
                isRegistrationOpen=False, # Default
                registrationLink=None,
                capacity=None
            )
            data_to_send.append(event_complex)

    except Exception as e:
        print("exception: ", e)
        raise HTTPException(status_code=500, detail=f"Exception occured in weekly events: {str(e)}")

    return schemas.MainResponse(success=True, data=data_to_send)


# get single event
@api.get("/events/{event_id}", response_model=schemas.EventResponse)
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
                

        event_complex = schemas.EventDataComplex(
            id=str(event.id),
            title=str(event.title),
            description=str(event.description),
            
            # Club Info (Fetched via joinedload)
            clubID=str(event.club_id),
            clubName=event.owner.club_name if event.owner else "Unknown Club",
            
            # Time
            date=str(event.date),
            startTime=str(event.start_time),
            endTime=str(event.end_time),
            duration=float(event.duration),
            
            # Location
            locationType=str(event.location_type),
            location=str(event.location),
            
            # Visuals & Details
            coverImage=str(event.cover_image),
            tags=[], 
            isRegistrationOpen=False,
            registrationLink=None,
            capacity=None
        )

        return schemas.EventResponse(success=True, data=event_complex)
            
    except HTTPException as he: # re-raise
        raise he
    
    except Exception as e:
        print("exception: ", e)
        raise HTTPException(400, detail=f"Exception occured in handle events: {str(e)}")
    
    

# get single club
@api.get("/clubs/{club_id}", response_model=schemas.ClubResponse)
async def handle_club(club_id: str, db: Session = Depends(database.get_db)):

    try:
        query = (
            select(models.User)
            .where(models.User.id == club_id)
        )
    
        club = db.execute(query).scalars().first()
    
        if not club:
            raise HTTPException(404, detail=f"No event found with id {club_id}")
        
        club_data = schemas.ClubData(
            id = str(club.id),
            slug = club.slug,
            clubName= club.club_name,
            email = club.email,
            description= club.description,
            logoUrl= club.logo_url,
            bannerUrl= club.banner_url,
            is_verified=bool(club.is_verified),
            role=str(club.role),
            rejectionReason=str(club.rejection_reason)
        )
        
        return schemas.ClubResponse(success=True, data=club_data)
            
    except Exception as e:
        print("exception: ", e)
        raise HTTPException(status_code=500, detail=f"Error occured in handle club: {str(e)}")
    

    
# get club's events
@api.get("/clubs/{club_id}/events", response_model=schemas.EventsResponse)
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
    
            event_to_return = schemas.EventDataComplex(
                id = str(event.id),
                title = str(event.title),
                description= str(event.description),
                clubID=str(event.club_id),
                clubName=event.owner.club_name if event.owner else "Unknown Club",
                
                # Time
                date=str(event.date),
                startTime=str(event.start_time),
                endTime=str(event.end_time),
                duration=float(event.duration),
                
                # Location
                locationType=str(event.location_type),
                location=str(event.location),
                
                # Visuals & Details
                coverImage=str(event.cover_image),
                tags=[], 
                isRegistrationOpen=False,
                registrationLink=None,
                capacity=None
            )
            clubs_events.append(event_to_return)
    
        return schemas.EventsResponse(success=True, data=clubs_events)

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


@api.post("/events", response_model=schemas.CreateEventResponse)
async def create_event(
    event_in: schemas.EventCreate, 
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
        date=datetime.strptime(event_in.date, "%Y-%m-%d").date(), # Convert Str -> Date
        start_time=event_in.start_time,
        end_time=event_in.end_time,
        duration=event_in.duration,
        location_type=event_in.location_type,
        location=event_in.location,
        cover_image=event_in.cover_image,
        # If your DB doesn't have 'tags' or 'registration' columns yet, 
        # you might need to skip these or add them to models.py first!
    )
    
    try:
        db.add(db_event)
        db.commit()
        db.refresh(db_event)
        
        # 3. Return the complex response (fetches club name automatically via relationship)
        # We re-query or just construct it manually to match the response schema
        created_event = schemas.EventDataComplex(
            id=str(db_event.id),
            title=str(db_event.title),
            description=str(db_event.description),
            clubID=str(db_event.club_id),
            clubName=db_event.owner.club_name if db_event.owner else "Loading...",
            date=str(db_event.date),
            startTime=str(db_event.start_time),
            endTime=str(db_event.end_time),
            duration=db_event.duration,
            locationType=str(db_event.location_type),
            location=str(db_event.location),
            coverImage=str(db_event.cover_image),
            tags=[], 
            isRegistrationOpen=False,
            registrationLink=None,
            capacity=None
        )

        return schemas.CreateEventResponse(success=True, data=created_event)
        
    except Exception as e:
        db.rollback()
        print(f"Error creating event: {e}")
        raise HTTPException(status_code=500, detail="Could not create event")

@api.get("/all_clubs", response_model=schemas.AllClubs)
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
            club_to_add = schemas.ClubData(
                id=str(club.id),
                slug=club.slug,
                clubName=club.club_name,
                email=club.email,
                description=club.description,
                logoUrl=club.logo_url,
                bannerUrl=club.banner_url,
                is_verified=bool(club.is_verified),
                role=str(club.role),
                rejectionReason=str(club.rejection_reason)
            )

            clubs_to_return.append(club_to_add)

        return schemas.AllClubs(success=True, data=clubs_to_return)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting all clubs: {e}")


@api.patch("/clubs/{club_id}", response_model=schemas.ClubResponse)
async def update_club(
    club_id: str, 
    club_update: schemas.ClubUpdate, 
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
    if club_update.clubName is not None:
        club.club_name = club_update.clubName
        
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
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update club: {str(e)}")

    # 4. Return the updated club (formatted for the response schema)
    return schemas.ClubResponse(
        success=True,
        data=schemas.ClubData(
            id=str(club.id),
            slug=club.slug,
            email=club.email,
            clubName=club.club_name,
            description=club.description,
            logoUrl=club.logo_url,
            bannerUrl=club.banner_url,
            is_verified=bool(club.is_verified),
            role=str(club.role),
            rejectionReason=str(club.rejection_reason)
        )
    )


@api.get("/admin/clubs", response_model=List[schemas.ClubData])
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
        c = schemas.ClubData(
            id=str(club.id),
            slug=club.slug,
            email=club.email,
            clubName=club.club_name,
            description=club.description,
            logoUrl=club.logo_url,
            bannerUrl=club.banner_url,
            is_verified=bool(club.is_verified),
            role=str(club.role),
            rejectionReason=str(club.rejection_reason)
        )
        clubs_to_return.append(c)
    print(clubs_to_return)
    return clubs_to_return


@api.patch("/admin/clubs/{club_id}/status", response_model=schemas.ClubResponse)
async def set_club_verification(
    club_id: str,
    status_update: schemas.ClubStatusUpdate,
    db: Session = Depends(database.get_db)
):
    """
    Admin endpoint to Verify or Reject a club.
    """
    club = db.query(models.User).filter(models.User.id == club_id).first()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")
        
    # Update Status
    club.is_verified = status_update.is_verified # type: ignore
    
    # 2. Handle Rejection Reason
    if status_update.is_verified:
        #  CLEANUP: If approved, clear any old rejection reasons
        club.rejection_reason = "" # type: ignore
    else:
        # If rejected, require/store the reason
        club.rejection_reason = status_update.rejection_reason # type: ignore

    try:
        db.commit()
        db.refresh(club)
        print(f"changing {club.id}'s status to {club.is_verified}")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update verification status.")
    
    club_to_return = schemas.ClubData(
        id=str(club.id),
        slug=club.slug,
        email=club.email,
        clubName=club.club_name,
        description=club.description,
        logoUrl=club.logo_url,
        bannerUrl=club.banner_url,
        is_verified=bool(club.is_verified),
        role=str(club.role),
        rejectionReason=str(club.rejection_reason)
    )
    
    return schemas.ClubResponse(success=True, data=club_to_return)


if __name__ == "__main__":
    uvicorn.run("main:api", host="0.0.0.0", port=4444, reload=True)