# Sarathi - agent instructions

Read `docs/architecture.md` before writing code - it is the authoritative blueprint. `docs/waves.md` has the build plan.

Hard rules:
- Identity: niheshr03@gmail.com everywhere. NEVER kdsintelligence@gmail.com.
- Do not commit or push - the advisor session handles all git operations.
- `docs/` is untracked internal material; keep it out of git.
- Production quality: typed (mypy strict / TS strict), tested, no stubs on demo paths.
- NO demo shortcuts: every feature must genuinely work end-to-end. No hardcoded fake responses, no Math.random() dashboard numbers, no if-demo branches. Synthetic data is allowed ONLY as the data source (sim engine, privacy story) - all logic, agents, APIs, emails, auth must be real and correct.
- UI: Aperture theme (stone neutrals, clay-orange #D97757 accent only, Geist fonts), minimal, micro-interactions, fully responsive (mobile-first for customer app).
- Backend: Python 3.12, uv, FastAPI, LangGraph, SQLAlchemy 2.0 async, Alembic, Postgres+pgvector, Redis Streams.
- Frontend: Next.js 15 App Router, TypeScript, Tailwind, shadcn/ui, framer-motion, pnpm.
- LLM calls only via `app/llm/router.py` policy tiers (`fast`/`smart`) - never instantiate provider SDKs elsewhere.
- NO em dashes (U+2014) anywhere: code, comments, UI strings, docs, commit messages. Use hyphens or restructure the sentence. `make check` enforces this.
- HARD BUDGET: the OpenAI org has a tiny spend cap. NEVER make live LLM calls during development or testing - FakeRouter/fakes only, always. Live verification happens once per iteration, run ONLY by the advisor session, minimal and preferring Gemini. If your task seems to need a live call, report that instead of making it.
