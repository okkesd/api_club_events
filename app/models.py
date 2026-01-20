# app/models.py
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Float, Text
from sqlalchemy.orm import relationship
from .database import Base
import uuid

# Helper to generate IDs
def generate_uuid():
    return str(uuid.uuid4())

class User(Base):
    __tablename__ = "users"

    # We use String for ID to keep it compatible with UUIDs if we want
    id = Column(String, primary_key=True, default=generate_uuid)
    
    # Auth details
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    
    # Club Profile details
    club_name = Column(String, index=True)
    description = Column(Text, nullable=True)
    logo_url = Column(String, nullable=True)
    banner_url = Column(String, nullable=True)
    
    # Relationships
    events = relationship("Event", back_populates="owner")


class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True, default=generate_uuid)
    
    # Fields from your Create Event form
    title = Column(String, index=True)
    description = Column(Text)
    cover_image = Column(String, nullable=True)
    
    # Time
    date = Column(String)       # Storing as ISO string "2026-01-18" is fine for now
    start_time = Column(String) # "10:00"
    duration = Column(Float)    # 1.5
    end_time = Column(String)   # "11:30"
    
    # Location
    location_type = Column(String) # "on-campus"
    location = Column(String)
    
    # Relationship (Foreign Key) - Links an event to a specific Club
    club_id = Column(String, ForeignKey("users.id"))
    
    # Navigation link back to the club
    owner = relationship("User", back_populates="events")