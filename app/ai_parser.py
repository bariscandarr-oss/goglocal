from __future__ import annotations

import json
import os
import re
from typing import Any

from .constants import AREA_ALIASES
from .intent_profiles import apply_intent_profile
from .models import QueryIntent

TAG_MAP = {
    "ders": ["ders", "study", "calis", "çalış", "odak", "focus", "work"],
    "sessiz": ["sessiz", "quiet", "sakin", "gürültüsüz", "gurultusuz"],
    "vegan": ["vegan"],
    "wifi": ["wifi", "wi-fi", "internet"],
    "priz": ["priz", "socket"],
    "kalabalik": ["kalabalik", "kalabalık", "crowded", "noisy"],
    "sutlu_tatli": [
        "sutlu tatli",
        "sütlü tatlı",
        "sutlac",
        "sütlaç",
        "muhallebi",
        "kazandibi",
        "profiterol",
        "trilece",
        "tatli",
        "tatlı",
        "dessert",
        "pastane",
        "patisserie",
        "pastry",
        "pasta",
        "pastalar",
    ],
    "sushi": ["sushi", "sushici", "suşi", "suşici", "japon"],
}
CATEGORY_MAP = {
    "cafe": ["cafe", "kafe", "kahve", "coffee"],
    "restaurant": ["restaurant", "restoran", "yemek", "sushi", "sushici", "japon"],
    "coworking": ["coworking", "co-working", "ofis", "çalışma alanı", "calisma alani"],
    "library": ["library", "kutuphane", "kütüphane"],
    "dessert": [
        "tatli",
        "tatlı",
        "dessert",
        "pastane",
        "bakery",
        "muhallebi",
        "sutlac",
        "sütlaç",
        "kazandibi",
        "patisserie",
        "pastry",
        "pasta",
        "pastalar",
        "kuru pasta",
        "yas pasta",
        "yaş pasta",
    ],
}

NOISE_WORDS = {
    "yer",
    "mekan",
    "mekani",
    "mekanı",
    "ariyorum",
    "istiyorum",
    "isterim",
    "olur",
    "olsun",
    "civarinda",
    "civarında",
    "yakinda",
    "yakınında",
    "icmek",
    "içmek",
    "yemek",
    "gidilecek",
    "oner",
    "oneri",
    "onerir",
    "en",
    "iyi",
    "kaliteli",
    "lezzetli",
}


def _normalize(text: str) -> str:
    text = text.lower().strip()
    tr_map = str.maketrans(
        {
            "ç": "c",
            "ğ": "g",
            "ı": "i",
            "ö": "o",
            "ş": "s",
            "ü": "u",
        }
    )
    text = text.translate(tr_map)
    return re.sub(r"\s+", " ", text)


def _uniq(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _extract_area(normalized_query: str) -> str | None:
    aliases = sorted(AREA_ALIASES.keys(), key=len, reverse=True)
    for alias in aliases:
        pattern = rf"\b{re.escape(alias)}(?:da|de|ta|te|daki|deki|dan|den|nda|nde|ndaki|nden)?\b"
        if re.search(pattern, normalized_query):
            return AREA_ALIASES[alias]
    return None


def _parse_with_rules(query: str) -> QueryIntent:
    q = _normalize(query)
    area = _extract_area(q)

    required_tags: list[str] = []
    excluded_tags: list[str] = []
    for canonical, words in TAG_MAP.items():
        if any(w in q for w in words):
            if canonical == "kalabalik":
                excluded_tags.append(canonical)
            else:
                required_tags.append(canonical)

    if any(k in q for k in ["kalabalik olmasin", "kalabalık olmasın", "gürültülü olmasın", "gurultulu olmasin"]):
        excluded_tags.append("kalabalik")
        if "sessiz" not in required_tags:
            required_tags.append("sessiz")

    preferred_categories: list[str] = []
    for category, words in CATEGORY_MAP.items():
        if any(w in q for w in words):
            preferred_categories.append(category)

    optional_tags: list[str] = []
    if any(k in q for k in ["lezzetli", "iyi", "en iyi", "best", "top rated", "kaliteli"]):
        optional_tags.append("high_rating")

    open_now = True if any(k in q for k in ["şimdi", "simdi", "açık", "acik", "open now"]) else None

    max_price_level = None
    if any(k in q for k in ["ucuz", "cheap", "öğrenci", "ogrenci"]):
        max_price_level = 2

    must_keywords = _extract_must_keywords(q=q, area=area)

    return QueryIntent(
        profile=None,
        area=area,
        must_keywords=must_keywords,
        required_tags=_uniq(required_tags),
        optional_tags=_uniq(optional_tags),
        excluded_tags=_uniq(excluded_tags),
        preferred_categories=_uniq(preferred_categories),
        open_now=open_now,
        max_price_level=max_price_level,
        min_google_rating=None,
        min_google_reviews=None,
        max_distance_m=None,
    )


def _extract_must_keywords(q: str, area: str | None) -> list[str]:
    def stem_locative(word: str) -> str:
        for suf in ["ndaki", "nde", "nda", "daki", "deki", "dan", "den", "de", "da", "ta", "te"]:
            if word.endswith(suf) and len(word) - len(suf) >= 4:
                return word[: -len(suf)]
        return word

    def stem_plural(word: str) -> str:
        if word.endswith("lar") and len(word) >= 6:
            return word[:-3]
        if word.endswith("ler") and len(word) >= 6:
            return word[:-3]
        return word

    words = re.findall(r"[a-z0-9]+", q)
    skip: set[str] = set(NOISE_WORDS)
    skip.update(AREA_ALIASES.keys())
    if area:
        skip.update([area])
    for values in TAG_MAP.values():
        skip.update([_normalize(v) for v in values])
    for values in CATEGORY_MAP.values():
        skip.update([_normalize(v) for v in values])

    out: list[str] = []
    seen: set[str] = set()
    for w in words:
        w = stem_locative(w)
        w = stem_plural(w)
        if len(w) < 4:
            continue
        if w in skip:
            continue
        if w in AREA_ALIASES:
            continue
        if w.isdigit():
            continue
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out[:3]


def _parse_with_openai(query: str) -> QueryIntent | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        completion = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "User place-search query to strict JSON intent converter. "
                        "Return only JSON with keys: area, required_tags, optional_tags, excluded_tags, "
                        "preferred_categories, open_now, max_price_level, min_google_rating, min_google_reviews, max_distance_m, must_keywords."
                    ),
                },
                {"role": "user", "content": query},
            ],
            response_format={"type": "json_object"},
        )

        raw = completion.choices[0].message.content or "{}"
        data: dict[str, Any] = json.loads(raw)
        return QueryIntent.model_validate(data)
    except Exception:
        return None


def parse_query_intent(query: str) -> QueryIntent:
    normalized = _normalize(query)
    ai_intent = _parse_with_openai(query)
    if ai_intent is not None:
        return apply_intent_profile(normalized, ai_intent)
    return apply_intent_profile(normalized, _parse_with_rules(query))


def parse_query_intent_with_source(query: str) -> tuple[QueryIntent, str]:
    normalized = _normalize(query)
    ai_intent = _parse_with_openai(query)
    if ai_intent is not None:
        return apply_intent_profile(normalized, ai_intent), "openai"
    return apply_intent_profile(normalized, _parse_with_rules(query)), "rules"
