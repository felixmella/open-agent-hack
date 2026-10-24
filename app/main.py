"""FactSync Chile HTTP API.

    POST /run                    run FactSync on a scope; the body is a run input, as in input_examples/. Answers with
                                 the result once the run ends; with ?wait=false, answers 202 at once and runs it in the
                                 background (poll GET /runs/{run_id}).
    GET  /runs                   recent runs, newest first
    GET  /runs/{run_id}          a run's result, or {"status": "running"} while it runs
    GET  /runs/{run_id}/report   its review queue (HTML)
    GET  /runs/{run_id}/trace    its trace so far (JSON lines)
    GET  /health                 mode, and whether Zetaris and Nightshift answer (no model call is made)

One run at a time: a POST while a run is going answers 409, since runs share the World Model store and Nightshift's
rate limits. Errors are JSON: {"run_id", "status": "error", "error": {code, message, stage, recoverable}}.

Start:  .venv\\Scripts\\uvicorn app.main:app --host 0.0.0.0 --port 8000      (or: python -m app.main)
"""
import json
import logging
import os
import re
import threading
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from app.adapters.meterless import NightshiftClient
from app.adapters.sample_data import SampleData
from app.adapters.zetaris import ZetarisClient, ZetarisError
from app.config import load_settings
from app.errors import RunError, error_body
from app.orchestration.loop import mode_of, new_run_id, run
from app.report.html import render_report
from app.schemas import RUN_ID, RunInput
from app.tracing import utc_now

log = logging.getLogger("factsync")
VERSION = "0.4.0"


def not_found(run_id):
    return RunError("not_found", f"no run {run_id!r}", stage="api", recoverable=False, status=404)


