.PHONY: up down init-db seed-google seed-json ingest-google-api run quality-prod quality-local quality-gate quality-smoke

up:
	docker compose up -d

down:
	docker compose down

init-db:
	curl -X POST http://127.0.0.1:8080/admin/init-db

seed-json:
	curl -X POST http://127.0.0.1:8080/admin/seed-json

seed-google:
	python -m app.ingest_google

ingest-google-api:
	curl -X POST http://127.0.0.1:8080/admin/ingest-google

run:
	uvicorn app.main:app --reload --port 8080

quality-prod:
	python -m app.eval_quality --base-url https://goglocal.app --dataset data/test_queries.json --min-pass-rate 85

quality-local:
	python -m app.eval_quality --base-url http://127.0.0.1:8080 --dataset data/test_queries.json --min-pass-rate 85

quality-gate: quality-prod

quality-smoke:
	python -m app.eval_quality --base-url https://goglocal.app --dataset data/test_queries_smoke.json --timeout 12 --min-pass-rate 85
