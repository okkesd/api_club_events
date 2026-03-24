from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator
from typing import Optional, List
import datetime
import re
import math

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

class PaginationMeta(CamelModel):
    page: int
    page_size: int
    total: int
    total_pages: int

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

class UserOut(BaseModel):
    id: str
    club_name: str
    email: EmailStr
    role: str
    # Map DB 'is_verified' -> JSON 'isVerified'
    is_verified: bool = Field(..., alias="isVerified") 
    # Map DB 'avatar_url' -> JSON 'avatarUrl'
    avatar_url: Optional[str] = Field(None, alias="avatarUrl")

    class Config:
        from_attributes = True # Was 'orm_mode = True' in Pydantic v1
        populate_by_name = True # Allows mapping by field name

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
    pagination: Optional[PaginationMeta] = None

# --- EVENTS ---

class EventBase(CamelModel):
    title: str = Field(..., max_length=200)
    description: str = Field(..., max_length=5000)
    date: datetime.date
    start_time: str
    end_time: str
    duration: float = Field(..., gt=0)
    location_type: str
    location: str = Field(..., max_length=500)
    cover_image: Optional[str] = None
    tags: List[str] = []

    # Registration Logic
    is_registration_open: bool = False
    registration_link: Optional[str] = None
    capacity: Optional[int] = Field(None, gt=0)
    likes: int

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        if not re.match(r"^\d{2}:\d{2}$", v):
            raise ValueError("Time must be in HH:MM format")
        h, m = map(int, v.split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("Invalid time value")
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: List[str]) -> List[str]:
        if len(v) > 10:
            raise ValueError("Maximum 10 tags allowed")
        for tag in v:
            if len(tag) > 50:
                raise ValueError(f"Tag '{tag[:20]}...' exceeds 50 characters")
        return v


class EventCreate(EventBase):
    club_id: str

class EventUpdate(CamelModel):
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    date: Optional[datetime.date] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration: Optional[float] = Field(None, gt=0)
    location_type: Optional[str] = None
    location: Optional[str] = Field(None, max_length=500)
    cover_image: Optional[str] = None
    is_registration_open: Optional[bool] = None
    registration_link: Optional[str] = None
    capacity: Optional[int] = Field(None, gt=0)
    likes: Optional[int] = None

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not re.match(r"^\d{2}:\d{2}$", v):
            raise ValueError("Time must be in HH:MM format")
        h, m = map(int, v.split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("Invalid time value")
        return v

class EventResponse(EventBase):
    id: str
    club_id: str
    club_name: str  # Flattened from relation for easy UI access

class SingleEventResponse(ApiResponse):
    data: Optional[EventResponse] = None

class MultiEventResponse(ApiResponse):
    data: List[EventResponse]
    pagination: Optional[PaginationMeta] = None

class EventLikeResponse(CamelModel):
    success: bool
    data: Optional[EventBase] = None

# --- ANNOUNCEMENTS ---

class AnnouncementBase(CamelModel):
    title: str
    body: str
    cover_image: Optional[str] = None
    link: Optional[str] = None
    tags: List[str] = []
    category: str = "general"
    is_pinned: bool = False
    expires_at: Optional[datetime.date] = None

class AnnouncementCreate(AnnouncementBase):
    club_id: str

class AnnouncementUpdate(CamelModel):
    title: Optional[str] = None
    body: Optional[str] = None
    cover_image: Optional[str] = None
    link: Optional[str] = None
    tags: Optional[List[str]] = None
    category: Optional[str] = None
    is_pinned: Optional[bool] = None
    expires_at: Optional[datetime.date] = None

class AnnouncementResponse(AnnouncementBase):
    id: str
    club_id: str
    club_name: str
    created_at: datetime.datetime
    updated_at: datetime.datetime

class SingleAnnouncementResponse(ApiResponse):
    data: Optional[AnnouncementResponse] = None

class MultiAnnouncementResponse(ApiResponse):
    data: List[AnnouncementResponse]

# --- CONTACT ---

class Contact(BaseModel):
    email: str
    message: str
    date: datetime.datetime

class ContactRequest(BaseModel):
    email: EmailStr
    message: str = Field(..., max_length=2000)

class ContactReturn(BaseModel):
    success: bool
    data: Optional[List[Contact]]