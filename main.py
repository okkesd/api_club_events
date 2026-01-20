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
from sqlalchemy.orm import Session
import time
from typing import Dict, List

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
@api.get("/events/weekly", response_model=MainResponse)
async def weekly_events(date: str = Query(..., description="Any date within the desired week (YYYY-MM-DD)")): # obj: MainRequest

    week_beginning, week_end = get_week_range(date)

    data_to_send: list[EventDataComplex] = []
    
    try:
        for item in event_data:

            event_date = datetime.strptime(item.startDate, "%Y-%m-%d")            
            if (week_beginning <= event_date < week_end):

                club_name = ""
                for club in club_data:
                    if club.id == item.clubID:
                        
                        club_name = club.clubName
                        item_dumped = item.model_dump()
                        event_to_add: EventDataComplex = EventDataComplex(**item_dumped, clubName=club_name)
                        data_to_send.append(event_to_add)
                        break

    except Exception as e:
        print("exception: ", e)
        raise HTTPException(status_code=500, detail=f"Exception occured in weekly events: {str(e)}")

    return MainResponse(success=True, data=data_to_send)


# get single event
@api.get("/events/{event_id}", response_model=EventResponse)
async def handle_events(event_id: str):

    try:
        for item in event_data:
            if item.id == event_id:

                # we would usually do this join in DB wiht select
                club_name = "Unknown club name"
                club_id = item.clubID
                for club in club_data:
                    if club_id == club.id:
                        club_name = club.clubName
                        break

                
                item_dict = item.model_dump() 
                
                # Create the complex object
                new_item = EventDataComplex(**item_dict, clubName=club_name)                
                return EventResponse(success=True, data=new_item)
            

        raise HTTPException(404, detail="Event not found")
                
    except HTTPException as he: # re-raise
        raise he
    
    except Exception as e:
        print("exception: ", e)
        raise HTTPException(400, detail=f"Exception occured in handle events: {str(e)}")
    
    


# get single club
@api.get("/clubs/{club_id}", response_model=ClubResponse)
async def handle_club(club_id: str):

    try:
        for item in club_data:
            if item.id == club_id:

                return ClubResponse(success=True, data=item)
            
        raise HTTPException(404, detail=f"No event found with id {club_id}")
        
    
    except Exception as e:
        print("exception: ", e)
        raise HTTPException(status_code=500, detail=f"Error occured in handle club: {str(e)}")
    

    
# get club's events
@api.get("/clubs/{club_id}/events", response_model=ClubEventsResponse)
async def handle_club_events(club_id: str):

    data_to_return: List[EventDataComplex] = []

    try:
        
        for event in event_data:
            if event.clubID == club_id:  

                for club in club_data:
                    if event.clubID == club.id:
                        event_dumped = event.model_dump()
                        event_to_add: EventDataComplex = EventDataComplex(**event_dumped, clubName=club.clubName)      
                        data_to_return.append(event_to_add)
        
        return ClubEventsResponse(success=True, data=data_to_return)
    
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
    existing_user = db.query(models.User).filter(models.User.email == user.email).first()
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
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    
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

if __name__ == "__main__":
    uvicorn.run("main:api", host="0.0.0.0", port=4444, reload=True)