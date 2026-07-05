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
  chat, and act before the customer asks. A third trigger, a proactive scheduler, reviews
  dormant accounts on a cadence so engagement does not depend on the customer chatting or a
  transaction streaming in at all.
- **Tools, not text** - agents open accounts, activate products, draft offers, and send
  email via typed tools against banking services.
- **Human-in-the-loop** - impactful actions (offers, outreach) become **Proposals** that
  queue for staff approval. The bank stays in command. Nothing impactful auto-fires.
- **Glass box** - every run is traced: nodes, tool calls, tokens, cost, latency. Auditable
  to the rupee in a built-in trace explorer and cost dashboard.
- **Guardrails by design** - PII redaction before every LLM call (PAN/Aadhaar/phone),
  a compliance rule engine (mandated disclosures, no unapproved product claims), and an
  immutable, hash-chained audit log of every agent action.
- **Vernacular chat + voice** - customers pick a chat language (Hindi, Hinglish, Telugu,
  Tamil, Kannada, Bengali, Marathi, or auto-detect) and every agent replies in it, with
  mandated disclosures always staying in English; voice input is available on the app.
- **Self-service depth** - a products surface where a customer can apply for a product
  (which routes into the same HITL approval queue), in-app notifications, guided
  walkthroughs, and a customer-facing memory-transparency page showing what the system
  remembers about them.
- **Measured, not claimed** - a detection scorecard scores life-event detection against the
  simulation's ground truth (precision / recall), with detection trends and proposal-outcome
  analytics in the console.
- **Retention tools** - a churn cockpit (risk-ranked roster, one-click re-engagement) and a
  customer 360 view (contacts, accounts, holdings, staff notes, a unified activity timeline)
  give staff the full picture on one customer.
- **Money habits** - savings goals tracked against real balance growth, spending insights
  (category breakdowns, movers, recurring merchants) computed from real transaction rows, and
  standing instructions: recurring auto-transfers the scheduler executes against the ledger
  (no-overdraw guarded, progress-neutral goal accounting, set up conversationally through HITL).
- **Memory you control** - durable facts dedup on write (exact match plus embedding
  similarity), episodic memories decay on a schedule, and a memory page lets a customer forget
  any single memory or everything at once.
- **Account control** - a human handoff queue for when a customer asks for a person, revocable
  active sessions, an account-activity feed, and staff-gated CSV exports (leads, detection).
- **Budget-governed autonomy** - a daily LLM spend ceiling pauses the event pipeline at the
  cap (user-facing chat is never blocked), alongside request rate limits and a console
  budget-guard view.
- **Operated from the console** - staff toggle the scheduler and standing instructions, adjust
  the daily budget, and switch model tiers live (no restart) from a console settings page, with
  every change audit-logged; a guarded demo-reset reseeds the synthetic cohort in one click.
- **Provider-agnostic** - a thin multi-provider LLM router (OpenAI / Gemini / Anthropic)
  with policy tiers (cheap model for classification, strong for dialogue), automatic
  fallback, and a per-request cost ledger. Self-hosted models are pluggable for data
  residency.
- **Privacy-safe demo** - a synthetic-India simulation engine (personas + transaction
  streams) is the only data source. Zero real customer data anywhere. All logic, agents,
  APIs, auth, and emails are real.

---

## Architecture

```mermaid
flowchart TB
  subgraph FE["Frontend - Next.js 15, PWA, responsive"]
    CA["Customer app<br/>chat, home, goals, insights, products"]
    BC["Bank console<br/>feed, approvals, analytics, traces, settings"]
  end
  API["FastAPI - REST + Server-Sent Events"]
  subgraph MESH["LangGraph agent mesh - Sarathi Core supervisor"]
    AQ["Acquisition<br/>onboarding, KYC"]
    AD["Adoption<br/>dormancy, nudges"]
    EN["Engagement<br/>life events, churn"]
    GR["Guardrails<br/>PII redaction, policy, hash-chained audit"]
    MEM["Memory<br/>pgvector: facts, dedup, decay"]
  end
  LLM["Multi-provider LLM router<br/>fast + smart tiers, fallback, cost ledger, daily budget guard"]
  OA(["OpenAI"])
  GE(["Gemini"])
  AN(["Anthropic"])
  WK["Workers<br/>event_consumer + scheduler"]
  PG[("Postgres 16 + pgvector")]
  RD[("Redis 7 Streams")]
  SIM["Synthetic-India simulation<br/>(or real core-banking feed)"]

  FE -->|REST + SSE| API
  API -->|1 chat| MESH
  MESH --> LLM
  LLM --> OA & GE & AN
  SIM --> RD
  RD -->|2 event| WK
  WK -->|3 scheduled sweep| MESH
  MESH -. proposals .-> BC
  MESH --- MEM
  MEM --- PG
  API --- PG
  WK --- RD
```

