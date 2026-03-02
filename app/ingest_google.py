from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from .constants import AREA_CENTERS
from .db import build_engine, has_database
from .models import Place
from .orm import PlaceRecord
from .storage import create_tables

NEARBY_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
NEARBY_NEW_URL = "https://places.googleapis.com/v1/places:searchNearby"
TEXT_NEW_URL = "https://places.googleapis.com/v1/places:searchText"


@dataclass
class GooglePlace:
    place_id: str
    name: str
    latitude: float
    longitude: float
    price_level: int
    rating: float
    user_ratings_total: int
    open_now: bool
    types: list[str]
    quietness_level: int


def _guess_area(lat: float, lng: float) -> str:
    def dist2(a: tuple[float, float]) -> float:
        return (a[0] - lat) ** 2 + (a[1] - lng) ** 2

    return min(AREA_CENTERS.keys(), key=lambda k: dist2(AREA_CENTERS[k]))


def _tags_from_types(types: list[str], name: str) -> list[str]:
    tags: set[str] = set()
    t = set(types)
    lower_name = name.lower()

    if "cafe" in t or "coffee_shop" in t or "restaurant" in t:
        tags.add("wifi")
    if "library" in t or "book_store" in t or "coworking_space" in t or "university" in t:
        tags.add("ders")
        tags.add("sessiz")
    if "coworking_space" in t:
        tags.add("priz")
    if "restaurant" in t and "vegan" in lower_name:
        tags.add("vegan")
    if "meal_takeaway" in t and "vegan" in lower_name:
        tags.add("vegan")
    if "vegetarian_restaurant" in t or "vegan_restaurant" in t:
        tags.add("vegan")
    if any(k in lower_name for k in ["cowork", "study", "library", "work"]):
        tags.add("ders")
    if any(k in lower_name for k in ["quiet", "silent"]):
        tags.add("sessiz")
    if any(k in lower_name for k in ["social", "lounge", "bar"]):
        tags.add("kalabalik")
    if any(k in lower_name for k in ["vegan", "plant"]):
        tags.add("vegan")
    if (
        "dessert_shop" in t
        or "ice_cream_shop" in t
        or any(k in lower_name for k in ["muhallebi", "sutlac", "sütlaç", "kazandibi", "profiterol", "trilece", "tatli", "tatlı", "dessert", "parfe", "supangle"])
    ):
        tags.add("sutlu_tatli")

    return sorted(tags)


def _category_from_types(types: list[str], name: str) -> str:
    t = set(types)
    lower = name.lower()
    if "coworking_space" in t or "cowork" in lower:
        return "coworking"
    if "library" in t or "book_store" in t or "library" in lower:
        return "library"
    if "restaurant" in t or "meal_takeaway" in t:
        return "restaurant"
    if "dessert_shop" in t or "ice_cream_shop" in t or any(
        k in lower for k in ["muhallebi", "sutlac", "sütlaç", "kazandibi", "tatli", "tatlı", "dessert"]
    ):
        return "dessert"
    if "bakery" in t:
        return "cafe"
    return "cafe"


def _quietness_from_types_name(types: list[str], name: str) -> int:
    t = set(types)
    lower = name.lower()
    if any(k in lower for k in ["bar", "social", "lounge", "club", "pub"]):
        return 1
    if "bar" in t or "night_club" in t:
        return 1
    if "library" in t or "coworking_space" in t or any(k in lower for k in ["study", "library", "cowork", "quiet"]):
        return 3
    return 2


def _price_level_to_int(raw: str | int | None) -> int:
    if raw is None:
        return 2
    if isinstance(raw, int):
        return raw
    mapping = {
        "PRICE_LEVEL_FREE": 1,
        "PRICE_LEVEL_INEXPENSIVE": 1,
        "PRICE_LEVEL_MODERATE": 2,
        "PRICE_LEVEL_EXPENSIVE": 3,
        "PRICE_LEVEL_VERY_EXPENSIVE": 4,
    }
    return mapping.get(str(raw), 2)


def _fetch_nearby_legacy(api_key: str, center: str, radius: int, keyword: str | None = None) -> list[GooglePlace]:
    params = {
        "location": center,
        "radius": radius,
        "key": api_key,
        "type": "cafe",
    }
    if keyword:
        params["keyword"] = keyword

    with httpx.Client(timeout=20.0) as client:
        resp = client.get(NEARBY_URL, params=params)
        resp.raise_for_status()
        payload = resp.json()

    status = payload.get("status", "UNKNOWN")
    if status not in {"OK", "ZERO_RESULTS"}:
        error_message = payload.get("error_message", status)
        raise RuntimeError(str(error_message))

    results = payload.get("results", [])
    places: list[GooglePlace] = []
    for r in results:
        loc = (r.get("geometry") or {}).get("location") or {}
        opening_hours = r.get("opening_hours") or {}
        place = GooglePlace(
            place_id=r.get("place_id", ""),
            name=r.get("name", "Unknown"),
            latitude=float(loc.get("lat", 0.0)),
            longitude=float(loc.get("lng", 0.0)),
            price_level=int(r.get("price_level", 2)),
            rating=float(r.get("rating", 0.0)),
            user_ratings_total=int(r.get("user_ratings_total", 0)),
            open_now=bool(opening_hours.get("open_now", False)),
            types=r.get("types", []),
            quietness_level=_quietness_from_types_name(r.get("types", []), r.get("name", "Unknown")),
        )
        if place.place_id:
            places.append(place)

    return places


