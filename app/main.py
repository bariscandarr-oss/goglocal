from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .ai_parser import parse_query_intent_with_source
from .explainer import add_recommendation_summaries
from .models import FeedbackRequest, Place, QueryIntent, ScoredPlace, SearchRequest, SearchResponse, UserProfileRequest, UserProfileResponse
from .scoring import score_places
from .seed import seed_from_json
from .ingest_google import ingest_google_places, search_live_places
from .storage import apply_feedback, count_db_places, create_tables, get_user_profile, load_places, upsert_user_profile

load_dotenv()

app = FastAPI(title="GoGlocal API", version="0.1.0")
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")


@app.on_event("startup")
def on_startup() -> None:
    if os.getenv("AUTO_INIT_DB", "false").strip().lower() in {"1", "true", "yes"}:
        try:
            create_tables()
            if os.getenv("AUTO_SEED_JSON", "false").strip().lower() in {"1", "true", "yes"}:
                if count_db_places() == 0:
                    seed_from_json()
        except Exception:
            # Keep app booting even when DB migration/seed fails; endpoints still return useful errors.
            pass


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "goglocal-api", "ui": "/app"}


@app.get("/app")
def web_app() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/places")
def list_places() -> list[Place]:
    places, _ = load_places()
    return places


@app.post("/admin/init-db")
def init_db() -> dict[str, str]:
    create_tables()
    return {"status": "ok"}


@app.post("/admin/seed-json")
def seed_json() -> dict[str, str | int]:
    inserted = seed_from_json()
    return {"status": "ok", "inserted": inserted}


@app.post("/admin/ingest-google")
def ingest_google() -> dict[str, str | int]:
    try:
        inserted = ingest_google_places()
        return {"status": "ok", "inserted": inserted}
    except Exception as exc:
        return {"status": "failed", "reason": str(exc)}


@app.post("/search", response_model=SearchResponse)
def search_places(payload: SearchRequest) -> SearchResponse:
    places, storage_source = load_places()
    intent, parser_source = parse_query_intent_with_source(payload.query)
    if storage_source == "json":
        try:
            live_places, live_source = search_live_places(
                query=payload.query,
                area=intent.area,
                profile=intent.profile,
                required_tags=intent.required_tags,
                must_keywords=intent.must_keywords,
            )
        except Exception:
            live_source = "none"
            live_places = []
        if live_places:
            merged: dict[str, Place] = {p.id: p for p in live_places}
            for p in places:
                if p.id not in merged:
                    merged[p.id] = p
            places = list(merged.values())
            storage_source = f"json+live_{live_source}"

    merged_tags = list(payload.user_tags)
    profile_budget = None

    if payload.user_id:
        profile = get_user_profile(payload.user_id)
        if profile is not None:
            profile_tags, profile_budget, _ = profile
            merged_tags = sorted(set(merged_tags + profile_tags))
            if intent.max_price_level is None and profile_budget is not None:
                intent.max_price_level = profile_budget

    scored = score_places(places, intent, merged_tags, payload.exclude_place_ids)
    top_results = scored[: payload.max_results]
    summary_source = add_recommendation_summaries(query=payload.query, intent=intent, results=top_results)
    no_result_reason = _build_no_result_reason(
        places=places,
        intent=intent,
        parser_source=parser_source,
        storage_source=storage_source,
        results=top_results,
    )

    return SearchResponse(
        interpreted_intent=intent,
        results=top_results,
        meta={
            "parser_source": parser_source,
            "intent_profile": intent.profile,
            "storage_source": storage_source,
            "summary_source": summary_source,
            "total_candidates": len(places),
            "effective_user_tags": merged_tags,
            "profile_budget": profile_budget,
            "no_result_reason": no_result_reason,
        },
    )


@app.post("/feedback")
def feedback(payload: FeedbackRequest) -> dict[str, str]:
    ok = apply_feedback(payload.place_id, payload.helpful, payload.signal_tags, payload.user_id)
    if ok:
        return {"status": "ok"}
    return {"status": "failed", "reason": "place_not_found_or_no_database"}


@app.put("/users/profile", response_model=UserProfileResponse)
def save_profile(payload: UserProfileRequest) -> UserProfileResponse:
    ok = upsert_user_profile(payload.user_id, payload.tags, payload.budget_level, payload.home_area)
    if not ok:
        raise HTTPException(status_code=400, detail="database_not_configured")
    return UserProfileResponse(
        user_id=payload.user_id,
        tags=payload.tags,
        budget_level=payload.budget_level,
        home_area=payload.home_area,
    )


@app.get("/users/profile/{user_id}", response_model=UserProfileResponse)
def read_profile(user_id: str) -> UserProfileResponse:
    profile = get_user_profile(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="profile_not_found")
    tags, budget_level, home_area = profile
    return UserProfileResponse(user_id=user_id, tags=tags, budget_level=budget_level, home_area=home_area)


def _build_no_result_reason(
    places: list[Place],
    intent: QueryIntent,
    parser_source: str,
    storage_source: str,
    results: list[ScoredPlace],
) -> str | None:
    if results:
        return None
    if not places:
        return "Veri kaynağında mekan yok. Önce seed/ingest yapılmalı."
    if intent.location_hint and not intent.area:
        return f"{intent.location_hint} için henüz veri yok. Bu şehir/semt desteklenmiyor olabilir."
    if intent.area:
        in_area = sum(1 for p in places if p.area == intent.area)
        if in_area == 0:
            return f"{intent.area} için veri yok. Bölge ingest listesine ekleyip tekrar deneyin."
    if intent.required_tags:
        need = ",".join(intent.required_tags)
        return f"Filtreler çok dar kaldı (gerekli etiketler: {need}). Alanı genişletin veya sorguyu sadeleştirin."
    if intent.must_keywords:
        return "Anahtar kelime eşleşmesi bulunamadı. Daha genel terimlerle tekrar deneyin."
    if parser_source == "rules":
        return "Sorgu kural tabanlı yorumlandı. OpenAI parser etkinse daha iyi intent ayrıştırma olabilir."
    if storage_source == "json" or storage_source.startswith("json+live_"):
        return "Canlı kaynaktan uygun sonuç bulunamadı. Farklı kelime veya yakın semt deneyin."
    return "Uygun sonuç bulunamadı."
