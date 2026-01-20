from typing import Optional, Dict, List
from pydantic import BaseModel

class EventData(BaseModel):
    id: str
    title: str
    clubID: str
    startTime: str
    duration: float
    startDate: str
    location: str
    description: str
    coverImage: Optional[str]
    tags: list[str]
    locationType: str
    isRegistrationOpen: bool
    registrationLink: Optional[str]
    capacity: Optional[int]

class EventDataComplex(BaseModel):
    clubName: str
    id: str
    title: str
    clubID: str
    startTime: str
    duration: float
    startDate:str
    location: str
    description: str
    coverImage: Optional[str]
    tags: list[str]
    locationType: str
    isRegistrationOpen: bool
    registrationLink: Optional[str]
    capacity: Optional[int]

class SocialLinks(BaseModel):
    instagram: Optional[str] = None
    website: Optional[str] = None
    linkedin: Optional[str] = None

class ClubData(BaseModel):
    id: str
    clubName: str
    clubMail: str
    description: str          # NEW: Tells the story of the club
    category: str             # NEW: e.g. "Tech", "Arts", "Sports"
    logo: str                 # NEW: URL to square logo
    banner: str               # NEW: URL to wide hero image
    socials: SocialLinks      # NEW: Object for links
    foundedYear: Optional[int] = None

class MainRequest(BaseModel):
    year: int
    month: int
    day: int


class MainResponse(BaseModel):
    success: bool
    data: Optional[List[EventDataComplex]] = None
    error_msg: Optional[str] = None


class EventResponse(BaseModel):
    success: bool
    data: EventDataComplex


class ClubResponse(BaseModel):
    success: bool
    data: ClubData

class ClubEventsResponse(BaseModel):
    success: bool
    data: List[EventDataComplex]