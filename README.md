# Sarathi

**A banker in every Indian's pocket.**

YONO gave every Indian a bank in their pocket. Sarathi gives every Indian a *banker*:
a persistent, proactive, auditable agentic relationship manager for every customer
and prospect. Built for the SBI Hackathon 2026 (GFF), theme: Agentic AI and Emerging Tech.

Human relationship managers exist only for the top few percent of customers. Sarathi
gives the other 95% an always-on agent mesh that acquires, activates, and engages them
autonomously, under full bank supervision, on a glass-box, human-in-the-loop platform.

---

## The three pillars

Sarathi maps directly to the hackathon's three pillars, one specialist agent each,
supervised by a routing core:

| Pillar | Agent | What it does autonomously |
|---|---|---|
| **Customer Acquisition** | Acquisition Agent | Qualifies leads, scores intent, runs conversational onboarding: KYC by dialogue (not forms), PAN validation, product matching, and account opening. The open-account KYC gate is enforced in code, not just the prompt. |
| **Digital Adoption** | Adoption Agent | Detects product dormancy from usage telemetry (UPI never activated, idle balance, no insurance), sends contextual nudges and guided walkthroughs, and measures nudge to activation conversion. |
| **Digital Engagement** | Engagement Agent | Reads live transaction streams, detects life events (job change via salary pattern, new child via merchant categories, home intent, bonus windfall), and proposes next-best-action outreach. Scores churn risk. |

**Sarathi Core** (supervisor) classifies intent, routes to the right specialist, owns
per-customer memory (episodic vector + structured profile facts), and enforces guardrails.

---

## Why this is agentic, not a chatbot

- **Event-driven autonomy** - agents wake on Redis-stream transaction events, not just
  chat. They act before the customer asks.
- **Tools, not text** - agents open accounts, activate products, draft offers, and send
  email via typed tools against banking services.
- **Human-in-the-loop** - impactful actions (offers, outreach) become **Proposals** that
  queue for staff approval. The bank stays in command. Nothing impactful auto-fires.
- **Glass box** - every run is traced: nodes, tool calls, tokens, cost, latency. Auditable
  to the rupee in a built-in trace explorer and cost dashboard.
- **Guardrails by design** - PII redaction before every LLM call (PAN/Aadhaar/phone),
  a compliance rule engine (mandated disclosures, no unapproved product claims), and an
  immutable, hash-chained audit log of every agent action.
- **Provider-agnostic** - a thin multi-provider LLM router (OpenAI / Gemini / Anthropic)
  with policy tiers (cheap model for classification, strong for dialogue), automatic
  fallback, and a per-request cost ledger. Self-hosted models are pluggable for data
  residency.
- **Privacy-safe demo** - a synthetic-India simulation engine (personas + transaction
  streams) is the only data source. Zero real customer data anywhere. All logic, agents,
  APIs, auth, and emails are real.

---

## Architecture

```
+--------------------------- frontend (Next.js 15, App Router) ---------------------------+
|   / (landing + auth)     /app (customer: chat, home, nudges)     /console (bank staff)  |
+---------------------------------------+-------------------------------------------------+
                                        | REST + SSE (chat streaming, live console feed)
+---------------------------------------v----------------- backend (FastAPI, Python 3.12) +
|  api/v1: auth, chat, customers (me), console, events, traces, costs                      |
|  +----------------- agents (LangGraph) ------------------+   +-- services -----------+  |
|  | Sarathi Core supervisor  (intent -> route -> merge)   |   | email (SES ap-south-1)|  |
|  | +- Acquisition Agent  (onboarding, KYC, matching)     |   | kyc   (mock verifiers)|  |
|  | +- Adoption Agent     (dormancy, nudges, walkthrough) |   | ledger(mock CBS)      |  |
|  | +- Engagement Agent   (life events, NBA, churn)       |   | products (catalog)    |  |
|  | shared: memory (pgvector), tools, guardrails, tracing |   +-----------------------+  |
|  +-------------------------------------------------------+                              |
|  llm/: router (policy + fallback + cost ledger) -> openai | gemini | anthropic          |
|  workers/: event_consumer (Redis Streams consumer group, prefilter -> agent -> proposal)|
|  sim/: persona factory + transaction generator + life-event scripts                     |
+--------------+--------------------------------------------------+------------------------+
               |                                                  |
       Postgres 16 + pgvector                              Redis 7 (streams:
    (relational + episodic vectors,                         txn.events, agent.actions;
     LangGraph checkpoints, cost ledger)                    cooldowns, rate limits)
```

**Event path:** `sim/runner` (or console inject) -> `txn.events` stream -> `event_consumer`
-> deterministic prefilter (cheap, rule-based) -> matched rule fires an agent run
(LangGraph) -> outputs are **Proposals**, never direct impactful actions -> HITL approval
queue -> approval executes the tool (nudge / email) + writes an audit row.

---

## Quickstart

