.PHONY: dev backend frontend sim check check-backend check-frontend migrate seed

dev:
	$(MAKE) -j2 backend frontend

backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && pnpm dev

sim:
	cd backend && uv run python -m app.sim.runner

migrate:
	cd backend && uv run alembic upgrade head

seed:
	cd backend && uv run python -m app.sim.seed

check: check-backend check-frontend

check-backend:
	cd backend && uv run ruff check . && uv run mypy app && uv run pytest -q

check-frontend:
	cd frontend && pnpm typecheck && pnpm lint
