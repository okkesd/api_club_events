"""Public cinema calendars. All timestamps are local Europe/Istanbul wall times."""
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import re
import time
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ISTANBUL = ZoneInfo("Europe/Istanbul")
BILETINIAL = "https://biletinial.com"
PERA = "https://www.peramuzesi.org.tr"
HORIZON_DAYS = 90


@dataclass(frozen=True)
class Venue:
    source: str
    name: str
    url: str
    branch_id: int | None = None


VENUES = (
    Venue("biletinial_majestic", "Beyoğlu Majestik Sinema",
          BILETINIAL + "/tr-tr/mekan/majestik-film-sinema", 1058),
    Venue("biletinial_atlas", "Atlas 1948",
          BILETINIAL + "/tr-tr/mekan/beyoglu-atlas-sinemasi-1", 22521),
    Venue("pera", "Pera Müzesi", PERA + "/Ajanda"),
)


@dataclass
class Screening:
    source_id: str
    title: str
    starts_at: datetime
    source_url: str
    ends_at: datetime | None = None
    description: str = ""
    image_url: str | None = None
    ticket_url: str | None = None
    auditorium: str | None = None


def local_datetime(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(ISTANBUL).replace(tzinfo=None) if parsed.tzinfo else parsed


def plain_text(value):
    return BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)[:5000]


def safe_url(base, value):
    if not value:
        return None
    url = urljoin(base, value)
    return url if urlsplit(url).scheme in ("https", "http") else None


def structured_data(html):
    rows = []
    for script in BeautifulSoup(html, "html.parser").select('script[type="application/ld+json"]'):
        data = json.loads(script.string or "")
        rows.extend(data if isinstance(data, list) else data.get("@graph", [data]))
    return rows


def movie_duration(value):
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not match:
        return None
    duration = timedelta(hours=int(match[1] or 0), minutes=int(match[2] or 0), seconds=int(match[3] or 0))
    return duration if duration.total_seconds() > 0 else None


def film_links(html):
    soup = BeautifulSoup(html, "html.parser")
    listing = soup.select_one("#placeEventsList")
    if listing is None:
        raise ValueError("Biletinial venue listing structure changed")
    return sorted({urljoin(BILETINIAL, a["href"]) for a in listing.select("h3 a[href]")
                   if re.match(r"/tr-tr/(sinema|etkinlik)/[\w-]+(?:\?|$)", a["href"])})


def seance_dates(html):
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one("#yn_dateList") is None:
        raise ValueError("Biletinial date list structure changed")
    return sorted({datetime.strptime(a["data-date"], "%Y-%m-%d").date()
                   for a in soup.select("#yn_dateList [data-date]")})


def parse_seances(html, venue, date, url, movie):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for cinema in soup.select(".yn_cinema"):
        link = cinema.select_one("h2 a[href]")
        if not link or urlsplit(link["href"]).path != urlsplit(venue.url).path:
            continue
        for room in cinema.select(".yn_cinema_salon_info"):
            auditorium = room.select_one("h2")
            for button in room.select("button[data-title]"):
                clock = button.get_text(strip=True)
                if not re.fullmatch(r"\d{2}:\d{2}", clock) or not button["data-title"].isdigit():
                    raise ValueError("Biletinial session structure changed")
                start = datetime.fromisoformat(f"{date.isoformat()}T{clock}")
                duration = movie_duration(movie.get("duration"))
                rows.append(Screening(button["data-title"], movie["name"], start, url,
                    start + duration if duration else None, plain_text(movie.get("description")),
                    safe_url(url, movie.get("image")), url,
                    auditorium.get_text(strip=True) if auditorium else None))
    if not rows:
        # A listed date must have a recognizable venue and sessions; preserve old
        # data on unexpected empty responses instead of cancelling the program.
        raise ValueError("No recognizable Biletinial sessions for a listed date")
    return rows


