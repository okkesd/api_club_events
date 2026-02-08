from sqlalchemy import Column, String, Boolean, ForeignKey, Float, Text, Date, Integer
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import relationship, Mapped, mapped_column
from database import Base
from typing import Optional
import datetime
import uuid
import re
from enum import Enum

class LocationType(str, Enum):
    ON_CAMPUS = "on-campus"
    OFF_CAMPUS = "off-campus"

class UserRole(str, Enum):
    CLUB = "club"
    ADMIN = "admin"

def generate_uuid():
    return str(uuid.uuid4())

def generate_slug(text: str) -> str:
    # Basic slugify: lowercase, remove special chars, replace space with dash
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'\s+', '-', text)
    return text

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String)
    
    # Profile
    club_name: Mapped[str] = mapped_column(String, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str] = mapped_column(String, nullable=True)
    banner_url: Mapped[str] = mapped_column(String, nullable=True)

    # Status / Access Control
    role: Mapped[str] = mapped_column(
        SQLEnum(UserRole),
        nullable=False,
        default=UserRole.CLUB
    )
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    rejection_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True, default=None)
    
    # Relationships
    events = relationship("Event", back_populates="owner", cascade="all, delete-orphan")

class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    
    # Content
    title: Mapped[str] = mapped_column(String, index=True)
    description: Mapped[str] = mapped_column(Text)
    cover_image: Mapped[str] = mapped_column(String, nullable=True)
    tags: Mapped[str] = mapped_column(String, default="") # Stored as comma-separated or JSON string usually
    
    # Time
    date: Mapped[datetime.date] = mapped_column(Date, index=True)
    start_time: Mapped[str] = mapped_column(String) # Format: "HH:MM"
    end_time: Mapped[str] = mapped_column(String)   # Format: "HH:MM"
    duration: Mapped[float] = mapped_column(Float)  # Hours (e.g. 1.5)
    
    # Location
    location_type: Mapped[str] = mapped_column(
        SQLEnum(LocationType),
        nullable=False
    ) 
    location: Mapped[str] = mapped_column(String)
    
    # Registration Logic (Future proofing based on schemas)
    is_registration_open: Mapped[bool] = mapped_column(Boolean, default=False)
    registration_link: Mapped[str] = mapped_column(String, nullable=True)
    capacity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True) # or Integer

    # Relationships
    club_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    owner = relationship("User", back_populates="events")

    likes: Mapped[int] = mapped_column(Integer, default=0)