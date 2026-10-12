"""Cinema parsing and synchronization use isolated databases and fixture calendars."""
from datetime import datetime, timedelta
import json
from unittest.mock import Mock

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import cinema_scraper as scraper
import cinema_job as job
import cinema_api
import database
import models

NOW = datetime(2026, 10, 12, 9)


@pytest.fixture
def db():
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    models.Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def screening(source_id='123', start=None):
    return scraper.Screening(source_id, 'Paris, Texas', start or NOW + timedelta(days=1),
        scraper.VENUES[0].url, description='Film gösterimi', ticket_url=scraper.VENUES[0].url)


def test_cinema_sessions_are_scoped_to_requested_venue_and_retain_runtime():
    html = '''<div class="yn_cinema"><h2><a href="/tr-tr/mekan/another-cinema">Other</a></h2>
      <div class="yn_cinema_salon_info"><h2>Other room</h2><button data-title="1">11:00</button></div></div>
      <div class="yn_cinema"><h2><a href="/tr-tr/mekan/majestik-film-sinema">Majestik</a></h2>
      <div class="yn_cinema_salon_info"><h2>Salon 1</h2><button data-title="2">18:30</button></div></div>'''
    rows = scraper.parse_seances(html, scraper.VENUES[0], NOW.date(), 'https://biletinial.com/tr-tr/sinema/paris-texas',
        {'name': 'Paris, Texas', 'duration': 'PT2H25M00S', 'description': '<p>A film</p>'})
    assert len(rows) == 1 and rows[0].source_id == '2'
    assert rows[0].starts_at == NOW.replace(hour=18, minute=30)
    assert rows[0].ends_at == NOW.replace(hour=20, minute=55)
    assert rows[0].auditorium == 'Salon 1'
    with pytest.raises(ValueError):
        scraper.parse_seances('<html>challenge</html>', scraper.VENUES[0], NOW.date(), '', {})


def test_special_screenings_use_session_times_instead_of_summary_metadata():
    summary = {'@type': 'Event', 'name': 'Gel ve Gör', 'description': 'Film Gösterimi',
               'startDate': '2026-11-22T20:00:00+03:00'}
    html = '<script type="application/ld+json">' + json.dumps(summary) + '</script>' + '''
        <div class="ed-biletler__sehir__gun"><a itemprop="location">Atlas 1948 Sineması</a>
        <time itemprop="startDate" content="2026-11-22T17:00"></time>
        <meta itemprop="endDate" content="2026-11-22T19:00">
        <button class="seanceSelect" data-title="18689823"></button>
        <button class="seance-share" data-url="https://biletinial.com/tr-tr/etkinlik/gel-ve-gor/18689823"></button></div>'''
    rows = scraper.parse_special_screenings(html, scraper.VENUES[1], 'https://biletinial.com/tr-tr/etkinlik/gel-ve-gor')
    assert rows[0].starts_at.hour == 17
    assert rows[0].ends_at.hour == 19
    summary['description'] = 'Konser'
    html = html.replace('Film Gösterimi', 'Konser')
    # JSON emits unicode escapes, so construct an explicit non-film summary.
    html = '<script type="application/ld+json">' + json.dumps(summary) + '</script>'
    assert scraper.parse_special_screenings(html, scraper.VENUES[1], '') == []


def pera_entry(**changes):
    entry = dict(id=6046, groupId=4, allDay=True, start='2026-10-13T00:00:00',
        end='2026-10-13T00:00:00', title='Eraserhead  \n19.00', url='/film/eraserhead/6046/3580',
        extendedProps={'Date': '13 Ekim 2026 / 19.00', 'subtitle': 'Eraserhead  \n',
                       'Summary': '<p>Film</p>', 'showTicketURL': ''})
    entry.update(changes)
    return entry


def test_pera_excludes_workshops_exhibitions_and_digital_programs():
    rows = scraper.parse_pera([pera_entry(), pera_entry(url='/pera-ogrenme/atolye/film-atolyesi/8264', groupId=3),
                              pera_entry(url='/sergi/cumhuriyetin-kamera-arkasi/1325'),
                              pera_entry(url='/film-programi/program/123')])
    assert len(rows) == 1
    assert rows[0].title == 'Eraserhead' and rows[0].starts_at.hour == 19
    assert rows[0].ends_at is None and rows[0].ticket_url is None
    assert scraper.parse_pera([]) == []
    with pytest.raises(ValueError):
        scraper.parse_pera(pera_entry())
    with pytest.raises(ValueError):
        scraper.parse_pera([pera_entry(title='Film', extendedProps={})])


def test_timezones_and_date_list_structure():
    assert scraper.local_datetime('2026-10-13T16:00:00Z') == datetime(2026, 10, 13, 19)
    assert scraper.seance_dates('<div id="yn_dateList"><a data-date="2027-01-01"></a></div>')[0].year == 2027
    with pytest.raises(ValueError):
        scraper.seance_dates('<html>challenge</html>')
    with pytest.raises(ValueError):
        scraper.film_links('<html>challenge</html>')


