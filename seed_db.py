import os
import datetime
from dotenv import load_dotenv
from database import SessionLocal, engine
import models
import utils

load_dotenv()


def simple_slugify(text):
    import re
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    return re.sub(r'\s+', '-', text)


MOCK_CLUBS = [
    {
        "id": "club-1",
        "club_name": "Tech & Coding Society",
        "email": "tech@university.edu",
        "description": "We build cool stuff with code. Join us for hackathons, workshops, and pizza nights.",
        "logo_url": "https://api.dicebear.com/7.x/identicon/svg?seed=TechClub",
        "banner_url": "https://images.unsplash.com/photo-1517694712202-14dd9538aa97?auto=format&fit=crop&q=80&w=1000",
        "is_verified": True,
    },
    {
        "id": "club-2",
        "club_name": "University Jazz Band",
        "email": "jazz@university.edu",
        "description": "Smooth jazz and good vibes. We perform every Tuesday at the student center.",
        "logo_url": "https://api.dicebear.com/7.x/identicon/svg?seed=Jazz",
        "banner_url": "https://images.unsplash.com/photo-1511192336575-5a79af67a629?auto=format&fit=crop&q=80&w=1000",
        "is_verified": True,
    },
    {
        "id": "club-3",
        "club_name": "Grandmaster Chess Club",
        "email": "chess@university.edu",
        "description": "Strategy, tactics, and tournaments. Beginners welcome!",
        "logo_url": "https://api.dicebear.com/7.x/identicon/svg?seed=Chess",
        "banner_url": "https://images.unsplash.com/photo-1529699211952-734e80c4d42b?auto=format&fit=crop&q=80&w=1000",
        "is_verified": False,
    },
    {
        "id": "club-4",
        "club_name": "Entrepreneurship Club",
        "email": "entrepreneur@university.edu",
        "description": "From idea to startup. Pitch nights, mentorship, and networking events.",
        "logo_url": "https://api.dicebear.com/7.x/identicon/svg?seed=Startup",
        "banner_url": "https://images.unsplash.com/photo-1556761175-5973dc0f32e7?auto=format&fit=crop&q=80&w=1000",
        "is_verified": True,
    },
    {
        "id": "club-5",
        "club_name": "Photography Society",
        "email": "photo@university.edu",
        "description": "Capture the campus. Weekly photowalks, editing workshops, and exhibitions.",
        "logo_url": "https://api.dicebear.com/7.x/identicon/svg?seed=Photo",
        "banner_url": "https://images.unsplash.com/photo-1452587925148-ce544e77e70d?auto=format&fit=crop&q=80&w=1000",
        "is_verified": True,
    },
]

# Dates relative to today so events are always upcoming
today = datetime.date.today()

