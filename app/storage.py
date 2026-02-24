from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from .db import build_engine, has_database
from .models import Place
from .orm import Base, PlaceRecord, UserProfileRecord

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = BASE_DIR / "data" / "places.json"


def _json_places() -> list[Place]:
    raw = json.loads(DATA_FILE.read_text())
    return [Place.model_validate(item) for item in raw]


def _record_to_place(row: PlaceRecord) -> Place:
    return Place(
        id=row.id,
        name=row.name,
        area=row.area,
        category=row.category,
        tags=row.tags(),
        quietness_level=row.quietness_level,
        latitude=row.latitude,
        longitude=row.longitude,
        price_level=row.price_level,
        google_rating=row.google_rating,
        google_reviews=row.google_reviews,
        is_open_now=row.is_open_now,
        local_votes_up=row.local_votes_up,
        local_votes_down=row.local_votes_down,
        local_weighted_up=row.local_weighted_up,
        local_weighted_down=row.local_weighted_down,
        updated_days_ago=row.updated_days_ago,
    )


def load_places() -> tuple[list[Place], str]:
    if not has_database():
        return _json_places(), "json"

    try:
        engine = build_engine()
        with Session(engine) as session:
            rows = session.query(PlaceRecord).all()
            if not rows:
                return _json_places(), "json"
            return [_record_to_place(r) for r in rows], "database"
    except Exception:
        return _json_places(), "json"


def create_tables() -> None:
    engine = build_engine()
    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.execute(text("ALTER TABLE places ADD COLUMN IF NOT EXISTS location geography(Point, 4326)"))
        conn.execute(text("ALTER TABLE places ADD COLUMN IF NOT EXISTS quietness_level integer DEFAULT 2"))
        conn.execute(text("ALTER TABLE places ADD COLUMN IF NOT EXISTS quiet_votes_up integer DEFAULT 0"))
        conn.execute(text("ALTER TABLE places ADD COLUMN IF NOT EXISTS quiet_votes_down integer DEFAULT 0"))
        conn.execute(text("ALTER TABLE places ADD COLUMN IF NOT EXISTS local_weighted_up double precision DEFAULT 0"))
        conn.execute(text("ALTER TABLE places ADD COLUMN IF NOT EXISTS local_weighted_down double precision DEFAULT 0"))
        conn.execute(text("UPDATE places SET quietness_level = 2 WHERE quietness_level IS NULL"))
        conn.execute(text("UPDATE places SET quiet_votes_up = 0 WHERE quiet_votes_up IS NULL"))
        conn.execute(text("UPDATE places SET quiet_votes_down = 0 WHERE quiet_votes_down IS NULL"))
        conn.execute(text("UPDATE places SET local_weighted_up = 0 WHERE local_weighted_up IS NULL"))
        conn.execute(text("UPDATE places SET local_weighted_down = 0 WHERE local_weighted_down IS NULL"))
        conn.execute(text("ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS home_area varchar(120)"))
        conn.execute(text("ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS feedback_count integer DEFAULT 0"))
        conn.execute(text("ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS trust_score double precision DEFAULT 0.5"))
        conn.execute(text("UPDATE user_profiles SET feedback_count = 0 WHERE feedback_count IS NULL"))
        conn.execute(text("UPDATE user_profiles SET trust_score = 0.5 WHERE trust_score IS NULL"))
        conn.execute(text("UPDATE places SET location = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography WHERE location IS NULL"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_places_location ON places USING GIST(location)"))


def _recompute_quietness_level(row: PlaceRecord) -> None:
    total = int(row.quiet_votes_up) + int(row.quiet_votes_down)
    if total < 3:
        return
    ratio = int(row.quiet_votes_up) / max(total, 1)
    if ratio >= 0.70:
        row.quietness_level = 3
    elif ratio <= 0.35:
        row.quietness_level = 1
    else:
        row.quietness_level = 2


def _feedback_weight(user: UserProfileRecord | None, place: PlaceRecord) -> float:
    trust = 0.5
    locality = 0.5
    if user is not None:
        trust = max(0.2, min(user.trust_score, 1.0))
        if user.home_area:
            locality = 1.0 if user.home_area == place.area else 0.25
    return max(0.1, min(1.0, trust * locality))


def apply_feedback(place_id: str, helpful: bool, signal_tags: list[str] | None = None, user_id: str | None = None) -> bool:
    if not has_database():
        return False

    engine = build_engine()
    with Session(engine) as session:
        row = session.get(PlaceRecord, place_id)
        if row is None:
            return False
        user = session.get(UserProfileRecord, user_id) if user_id else None

        if helpful:
            row.local_votes_up = int(row.local_votes_up) + 1
        else:
            row.local_votes_down = int(row.local_votes_down) + 1

        weight = _feedback_weight(user, row)
        if helpful:
            row.local_weighted_up = float(row.local_weighted_up) + weight
        else:
            row.local_weighted_down = float(row.local_weighted_down) + weight

        signals = set(signal_tags or [])
        if "sessiz" in signals or "kalabalik" in signals:
            quiet_helpful = helpful
            if "kalabalik" in signals and "sessiz" not in signals:
                quiet_helpful = not helpful
            if quiet_helpful:
                row.quiet_votes_up = int(row.quiet_votes_up) + 1
            else:
                row.quiet_votes_down = int(row.quiet_votes_down) + 1
            _recompute_quietness_level(row)

        if user is not None:
            user.feedback_count = int(user.feedback_count) + 1
            user.trust_score = min(1.0, 0.5 + (user.feedback_count / 200))

        row.updated_days_ago = 0
        session.commit()
        return True


def upsert_user_profile(user_id: str, tags: list[str], budget_level: int | None, home_area: str | None = None) -> bool:
    if not has_database():
        return False

    try:
        engine = build_engine()
        with Session(engine) as session:
            row = session.get(UserProfileRecord, user_id)
            if row is None:
                row = UserProfileRecord(user_id=user_id)
                session.add(row)

            row.tags_csv = ",".join(sorted({t.strip() for t in tags if t.strip()}))
            row.budget_level = budget_level
            row.home_area = home_area
            session.commit()
            return True
    except Exception:
        return False


def get_user_profile(user_id: str) -> tuple[list[str], int | None, str | None] | None:
    if not has_database():
        return None

    try:
        engine = build_engine()
        with Session(engine) as session:
            row = session.get(UserProfileRecord, user_id)
            if row is None:
                return None
            return row.tags(), row.budget_level, row.home_area
    except Exception:
        return None


def count_db_places() -> int:
    if not has_database():
        return 0

    try:
        engine = build_engine()
        with Session(engine) as session:
            return int(session.query(PlaceRecord).count())
    except Exception:
        return 0
