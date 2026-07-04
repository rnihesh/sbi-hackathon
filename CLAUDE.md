# Sarathi — agent instructions

Read `docs/architecture.md` before writing code — it is the authoritative blueprint. `docs/waves.md` has the build plan.

Hard rules:
- Identity: niheshr03@gmail.com everywhere. NEVER kdsintelligence@gmail.com.
- Do not commit or push — the advisor session handles all git operations.
- `docs/` is untracked internal material; keep it out of git.
- Production quality: typed (mypy strict / TS strict), tested, no stubs on demo paths.
- UI: Aperture theme (stone neutrals, clay-orange #D97757 accent only, Geist fonts), minimal, micro-interactions, fully responsive (mobile-first for customer app).
- Backend: Python 3.12, uv, FastAPI, LangGraph, SQLAlchemy 2.0 async, Alembic, Postgres+pgvector, Redis Streams.
- Frontend: Next.js 15 App Router, TypeScript, Tailwind, shadcn/ui, framer-motion, pnpm.
- LLM calls only via `app/llm/router.py` policy tiers (`fast`/`smart`) — never instantiate provider SDKs elsewhere.
