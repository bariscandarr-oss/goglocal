from __future__ import annotations

import math

from .constants import AREA_CENTERS
from .models import Place, QueryIntent, ScoredPlace
AREA_RADIUS_M = 4500


def _human_tag(tag: str) -> str:
    mapping = {
        "sutlu_tatli": "sütlü tatlı",
        "ders": "ders çalışma",
        "sessiz": "sessizlik",
        "vegan": "vegan",
        "wifi": "wifi",
        "priz": "priz",
        "kalabalik": "kalabalık",
    }
    return mapping.get(tag, tag)


def _is_milk_dessert_candidate(place: Place) -> bool:
    name = place.name.lower()
    milk_signals = ["muhallebi", "sutlac", "sütlaç", "kazandibi", "profiterol", "trilece", "puding", "parfe", "sütlü"]
    syrupy_signals = ["baklava", "kadayif", "kadayıf", "kunefe", "künefe", "burma", "şöbiyet", "katmer"]
    has_milk = any(s in name for s in milk_signals)
    has_syrupy = any(s in name for s in syrupy_signals)
    if has_milk:
        return True
    if has_syrupy:
        return False
    return place.category == "dessert"


def _milk_dessert_specificity(place: Place) -> float:
    name = place.name.lower()
    strong_signals = ["muhallebi", "sutlac", "sütlaç", "kazandibi", "profiterol", "trilece", "tiramisu", "puding", "parfe"]
    medium_signals = ["pastane", "patisserie", "dessert", "tatli", "tatlı", "supangle", "tavukgogsu", "tavukgöğsü"]
    if any(s in name for s in strong_signals):
        return 1.0
    if any(s in name for s in medium_signals):
        return 0.6
    if place.category == "dessert":
        return 0.5
    return 0.0


def _normalize_google_score(rating: float, reviews: int) -> float:
    rating_part = min(max(rating / 5.0, 0.0), 1.0)
    review_part = min(math.log10(max(reviews, 1)) / 4.0, 1.0)
    return 0.7 * rating_part + 0.3 * review_part


def _compute_local_score(place: Place) -> float:
    total = place.local_votes_up + place.local_votes_down
    vote_quality = place.local_votes_up / max(total, 1)
    weighted_total = place.local_weighted_up + place.local_weighted_down
    authentic_quality = place.local_weighted_up / max(weighted_total, 1e-6) if weighted_total > 0 else vote_quality
    freshness = max(0.0, 1.0 - (place.updated_days_ago / 30.0))
    return (0.45 * vote_quality) + (0.35 * authentic_quality) + (0.20 * freshness)


def _compute_relevance(place: Place, intent: QueryIntent) -> float:
    score = 0.0
    tags = set(place.tags)

    if intent.area:
        d = _distance_to_area_m(place, intent.area)
        if d is not None and d <= AREA_RADIUS_M:
            score += 0.25
        else:
            score -= 0.15

    if intent.required_tags:
        hit_count = sum(1 for t in intent.required_tags if t in tags)
        score += 0.50 * (hit_count / len(intent.required_tags))

    if intent.optional_tags:
        opt_hit = sum(1 for t in intent.optional_tags if t in tags)
        score += 0.10 * (opt_hit / len(intent.optional_tags))
        if "high_rating" in set(intent.optional_tags):
            score += 0.08 * _normalize_google_score(place.google_rating, place.google_reviews)

    if intent.preferred_categories:
        if place.category in set(intent.preferred_categories):
            score += 0.15
        else:
            score -= 0.08

    if intent.excluded_tags:
        excluded_hit = sum(1 for t in intent.excluded_tags if t in tags)
        if excluded_hit:
            score -= 0.25 * (excluded_hit / len(intent.excluded_tags))
        if "kalabalik" in set(intent.excluded_tags):
            if place.quietness_level == 1:
                score -= 0.25
            elif place.quietness_level == 3:
                score += 0.08

    if intent.open_now is not None:
        score += 0.10 if place.is_open_now == intent.open_now else 0.0

    if "sutlu_tatli" in set(intent.required_tags):
        score += 0.10 * _milk_dessert_specificity(place)

    return min(max(score, 0.0), 1.0)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2) + math.cos(p1) * math.cos(p2) * (math.sin(dl / 2) ** 2)
    return 2 * earth_r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _distance_score(place: Place, intent: QueryIntent) -> tuple[float, int | None]:
    if not intent.area:
        return 0.5, None

    center = AREA_CENTERS.get(intent.area)
    if center is None:
        return 0.5, None

    distance_m = int(_haversine_m(place.latitude, place.longitude, center[0], center[1]))
    max_range = float(intent.max_distance_m or 5000)
    score = max(0.0, min(1.0, 1.0 - (distance_m / max_range)))
    return score, distance_m


