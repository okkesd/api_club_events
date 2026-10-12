"""Add optional source end datetime to existing scraping inboxes."""
from sqlalchemy import inspect, text


def migrate(engine):
    inspector = inspect(engine)
    if "scraped_events" not in inspector.get_table_names():
        return
    if "end_date" not in {c["name"] for c in inspector.get_columns("scraped_events")}:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE scraped_events ADD COLUMN end_date TIMESTAMP"))


if __name__ == "__main__":
    from database import engine
    migrate(engine)
