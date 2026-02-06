# app/database.py
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os

load_dotenv()

# --- CONFIGURATION ---
# 1. SQLite (Development) - fast, simple, file-based
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "")
if SQLALCHEMY_DATABASE_URL == "":
    raise ValueError("DATABASE URL is not configures. Please check env files")

# 2. PostgreSQL (Production) - We will swap to this later
# SQLALCHEMY_DATABASE_URL = "postgresql://user:password@localhost/dbname"

# --- THE ENGINE ---
# check_same_thread is needed only for SQLite
if SQLALCHEMY_DATABASE_URL.startswith("postgresql"):
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_size=20,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=3600
    )
else:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False}
    )

# --- THE SESSION ---
# This is what you use to talk to the DB in your endpoints
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# --- THE BASE ---
# All our models (User, Event, Club) will inherit from this
Base = declarative_base()

# --- DEPENDENCY ---
# This helper function ensures we open a connection for a request 
# and close it immediately after, even if there's an error.
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()