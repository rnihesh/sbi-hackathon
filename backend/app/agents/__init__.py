"""Sarathi agent mesh — LangGraph supervisor + specialists, guardrails, memory.

Public entry points live in :mod:`app.agents.entrypoints`:
- ``run_chat_turn`` — streaming chat turn (SSE-friendly async iterator).
- ``run_event_trigger`` — event-driven agent run for the Redis consumer.
- ``execute_proposal`` — human-in-the-loop proposal executor.

Submodules are imported directly (e.g. ``from app.agents import entrypoints``) to
avoid eager import cycles at package load.
"""

from __future__ import annotations
