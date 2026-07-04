# sarathi-backend

FastAPI + LangGraph backend for **Sarathi**. See `../docs/architecture.md` for the blueprint.

## Dev

```bash
uv sync                       # install deps into .venv
uv run alembic upgrade head   # apply migrations (needs postgres from ../docker-compose.yml)
uv run uvicorn app.main:app --reload --port 8000
```

## Quality gate

```bash
uv run ruff check .
uv run mypy app
uv run pytest -q
```
