from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List

# --- USER SCHEMAS ---

# What the frontend sends to US
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    club_name: str
    description: Optional[str] = None

# What WE send back to the frontend (No password!)
class UserResponse(BaseModel):
    id: str
    email: EmailStr
    club_name: str
    
    class Config:
        # This tells Pydantic to read data even if it's an ORM object (not just a dict)
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None


class EventDataComplex(BaseModel):
    # Identity
    id: str
    title: str
    description: str
    
    # Club Info (The "Complex" part)
    clubID: str      # Matches frontend interface 'clubID'
    clubName: str    # Joined from User table
    
    # Time
    date: str        # ISO String "YYYY-MM-DD"
    startTime: str   # "HH:MM"
    endTime: Optional[str] = None
    duration: float
    
    # Location
    location: str
    locationType: str # "on-campus" | "off-campus"
    
    # Visuals
    coverImage: Optional[str] = None
    
    # Details & Registration
    # We set defaults here so the API doesn't crash if these are null in the DB
    tags: List[str] = [] 
    isRegistrationOpen: bool = False
    registrationLink: Optional[str] = None
    capacity: Optional[int] = None

    class Config:
        # This allows Pydantic to read data from SQLAlchemy models if needed
        from_attributes = True

class MainResponse(BaseModel):
    success: bool
    data: Optional[List[EventDataComplex]] = None
    error_msg: Optional[str] = None


class EventResponse(BaseModel):
    success: bool
    data: Optional[EventDataComplex] = None
    error_msg: Optional[str] = None

class ClubData(BaseModel):
    id: str
    slug: str
    email:str
    clubName: str
    description: Optional[str]
    logoUrl: Optional[str]
    bannerUrl: Optional[str]

    is_verified: bool
    role: str
    rejectionReason: str

    class Config:
        from_attributes = True
    

class ClubResponse(BaseModel):
    success: bool
    data: Optional[ClubData] = None
    error_msg: Optional[str] = None

class EventsResponse(BaseModel):
    success: bool
    data: Optional[List[EventDataComplex]] = None
    error_msg: Optional[str] = None


class EventCreate(BaseModel):
    # Required Fields
    title: str
    description: str
    club_id: str = Field(..., alias="clubId")
    date: str
    start_time: str = Field(..., alias="startTime")
    end_time: str = Field(..., alias="endTime")
    duration: float
    location_type: str = Field(..., alias="locationType")
    location: str
    
    # Optional Fields
    cover_image: Optional[str] = Field(None, alias="coverImage")
    tags: List[str] = []
    
    # Registration
    # Map 'isRegistrationRequired' (Frontend) to 'is_registration_open' (likely DB logic)
    is_registration_open: bool = Field(False, alias="isRegistrationRequired")
    registration_link: Optional[str] = Field(None, alias="registrationLink")
    capacity: Optional[int] = None

    class Config:
        populate_by_name = True

class CreateEventResponse(BaseModel):
    success: bool
    data: Optional[EventDataComplex] = None
    error_msg: Optional[str] = None

class AllClubs(BaseModel):
    success: bool
    data: Optional[List[ClubData]]

class ClubUpdate(BaseModel):
    # We use camelCase here to match the Frontend, but map to snake_case manually or via alias
    clubName: Optional[str] = None
    email: Optional[str] = None
    description: Optional[str] = None
    logo_url: Optional[str] = None
    banner_url: Optional[str] = None
    
    # NOTE: 'website' and 'tags' are commented out until we add them to the Database Model
    # website: Optional[str] = None 
    # tags: Optional[List[str]] = None

    class Config:
        from_attributes = True

# club status update by admin (chaning is_verified and rejection_reason)
class ClubStatusUpdate(BaseModel):
    is_verified: bool
    rejection_reason: Optional[str] = None

# event update by club owner (changing event infos as they wish)
class EventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    date: Optional[str] = None      # "YYYY-MM-DD"
    start_time: Optional[str] = None # "10:00"
    end_time: Optional[str] = None   # "12:00"
    duration: Optional[float] = None
    location_type: Optional[str] = None
    location: Optional[str] = None
    cover_image: Optional[str] = None
    # Add other fields like capacity or registration link if needed