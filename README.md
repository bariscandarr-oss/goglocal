# GoGlocal Backend

Google Maps aramasini sohbet tabanli hale getiren ve `local_score` ile siralama yapan backend.

## Bu surumde gelenler
- Dogal dil sorgu -> intent parser (OpenAI + fallback)
- Skorlama modeli:
  - `relevance_score`
  - `general_score` (rating + review)
  - `local_score` (community + freshness)
  - `personalized_score`
  - `distance_score` (alan merkezine yakinlik)
- `PostgreSQL + PostGIS` entegrasyonu
- Google Places ingest komutu
- JSON fallback (DB yoksa calismaya devam eder)
- Chat + harita web arayuzu (`/app`)
- Kullanici profili endpointleri (`user_id`, tercih etiketleri, butce)

## Dosya yapisi
- API: `/Users/bariscandar/Documents/goglocal/app/main.py`
- Intent parser: `/Users/bariscandar/Documents/goglocal/app/ai_parser.py`
- Scoring: `/Users/bariscandar/Documents/goglocal/app/scoring.py`
- DB model: `/Users/bariscandar/Documents/goglocal/app/orm.py`
- Storage layer: `/Users/bariscandar/Documents/goglocal/app/storage.py`
- JSON seed: `/Users/bariscandar/Documents/goglocal/app/seed.py`
- Google ingest: `/Users/bariscandar/Documents/goglocal/app/ingest_google.py`
- Compose: `/Users/bariscandar/Documents/goglocal/docker-compose.yml`
- Frontend: `/Users/bariscandar/Documents/goglocal/frontend/index.html`

## 1) Kurulum
```bash
cd /Users/bariscandar/Documents/goglocal
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 2) Postgres + PostGIS ayaga kaldir
```bash
make up
```

## 3) API calistir
```bash
make run
```

## 4) DB schema olustur
```bash
make init-db
```

## 5) Ilk veri yukle (JSON'dan)
```bash
make seed-json
```

## 6) Google Places'tan cek (opsiyonel)
`.env` icine `GOOGLE_MAPS_API_KEY` gir:
```bash
make seed-google
```

## API
### Web UI
`http://127.0.0.1:8080/app`

### Saglik
```bash
curl http://127.0.0.1:8080/health
```

### Arama
```bash
curl -X POST http://127.0.0.1:8080/search \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "kadikoy civarinda vegan ve sessiz ders calisabilecegim acik bir yer",
    "user_id": "baris",
    "user_tags": ["wifi", "priz", "sessiz"],
    "max_results": 3
  }'
```

### Admin endpointleri
- `POST /admin/init-db`
- `POST /admin/seed-json`
- `POST /admin/ingest-google`

### Feedback
```bash
curl -X POST http://127.0.0.1:8080/feedback \
  -H 'Content-Type: application/json' \
  -d '{"place_id":"p1","helpful":true}'
```

### Kullanici profili
```bash
curl -X PUT http://127.0.0.1:8080/users/profile \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"baris","tags":["sessiz","wifi","vegan"],"budget_level":2}'
```

```bash
curl http://127.0.0.1:8080/users/profile/baris
```

## Kalite olcumu (test seti)
Test sorgulari:
- `/Users/bariscandar/Documents/goglocal/data/test_queries.json`

Calistir:
```bash
cd /Users/bariscandar/Documents/goglocal
source .venv/bin/activate
python -m app.eval_quality --base-url https://goglocal.app
```

Opsiyonel:
```bash
python -m app.eval_quality --base-url http://127.0.0.1:8080 --dataset data/test_queries.json
```

Quality gate (deploy oncesi):
```bash
make quality-gate
```

Esik degeriyle:
```bash
python -m app.eval_quality --base-url https://goglocal.app --dataset data/test_queries.json --min-pass-rate 85
```

GitHub Actions quality gate:
- Workflow: `/Users/bariscandar/Documents/goglocal/.github/workflows/quality-gate.yml`
- Opsiyonel repo variables:
  - `QUALITY_BASE_URL` (default: `https://goglocal.app`)
  - `QUALITY_MIN_PASS_RATE` (default: `85`)

## Ortam degiskenleri
`.env.example`:
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `DATABASE_URL`
- `AUTO_INIT_DB`
- `AUTO_SEED_JSON`
- `GOOGLE_MAPS_API_KEY`
- `GOOGLE_SEARCH_CENTER`
- `GOOGLE_SEARCH_RADIUS_METERS`
- `GOOGLE_INGEST_AREAS`

## Render deploy (goglocal.app icin)
Bu repoda `/Users/bariscandar/Documents/goglocal/render.yaml` hazir.

1. Kodu GitHub'a push et.
2. Render'da **Blueprint** ile repo'yu sec ve olustur.
3. Web servis env varlarini doldur:
 - `OPENAI_API_KEY`
 - `GOOGLE_MAPS_API_KEY`
4. Deploy bittikten sonra su endpointleri bir kez cagir:
```bash
curl -X POST https://<render-web-url>/admin/init-db
curl -X POST https://<render-web-url>/admin/ingest-google
```
5. Domain bagla:
 - Render Web Service -> `Settings` -> `Custom Domains` -> `goglocal.app` ve `www.goglocal.app` ekle.
 - GoDaddy DNS:
   - `@` kaydini Render'in verdigi hedefe guncelle
   - `www` kaydini Render'in verdigi CNAME hedefine guncelle
 - SSL durumunu Render'da `Active` olana kadar bekle.