def create_app(settings=None, runner=None):
    """The API. `runner(run_input)` runs FactSync (tests pass one with a fake model and data)."""
    settings = settings or load_settings()
    runner = runner or (lambda run_input: run(run_input, settings))
    app = FastAPI(title="FactSync Chile", version=VERSION,
                  description="Checks the population figures of Chilean comunas in Spanish and English Wikipedia and "
                              "in Wikidata against INE's official figures, explains why they differ, and drafts sourced "
                              "corrections for a human to review. Drafts only: it never edits Wikipedia or Wikidata.")
    gate = threading.Lock()
    running = {}  # run_id -> when it started

    def links(run_id):
        return {"result": f"/runs/{run_id}", "report": f"/runs/{run_id}/report", "trace": f"/runs/{run_id}/trace"}

    def result_path(run_id):
        if not re.fullmatch(RUN_ID, run_id):
            raise not_found(run_id)
        return settings.output_dir / run_id / "result.json"

    @app.exception_handler(RunError)
    async def run_error(request: Request, error: RunError):
        return JSONResponse(error_body(error, (error.result or {}).get("run_id")), status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'] if p != 'body') or 'body'}: {e['msg']}"
                             for e in error.errors())
        return JSONResponse(error_body(RunError("invalid_input", problems, stage="input", recoverable=False)),
                            status_code=422)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception):
        log.exception("unexpected error on %s", request.url.path)
        return JSONResponse(error_body(RunError("internal_error", f"{type(error).__name__}: {error}", stage="api",
                                                recoverable=False)), status_code=500)

    @app.get("/", include_in_schema=False)
    def home():
        return RedirectResponse("/docs")

    @app.post("/run")
    def post_run(run_input: RunInput, wait: bool = True):
        """Run FactSync on a scope (comuna codes, a region, or comuna names)."""
        run_id = run_input.run_id or new_run_id()
        run_input = run_input.model_copy(update={"run_id": run_id})
        if not gate.acquire(blocking=False):
            busy = ", ".join(running) or "another run"
            raise RunError("busy", f"{busy} is in progress; one run at a time, try again when it ends", stage="api",
                           recoverable=True, status=409)
        running[run_id] = utc_now()

        def work():
            try:
                return runner(run_input)
            finally:
                running.pop(run_id, None)
                gate.release()

        if wait:
            return work()

        def background():
            try:
                work()
            except RunError:
                pass  # the run wrote its error result, which GET /runs/{run_id} returns
            except Exception:
                log.exception("run %s failed", run_id)
        threading.Thread(target=background, name=f"run-{run_id}", daemon=True).start()
        return JSONResponse({"run_id": run_id, "status": "running", "links": links(run_id)}, status_code=202)

    @app.get("/runs")
    def list_runs(limit: int = 50):
        """Recent runs, newest first."""
        paths = sorted(settings.output_dir.glob("*/result.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        runs = [{"run_id": run_id, "status": "running", "started_at": started, "links": links(run_id)}
                for run_id, started in running.items()]
        for path in paths[:max(0, limit)]:
            try:
                result = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            summary = result.get("summary") or {}
            runs.append({"run_id": result.get("run_id"), "status": result.get("status"), "mode": result.get("mode"),
                         "comunas": summary.get("comunas"), "findings": summary.get("findings"),
                         "drafts": summary.get("drafts"), "escalations": summary.get("escalations"),
                         "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime)),
                         "links": links(result.get("run_id"))})
        return {"runs": runs}

    @app.get("/runs/{run_id}")
    def get_run(run_id: str):
        """A run's result (as in output/<run_id>/result.json), or its status while it runs."""
        path = result_path(run_id)
        if run_id in running:
            return {"run_id": run_id, "status": "running", "started_at": running[run_id], "links": links(run_id)}
        if not path.exists():
            raise not_found(run_id)
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))

    @app.get("/runs/{run_id}/report", response_class=HTMLResponse)
    def get_report(run_id: str):
        """The run's review queue."""
        path = result_path(run_id)
        if run_id in running:
            return HTMLResponse(f"<!doctype html><meta charset=utf-8><meta http-equiv=refresh content=10>"
                                f"<title>FactSync Chile · {run_id}</title><p style='font-family:system-ui'>Run "
                                f"<code>{run_id}</code> is still running; this page reloads every 10 seconds.</p>")
        if not path.exists():
            raise not_found(run_id)
        return HTMLResponse(render_report(json.loads(path.read_text(encoding="utf-8"))))

    @app.get("/runs/{run_id}/trace", response_class=PlainTextResponse)
    def get_trace(run_id: str):
        """The run's trace: one JSON object per agent action, as written so far."""
        result_path(run_id)
        path = settings.logs_dir / f"trace-{run_id}.jsonl"
        if not path.exists():
            raise not_found(run_id)
        return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="application/x-ndjson")

    @app.get("/health")
    def health():
        """Whether the service can run: in sample mode, the sample data; otherwise Zetaris (SELECT 1) and Nightshift
        (the model list). No model call is made."""
        checks = {}
        if settings.sample_mode:
            try:
                sample = SampleData(settings.sample_dir)
                checks["sample_data"] = {"ok": True, "recorded_at": sample.recorded_at, "comunas": len(sample.comunas)}
            except ZetarisError as exc:
                checks["sample_data"] = {"ok": False, "error": str(exc)}
        else:
            started = time.monotonic()
            try:
                ZetarisClient(settings.zetaris_rest_url, settings.zetaris_org_id, settings.zetaris_api_key,
                              timeout=10.0, retries=0).query("SELECT 1 AS one", limit=1)
                checks["zetaris"] = {"ok": True, "ms": int((time.monotonic() - started) * 1000)}
            except ZetarisError as exc:
                checks["zetaris"] = {"ok": False, "error": exc.code, "detail": str(exc)[:200]}
            try:
                models = NightshiftClient(settings.meterless_base_url, settings.meterless_runtime_token,
                                          settings.meterless_model, timeout=10.0).models()
                listed = settings.meterless_model in models
                checks["nightshift"] = {"ok": listed, "model": settings.meterless_model,
                                        **({} if listed else {"error": "the model is not among those Nightshift lists"})}
            except Exception as exc:  # any failure to reach or authenticate with Nightshift
                checks["nightshift"] = {"ok": False, "error": type(exc).__name__, "detail": str(exc)[:200]}
        status = "ok" if all(c["ok"] for c in checks.values()) else "degraded"
        return {"status": status, "mode": mode_of(settings), "version": VERSION, "running": list(running),
                "checks": checks}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
