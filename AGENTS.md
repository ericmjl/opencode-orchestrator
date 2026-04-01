# AGENTS.md — Project Conventions

## Running Tests

Always use `pixi run python -m pytest` (not `pixi run pytest` — the package isn't on the path for bare pytest).

```bash
pixi run python -m pytest tests/ -v
```

## UI Verification with agent-browser

**Priority: API first, then agent-browser.** For any frontend change, first verify the API works correctly (curl, httpie, or `/docs`). Only use `agent-browser` after confirming the API endpoint behaves as expected.

After making frontend changes, use the `agent-browser` skill to verify behavior:

1. Load the `agent-browser` skill
2. Navigate to the relevant page
3. Take a **snapshot** (accessibility tree, not screenshot) to verify DOM state
4. For immediate changes (e.g. status badge flip, optimistic message), check right away
5. For async changes (e.g. assistant reply appearing), add a short sleep/timeout before checking
6. Verify both the expected content and the absence of regressions

Typical loop: make change → start server → agent-browser navigate → snapshot → assert → fix if needed.

## Linting / Typechecking

```bash
pixi run python -m ruff check opencode_orchestrator/
pixi run python -m mypy opencode_orchestrator/
```

## Tech Stack

- Backend: FastAPI + aiosqlite
- Frontend: HTMX-first server-rendered UI (minimize imperative JS)
- Agent integration: httpx streaming to opencode's HTTP API
- Templates: Jinja2 in `opencode_orchestrator/templates/`

## Key Patterns

- **Default port: 8627** — The orchestrator server runs on port 8627. Never kill this server. Use a different port for testing if needed.
- Server port configurable via `OC_PORT` env var
- Agent ports come from `agent_registry` table (set at registration time)
- Messages use count-based dedup (`knownMessageCount`) not timestamps
- Sessions stay `running` after task completes to preserve context for follow-ups
- Polling (1s interval, 2min timeout) replaces SSE for message fetching
- `datetime.datetime.now(datetime.UTC)` instead of deprecated `utcnow()`
- Always use `pathlib.Path` over `os.path`
- All UI interactions must be mediated through HTMX endpoints and HTML snippets; prefer OOB swaps for cross-region updates (sidebar badges, status chips, counters).

## Arrow of Intent Updates

- If the user says **"update the arrow of intent"**, update this full document chain together:
  1. `docs/high-level-design.md`
  2. The appropriate LLDs under `docs/designs/**/LLD.md` (create new LLDs if needed)
  3. The appropriate EARS files (`docs/designs/ears.md` and domain EARS files under `docs/designs/**`)
- Do not stop at one layer; keep HLD, LLD, and EARS consistent in the same change.
