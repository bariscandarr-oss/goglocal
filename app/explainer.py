from __future__ import annotations

import json
import os
from typing import Any

from .models import QueryIntent, ScoredPlace


def _human_tag(tag: str) -> str:
    mapping = {
        "sutlu_tatli": "sütlü tatlı",
        "sushi": "sushi",
        "ders": "ders çalışma",
        "sessiz": "sessiz ortam",
        "vegan": "vegan",
        "wifi": "wifi",
        "priz": "priz",
        "kalabalik": "kalabalık",
    }
    return mapping.get(tag, tag)


def _grounded_points(intent: QueryIntent, item: ScoredPlace) -> list[str]:
    p = item.place
    tags = set(p.tags)
    points: list[str] = []

    for t in intent.required_tags:
        if t in tags:
            points.append(f"{_human_tag(t)} kriterini karşılıyor")
    if intent.preferred_categories and p.category in set(intent.preferred_categories):
        points.append(f"{p.category} kategorisinde")
    if intent.area and item.distance_m is not None and item.distance_m <= 4500:
        points.append(f"{intent.area} bölgesinde")
    if intent.open_now is True and p.is_open_now:
        points.append("şu an açık")
    if intent.max_price_level is not None and p.price_level <= intent.max_price_level:
        points.append("bütçe sınırına uygun")
    if intent.min_google_rating is not None and p.google_rating >= intent.min_google_rating:
        points.append(f"puanı en az {intent.min_google_rating:.1f}")
    if intent.min_google_reviews is not None and p.google_reviews >= intent.min_google_reviews:
        points.append(f"yeterli yorum sayısı ({p.google_reviews})")
    if item.distance_m is not None and intent.area:
        points.append(f"yaklaşık {item.distance_m}m uzaklıkta")

    if not points:
        points.append("genel puanı ve erişilebilirliği iyi")
    return points


def _tradeoff(item: ScoredPlace) -> str:
    p = item.place
    if item.distance_m is not None and item.distance_m > 2500:
        return "biraz uzak olabilir"
    if p.price_level >= 4:
        return "fiyat seviyesi yüksek"
    if not p.is_open_now:
        return "şu an kapalı olabilir"
    return "yoğun saatlerde kalabalıklaşabilir"


def _fallback_summary(intent: QueryIntent, item: ScoredPlace) -> str:
    p = item.place
    points = _grounded_points(intent=intent, item=item)
    return f"{p.name}: " + "; ".join(points[:2]) + f". Not: {_tradeoff(item)}."


def _openai_summaries(query: str, intent: QueryIntent, results: list[ScoredPlace]) -> dict[str, str] | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        from openai import OpenAI

        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        client = OpenAI(api_key=api_key)

        payload: list[dict[str, Any]] = []
        for item in results:
            payload.append(
                {
                    "place_id": item.place.id,
                    "name": item.place.name,
                    "area": item.place.area,
                    "category": item.place.category,
                    "tags": item.place.tags,
                    "price_level": item.place.price_level,
                    "open_now": item.place.is_open_now,
                    "distance_m": item.distance_m,
                    "reasons": item.reasons,
                    "scores": {
                        "final": item.final_score,
                        "local": item.local_score,
                        "general": item.general_score,
                    },
                }
            )

        completion = client.chat.completions.create(
            model=model,
            temperature=0.3,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a concise Turkish recommender. Return strict JSON with key 'summaries' as array. "
                        "Each item must contain: place_id, text. text max 28 words. "
                    "Only mention constraints present in intent (required_tags, preferred_categories, area, open_now, max_price_level). "
                    "Also use intent.profile, min_google_rating, min_google_reviews, max_distance_m when present. "
                    "Do not mention unrelated attributes. Add exactly one short tradeoff sentence."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "query": query,
                            "intent": intent.model_dump(),
                            "results": payload,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )

        raw = completion.choices[0].message.content or "{}"
        data = json.loads(raw)
        summaries = data.get("summaries", [])

        mapped: dict[str, str] = {}
        for item in summaries:
            pid = str(item.get("place_id", "")).strip()
            text = str(item.get("text", "")).strip()
            if pid and text:
                mapped[pid] = text
        return mapped
    except Exception:
        return None


def add_recommendation_summaries(query: str, intent: QueryIntent, results: list[ScoredPlace]) -> str:
    ai = _openai_summaries(query=query, intent=intent, results=results)
    if ai is not None:
        for item in results:
            item.recommendation_summary = ai.get(item.place.id) or _fallback_summary(intent, item)
        return "openai"

    for item in results:
        item.recommendation_summary = _fallback_summary(intent, item)
    return "fallback"