def test_sync_is_idempotent_updates_times_and_cancels_removed_sessions(db):
    assert job.sync_source(db, scraper.VENUES[0], [screening()], NOW) == (1, 0, 0)
    changed = screening(start=NOW + timedelta(days=2))
    assert job.sync_source(db, scraper.VENUES[0], [changed], NOW) == (0, 1, 0)
    assert db.scalar(select(models.CinemaScreening)).starts_at == changed.starts_at
    assert job.sync_source(db, scraper.VENUES[0], [], NOW) == (0, 0, 1)
    assert not db.scalar(select(models.CinemaScreening)).is_active
    assert job.sync_source(db, scraper.VENUES[0], [changed], NOW) == (0, 1, 0)
    assert db.query(models.CinemaScreening).count() == 1
    assert db.query(models.Event).count() == 0


def test_source_failure_preserves_schedule_and_other_sources_continue(db, monkeypatch):
    job.sync_source(db, scraper.VENUES[0], [screening()], NOW)
    fetch = Mock(side_effect=[ValueError('layout changed'), [screening('atlas')], []])
    monkeypatch.setattr(job, 'scrape', fetch)
    assert job.run(db, client=Mock(), now=NOW) == ['biletinial_majestic']
    rows = db.scalars(select(models.CinemaScreening)).all()
    assert len(rows) == 2 and all(row.is_active for row in rows)
    assert fetch.call_count == 3


def test_dry_run_never_writes_and_job_reports_partial_failures(monkeypatch):
    db = Mock()
    monkeypatch.setattr(job, 'scrape', Mock(side_effect=[[], [], ValueError('bad')]))
    assert job.run(db, client=Mock(), now=NOW, dry_run=True) == ['pera']
    db.commit.assert_not_called()


def test_api_week_boundaries_pagination_inactive_and_auth(db):
    job.sync_source(db, scraper.VENUES[0], [screening(str(i), datetime(2026, 10, 12, 10) + timedelta(hours=i))
                                          for i in range(4)], NOW)
    job.sync_source(db, scraper.VENUES[1], [screening('next-week', datetime(2026, 10, 19, 0))], NOW)
    cancelled = db.scalar(select(models.CinemaScreening).where(models.CinemaScreening.source_id == '0'))
    cancelled.is_active = False
    db.commit()
    def verify(x_api_key: str = Header(None)):
        if x_api_key != 'test':
            raise HTTPException(403)
    app = FastAPI()
    app.include_router(cinema_api.router(verify))
    app.dependency_overrides[database.get_db] = lambda: db
    with TestClient(app) as client:
        assert client.get('/sinefil/screenings?week=2026-10-14').status_code == 403
        headers = {'x-api-key': 'test'}
        result = client.get('/sinefil/screenings?week=2026-10-14&page_size=2', headers=headers).json()
        assert result['pagination'] == dict(page=1, pageSize=2, total=3, totalPages=2)
        assert len(result['data']) == 2 and 'startsAt' in result['data'][0]
        assert len(client.get('/sinefil/screenings?week=2026-10-14&page=2&page_size=2', headers=headers).json()['data']) == 1
        assert client.get('/sinefil/screenings?week=bad', headers=headers).status_code == 422


def test_film_identity_is_stable_across_case_spacing_and_unicode():
    assert cinema_api.film_id('  PARIS,  TEXAS ') == cinema_api.film_id('Paris, Texas')
    assert cinema_api.film_id('Cafe\u0301') == cinema_api.film_id('Café')
    assert cinema_api.film_id('Akira') != cinema_api.film_id('Paris, Texas')


def test_film_page_combines_venues_dates_and_preserves_link_after_cancellation(db):
    from dataclasses import replace
    first = screening('morning')
    later = screening('evening', NOW + timedelta(days=1, hours=8))
    next_day = replace(screening('atlas', NOW + timedelta(days=2)), title=' PARIS,  TEXAS ')
    other_film = replace(screening('other'), title='Akira')
    job.sync_source(db, scraper.VENUES[0], [first, later, other_film], NOW)
    job.sync_source(db, scraper.VENUES[1], [next_day], NOW)
    cancelled = db.scalar(select(models.CinemaScreening).where(models.CinemaScreening.source_id == 'morning'))
    cancelled.is_active = False
    db.commit()
    def verify(x_api_key: str = Header(None)):
        if x_api_key != 'test':
            raise HTTPException(403)
    app = FastAPI()
    app.include_router(cinema_api.router(verify))
    app.dependency_overrides[database.get_db] = lambda: db
    movie_id = cinema_api.film_id(first.title)
    with TestClient(app) as client:
        path = f'/sinefil/films/{movie_id}'
        assert client.get(path).status_code == 403
        headers = {'x-api-key': 'test'}
        result = client.get(path, headers=headers).json()['data']
        assert result['id'] == movie_id
        assert len(result['screenings']) == 2
        assert [row['venue'] for row in result['screenings']] == ['Beyoğlu Majestik Sinema', 'Atlas 1948']
        assert all(row['filmId'] == movie_id for row in result['screenings'])
        week = client.get('/sinefil/screenings?week=2026-10-12', headers=headers).json()['data']
        assert len([row for row in week if row['filmId'] == movie_id]) == 2
        assert client.get('/sinefil/films/missing', headers=headers).status_code == 404
        job.sync_source(db, scraper.VENUES[0], [], NOW)
        job.sync_source(db, scraper.VENUES[1], [], NOW)
        result = client.get(path, headers=headers).json()['data']
        assert result['id'] == movie_id and result['screenings'] == []
