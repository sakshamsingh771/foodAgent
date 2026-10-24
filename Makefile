.PHONY: up down build seed demo test lint format migrate logs
up:        ## start everything
	docker compose up -d --build
down:
	docker compose down
build:
	docker compose build
migrate:   ## apply Alembic migrations
	docker compose exec api alembic upgrade head
seed:      ## load demo data (idempotent)
	docker compose exec api python -m app.seed
demo:      ## fresh demo: start stack, migrate, rebuild demo data
	docker compose up -d --build
	docker compose exec api alembic upgrade head
	docker compose exec api python -m app.seed --reset
	@echo "foodAgent demo: http://localhost:3000  (password FoodAgent#2026demo, see DEMO.md)"
test:
	cd backend && python -m pytest app/tests -q
	cd frontend && npm run typecheck
lint:
	cd backend && ruff check app || true
	cd frontend && npm run lint
format:
	cd backend && ruff format app
logs:
	docker compose logs -f --tail=100