def _fetch_nearby_new(api_key: str, center: str, radius: int) -> list[GooglePlace]:
    return _fetch_nearby_new_by_type(api_key=api_key, center=center, radius=radius, included_type="cafe")


def _fetch_nearby_new_by_type(api_key: str, center: str, radius: int, included_type: str) -> list[GooglePlace]:
    lat, lng = center.split(",", 1)
    body = {
        "includedTypes": [included_type],
        "maxResultCount": 20,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": float(lat), "longitude": float(lng)},
                "radius": float(radius),
            }
        },
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.location,places.priceLevel,"
            "places.rating,places.userRatingCount,places.currentOpeningHours.openNow,places.types"
        ),
    }

    with httpx.Client(timeout=20.0) as client:
        resp = client.post(NEARBY_NEW_URL, headers=headers, json=body)
        resp.raise_for_status()
        payload = resp.json()

    results = payload.get("places", [])
    places: list[GooglePlace] = []
    for r in results:
        loc = r.get("location") or {}
        display_name = (r.get("displayName") or {}).get("text", "Unknown")
        opening_hours = r.get("currentOpeningHours") or {}
        place = GooglePlace(
            place_id=str(r.get("id", "")),
            name=display_name,
            latitude=float(loc.get("latitude", 0.0)),
            longitude=float(loc.get("longitude", 0.0)),
            price_level=_price_level_to_int(r.get("priceLevel")),
            rating=float(r.get("rating", 0.0)),
            user_ratings_total=int(r.get("userRatingCount", 0)),
            open_now=bool(opening_hours.get("openNow", False)),
            types=r.get("types", []),
            quietness_level=_quietness_from_types_name(r.get("types", []), display_name),
        )
        if place.place_id:
            places.append(place)
    return places


def _fetch_text_new(api_key: str, center: str, radius: int, query: str) -> list[GooglePlace]:
    lat, lng = center.split(",", 1)
    body = {
        "textQuery": query,
        "maxResultCount": 20,
        "locationBias": {
            "circle": {
                "center": {"latitude": float(lat), "longitude": float(lng)},
                "radius": float(radius),
            }
        },
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.location,places.priceLevel,"
            "places.rating,places.userRatingCount,places.currentOpeningHours.openNow,places.types"
        ),
    }

    with httpx.Client(timeout=20.0) as client:
        resp = client.post(TEXT_NEW_URL, headers=headers, json=body)
        resp.raise_for_status()
        payload = resp.json()

    results = payload.get("places", [])
    places: list[GooglePlace] = []
    for r in results:
        loc = r.get("location") or {}
        display_name = (r.get("displayName") or {}).get("text", "Unknown")
        opening_hours = r.get("currentOpeningHours") or {}
        base_types = r.get("types", [])
        if "vegan" in query.lower():
            base_types = list(set(base_types + ["vegan_restaurant"]))
        place = GooglePlace(
            place_id=str(r.get("id", "")),
            name=display_name,
            latitude=float(loc.get("latitude", 0.0)),
            longitude=float(loc.get("longitude", 0.0)),
            price_level=_price_level_to_int(r.get("priceLevel")),
            rating=float(r.get("rating", 0.0)),
            user_ratings_total=int(r.get("userRatingCount", 0)),
            open_now=bool(opening_hours.get("openNow", False)),
            types=base_types,
            quietness_level=_quietness_from_types_name(base_types, display_name),
        )
        if place.place_id:
            places.append(place)
    return places


def _fetch_nearby(api_key: str, center: str, radius: int, keyword: str | None = None) -> list[GooglePlace]:
    try:
        return _fetch_nearby_legacy(api_key=api_key, center=center, radius=radius, keyword=keyword)
    except RuntimeError as exc:
        message = str(exc).lower()
        if "legacy api" in message or "request_denied" in message or "not enabled" in message:
            combined: dict[str, GooglePlace] = {}
            for t in ["cafe", "restaurant", "meal_takeaway", "bakery"]:
                for p in _fetch_nearby_new_by_type(api_key=api_key, center=center, radius=radius, included_type=t):
                    combined[p.place_id] = p
            for q in [
                "vegan restaurant",
                "vegan cafe",
                "plant based food",
                "sutlu tatli",
                "muhallebi",
                "kazandibi",
                "sutlac",
                "dessert",
            ]:
                for p in _fetch_text_new(api_key=api_key, center=center, radius=radius, query=q):
                    combined[p.place_id] = p
            return list(combined.values())
        raise


