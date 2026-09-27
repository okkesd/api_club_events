"""Idempotent additive category migration; no guessed organizer assignments."""
from sqlalchemy import inspect, text
import models


def migrate(engine):
    models.OrganizerCategory.__table__.create(engine, checkfirst=True)
    with engine.begin() as connection:
        for table in ('events', 'users'):
            if 'category' not in {col['name'] for col in inspect(connection).get_columns(table)}:
                connection.execute(text(f'ALTER TABLE {table} ADD COLUMN category VARCHAR(40)'))


if __name__ == '__main__':
    from database import engine
    migrate(engine)
