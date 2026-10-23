"""Smoke test for the Data (Zetaris) and Power (Meterless Nightshift) layers.

Run from the project root:  .venv\\Scripts\\python scripts\\smoke_test.py
Needs Zetaris and Nightshift running and .env filled in. Never prints secret values.
"""
import functools
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.meterless import NightshiftClient  # noqa: E402
from app.adapters.zetaris import ZetarisClient  # noqa: E402
from app.config import load_settings  # noqa: E402

RUN_SQL_TOOL = {
    "type": "function",
    "function": {
        "name": "run_sql",
        "description": "Run one SQL statement against Zetaris and return the rows.",
        "parameters": {
            "type": "object",
            "properties": {"sql": {"type": "string", "description": "A single SQL statement."}},
            "required": ["sql"],
        },
    },
}
failures = 0


def check(name, fn):
    global failures
    try:
        detail = fn()
        print(f"PASS {name}" + (f"  ({detail})" if detail else ""))
    except Exception as error:
        failures += 1
        print(f"FAIL {name}  ({type(error).__name__}: {str(error)[:200]})")


@functools.cache
def settings():
    return load_settings()


@functools.cache
def zetaris():
    s = settings()
    return ZetarisClient(s.zetaris_rest_url, s.zetaris_org_id, s.zetaris_api_key, retries=0)


@functools.cache
def llm():
    s = settings()
    return NightshiftClient(s.meterless_base_url, s.meterless_runtime_token, s.meterless_model, retries=0)


def assert_served_by(result):
    # Nightshift silently answers with a lane model when the requested one isn't assigned to a lane.
    served = {result.model_served, result.routed_model} - {None}
    assert served == {result.model_requested}, (
        f"asked for {result.model_requested} but {', '.join(sorted(served))} answered (is it assigned to a Nightshift lane?)"
    )


def zetaris_web():
    url = os.environ.get("ZETARIS_UI_URL", "http://localhost:3000")
    httpx.get(url, timeout=10, follow_redirects=True).raise_for_status()


def zetaris_rest():
    result = zetaris().query("SELECT 1 AS one", limit=1)
    assert result.rows and str(result.rows[0]["one"]) == "1", f"unexpected reply: {result.rows[:1]}"
    return f"columns {result.columns}, {result.elapsed_ms} ms"


def nightshift_models():
    ids = llm().models()
    model = settings().meterless_model
    assert model in ids, f"{model} is not among the {len(ids)} models Nightshift lists"
    return f"{len(ids)} models listed, including {model}"


def nemotron_chat():
    result = llm().chat([{"role": "user", "content": "Reply with the single word: ready"}])
    assert result.text, "empty reply"
    assert_served_by(result)
    return f"model={result.model_served}, routed={result.routed_model}, reply={result.text[:40]!r}"


def nemotron_tool_round_trip():
    messages = [{
        "role": "user",
        "content": "Use the run_sql tool to run SELECT 1 + 1 AS two, then tell me the result.",
    }]
    first = llm().chat(messages, tools=[RUN_SQL_TOOL])
    assert_served_by(first)
    assert first.tool_calls, "the model answered without calling run_sql"
    call = first.tool_calls[0]
    sql = json.loads(call.function.arguments)["sql"]
    rows = zetaris().query(sql, limit=10).rows
    messages += [first.message, {"role": "tool", "tool_call_id": call.id, "content": json.dumps(rows)}]
    final = llm().chat(messages, tools=[RUN_SQL_TOOL])
    assert final.text, "no final answer after the tool result"
    return f"sql={sql!r}, rows={json.dumps(rows)[:40]}, answer={final.text[:60]!r}"


if __name__ == "__main__":
    check("Data: Zetaris web interface", zetaris_web)
    check("Data: Zetaris runs SQL over its REST API", zetaris_rest)
    check("Power: Nightshift lists the pinned model", nightshift_models)
    check("Power: Nemotron replies through Nightshift", nemotron_chat)
    check("Power+Data: Nemotron tool call round trip through Zetaris", nemotron_tool_round_trip)
    sys.exit(1 if failures else 0)