def _distance_to_area_m(place: Place, area: str) -> int | None:
    center = AREA_CENTERS.get(area)
    if center is None:
        return None
    return int(_haversine_m(place.latitude, place.longitude, center[0], center[1]))


def _is_in_area(place: Place, area: str, radius_m: int = AREA_RADIUS_M) -> bool:
    d = _distance_to_area_m(place, area)
    return d is not None and d <= radius_m


def _compute_personalized(place: Place, user_tags: list[str]) -> float:
    if not user_tags:
        return 0.5

    tags = set(place.tags)
    hit = sum(1 for t in user_tags if t in tags)
    return hit / len(user_tags)


def _passes_hard_filters(place: Place, intent: QueryIntent) -> bool:
    tags = set(place.tags)
    # Keep hard filters minimal; tags are primarily ranking signals.
    if intent.max_price_level and place.price_level > intent.max_price_level:
        return False
    if intent.open_now is True and not place.is_open_now:
        return False
    if intent.min_google_rating is not None and place.google_rating < intent.min_google_rating:
        return False
    if intent.min_google_reviews is not None and place.google_reviews < intent.min_google_reviews:
        return False
    if intent.max_distance_m is not None and intent.area:
        d = _distance_to_area_m(place, intent.area)
        if d is not None and d > intent.max_distance_m:
            return False
    if intent.excluded_tags and any(t in tags for t in intent.excluded_tags):
        return False
    if "sessiz" in set(intent.required_tags) and place.quietness_level == 1:
        return False
    if "kalabalik" in set(intent.excluded_tags) and place.quietness_level == 1:
        return False
    if intent.required_tags and any(t not in tags for t in intent.required_tags):
        return False
    if "sutlu_tatli" in set(intent.required_tags) and not _is_milk_dessert_candidate(place):
        return False
    if "sutlu_tatli" in set(intent.required_tags) and _milk_dessert_specificity(place) < 0.6:
        return False
    if "high_rating" in set(intent.optional_tags) and (place.google_rating < 4.0 or place.google_reviews < 10):
        return False
    return True


def _passes_base_filters(place: Place, intent: QueryIntent) -> bool:
    tags = set(place.tags)
    if intent.max_price_level and place.price_level > intent.max_price_level:
        return False
    if intent.open_now is True and not place.is_open_now:
        return False
    if intent.min_google_rating is not None and place.google_rating < intent.min_google_rating:
        return False
    if intent.min_google_reviews is not None and place.google_reviews < intent.min_google_reviews:
        return False
    if intent.max_distance_m is not None and intent.area:
        d = _distance_to_area_m(place, intent.area)
        if d is not None and d > (intent.max_distance_m + 1200):
            return False
    if intent.excluded_tags and any(t in tags for t in intent.excluded_tags):
        return False
    if "sessiz" in set(intent.required_tags) and place.quietness_level == 1:
        return False
    if "kalabalik" in set(intent.excluded_tags) and place.quietness_level == 1:
        return False
    return True


