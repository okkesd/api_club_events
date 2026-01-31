from custom_types import *
from typing import Dict

event_data: list[EventData] = [
    EventData(
        id="evt-1",
        title="Intro to React",
        clubID="123",
        startTime="10:00",
        duration=2.0,
        startDate="2026-01-18",
        location="Room 101, Tech Hall",
        description="Join us to learn the basics of React...",
        coverImage="https://images.unsplash.com/photo-1633356122544-f134324a6cee?q=80&w=1000&auto=format&fit=crop",
        tags=["Workshop", "Free Food"],
        locationType="on-campus",
        isRegistrationOpen=True,
        registrationLink=None,
        capacity=30,
    ),
    EventData(
        id="evt-2",
        title="Robotics Workshop",
        clubID="456",
        startTime="14:00",
        duration=2.0,
        startDate="2026-01-16",
        location="Engineering Lab B",
        description="Build and program your first robot...",
        coverImage="https://images.unsplash.com/photo-1561557944-6e7860d1a7eb?q=80&w=1000&auto=format&fit=crop",
        tags=["Hardware", "Hands-on"],
        locationType="on-campus",
        isRegistrationOpen=False,
        registrationLink="https://robotics.example.com/signup",
        capacity=15,
    ),
    EventData(
        id="evt-3",
        title="Robotics Workshop 2",
        clubID="456",
        startTime="14:00",
        duration=2.0,
        startDate="2026-01-19",
        location="Engineering Lab B",
        description="Build and program your first robot...",
        coverImage="https://images.unsplash.com/photo-1561557944-6e7860d1a7eb?q=80&w=1000&auto=format&fit=crop",
        tags=["Hardware", "Hands-on"],
        locationType="on-campus",
        isRegistrationOpen=False,
        registrationLink="https://robotics.example.com/signup",
        capacity=15,
    )
    ,
    EventData(
        id="evt-5",
        title="Stargazing Night",
        clubID="457",
        startTime="16:00",
        duration=2.0,
        startDate="2026-01-25",
        location="City Observatory (Downtown)",
        description="Join us to look at Mars...",
        coverImage="https://images.unsplash.com/photo-1444703686981-a3abbc4d4fe3?q=80&w=1000&auto=format&fit=crop",
        tags=["Outdoors", "Science"],
        locationType="off-campus",
        isRegistrationOpen=True,
        registrationLink=None,
        capacity=50,
    ),
]


club_data: list[ClubData] = [
    ClubData(
        id="123",
        clubName="Coding Club",
        clubMail="coding@univ.edu",
        category="Technology",
        foundedYear=2019,
        description="We are a community of developers, hackers, and designers building cool things. Join us for weekly hackathons, workshops on React/Python, and industry talks.",
        logo="https://api.dicebear.com/7.x/identicon/svg?seed=CodingClub", 
        banner="https://images.unsplash.com/photo-1517694712202-14dd9538aa97?auto=format&fit=crop&q=80&w=2000",
        socials=SocialLinks(
            instagram="https://instagram.com/codingclub",
            website="https://github.com/codingclub",
            linkedin="https://linkedin.com/company/coding-club"
        )
    ),
    ClubData(
        id="456",
        clubName="Robotics Club",
        clubMail="robotics@univ.edu",
        category="Engineering",
        foundedYear=2021,
        description="Building the future, one servo at a time. We participate in national rover competitions and host beginner-friendly Arduino nights.",
        logo="https://api.dicebear.com/7.x/bottts/svg?seed=Robotics",
        banner="https://images.unsplash.com/photo-1581091226825-a6a2a5aee158?auto=format&fit=crop&q=80&w=2000",
        socials=SocialLinks(
            instagram="https://instagram.com/robotics",
            website="https://robotics-club.univ.edu"
        )
    ),
    ClubData(
        id="457",
        clubName="Astronomy Club",
        clubMail="astro@univ.edu",
        category="Science",
        foundedYear=2015,
        description="Look up! We organize stargazing trips to the desert, telescope building workshops, and lectures on astrophysics.",
        logo="https://api.dicebear.com/7.x/shapes/svg?seed=Astro",
        banner="https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&q=80&w=2000",
        socials=SocialLinks(
            instagram="https://instagram.com/astro"
        )
    )
]