MOCK_EVENTS = [
    # This week
    {
        "title": "Intro to Python Workshop",
        "description": "Learn the basics of Python programming. No prior experience needed! We'll cover variables, loops, and build a small project together.",
        "club_id": "club-1",
        "date": today + datetime.timedelta(days=1),
        "start_time": "10:00",
        "end_time": "12:00",
        "duration": 2.0,
        "location_type": "on-campus",
        "location": "Engineering Building, Room 304",
        "tags": "python,workshop,beginner-friendly",
        "cover_image": "https://images.unsplash.com/photo-1546410531-bb4caa6b424d?auto=format&fit=crop&q=80&w=1000",
    },
    {
        "title": "Jazz Night Live",
        "description": "Live performance by the University Jazz Band. Free entry! Featuring special guest saxophonist.",
        "club_id": "club-2",
        "date": today + datetime.timedelta(days=2),
        "start_time": "18:00",
        "end_time": "20:00",
        "duration": 2.0,
        "location_type": "on-campus",
        "location": "Student Center, Main Hall",
        "tags": "music,social,performance",
        "cover_image": "https://images.unsplash.com/photo-1415201364774-f6f0bb35f28f?auto=format&fit=crop&q=80&w=1000",
    },
    {
        "title": "Startup Pitch Night",
        "description": "5 student teams pitch their startup ideas to a panel of local investors. Come watch, vote, and network!",
        "club_id": "club-4",
        "date": today + datetime.timedelta(days=3),
        "start_time": "17:00",
        "end_time": "19:30",
        "duration": 2.5,
        "location_type": "on-campus",
        "location": "Business School Auditorium",
        "tags": "career,networking,startup",
        "cover_image": "https://images.unsplash.com/photo-1556761175-5973dc0f32e7?auto=format&fit=crop&q=80&w=1000",
    },
    # Next week
    {
        "title": "Campus Photowalk",
        "description": "Explore hidden corners of campus through your lens. Bring any camera — phone works too!",
        "club_id": "club-5",
        "date": today + datetime.timedelta(days=7),
        "start_time": "15:00",
        "end_time": "17:00",
        "duration": 2.0,
        "location_type": "on-campus",
        "location": "Meet at Library Entrance",
        "tags": "photography,social,outdoor",
        "cover_image": "https://images.unsplash.com/photo-1452587925148-ce544e77e70d?auto=format&fit=crop&q=80&w=1000",
    },
    {
        "title": "Web Dev Bootcamp: React Basics",
        "description": "Build your first React app in 3 hours. Laptop required. We'll provide snacks and mentorship.",
        "club_id": "club-1",
        "date": today + datetime.timedelta(days=8),
        "start_time": "13:00",
        "end_time": "16:00",
        "duration": 3.0,
        "location_type": "on-campus",
        "location": "CS Lab 201",
        "tags": "react,workshop,engineering",
        "cover_image": "https://images.unsplash.com/photo-1633356122544-f134324a6cee?auto=format&fit=crop&q=80&w=1000",
    },
    {
        "title": "Chess Tournament: Spring Open",
        "description": "Monthly rapid chess tournament. Prizes for top 3. All skill levels welcome.",
        "club_id": "club-3",
        "date": today + datetime.timedelta(days=9),
        "start_time": "14:00",
        "end_time": "17:00",
        "duration": 3.0,
        "location_type": "on-campus",
        "location": "Library Hall B",
        "tags": "competition,chess,social",
        "cover_image": "https://images.unsplash.com/photo-1586165368502-1bad197a6461?auto=format&fit=crop&q=80&w=1000",
    },
    {
        "title": "Resume Workshop with Career Services",
        "description": "Get your resume reviewed by professionals. Bring a printed copy or laptop with your latest version.",
        "club_id": "club-4",
        "date": today + datetime.timedelta(days=10),
        "start_time": "11:00",
        "end_time": "13:00",
        "duration": 2.0,
        "location_type": "on-campus",
        "location": "Career Center, Floor 2",
        "tags": "career,workshop,professional",
        "cover_image": "https://images.unsplash.com/photo-1586281380349-632531db7ed4?auto=format&fit=crop&q=80&w=1000",
    },
    # Week after
    {
        "title": "Hackathon: Build for Good",
        "description": "24-hour hackathon focused on social impact. Teams of 2-4. Meals provided. Top 3 win prizes!",
        "club_id": "club-1",
        "date": today + datetime.timedelta(days=14),
        "start_time": "09:00",
        "end_time": "09:00",
        "duration": 24.0,
        "location_type": "on-campus",
        "location": "Innovation Hub",
        "tags": "hackathon,engineering,competition",
        "cover_image": "https://images.unsplash.com/photo-1504384308090-c894fdcc538d?auto=format&fit=crop&q=80&w=1000",
        "is_registration_open": True,
        "capacity": 100,
    },
    {
        "title": "Jazz & Coffee Morning",
        "description": "Acoustic jazz session with free coffee. Perfect study break.",
        "club_id": "club-2",
        "date": today + datetime.timedelta(days=15),
        "start_time": "09:00",
        "end_time": "11:00",
        "duration": 2.0,
        "location_type": "on-campus",
        "location": "Garden Cafe",
        "tags": "music,social,relaxing",
        "cover_image": "https://images.unsplash.com/photo-1511192336575-5a79af67a629?auto=format&fit=crop&q=80&w=1000",
    },
    {
        "title": "Photo Exhibition: Campus Life",
        "description": "Student photography exhibition showcasing the best shots from this semester's photowalks.",
        "club_id": "club-5",
        "date": today + datetime.timedelta(days=17),
        "start_time": "10:00",
        "end_time": "18:00",
        "duration": 8.0,
        "location_type": "on-campus",
        "location": "Art Gallery, Student Union",
        "tags": "photography,exhibition,art",
        "cover_image": "https://images.unsplash.com/photo-1513364776144-60967b0f800f?auto=format&fit=crop&q=80&w=1000",
    },
]


def seed():
    print("Seeding Database...")

    # Drop & recreate all tables (safe — app not published, DB empty)
    models.Base.metadata.drop_all(bind=engine)
    models.Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    try:
        hashed_pwd = utils.hash_password("password123")

        # Admin
        admin_email = os.getenv("ADMIN_EMAIL", "admin@uni.edu")
        admin_password = os.getenv("ADMIN_PASSWORD", "password123")

        print("  Creating Admin...")
        admin_user = models.User(
            id="admin-1",
            email=admin_email,
            hashed_password=utils.hash_password(admin_password),
            club_name="System Administrator",
            description="Main platform administrator.",
            role="admin",
            is_verified=True,
            logo_url="https://ui-avatars.com/api/?name=Admin&background=000&color=fff",
        )
        db.add(admin_user)

        # Clubs
        print(f"  Creating {len(MOCK_CLUBS)} clubs...")
        for club_data in MOCK_CLUBS:
            user = models.User(
                id=club_data["id"],
                email=club_data["email"],
                hashed_password=hashed_pwd,
                club_name=club_data["club_name"],
                description=club_data["description"],
                logo_url=club_data["logo_url"],
                banner_url=club_data["banner_url"],
                role="club",
                is_verified=club_data["is_verified"],
            )
            db.add(user)

        db.commit()

        # Events
        print(f"  Creating {len(MOCK_EVENTS)} events...")
        for event_data in MOCK_EVENTS:
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
                cover_image=event_data["cover_image"],
                tags=event_data.get("tags", ""),
                is_registration_open=event_data.get("is_registration_open", False),
                capacity=event_data.get("capacity"),
            )
            db.add(event)

        db.commit()
        print(f"Seeding complete! {len(MOCK_CLUBS)} clubs + {len(MOCK_EVENTS)} events created.")
        print(f"Admin login: {admin_email}")
        print(f"Club login: any club email with password 'password123'")

    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    seed()
