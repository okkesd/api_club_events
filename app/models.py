# app/models.py
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Float, Text, Date
from sqlalchemy.orm import relationship
from .database import Base
import uuid
import re

# Helper to generate IDs
def generate_uuid():
    return str(uuid.uuid4())

# Helper to generate slugs
def generate_slug(text: str) -> str:
    # 1. Lowercase
    text = text.lower()
    # 2. Remove non-alphanumeric (keep hyphens)
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    # 3. Replace spaces with hyphens
    text = re.sub(r'\s+', '-', text)
    return text

class User(Base):
    __tablename__ = "users"

    # We use String for ID to keep it compatible with UUIDs if we want
    id = Column(String, primary_key=True, default=generate_uuid) # type: ignore

    slug: str = Column(String, unique=True, index=True) # type: ignore
    
    # Auth details
    email: str = Column(String, unique=True, index=True) # type: ignore
    hashed_password: str = Column(String) # type: ignore
    
    # Club Profile details
    club_name: str = Column(String, index=True) # type: ignore
    description: str = Column(Text, nullable=True) # type: ignore
    logo_url: str = Column(String, nullable=True) # type: ignore
    banner_url: str = Column(String, nullable=True) # type: ignore

    role = Column(String, default="club")
    is_verified = Column(Boolean, default=False)
    rejection_reason = Column(String, default="")
    
    # Relationships
    events = relationship("Event", back_populates="owner")


class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True, default=generate_uuid)

    slug = Column(String, unique=True, index=True)
    
    # Fields from your Create Event form
    title = Column(String, index=True)
    description = Column(Text)
    cover_image = Column(String, nullable=True)
    
    # Time
    date = Column(Date)       # Storing as ISO string "2026-01-18" is fine for now
    start_time = Column(String) # "10:00"
    duration: float = Column(Float)    # 1.5 # type: ignore
    end_time = Column(String)   # "11:30"
    
    # Location
    location_type = Column(String) # "on-campus"
    location = Column(String)
    
    # Relationship (Foreign Key) - Links an event to a specific Club
    club_id = Column(String, ForeignKey("users.id"))
    
    # Navigation link back to the club
    owner = relationship("User", back_populates="events")