# Project rules

- Full hackathon context is in HACKATHON_CONTEXT.md (private, gitignored). Read only the sections a task needs.
- Before writing Lightning SQL, read C:\dev\getting-started\AGENTS.md and follow it. Ignore its references to scripts/ and .env.local; settings are in .env.
- Zetaris REST: POST {ZETARIS_REST_URL}/sql-editor/sqls/run with Bearer ZETARIS_API_KEY, X-Org-ID and a fresh UUID X-Request-ID; body {queryId, sql, source: "SqlEditor", limit}; rows are in `data`. One SQL statement per request. Timeouts on every call. The app uses a read-only (General role) user's key; source registration runs as admin in setup scripts.
- LLM provider: Meterless Nightshift (OpenAI-compatible) at METERLESS_BASE_URL with METERLESS_RUNTIME_TOKEN. Every request sends headers `meterless-app: open-agent-hack` and `meterless-scope: user`. Nightshift model ids are routing modes (`meterless/<class>.<disposition>`), not models; concrete `nvidia/...` ids are treated as `meterless/auto`, and model selection is still being worked out (HACKATHON_CONTEXT.md §6). Never infer which model answered from the request: log the receipt's `requested_model` and `routed_model` plus `response.model` on every call. On a provider error, retry once and log which model answered.
- Never print, log, echo or read out values from .env. Never create or fetch API keys.
- No hardcoded outputs; output_examples/ is never read at runtime. Traces must reflect real execution.
- Python 3.13 locally (keep code 3.11-compatible), venv in .venv: run things with `.venv\Scripts\python`. Code runs on the Windows side; Zetaris and Nightshift are on localhost.
- Zetaris setup scripts live in `zetaris/` and run with `.venv\Scripts\python scripts\zetaris_sql.py <file> [--dry-run] [--skip-exists]` (admin key). Dry-run first and get the user's go-ahead before running anything that creates, drops, grants or writes. Verify new objects by comparing row counts with a direct call to the source.
- Smoke test: `.venv\Scripts\python scripts\smoke_test.py` (needs Docker Desktop with Zetaris, and Nightshift, running).
