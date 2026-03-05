from __future__ import annotations

from dataclasses import dataclass

from .models import QueryIntent


@dataclass(frozen=True)
class IntentProfile:
    name: str
    triggers: tuple[str, ...]
    required_tags: tuple[str, ...] = ()
    optional_tags: tuple[str, ...] = ()
    excluded_tags: tuple[str, ...] = ()
    preferred_categories: tuple[str, ...] = ()
    open_now: bool | None = None
    max_price_level: int | None = None
    min_google_rating: float | None = None
    min_google_reviews: int | None = None
    max_distance_m: int | None = None


INTENT_PROFILES: tuple[IntentProfile, ...] = (
    IntentProfile(
        name="vegan_food",
        triggers=("vegan", "plant based", "bitkisel"),
        required_tags=("vegan",),
        preferred_categories=("restaurant", "cafe"),
        min_google_rating=4.0,
        min_google_reviews=20,
        max_distance_m=5000,
    ),
    IntentProfile(
        name="sushi_food",
        triggers=("sushi", "sushici", "suşi", "suşici", "japon"),
        required_tags=("sushi",),
        preferred_categories=("restaurant",),
        min_google_rating=4.0,
        min_google_reviews=20,
        max_distance_m=6000,
    ),
    IntentProfile(
        name="study_quiet",
        triggers=("ders", "calis", "çalış", "study", "odak", "focus", "sessiz", "sakin"),
        required_tags=("ders", "sessiz"),
        optional_tags=("wifi", "priz"),
        excluded_tags=("kalabalik",),
        preferred_categories=("cafe", "library", "coworking"),
        max_price_level=2,
        min_google_rating=4.0,
        min_google_reviews=20,
        max_distance_m=4000,
    ),
    IntentProfile(
        name="milk_dessert",
        triggers=("sutlu tatli", "sütlü tatlı", "sutlac", "sütlaç", "muhallebi", "kazandibi", "profiterol", "dessert"),
        required_tags=("sutlu_tatli",),
        preferred_categories=("dessert", "restaurant"),
        min_google_rating=4.0,
        min_google_reviews=10,
        max_distance_m=4500,
    ),
    IntentProfile(
        name="pastry_cake",
        triggers=("pasta", "pastalar", "pastane", "patisserie", "pastry", "yas pasta", "yaş pasta"),
        preferred_categories=("dessert", "cafe"),
        min_google_rating=3.8,
        min_google_reviews=8,
        max_distance_m=5000,
    ),
    IntentProfile(
        name="night_open",
        triggers=("gece", "24 saat", "acik", "açık", "open now"),
        open_now=True,
        preferred_categories=("cafe", "restaurant"),
        max_distance_m=6000,
    ),
    IntentProfile(
        name="budget_friendly",
        triggers=("ucuz", "ögrenci", "ogrenci", "fiyat performans", "hesapli", "ekonomik"),
        max_price_level=2,
        min_google_rating=3.8,
        min_google_reviews=20,
    ),
)


def _uniq(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _best_profile(normalized_query: str) -> IntentProfile | None:
    best: IntentProfile | None = None
    best_hits = 0
    for profile in INTENT_PROFILES:
        hits = sum(1 for t in profile.triggers if t in normalized_query)
        if hits > best_hits:
            best = profile
            best_hits = hits
    return best


def apply_intent_profile(normalized_query: str, intent: QueryIntent) -> QueryIntent:
    profile = _best_profile(normalized_query)
    if profile is None:
        return intent

    required_tags = _uniq(list(intent.required_tags) + list(profile.required_tags))
    optional_tags = _uniq(list(intent.optional_tags) + list(profile.optional_tags))
    excluded_tags = _uniq(list(intent.excluded_tags) + list(profile.excluded_tags))
    preferred_categories = _uniq(list(intent.preferred_categories) + list(profile.preferred_categories))

    max_price_level = intent.max_price_level
    if max_price_level is None:
        max_price_level = profile.max_price_level
    elif profile.max_price_level is not None:
        max_price_level = min(max_price_level, profile.max_price_level)

    min_google_rating = intent.min_google_rating
    if min_google_rating is None:
        min_google_rating = profile.min_google_rating
    elif profile.min_google_rating is not None:
        min_google_rating = max(min_google_rating, profile.min_google_rating)

    min_google_reviews = intent.min_google_reviews
    if min_google_reviews is None:
        min_google_reviews = profile.min_google_reviews
    elif profile.min_google_reviews is not None:
        min_google_reviews = max(min_google_reviews, profile.min_google_reviews)

    max_distance_m = intent.max_distance_m
    if max_distance_m is None:
        max_distance_m = profile.max_distance_m
    elif profile.max_distance_m is not None:
        max_distance_m = min(max_distance_m, profile.max_distance_m)

    return QueryIntent(
        profile=profile.name,
        area=intent.area,
        must_keywords=intent.must_keywords,
        required_tags=required_tags,
        optional_tags=optional_tags,
        excluded_tags=excluded_tags,
        preferred_categories=preferred_categories,
        open_now=intent.open_now if intent.open_now is not None else profile.open_now,
        max_price_level=max_price_level,
        min_google_rating=min_google_rating,
        min_google_reviews=min_google_reviews,
        max_distance_m=max_distance_m,
    )
