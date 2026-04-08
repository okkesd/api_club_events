# Project: Club Events Platform — Backend API

University club management system backend built with FastAPI + SQLAlchemy + PostgreSQL (Supabase).

## What it does
- **Clubs** register as users, get verified by admin, then post **events** and **announcements**
- **Students** (public, no auth) browse events/announcements and subscribe to get email notifications
- **Admin** manages club verification, views subscriptions, and oversees content

## Subscription system
Two types of subscriptions, both stored under a single `Subscription` row per email:
- **Club subscriptions** — `ClubSubscription` junction table links subscriber to specific clubs (instant/weekly notifications when that club posts)
- **Category subscriptions** — `CategorySubscription` junction table links subscriber to announcement categories (internship, job, scholarship, competition, recruitment, academic, workshop, general)
- Empty clubs + empty categories = subscribed to everything (weekly digest sends all)
- Email sending handled by `weekly_digest.py` (not fully configured yet)

## Key files
- `main.py` — all FastAPI endpoints (events, announcements, subscriptions, admin, auth)
- `models.py` — SQLAlchemy models (User, Event, Announcement, Subscription, ClubSubscription, CategorySubscription, etc.)
- `schemas.py` — Pydantic request/response schemas (uses CamelCase conversion for frontend)
- `database.py` — DB engine/session setup (PostgreSQL via Supabase)
- `weekly_digest.py` — email digest script
- `migrate_db.py` — manual migration scripts
- `dump_db.py` — dumps all tables to markdown files in `db_dump/` for inspection

## Database
- PostgreSQL hosted on Supabase
- Migrations are manual scripts (`migrate_db.py`), not Alembic

## Agent Bridge

You are the "backend" agent. There is a "frontend" agent working in `/home/debianokkes/okkes/club_events/`.
You share a communication bridge via MCP (server name: "bridge").

Rules:
- When you change something that affects the API contract (request/response shapes, endpoints, headers), create a ticket or send a message to notify frontend.
- When you see bridge messages in the conversation, read and act on them.
- When you see an open ticket from frontend, pick it up with add_to_ticket and work on it.
- When you've completed the work for a ticket, resolve it with resolve_ticket and a summary of what you did.
- Keep ticket messages concise — the other agent has limited context too.
- One open ticket at a time.

### Ticket lifecycle
Tickets follow a strict lifecycle: **open → in_progress → resolved → closed**.
- **Creator** calls `create_ticket` → status becomes `open`.
- **Non-creator** calls `add_to_ticket` to comment → status becomes `in_progress`.
- **Non-creator** calls `resolve_ticket` with a summary when done → status becomes `resolved`.
- **Creator** calls `close_ticket` to confirm and close → status becomes `closed`.
- Only the non-creator can resolve; only the creator can close.
- Always check inbox (`check_inbox`) for ticket updates before acting on tickets.

### User shorthand
- When the user types just `.` (a single dot), it means "check the bridge" — call `check_inbox` immediately.