Prerequisites: Python 3.12, [uv](https://docs.astral.sh/uv/), Node 20+ and
[pnpm](https://pnpm.io/), and either Docker (for Postgres + Redis) or native Postgres 16
(with the `pgvector` extension) and Redis 7.

```bash
cp .env.example .env          # fill in at least one LLM key (OpenAI or Gemini)
```

### Path A - Docker for infra, native app (recommended for dev)

```bash
docker compose up -d          # Postgres (pgvector) + Redis with healthchecks
cd backend && uv sync && uv run alembic upgrade head && cd ..
make seed                     # 20 synthetic-India customers, 6 months of history
make dev                      # backend :8000  +  frontend :3000
make worker                   # (separate shell) event consumer
```

### Path B - fully native

```bash
# Start your own Postgres 16 + pgvector and Redis 7, matching DATABASE_URL / REDIS_URL.
createdb sarathi && psql sarathi -c 'CREATE EXTENSION IF NOT EXISTS vector;'
cd backend && uv sync && uv run alembic upgrade head && cd ..
make seed && make dev
make worker                   # separate shell
```

### Path C - full stack in containers (production shape)

```bash
# Builds backend + frontend + worker + Postgres + Redis, runs migrations, seeds.
docker compose -f infra/docker-compose.prod.yml up -d --build
```

Then open the customer app at `http://localhost:3000` and the staff console at
`http://localhost:3000/console`. See `infra/DEPLOY.md` for the real deployment runbook.

To drive a live demo end to end (onboarding -> life-event injection -> approval -> trace),
follow `docs/demo-script.md`.

---

## Make targets

| Target | What it does |
|---|---|
| `make dev` | Run backend (`:8000`) and frontend (`:3000`) together |
| `make backend` | Run the FastAPI backend with reload |
| `make frontend` | Run the Next.js dev server |
| `make worker` | Run the Redis Streams event consumer |
| `make sim` | Run the synthetic-India simulation (streams live transactions) |
| `make seed` | Seed a deterministic 20-customer cohort with 6 months of history |
| `make migrate` | Apply Alembic migrations (`alembic upgrade head`) |
| `make check` | Full gate: em-dash check + backend (ruff, mypy, pytest) + frontend (tsc, eslint) |

Reset the demo cohort to a clean slate (also clears traces, proposals, and the cost
ledger): `cd backend && uv run python -m app.seed --reset`.

---

## Configuration

Settings load from the repo-root `.env` (see `.env.example`). At least one LLM key is
required for live agent calls.

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `dev` | `dev` relaxes the staff gate and cookie `Secure`; set `prod` in production |
| `OPENAI_API_KEY` / `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` | empty | At least one required; router falls back across whatever is present |
| `DATABASE_URL` | `postgresql+asyncpg://sarathi:sarathi@localhost:5432/sarathi` | Async SQLAlchemy DSN |
| `REDIS_URL` | `redis://localhost:6379/0` | Streams, cooldowns, session/OTP tracking |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | empty | Google OAuth sign-in |
| `JWT_SECRET` | `change-me` | Must be a real secret when `APP_ENV != dev` (boot refuses otherwise) |
| `COOKIE_DOMAIN` | none | Set to `.yourdomain.com` when frontend and API share a parent domain |
| `WEBAUTHN_RP_ID` / `WEBAUTHN_ORIGIN` | `localhost` / `http://localhost:3000` | Passkey relying-party id and origin |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | Credentialed origins allowed to call the API |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_REGION` | empty / `ap-south-1` | SES credentials; absent = email skipped gracefully |
| `SES_FROM_ADDRESS` | `no-reply@niheshr.com` | Verified SES sender |
| `STAFF_EMAILS` | empty | Console allowlist (comma-separated or JSON array); empty + `dev` = any authed user is staff |
| `EVENT_COOLDOWN_SECONDS` | `300` | Min gap between agent runs per (customer, rule) |

Model ids, LLM timeouts, and JWT/OTP TTLs are also configurable; see
`backend/app/core/config.py` for the full typed list.

---

## Project structure

```
backend/
  app/
    main.py            # FastAPI factory, lifespan, health, middleware
    core/              # config, async db, redis, security (JWT sessions), logging
    llm/               # router (policy + fallback + cost), providers/, embeddings
    agents/            # graph, supervisor, acquisition/adoption/engagement,
                       #   memory (pgvector), guardrails, tracing, toolkit
    api/v1/            # auth, chat (SSE), customers, console, nudges
    models/            # SQLAlchemy models  |  schemas/  # pydantic mirrors
    services/          # email (SES), kyc, ledger, products
    sim/               # personas, generator, life-event scripts, runner
    workers/           # event_consumer, prefilter, activity
    seed.py            # full-stack DB seeder
  alembic/             # migrations
  tests/               # 219 tests (agents, api, auth, sim, workers, llm)
frontend/
  app/                 # (landing)/, app/ (customer), console/ (staff)
  components/          # shadcn/ui ported to the Aperture theme
  lib/                 # typed API client, SSE hooks, auth context
infra/                 # production Dockerfiles, docker-compose.prod.yml, DEPLOY.md
docker-compose.yml     # dev infra: Postgres (pgvector) + Redis
```

---

## Quality bar

- Backend: `ruff` clean, `mypy --strict` clean, `pytest` (219 tests) green.
- Frontend: `tsc --noEmit` and `eslint` clean, responsive at 360 / 768 / 1280.
- No em dashes anywhere (enforced by `make check`).
- No demo shortcuts: every feature works end to end. Synthetic data is the only data
  source; all logic, agents, APIs, auth, and emails are real.

Run the whole gate with `make check`.

---

## Screenshots

UI captures live under `docs/screenshots/` (untracked internal material). The customer app
uses the Aperture theme: stone neutrals, a single clay-orange accent (`#D97757`), Geist
type, minimal, with micro-interactions and mobile-first responsiveness.

---

## License

Proprietary. Prepared for the SBI Hackathon 2026 (GFF). Not licensed for redistribution.
