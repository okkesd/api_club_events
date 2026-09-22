from sqlalchemy import Column, String, Boolean, ForeignKey, Float, Text, Date, Integer, DateTime, UniqueConstraint, Index
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

class AnnouncementCategory(str, Enum):
    INTERNSHIP = "internship"
    JOB = "job"
    SCHOLARSHIP = "scholarship"
    COMPETITION = "competition"
    RECRUITMENT = "recruitment"
    ACADEMIC = "academic"
    WORKSHOP = "workshop"
    GENERAL = "general"

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
    # Instagram handle scraped events are matched against (ig_pipeline posts.club_username)
    ig_username: Mapped[Optional[str]] = mapped_column(String, nullable=True, unique=True, index=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True, default=None)
    
    # Relationships
    events = relationship("Event", back_populates="owner", cascade="all, delete-orphan")
    announcements = relationship("Announcement", back_populates="owner", cascade="all, delete-orphan")

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
    source_posts = relationship("ScrapedEvent", foreign_keys="ScrapedEvent.created_event_id", viewonly=True, lazy="selectin")

    likes: Mapped[int] = mapped_column(Integer, default=0)
    view_count: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    event_likes = relationship("EventLike", back_populates="event", cascade="all, delete-orphan")
    translations = relationship("EventTranslation", back_populates="event", cascade="all, delete-orphan")