def ingest_google_places() -> int:
    if not has_database():
        raise RuntimeError("DATABASE_URL is not configured")

    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    center = os.getenv("GOOGLE_SEARCH_CENTER", "41.0422,29.0083").strip()
    radius = int(os.getenv("GOOGLE_SEARCH_RADIUS_METERS", "2500"))
    ingest_areas = [x.strip() for x in os.getenv("GOOGLE_INGEST_AREAS", "").split(",") if x.strip()]
    if not api_key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is not configured")

    create_tables()
    centers: list[str] = []
    if ingest_areas:
        for area in ingest_areas:
            c = AREA_CENTERS.get(area)
            if c:
                centers.append(f"{c[0]},{c[1]}")
    else:
        centers = [f"{c[0]},{c[1]}" for c in AREA_CENTERS.values()]
    if not centers:
        centers = [center]

    fetched_map: dict[str, GooglePlace] = {}
    for c in centers:
        try:
            for gp in _fetch_nearby(api_key=api_key, center=c, radius=radius):
                fetched_map[gp.place_id] = gp
        except Exception:
            continue
    fetched = list(fetched_map.values())

    engine = build_engine()
    count = 0
    with Session(engine) as session:
        for gp in fetched:
            row = session.get(PlaceRecord, gp.place_id)
            if row is None:
                row = PlaceRecord(id=gp.place_id)
                session.add(row)

            row.name = gp.name
            row.area = _guess_area(gp.latitude, gp.longitude)
            row.category = _category_from_types(gp.types, gp.name)
            row.tags_csv = ",".join(_tags_from_types(gp.types, gp.name))
            row.quietness_level = gp.quietness_level
            row.latitude = gp.latitude
            row.longitude = gp.longitude
            row.price_level = gp.price_level
            row.google_rating = gp.rating
            row.google_reviews = gp.user_ratings_total
            row.is_open_now = gp.open_now
            row.local_votes_up = row.local_votes_up or 0
            row.local_votes_down = row.local_votes_down or 0
            row.local_weighted_up = row.local_weighted_up or 0.0
            row.local_weighted_down = row.local_weighted_down or 0.0
            row.updated_days_ago = 0
            count += 1

        session.commit()

    return count


def search_google_places_live(
    query: str,
    area: str | None = None,
    radius: int | None = None,
    max_count: int = 80,
) -> list[Place]:
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key:
        return []

    default_center = os.getenv("GOOGLE_SEARCH_CENTER", "41.0422,29.0083").strip()
    default_radius = int(os.getenv("GOOGLE_SEARCH_RADIUS_METERS", "2500"))
    search_radius = radius or default_radius

    center = default_center
    if area and area in AREA_CENTERS:
        c = AREA_CENTERS[area]
        center = f"{c[0]},{c[1]}"

    q = query.lower()
    query_variants: list[str] = [query]
    if "vegan" in q:
        query_variants.append("vegan restaurant")
    if any(k in q for k in ["sutlu", "sütlü", "muhallebi", "sutlac", "sütlaç", "kazandibi", "dessert", "tatli", "tatlı"]):
        query_variants.extend(["sutlu tatli", "dessert"])
    if any(k in q for k in ["ders", "study", "sessiz", "quiet", "calis", "çalış"]):
        query_variants.extend(["quiet cafe", "study cafe"])

    combined: dict[str, GooglePlace] = {}
    try:
        for qq in query_variants:
            for p in _fetch_text_new(api_key=api_key, center=center, radius=search_radius, query=qq):
                combined[p.place_id] = p
        for p in _fetch_nearby(api_key=api_key, center=center, radius=search_radius):
            combined[p.place_id] = p
    except Exception:
        pass

    out: list[Place] = []
    for gp in list(combined.values())[:max_count]:
        out.append(
            Place(
                id=gp.place_id,
                name=gp.name,
                area=_guess_area(gp.latitude, gp.longitude),
                category=_category_from_types(gp.types, gp.name),
                tags=_tags_from_types(gp.types, gp.name),
                quietness_level=gp.quietness_level,
                latitude=gp.latitude,
                longitude=gp.longitude,
                price_level=gp.price_level,
                google_rating=gp.rating,
                google_reviews=gp.user_ratings_total,
                is_open_now=gp.open_now,
                local_votes_up=0,
                local_votes_down=0,
                local_weighted_up=0.0,
                local_weighted_down=0.0,
                updated_days_ago=0,
            )
        )
    return out


if __name__ == "__main__":
    inserted = ingest_google_places()
    print(f"ingested: {inserted}")
