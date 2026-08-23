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
    # Instagram handle used to auto-match scraped events to this club (admin only)
    ig_username: Optional[str] = None
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
    ig_username: Optional[str] = None

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
    capacity: Optional[int] = Field(None, ge=0)
    likes: int = 0
    view_count: int = 0

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
    # 0 means "no limit", same as on create — an empty capacity field in the form sends 0.
    capacity: Optional[int] = Field(None, ge=0)
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
    has_liked: bool = False

class SingleEventResponse(ApiResponse):
    data: Optional[EventResponse] = None

class MultiEventResponse(ApiResponse):
    data: List[EventResponse]
    pagination: Optional[PaginationMeta] = None

class EventLikeData(CamelModel):
    likes: int
    has_liked: bool

class EventLikeResponse(CamelModel):
    success: bool
    data: EventLikeData

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

# --- SUBSCRIPTIONS ---

class SubscribeRequest(CamelModel):
    email: EmailStr
    club_ids: List[str] = []       # creates ClubSubscription rows
    categories: List[str] = []

class ClubSubscribeRequest(CamelModel):
    email: EmailStr

class ClubSubscriptionInfo(CamelModel):
    club_id: str
    club_name: str
    is_active: bool

class CategorySubscriptionInfo(CamelModel):
    category: str
    is_active: bool

class SubscriptionResponse(CamelModel):
    id: str
    email: str
    clubs: List[ClubSubscriptionInfo] = []
    categories: List[CategorySubscriptionInfo] = []
    is_active: bool
    created_at: datetime.datetime

class SingleSubscriptionResponse(ApiResponse):
    data: Optional[SubscriptionResponse] = None

class MultiSubscriptionResponse(ApiResponse):
    data: List[SubscriptionResponse]
    pagination: Optional[PaginationMeta] = None

class ClubSubscriptionToggleResponse(CamelModel):
    success: bool
    message: str
    is_subscribed: bool
# --- SCRAPED EVENTS (admin approval inbox) ---

class ScrapedEventResponse(CamelModel):
    id: str
    source: str
    source_event_id: str

    # Source post context, so the admin can judge without leaving the panel
    club_username: str
    post_shortcode: str
    post_url: Optional[str] = None
    post_caption: Optional[str] = None
    post_image_url: Optional[str] = None
    posted_at: Optional[datetime.datetime] = None

    # Extracted content
    title: Optional[str] = None
    date: Optional[datetime.datetime] = None
    location: Optional[str] = None
    description: Optional[str] = None
    confidence: float

    # Review state
    status: str
    rejection_reason: Optional[str] = None
    reviewed_at: Optional[datetime.datetime] = None
    club_id: Optional[str] = None
    club_name: Optional[str] = None
    # true when club_id came from a remembered handle mapping rather than a fresh guess
    club_is_remembered: bool = False
    created_event_id: Optional[str] = None
    created_at: datetime.datetime


class SingleScrapedEventResponse(ApiResponse):
    data: Optional[ScrapedEventResponse] = None


class MultiScrapedEventResponse(ApiResponse):
    data: List[ScrapedEventResponse]
    pagination: Optional[PaginationMeta] = None


class ScrapedEventUpdate(CamelModel):
    """Admin fixes to the extracted content before approving."""
    title: Optional[str] = Field(None, max_length=200)
    date: Optional[datetime.datetime] = None
    location: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = Field(None, max_length=5000)
    club_id: Optional[str] = None


class IgClubMappingResponse(CamelModel):
    club_username: str
    user_id: str
    user_name: str
    is_admin: bool
    updated_at: datetime.datetime


class MultiIgClubMappingResponse(ApiResponse):
    data: List[IgClubMappingResponse]


class ScrapedEventApprove(CamelModel):
    """Everything the real Event needs that the extractor cannot know.

    Anything left out falls back to the extracted value (or a sane default:
    2-hour on-campus event starting at the extracted time).
    """
    club_id: Optional[str] = None
    # Publish under the admin account instead of a club — for handles whose club is not
    # on the platform, or does not want its name on the listing.
    publish_as_admin: bool = False
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    date: Optional[datetime.date] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration: Optional[float] = Field(None, gt=0)
    location_type: Optional[str] = None
    location: Optional[str] = Field(None, max_length=500)
    cover_image: Optional[str] = None
    tags: List[str] = []
    is_registration_open: bool = False
    registration_link: Optional[str] = None
    capacity: Optional[int] = Field(None, ge=0)

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


class ScrapedEventReject(CamelModel):
    rejection_reason: Optional[str] = Field(None, max_length=500)


class ScrapedEventImportStats(CamelModel):
    imported: int
    skipped: int
    matched_clubs: int


class ScrapedEventImportResponse(ApiResponse):
    data: Optional[ScrapedEventImportStats] = None