class EventTranslation(Base):
    __tablename__ = "event_translations"
    __table_args__ = (
        UniqueConstraint("event_id", "target_language", "description_hash", name="uq_event_translation_version"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    event_id: Mapped[str] = mapped_column(String, ForeignKey("events.id", ondelete="CASCADE"))
    target_language: Mapped[str] = mapped_column(String(2))
    description_hash: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

    event = relationship("Event", back_populates="translations")


class EventLike(Base):
    __tablename__ = "event_likes"
    __table_args__ = (
        UniqueConstraint("event_id", "visitor_id", name="uq_event_visitor"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    event_id: Mapped[str] = mapped_column(String, ForeignKey("events.id", ondelete="CASCADE"))
    visitor_id: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

    event = relationship("Event", back_populates="event_likes")


class EventView(Base):
    __tablename__ = "event_views"
    __table_args__ = (
        UniqueConstraint("event_id", "visitor_id", name="uq_event_view_visitor"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    event_id: Mapped[str] = mapped_column(String, ForeignKey("events.id", ondelete="CASCADE"))
    visitor_id: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

    event = relationship("Event")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    token: Mapped[str] = mapped_column(String, unique=True, index=True)  # master unsubscribe
    categories: Mapped[str] = mapped_column(Text, default="")  # comma-separated: "workshop,social,career"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow, index=True)

    # Relationships
    club_subscriptions = relationship("ClubSubscription", back_populates="subscription", cascade="all, delete-orphan")
    category_subscriptions = relationship("CategorySubscription", back_populates="subscription", cascade="all, delete-orphan")


class ClubSubscription(Base):
    __tablename__ = "club_subscriptions"
    __table_args__ = (
        UniqueConstraint("subscription_id", "club_id", name="uix_subscription_club"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    subscription_id: Mapped[str] = mapped_column(String, ForeignKey("subscriptions.id", ondelete="CASCADE"), index=True)
    club_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String, unique=True, index=True)  # per-club unsubscribe
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    subscription = relationship("Subscription", back_populates="club_subscriptions")
    club = relationship("User")

class CategorySubscription(Base):
    __tablename__ = "category_subscriptions"
    __table_args__ = (
        UniqueConstraint("subscription_id", "category", name="uix_subscription_category"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    subscription_id: Mapped[str] = mapped_column(String, ForeignKey("subscriptions.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(
        SQLEnum(AnnouncementCategory),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    subscription = relationship("Subscription", back_populates="category_subscriptions")


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)

    # Content
    title: Mapped[str] = mapped_column(String, index=True)
    body: Mapped[str] = mapped_column(Text)
    cover_image: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    link: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    tags: Mapped[str] = mapped_column(String, default="")
    category: Mapped[str] = mapped_column(
        SQLEnum(AnnouncementCategory),
        nullable=False,
        default=AnnouncementCategory.GENERAL
    )

    # Visibility
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[Optional[datetime.date]] = mapped_column(Date, nullable=True, index=True)

    # Timestamps
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow, index=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    club_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    owner = relationship("User", back_populates="announcements")
    source_posts = relationship("ScrapedEvent", foreign_keys="ScrapedEvent.created_announcement_id", viewonly=True, lazy="selectin")


class DigestDelivery(Base):
    """One durable delivery per subscriber and Istanbul calendar week."""
    __tablename__ = "digest_deliveries"
    __table_args__ = (
        UniqueConstraint("week_start", "subscription_id", name="uq_digest_week_subscriber"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    week_start: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    subscription_id: Mapped[str] = mapped_column(String, ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False)
    recipient: Mapped[str] = mapped_column(String, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    html_body: Mapped[str] = mapped_column(Text, nullable=False)
    text_body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    attempted_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    sent_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)


class Contact(Base):
    __tablename__ = "contact"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)

    email: Mapped[str] = mapped_column(String)
    message: Mapped[str] = mapped_column(String)

    date : Mapped[datetime.datetime] = mapped_column(DateTime, index=True)

    class Config:
        from_attributes = True

class ScrapedEventStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ScrapedEvent(Base):
    """Event extracted from a scraped Instagram post, waiting for admin approval.

    Rows are imported from the ig_pipeline database. Approving one creates a real Event;
    the staging row keeps the link so the same post is never published twice.
    """
    __tablename__ = "scraped_events"
    __table_args__ = (
        UniqueConstraint("source", "source_event_id", name="uq_scraped_source_event"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)

    # Provenance
    source: Mapped[str] = mapped_column(String, default="instagram", index=True)
    source_event_id: Mapped[str] = mapped_column(String, index=True)  # Event.id in ig_pipeline.db
    club_username: Mapped[str] = mapped_column(String, index=True)
    post_shortcode: Mapped[str] = mapped_column(String, index=True)
    post_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    post_caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    post_image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    posted_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)

    # What this candidate becomes when approved: an Event or an Announcement.
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="event", index=True)

    # Extracted content (editable by the admin before approval)
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    date: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True, index=True)
    location: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)

    # Announcement-only fields; null on events
    category: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    link: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    expires_at: Mapped[Optional[datetime.date]] = mapped_column(Date, nullable=True)

    # Review state
    status: Mapped[str] = mapped_column(
        SQLEnum(ScrapedEventStatus), nullable=False, default=ScrapedEventStatus.PENDING, index=True
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    reviewed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"), nullable=True)

    # Resolved club (auto-matched on ig_username, or picked by the admin)
    club_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"), nullable=True, index=True)
    # Set once approved — one of the two, matching `kind`
    created_event_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("events.id", ondelete="SET NULL"), nullable=True
    )
    created_announcement_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("announcements.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, index=True
    )

    club = relationship("User", foreign_keys=[club_id])
    created_event = relationship("Event", foreign_keys=[created_event_id])
    created_announcement = relationship("Announcement", foreign_keys=[created_announcement_id])


class IgClubMapping(Base):
    """Remembers which app user an Instagram handle publishes under.

    Learned from the admin's choice in the approval panel, so a handle only has to be
    resolved once. Distinct from `User.ig_username` (which is a club declaring its own
    handle) because the target may be the admin account, and the admin publishes for
    many handles — one unique column on `users` cannot express that.
    """
    __tablename__ = "ig_club_mappings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    club_username: Mapped[str] = mapped_column(String, unique=True, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )

    user = relationship("User")


class Suggestion(Base):
    __tablename__ = "suggestions"

    id = Column(String, primary_key=True, default=generate_uuid)
    kind = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="pending", index=True)
    title = Column(String(200))
    description = Column(Text)
    date = Column(Date)
    start_time = Column(String(5))
    end_time = Column(String(5))
    location = Column(String(500))
    organizer = Column(String(500))
    link = Column(String(2048))
    category = Column(String)
    expires_at = Column(Date)
    email = Column(String(320))
    image_url = Column(String)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    reviewed_at = Column(DateTime)
    reviewed_by = Column(String, ForeignKey("users.id"))
    rejection_reason = Column(Text)
    created_event_id = Column(String, ForeignKey("events.id", ondelete="SET NULL"), unique=True)
    created_announcement_id = Column(String, ForeignKey("announcements.id", ondelete="SET NULL"), unique=True)


class MetricRecord(Base):
    """Append-only history, deliberately independent of deletable content rows."""
    __tablename__ = "metric_records"
    __table_args__ = (Index("ix_metric_kind_time", "kind", "occurred_at"),)
    id = Column(String, primary_key=True, default=generate_uuid)
    kind = Column(String(40), nullable=False)
    occurred_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    event_id = Column(String, index=True)
    subject = Column(String)
    club_id = Column(String)


class MetricCoverage(Base):
    __tablename__ = "metric_coverage"
    name = Column(String, primary_key=True)
    started_at = Column(DateTime, nullable=False)


class MetricSubscriber(Base):
    __tablename__ = "metric_subscribers"
    email_hash = Column(String(64), primary_key=True)
    # Null for pre-tracking subscribers: their original activation is unknown.
    first_activated_at = Column(DateTime)