def parse_special_screenings(html, venue, url):
    data = structured_data(html)
    event = next((e for e in data if e.get("@type") == "Event"), None)
    if not event:
        raise ValueError("Biletinial event metadata missing")
    description = plain_text(event.get("description"))
    if not re.search(r"film\s+gösterim", description, re.I):
        return []
    soup = BeautifulSoup(html, "html.parser")
    containers = soup.select(".ed-biletler__sehir__gun")
    if not containers:
        raise ValueError("Biletinial special screening structure changed")
    rows = []
    for container in containers:
        location = container.select_one('[itemprop="location"]')
        name = location.get_text(" ", strip=True) if location else ""
        if not ((venue.branch_id == 22521 and "atlas" in name.lower()) or
                (venue.branch_id == 1058 and "majestik" in name.lower())):
            continue
        start = container.select_one('[itemprop="startDate"][content]')
        end = container.select_one('[itemprop="endDate"][content]')
        button = container.select_one(".seanceSelect[data-title]")
        share = container.select_one(".seance-share[data-url]")
        if not start or not button or not button["data-title"].isdigit():
            raise ValueError("Missing special screening session identity/time")
        rows.append(Screening(button["data-title"], event["name"], local_datetime(start["content"]),
            url, local_datetime(end["content"]) if end else None, description,
            safe_url(url, event.get("image")), safe_url(url, share["data-url"]) if share else url))
    return rows


def parse_pera(entries):
    if not isinstance(entries, list) or any(not isinstance(e, dict) or "start" not in e for e in entries):
        raise ValueError("Pera calendar response structure changed")
    rows = []
    for entry in entries:
        path = urlsplit(entry.get("url") or "").path
        # The live film category is groupId=4 (old JS comments say 3). Route
        # plus film/program IDs distinguish films from workshops and exhibitions.
        if not re.fullmatch(r"/film/[^/]+/\d+/\d+", path, re.I):
            continue
        url = safe_url(PERA, entry["url"])
        if urlsplit(url).netloc != urlsplit(PERA).netloc:
            raise ValueError("Unexpected Pera film origin")
        props = entry.get("extendedProps") or {}
        start = local_datetime(entry["start"])
        if entry.get("allDay"):
            clock = re.search(r"\b([01]?\d|2[0-3])[.:]([0-5]\d)\b",
                              props.get("Date", "") + " " + entry.get("title", ""))
            if not clock:
                raise ValueError("Missing Pera film screening time")
            start = start.replace(hour=int(clock[1]), minute=int(clock[2]))
        title = (props.get("subtitle") or re.sub(r"\s*\d{1,2}[.:]\d{2}\s*$", "", entry["title"])).strip()
        if not title:
            raise ValueError("Missing Pera film title")
        end = local_datetime(entry["end"]) if entry.get("end") else None
        rows.append(Screening(f"{entry['id']}:{start.isoformat()}", title, start, url,
            end if end and end > start else None, plain_text(props.get("Summary")),
            safe_url(PERA, props.get("ImageURL")), safe_url(PERA, props.get("showTicketURL"))))
    return rows


class CalendarClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Evenements-Sinefil/1.0",
                                     "X-Requested-With": "XMLHttpRequest"})
        self.session.mount("https://", HTTPAdapter(max_retries=Retry(total=2, backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])))

    def get(self, url, **kwargs):
        time.sleep(0.2)
        response = self.session.get(url, timeout=(10, 25), allow_redirects=False, **kwargs)
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("Unexpected calendar redirect")
        response.encoding = "utf-8"
        return response

    def close(self):
        self.session.close()


def scrape(venue, client, now):
    cutoff = (now + timedelta(days=HORIZON_DAYS)).replace(hour=0, minute=0, second=0, microsecond=0)
    if venue.source == "pera":
        entries = client.get(PERA + "/Home/GetCalendarEvents", params={
            "start": now.date().isoformat(), "end": cutoff.date().isoformat()}).json()
        rows = parse_pera(entries)
    else:
        rows = []
        for url in film_links(client.get(venue.url).text):
            html = client.get(url).text
            if "/etkinlik/" in urlsplit(url).path:
                rows.extend(parse_special_screenings(html, venue, url))
                continue
            movie = next((e for e in structured_data(html) if e.get("@type") == "Movie"), None)
            event_id = re.search(r"\bvar\s+eventId\s*=\s*(\d+)\s*;", html)
            if not movie or not event_id:
                raise ValueError("Biletinial movie structure changed")
            dates = seance_dates(client.get(BILETINIAL + "/details/GetDateListForCity", params={
                "eventId": event_id[1], "langId": 1, "cityId": 5, "cinemaBranchId": venue.branch_id}).text)
            for date in dates:
                if now.date() <= date < cutoff.date():
                    sessions = client.get(BILETINIAL + f"/dynamic/get_seances/{event_id[1]}/5/{date}/1/tr",
                        params={"cinemaBranchId": venue.branch_id}).text
                    rows.extend(parse_seances(sessions, venue, date, url, movie))
    return [row for row in rows if now <= row.starts_at < cutoff]
