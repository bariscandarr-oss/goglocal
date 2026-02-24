from __future__ import annotations

from sqlalchemy import Boolean, Float, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PlaceRecord(Base):
    __tablename__ = "places"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    area: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    tags_csv: Mapped[str] = mapped_column(String(600), default="", nullable=False)
    quietness_level: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    quiet_votes_up: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quiet_votes_down: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    local_weighted_up: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    local_weighted_down: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)

    price_level: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    google_rating: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    google_reviews: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_open_now: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    local_votes_up: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    local_votes_down: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_days_ago: Mapped[int] = mapped_column(Integer, default=30, nullable=False)

    def tags(self) -> list[str]:
        if not self.tags_csv:
            return []
        return [x.strip() for x in self.tags_csv.split(",") if x.strip()]


class UserProfileRecord(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    tags_csv: Mapped[str] = mapped_column(String(600), default="", nullable=False)
    budget_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_area: Mapped[str | None] = mapped_column(String(120), nullable=True)
    feedback_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    trust_score: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)

    def tags(self) -> list[str]:
        if not self.tags_csv:
            return []
        return [x.strip() for x in self.tags_csv.split(",") if x.strip()]