def _choose_candidates(places: list[Place], intent: QueryIntent, exclude_ids: set[str] | None = None) -> list[Place]:
    excluded = exclude_ids or set()
    pool = [p for p in places if p.id not in excluded]
    pool = pool if pool else places
    has_specific_constraints = bool(
        intent.required_tags
        or intent.excluded_tags
        or intent.max_price_level
        or intent.open_now
        or intent.min_google_rating is not None
        or intent.min_google_reviews is not None
        or intent.max_distance_m is not None
    )

    strict = [p for p in pool if _passes_hard_filters(p, intent)]
    if intent.area:
        strict_in_area = [p for p in strict if _is_in_area(p, intent.area)]
        if strict_in_area:
            return strict_in_area

        if has_specific_constraints:
            relaxed_zone = [p for p in pool if _passes_base_filters(p, intent) and _is_in_area(p, intent.area, radius_m=7000)]
            if relaxed_zone and intent.required_tags:
                min_hits = max(1, math.ceil(len(intent.required_tags) / 2))
                relaxed_zone = [p for p in relaxed_zone if sum(1 for t in intent.required_tags if t in set(p.tags)) >= min_hits]
            if relaxed_zone:
                return relaxed_zone
            return []

        area_only = [p for p in pool if _is_in_area(p, intent.area)]
        if area_only:
            return area_only
        return []

    if strict:
        return strict
    return places


def _weights_for_profile(profile: str | None) -> tuple[float, float, float, float, float]:
    if profile == "study_quiet":
        return 0.50, 0.15, 0.12, 0.08, 0.15
    if profile == "vegan_food":
        return 0.50, 0.20, 0.10, 0.05, 0.15
    if profile == "milk_dessert":
        return 0.42, 0.25, 0.12, 0.06, 0.15
    if profile == "budget_friendly":
        return 0.48, 0.17, 0.15, 0.08, 0.12
    if profile == "night_open":
        return 0.46, 0.17, 0.12, 0.05, 0.20
    return 0.45, 0.20, 0.15, 0.10, 0.10


def score_places(
    places: list[Place],
    intent: QueryIntent,
    user_tags: list[str],
    exclude_place_ids: list[str] | None = None,
) -> list[ScoredPlace]:
    candidates = _choose_candidates(places, intent, set(exclude_place_ids or []))
    wr, wg, wl, wp, wd = _weights_for_profile(intent.profile)

    scored: list[ScoredPlace] = []
    for place in candidates:
        general = _normalize_google_score(place.google_rating, place.google_reviews)
        local = _compute_local_score(place)
        weighted_total = place.local_weighted_up + place.local_weighted_down
        local_authenticity = place.local_weighted_up / max(weighted_total, 1e-6) if weighted_total > 0 else 0.5
        relevance = _compute_relevance(place, intent)
        personalized = _compute_personalized(place, user_tags)
        distance_score, distance_m = _distance_score(place, intent)

        final = (wr * relevance) + (wg * general) + (wl * local) + (wp * personalized) + (wd * distance_score)

        reasons: list[str] = []
        tags = set(place.tags)
        for t in intent.required_tags:
            if t in tags:
                reasons.append(f"{_human_tag(t)} kriterini sağlıyor")
            else:
                reasons.append(f"{_human_tag(t)} kriteri kısmi")
        for t in intent.excluded_tags:
            if t in tags:
                reasons.append(f"{_human_tag(t)} olabileceği için daha düşük puan")
        if intent.preferred_categories and place.category in set(intent.preferred_categories):
            reasons.append(f"{place.category} kategorisinde")
        if place.quietness_level == 3:
            reasons.append("sessizlik seviyesi yüksek")
        elif place.quietness_level == 2:
            reasons.append("sessizlik seviyesi orta")
        else:
            reasons.append("sessizlik seviyesi düşük")
        if intent.area and _is_in_area(place, intent.area):
            reasons.append(f"{intent.area} bölgesinde")
        if distance_m is not None:
            reasons.append(f"yaklaşık {distance_m}m mesafede")
        if place.is_open_now:
            reasons.append("şu an açık")

        scored.append(
            ScoredPlace(
                place=place,
                final_score=round(final, 4),
                general_score=round(general, 4),
                local_score=round(local, 4),
                local_authenticity_score=round(local_authenticity, 4),
                personalized_score=round(personalized, 4),
                relevance_score=round(relevance, 4),
                distance_m=distance_m,
                reasons=reasons,
            )
        )

    scored.sort(key=lambda x: x.final_score, reverse=True)
    return scored