<details>
<summary>Same topology as plain-text ASCII</summary>

```
+--------------------------- frontend (Next.js 15, App Router) ---------------------------+
|   / (landing + auth)     /app (customer: chat, home, nudges)     /console (bank staff)  |
+---------------------------------------+-------------------------------------------------+
                                        | REST + SSE (chat streaming, live console feed)
+---------------------------------------v----------------- backend (FastAPI, Python 3.12) +
|  api/v1: auth, chat, customers (me), console, events, traces, costs                     |
|  +----------------- agents (LangGraph) ------------------+   +-- services -----------+  |
|  | Sarathi Core supervisor  (intent -> route -> merge)   |   | email (SES ap-south-1)|  |
|  | +- Acquisition Agent  (onboarding, KYC, matching)     |   | kyc   (mock verifiers)|  |
|  | +- Adoption Agent     (dormancy, nudges, walkthrough) |   | ledger(mock CBS)      |  |
|  | +- Engagement Agent   (life events, NBA, churn)       |   | products (catalog)    |  |
|  | shared: memory (pgvector), tools, guardrails, tracing |   +-----------------------+  |
|  +-------------------------------------------------------+                              |
|  llm/: router (policy + fallback + cost ledger) -> openai | gemini | anthropic          |
|  workers/: event_consumer (Streams: prefilter -> agent -> proposal); scheduler (sweep:  |
|            dormant-account review, goals, memory pruning)                               |
|  sim/: persona factory + transaction generator + life-event scripts                     |
+--------------+--------------------------------------------------+------------------------+
               |                                                  |
       Postgres 16 + pgvector                              Redis 7 (streams:
    (relational + episodic vectors,                         txn.events, agent.actions;
     LangGraph checkpoints, cost ledger)                    cooldowns, rate limits)
```

</details>

**Event path:** `sim/runner` (or console inject) -> `txn.events` stream -> `event_consumer`
-> deterministic prefilter (cheap, rule-based) -> matched rule fires an agent run
(LangGraph) -> outputs are **Proposals**, never direct impactful actions -> HITL approval
queue -> approval executes the tool (nudge / email) + writes an audit row.

**Three ways an agent run starts:** a chat message (supervisor routes it live), a transaction
event (the path above), or the **scheduler** waking on its own cadence with no trigger from
the customer at all - it reviews dormant accounts, evaluates savings goals, and prunes stale
memory as DB-only side jobs on every tick.

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
follow `docs/demo-script.md`, or use the built-in **Demo tour** (the presentation icon in the
console top bar): an 8-step checklist with a narration line and a deep link per step.

To verify a deployment without spending anything on LLMs, run the curl-based smoke checks
(healthz, landing, manifest, docs, staff auth-gate, chat session create, and more):

```bash
bash scripts/prod-smoke.sh     # defaults to production; override with SARATHI_FE_URL / SARATHI_API_URL
```

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
| `LLM_DAILY_BUDGET_USD` | `0.25` | Daily spend ceiling (UTC day); event-driven agent runs pause above it, chat is never blocked |
| `SCHEDULER_ENABLED` | `true` | Master switch for the proactive scheduler's sweep loop |
| `SWEEP_INTERVAL_SECONDS` | `3600` | Base cadence of the sweep loop (jittered +-10% per tick) |
| `SWEEP_CUSTOMER_COOLDOWN_DAYS` | `7` | A customer is sweep-eligible only after this many days with no agent run |
| `SWEEP_BATCH_SIZE` | `3` | Max customers swept per tick |
| `SWEEP_DAILY_CAP` | `10` | Hard ceiling on sweeps per UTC day |

Model ids (e.g. `OPENAI_MODEL_SMART`), purpose-based provider routing
(`LLM_PURPOSE_ROUTING`), LLM timeouts, request hardening (`MAX_REQUEST_BYTES`), JWT/OTP TTLs,
and standing-instruction execution limits are also configurable; see
`backend/app/core/config.py` for the full typed list, and `infra/DEPLOY.md` for the
dev-vs-prod env-var deltas.

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
  tests/               # 603 tests (agents, api, auth, sim, workers, scheduler, console, llm)
frontend/
  app/                 # (landing)/, app/ (customer), console/ (staff)
  components/          # shadcn/ui ported to the Aperture theme
  lib/                 # typed API client, SSE hooks, auth context
infra/                 # production Dockerfiles, docker-compose.prod.yml, DEPLOY.md
docker-compose.yml     # dev infra: Postgres (pgvector) + Redis
```

---

## Quality bar

- Backend: `ruff` clean, `mypy --strict` clean, `pytest` (603 tests) green.
- Frontend: `tsc --noEmit`, `eslint`, and `next build` clean, responsive at 360 / 768 / 1280.
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
