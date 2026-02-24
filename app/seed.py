from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from .db import build_engine, has_database
from .models import Place
from .orm import PlaceRecord
from .storage import create_tables

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = BASE_DIR / "data" / "places.json"


def _upsert_place(session: Session, place: Place) -> None:
    row = session.get(PlaceRecord, place.id)
    tags_csv = ",".join(place.tags)

    if row is None:
        row = PlaceRecord(
            id=place.id,
            name=place.name,
            area=place.area,
            category=place.category,
            tags_csv=tags_csv,
            quietness_level=place.quietness_level,
            quiet_votes_up=0,
            quiet_votes_down=0,
            latitude=place.latitude,
            longitude=place.longitude,
            price_level=place.price_level,
            google_rating=place.google_rating,
            google_reviews=place.google_reviews,
            is_open_now=place.is_open_now,
            local_votes_up=place.local_votes_up,
            local_votes_down=place.local_votes_down,
            local_weighted_up=0.0,
            local_weighted_down=0.0,
            updated_days_ago=place.updated_days_ago,
        )
        session.add(row)
        return

    row.name = place.name
    row.area = place.area
    row.category = place.category
    row.tags_csv = tags_csv
    row.quietness_level = place.quietness_level
    row.quiet_votes_up = 0
    row.quiet_votes_down = 0
    row.latitude = place.latitude
    row.longitude = place.longitude
    row.price_level = place.price_level
    row.google_rating = place.google_rating
    row.google_reviews = place.google_reviews
    row.is_open_now = place.is_open_now
    row.local_votes_up = place.local_votes_up
    row.local_votes_down = place.local_votes_down
    row.local_weighted_up = 0.0
    row.local_weighted_down = 0.0
    row.updated_days_ago = place.updated_days_ago


def seed_from_json() -> int:
    if not has_database():
        raise RuntimeError("DATABASE_URL is not configured")

    create_tables()
    raw = json.loads(DATA_FILE.read_text())
    places = [Place.model_validate(item) for item in raw]

    engine = build_engine()
    with Session(engine) as session:
        for place in places:
            _upsert_place(session, place)
        session.commit()

    return len(places)
