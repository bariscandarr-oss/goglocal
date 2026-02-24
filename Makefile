.PHONY: up down init-db seed-google seed-json ingest-google-api run

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
