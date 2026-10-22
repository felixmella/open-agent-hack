"""Smoke test for the Data (Zetaris) and Power (Meterless Nightshift) layers.

Run from the project root:  .venv\\Scripts\\python scripts\\smoke_test.py
Needs Zetaris and Nightshift running and .env filled in. Never prints secret values.
"""
import functools
import json
import os
import sys
import uuid

import httpx
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

APP_HEADERS = {"meterless-app": "open-agent-hack", "meterless-scope": "user"}
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


def need(*names):
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"missing from .env: {', '.join(missing)}")


def zetaris_sql(sql, limit=10):
    need("ZETARIS_REST_URL", "ZETARIS_ORG_ID", "ZETARIS_API_KEY")
    response = httpx.post(
        os.environ["ZETARIS_REST_URL"].rstrip("/") + "/sql-editor/sqls/run",
        headers={
            "Authorization": "Bearer " + os.environ["ZETARIS_API_KEY"],
            "X-Org-ID": os.environ["ZETARIS_ORG_ID"],
            "X-Request-ID": str(uuid.uuid4()),
        },
        json={"queryId": str(uuid.uuid4()), "sql": sql, "source": "SqlEditor", "limit": limit},
        timeout=60,
    )
    if response.is_error:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:150]}")
    return response.json()


@functools.cache
def client():
    need("METERLESS_BASE_URL", "METERLESS_RUNTIME_TOKEN", "METERLESS_MODEL")
    return OpenAI(
        api_key=os.environ["METERLESS_RUNTIME_TOKEN"],
        base_url=os.environ["METERLESS_BASE_URL"],
        default_headers=APP_HEADERS,
        timeout=90.0,
        max_retries=1,
    )


def routed_model(reply):
    receipt = (getattr(reply, "model_extra", None) or {}).get("meterless") or {}
    return receipt.get("routed_model", "n/a")


def zetaris_web():
    url = os.environ.get("ZETARIS_UI_URL", "http://localhost:3000")
    httpx.get(url, timeout=10, follow_redirects=True).raise_for_status()


def zetaris_rest():
    body = zetaris_sql("SELECT 1 AS one", limit=1)
    data = body.get("data")
    assert data, f"no rows: {json.dumps(body)[:150]}"
    row = data[0]
    value = row[0] if isinstance(row, list) else next(iter(row.values()))
    assert str(value) == "1", f"unexpected reply: {json.dumps(body)[:150]}"
    return f"rows are {type(row).__name__}s; response keys: {sorted(body)}"


def nightshift_models():
    ids = [model.id for model in client().models.list()]
    model = os.environ["METERLESS_MODEL"]
    assert model in ids, f"{model} is not among the {len(ids)} models Nightshift lists"
    return f"{len(ids)} models listed, including {model}"


def nemotron_chat():
    reply = client().chat.completions.create(
        model=os.environ["METERLESS_MODEL"],
        messages=[{"role": "user", "content": "Reply with the single word: ready"}],
    )
    text = (reply.choices[0].message.content or "").strip()
    assert text, "empty reply"
    return f"model={reply.model}, routed={routed_model(reply)}, reply={text[:40]!r}"


def nemotron_tool_round_trip():
    llm = client()
    model = os.environ["METERLESS_MODEL"]
    messages = [{
        "role": "user",
        "content": "Use the run_sql tool to run SELECT 1 + 1 AS two, then tell me the result.",
    }]
    first = llm.chat.completions.create(model=model, messages=messages, tools=[RUN_SQL_TOOL])
    message = first.choices[0].message
    assert message.tool_calls, "the model answered without calling run_sql"
    call = message.tool_calls[0]
    sql = json.loads(call.function.arguments)["sql"]
    rows = zetaris_sql(sql).get("data")
    messages += [
        message.model_dump(exclude_none=True),
        {"role": "tool", "tool_call_id": call.id, "content": json.dumps(rows)},
    ]
    final = llm.chat.completions.create(model=model, messages=messages, tools=[RUN_SQL_TOOL])
    text = (final.choices[0].message.content or "").strip()
    assert text, "no final answer after the tool result"
    return f"sql={sql!r}, rows={json.dumps(rows)[:40]}, answer={text[:60]!r}"


if __name__ == "__main__":
    check("Data: Zetaris web interface", zetaris_web)
    check("Data: Zetaris runs SQL over its REST API", zetaris_rest)
    check("Power: Nightshift lists the pinned model", nightshift_models)
    check("Power: Nemotron replies through Nightshift", nemotron_chat)
    check("Power+Data: Nemotron tool call round trip through Zetaris", nemotron_tool_round_trip)
    sys.exit(1 if failures else 0)
