import sys
import os

# 1. Add the current directory to Python path so we can import 'app'
sys.path.append(os.getcwd())

from app import models, database, utils
from app.database import SessionLocal

# --- MOCK DATA ---

MOCK_CLUBS = [
    {
        "id": "club-1",  # We force a specific ID so we can link events easily
        "email": "tech@university.edu",
        "club_name": "Tech & Coding Society",
        "description": "We build cool apps, host hackathons, and drink too much coffee. Join us to learn React, Python, and AI.",
        "logo_url": "https://api.dicebear.com/7.x/identicon/svg?seed=tech",
        "banner_url": "/gsu_image.jpg"
    },
    {
        "id": "club-2",
        "email": "music@university.edu",
        "club_name": "University Jazz Band",
        "description": "Bringing smooth jazz and funk to the campus. We meet every Tuesday for jam sessions.",
        "logo_url": "https://api.dicebear.com/7.x/identicon/svg?seed=music",
        "banner_url": "https://images.unsplash.com/photo-1511192336575-5a79af67a629?auto=format&fit=crop&q=80&w=1000"
    },
    {
        "id": "club-3",
        "email": "chess@university.edu",
        "club_name": "Grandmaster Chess Club",
        "description": "From beginners to rated players. Come sharpen your mind and learn strategy.",
        "logo_url": "https://api.dicebear.com/7.x/identicon/svg?seed=chess",
        "banner_url": "https://images.unsplash.com/photo-1529699211952-734e80c4d42b?auto=format&fit=crop&q=80&w=1000"
    }
]

MOCK_EVENTS = [
    {
        "title": "Intro to Python Workshop",
        "description": "Learn the basics of Python in this hands-on workshop. No prior experience needed! Bring your laptop.",
        "club_id": "club-1",
        "date": "2026-01-25",
        "start_time": "14:00",
        "end_time": "16:00",
        "duration": 2.0,
        "location_type": "on-campus",
        "location": "Room 304, Science Block",
        "cover_image": "https://images.unsplash.com/photo-1526379095098-d400fd0bf935?auto=format&fit=crop&q=80&w=1000"
    },
    {
        "title": "AI & The Future Talk",
        "description": "A guest lecture from an industry expert on how AI is changing software engineering jobs.",
        "club_id": "club-1",
        "date": "2026-01-28",
        "start_time": "18:00",
        "end_time": "19:30",
        "duration": 1.5,
        "location_type": "on-campus",
        "location": "Main Auditorium",
        "cover_image": "" # Test empty image fallback
    },
    {
        "title": "Jazz Night: Live Performance",
        "description": "Relax after classes with some live jazz performed by our talented students. Free snacks!",
        "club_id": "club-2",
        "date": "2026-01-26",
        "start_time": "19:00",
        "end_time": "22:00",
        "duration": 3.0,
        "location_type": "off-campus",
        "location": "The Blue Note Cafe, Downtown",
        "cover_image": "https://images.unsplash.com/photo-1514525253440-b393452e8d26?auto=format&fit=crop&q=80&w=1000"
    },
    {
        "title": "Spring Chess Tournament",
        "description": "Swiss system tournament. 5 rounds. Winner gets a $50 gift card!",
        "club_id": "club-3",
        "date": "2026-02-01",
        "start_time": "10:00",
        "end_time": "15:00",
        "duration": 5.0,
        "location_type": "on-campus",
        "location": "Student Center Hall B",
        "cover_image": "https://images.unsplash.com/photo-1586165368502-1bad197a6461?auto=format&fit=crop&q=80&w=1000"
    }
]

# --- SEEDING LOGIC ---

def seed():
    print("🌱 Seeding Database...")
    db = SessionLocal()

    try:
        # 1. Clear existing data (Optional: Remove if you want to keep adding)
        print("   Cleaning old data...")
        db.query(models.Event).delete()
        db.query(models.User).delete()
        db.commit()

        # 2. Create Clubs (Users)
        print(f"   Creating {len(MOCK_CLUBS)} Clubs...")
        
        # We use a standard password for everyone for testing
        hashed_pwd = utils.hash_password("password123")

        for club_data in MOCK_CLUBS:
            user = models.User(
                id=club_data["id"], # Force specific ID
                email=club_data["email"],
                hashed_password=hashed_pwd,
                club_name=club_data["club_name"],
                description=club_data["description"],
                logo_url=club_data["logo_url"],
                banner_url=club_data["banner_url"]
            )
            db.add(user)
        
        db.commit() # Commit clubs so they exist for Foreign Keys

        # 3. Create Events
        print(f"   Creating {len(MOCK_EVENTS)} Events...")
        for event_data in MOCK_EVENTS:
            event = models.Event(
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
        print("✅ Database populated successfully!")
        print("   Test Login Credentials:")
        print("   - Email: tech@university.edu")
        print("   - Pass : password123")

    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed()