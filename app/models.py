from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2)
    user_id: str | None = None
    user_tags: list[str] = Field(default_factory=list)
    exclude_place_ids: list[str] = Field(default_factory=list)
    max_results: int = Field(default=5, ge=1, le=20)


class QueryIntent(BaseModel):
    profile: str | None = None
    area: str | None = None
    location_hint: str | None = None
    must_keywords: list[str] = Field(default_factory=list)
    required_tags: list[str] = Field(default_factory=list)
    optional_tags: list[str] = Field(default_factory=list)
    excluded_tags: list[str] = Field(default_factory=list)
    preferred_categories: list[str] = Field(default_factory=list)
    open_now: bool | None = None
    max_price_level: int | None = Field(default=None, ge=1, le=4)
    min_google_rating: float | None = Field(default=None, ge=0, le=5)
    min_google_reviews: int | None = Field(default=None, ge=0)
    max_distance_m: int | None = Field(default=None, ge=100, le=20000)


class Place(BaseModel):
    id: str
    name: str
    city: str = "istanbul"
    area: str
    category: str
    tags: list[str]
    quietness_level: int = Field(default=2, ge=1, le=3)
    latitude: float
    longitude: float
    price_level: int
    google_rating: float
    google_reviews: int
    is_open_now: bool
    local_votes_up: int
    local_votes_down: int
    local_weighted_up: float = 0.0
    local_weighted_down: float = 0.0
    updated_days_ago: int


class ScoredPlace(BaseModel):
    place: Place
    final_score: float
    general_score: float
    local_score: float
    local_authenticity_score: float
    personalized_score: float
    relevance_score: float
    distance_m: int | None = None
    recommendation_summary: str | None = None
    reasons: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    interpreted_intent: QueryIntent
    results: list[ScoredPlace]
    meta: dict[str, Any]


class FeedbackRequest(BaseModel):
    place_id: str = Field(..., min_length=1)
    helpful: bool
    signal_tags: list[str] = Field(default_factory=list)
    user_id: str | None = None


class UserProfileRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=120)
    tags: list[str] = Field(default_factory=list)
    budget_level: int | None = Field(default=None, ge=1, le=4)
    home_area: str | None = None


class UserProfileResponse(BaseModel):
    user_id: str
    tags: list[str] = Field(default_factory=list)
    budget_level: int | None = None
    home_area: str | None = None
