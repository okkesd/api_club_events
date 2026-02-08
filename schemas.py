from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Optional, List
import datetime

# --- BASE CONFIG ---
class CamelModel(BaseModel):
    """
    Base model that automatically maps python_snake_case to jsonCamelCase.
    """
    model_config = ConfigDict(
        from_attributes=True, 
        populate_by_name=True, 
        alias_generator=lambda s: "".join(
            word.capitalize() if i > 0 else word 
            for i, word in enumerate(s.split('_'))
        )
    )

# --- SHARED/GENERIC RESPONSES ---
class ApiResponse(CamelModel):
    success: bool
    error_msg: Optional[str] = None

# --- AUTH & USERS ---

class Token(BaseModel):
    access_token: str
    token_type: str

class UserCreate(CamelModel):
    email: EmailStr
    password: str
    club_name: str
    description: Optional[str] = None

class UserCreate2(CamelModel):
    id: str
    email: EmailStr
    club_name: str
    role: str
    is_verified: bool
    
    # Optional profile fields that might be empty initially
    logo_url: Optional[str] = None
    banner_url: Optional[str] = None
class UserResponse(CamelModel):
    success: bool
    data: UserCreate2

# --- CLUBS ---

class ClubBase(CamelModel):
    club_name: str
    email: EmailStr
    description: Optional[str] = None
    logo_url: Optional[str] = None
    banner_url: Optional[str] = None
    
    # Future-proofing (Add to DB later if needed)
    # website: Optional[str] = None 
    # socials: Optional[dict] = None

class ClubUpdate(CamelModel):
    club_name: Optional[str] = None
    email: Optional[EmailStr] = None
    description: Optional[str] = None
    logo_url: Optional[str] = None
    banner_url: Optional[str] = None

class ClubStatusUpdate(CamelModel):
    is_verified: bool
    rejection_reason: Optional[str] = None

class ClubResponse(ClubBase):
    id: str
    role: str
    is_verified: bool
    rejection_reason: Optional[str] = None

class ClubApiResponse(ApiResponse):
    data: Optional[ClubResponse] = None

class AllClubsResponse(ApiResponse):
    data: List[ClubResponse]

# --- EVENTS ---

class EventBase(CamelModel):
    title: str
    description: str
    date: datetime.date  # Pydantic handles "YYYY-MM-DD" string -> date obj conversion
    start_time: str
    end_time: str
    duration: float
    location_type: str
    location: str
    cover_image: Optional[str] = None
    tags: List[str] = []
    
    # Registration Logic
    is_registration_open: bool = False
    registration_link: Optional[str] = None
    capacity: Optional[int] = None
    likes: int



class EventCreate(EventBase):
    club_id: str

class EventUpdate(CamelModel):
    title: Optional[str] = None
    description: Optional[str] = None
    date: Optional[datetime.date] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration: Optional[float] = None
    location_type: Optional[str] = None
    location: Optional[str] = None
    cover_image: Optional[str] = None
    is_registration_open: Optional[bool] = None
    registration_link: Optional[str] = None
    capacity: Optional[int] = None
    likes: Optional[int] = None

class EventResponse(EventBase):
    id: str
    club_id: str
    club_name: str  # Flattened from relation for easy UI access

class SingleEventResponse(ApiResponse):
    data: Optional[EventResponse] = None

class MultiEventResponse(ApiResponse):
    data: List[EventResponse]

class EventLikeResponse(CamelModel):
    success: bool
    data: Optional[EventBase] = None