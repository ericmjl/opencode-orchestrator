# AGENTS.md — Project Conventions

## Running Tests

Always use `pixi run python -m pytest` (not `pixi run pytest` — the package isn't on the path for bare pytest).

```
pixi run python -m pytest tests/ -v
```

## UI Verification with agent-browser

After making frontend changes, use the `agent-browser` skill to verify behavior:

1. Load the `agent-browser` skill
2. Navigate to the relevant page
3. Take a **snapshot** (accessibility tree, not screenshot) to verify DOM state
4. For immediate changes (e.g. status badge flip, optimistic message), check right away
5. For async changes (e.g. assistant reply appearing), add a short sleep/timeout before checking
6. Verify both the expected content and the absence of regressions

Typical loop: make change → start server → agent-browser navigate → snapshot → assert → fix if needed.

## Linting / Typechecking

```
pixi run python -m ruff check opencode_orchestrator/
pixi run python -m mypy opencode_orchestrator/
```

## Tech Stack

- Backend: FastAPI + aiosqlite
- Frontend: HTMX + plain JS (no Alpine.js, no React)
- Agent integration: httpx streaming to opencode's HTTP API
- Templates: Jinja2 in `opencode_orchestrator/templates/`

## Key Patterns

- Server port configurable via `OC_PORT` env var (default: random 8000-9000)
- Agent ports come from `agent_registry` table (set at registration time)
- Messages use count-based dedup (`knownMessageCount`) not timestamps
- Sessions stay `running` after task completes to preserve context for follow-ups
- Polling (1s interval, 2min timeout) replaces SSE for message fetching
- `datetime.datetime.now(datetime.UTC)` instead of deprecated `utcnow()`
- Always use `pathlib.Path` over `os.path`
