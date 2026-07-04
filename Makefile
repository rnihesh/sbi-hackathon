.PHONY: dev backend frontend worker sim check check-backend check-frontend migrate seed

dev:
	$(MAKE) -j2 backend frontend

backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && pnpm dev

worker:
	cd backend && uv run python -m app.workers.event_consumer

sim:
	cd backend && uv run python -m app.sim.runner

migrate:
	cd backend && uv run alembic upgrade head

seed:
	cd backend && uv run python -m app.seed --cohort 20 --months 6 --seed 42

check: check-emdash check-backend check-frontend

check-emdash:
	@! grep -r $$'\xe2\x80\x94' --include='*.py' --include='*.ts' --include='*.tsx' --include='*.css' --include='*.html' --include='*.md' --include='*.toml' --include='*.yml' backend/app backend/tests frontend/app frontend/components frontend/lib *.md Makefile 2>/dev/null || (echo "em dashes found (banned)"; exit 1)

check-backend:
	cd backend && uv run ruff check . && uv run mypy app && uv run pytest -q

check-frontend:
	cd frontend && pnpm typecheck && pnpm lint
