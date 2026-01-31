# seed_db.py
import datetime
from database import SessionLocal, engine
import models, utils
import re

# --- HELPER: Slugify ---
def simple_slugify(text):
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    return re.sub(r'\s+', '-', text)

# --- MOCK DATA ---
MOCK_CLUBS = [
    {
        "id": "club-1",
        "club_name": "Tech & Coding Society",
        "email": "tech@university.edu",
        "description": "We build cool stuff with code. Join us for hackathons, workshops, and pizza nights.",
        "logo_url": "https://api.dicebear.com/7.x/identicon/svg?seed=TechClub",
        "banner_url": "https://images.unsplash.com/photo-1517694712202-14dd9538aa97?auto=format&fit=crop&q=80&w=1000",
        "is_verified": True, # ✅ Verified Club
        "rejection_reason": ""
    },
    {
        "id": "club-2",
        "club_name": "University Jazz Band",
        "email": "jazz@university.edu",
        "description": "Smooth jazz and good vibes. We perform every Tuesday at the student center.",
        "logo_url": "https://api.dicebear.com/7.x/identicon/svg?seed=Jazz",
        "banner_url": "https://images.unsplash.com/photo-1511192336575-5a79af67a629?auto=format&fit=crop&q=80&w=1000",
        "is_verified": True,  # ✅ Verified Club
        "rejection_reason": ""
    },
    {
        "id": "club-3",
        "club_name": "Grandmaster Chess Club",
        "email": "chess@university.edu",
        "description": "Strategy, tactics, and tournaments. Beginners welcome!",
        "logo_url": "https://api.dicebear.com/7.x/identicon/svg?seed=Chess",
        "banner_url": "https://images.unsplash.com/photo-1529699211952-734e80c4d42b?auto=format&fit=crop&q=80&w=1000",
        "is_verified": False, # ❌ Unverified (Pending) - Good for testing Admin Panel
        "rejection_reason": "pending review"
    }
]

MOCK_EVENTS = [
    {
        "title": "Intro to Python Workshop",
        "description": "Learn the basics of Python programming. No prior experience needed!",
        "club_id": "club-1",
        "date": datetime.date(2026, 1, 28),
        "start_time": "10:00",
        "end_time": "12:00",
        "duration": 2.0,
        "location_type": "on-campus",
        "location": "Room 304",
        "cover_image": "https://images.unsplash.com/photo-1546410531-bb4caa6b424d?auto=format&fit=crop&q=80&w=1000"
    },
    {
        "title": "Jazz Night Live",
        "description": "Live performance by the University Jazz Band. Free entry!",
        "club_id": "club-2",
        "date": datetime.date(2026, 1, 29),
        "start_time": "18:00",
        "end_time": "20:00",
        "duration": 2.0,
        "location_type": "on-campus",
        "location": "Student Center",
        "cover_image": "https://images.unsplash.com/photo-1415201364774-f6f0bb35f28f?auto=format&fit=crop&q=80&w=1000"
    },
    {
        "title": "Chess Tournament",
        "description": "Monthly rapid chess tournament. Prizes for top 3.",
        "club_id": "club-3",
        "date": datetime.date(2026, 1, 30),
        "start_time": "14:00",
        "end_time": "17:00",
        "duration": 3.0,
        "location_type": "on-campus",
        "location": "Library Hall",
        "cover_image": "https://images.unsplash.com/photo-1586165368502-1bad197a6461?auto=format&fit=crop&q=80&w=1000"
    }
]

def seed():
    print("🌱 Seeding Database...")
    
    # 1. Reset Tables (Drop & Create)
    models.Base.metadata.drop_all(bind=engine)
    models.Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    try:
        hashed_pwd = utils.hash_password("password123")

        # --- 2. Create ADMIN User ---
        print("   Creating Admin User...")
        admin_user = models.User(
            id="admin-1",
            slug="system-admin",
            email="admin@uni.edu",
            hashed_password=hashed_pwd,
            club_name="System Administrator",
            description="Main platform administrator.",
            role="admin",        # 🛡️ ROLE SET TO ADMIN
            is_verified=True,    # Admins are always verified
            logo_url="https://ui-avatars.com/api/?name=Admin&background=000&color=fff"
        )
        db.add(admin_user)

        # --- 3. Create CLUBS ---
        print(f"   Creating {len(MOCK_CLUBS)} Clubs...")
        for club_data in MOCK_CLUBS:
            user = models.User(
                id=club_data["id"],
                slug=simple_slugify(club_data["club_name"]),
                email=club_data["email"],
                hashed_password=hashed_pwd,
                club_name=club_data["club_name"],
                description=club_data["description"],
                logo_url=club_data["logo_url"],
                banner_url=club_data["banner_url"],
                
                role="club",                # Default role
                is_verified=club_data["is_verified"] # Mix of True/False
            )
            db.add(user)
        
        db.commit() # Commit users so IDs exist for events

        # --- 4. Create EVENTS ---
        print(f"   Creating {len(MOCK_EVENTS)} Events...")
        for event_data in MOCK_EVENTS:
            # Unique Slug logic
            raw_slug = f"{event_data['title']} {event_data['date']}"
            
            event = models.Event(
                slug=simple_slugify(raw_slug),
                title=event_data["title"],
                description=event_data["description"],
                club_id=event_data["club_id"],
                date=event_data["date"],
                start_time=event_data["start_time"],
                end_time=event_data["end_time"],
                duration=event_data["duration"],
                location_type=event_data["location_type"],
                location=event_data["location"],
                cover_image=event_data["cover_image"]
            )
            db.add(event)

        db.commit()
        print("✅ Seeding Complete!")

    except Exception as e:
        print("❌ Error:", e)
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed()