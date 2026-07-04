# Sarathi

**A banker in every Indian's pocket.** Agentic AI relationship manager covering customer acquisition, digital adoption, and digital engagement - built for SBI Hackathon 2026 (GFF).

## What it does

Every customer gets a persistent agent mesh, supervised by the bank:

- **Acquisition Agent** - lead qualification and conversational onboarding: KYC by dialogue, document extraction, product matching, account opening.
- **Adoption Agent** - detects product dormancy from usage telemetry and drives activation with contextual nudges and walkthroughs.
- **Engagement Agent** - reads transaction streams, detects life events (job change, new child, home intent), and proposes next-best-action outreach.
- **Sarathi Core** - supervisor: routing, per-customer memory, guardrails (PII redaction, compliance rules, hash-chained audit log).

Impactful actions become **proposals** requiring staff approval (human-in-the-loop). Every agent run is fully traced - nodes, tools, tokens, cost - in a glass-box trace explorer.

## Stack

FastAPI · LangGraph · multi-provider LLM router (OpenAI / Gemini / Anthropic) · Postgres + pgvector · Redis Streams · Next.js 15 · Tailwind + shadcn · Google OAuth + passkeys · AWS SES.

## Quickstart

```bash
cp .env.example .env   # fill keys
docker compose up -d   # postgres + redis
make dev               # backend :8000, frontend :3000
make sim               # start synthetic-India simulation
```

## Development

```bash
make check             # lint + typecheck + tests, both stacks
```

Structure: `backend/` (FastAPI + agents), `frontend/` (Next.js), `infra/` (compose, deploy).
