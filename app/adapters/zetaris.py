"""Zetaris REST client: one SQL statement per request, rows returned as dicts.

Zetaris returns every value as a string (SELECT 1 + 1 gives [["2"]]), so callers convert with as_int / as_str.
"""
import time
import uuid
from dataclasses import dataclass

import httpx


class ZetarisError(RuntimeError):
    """`code`: zetaris_not_configured, zetaris_unreachable, zetaris_unauthorized (key rejected), zetaris_forbidden
    (the key's user may not read the view: see zetaris/05_readonly_grants.sql), zetaris_server_error,
    zetaris_query_failed, or not_in_sample (sample mode, for comunas the snapshot doesn't hold)."""

    def __init__(self, message, *, status=None, recoverable=True, code="zetaris_unreachable"):
        super().__init__(message)
        self.status = status
        self.recoverable = recoverable
        self.code = code


def error_code(status, text=""):
    if status in (401, 403):
        return "zetaris_unauthorized"
    if "does not have privileges" in text:  # Zetaris answers a missing grant with HTTP 400
        return "zetaris_forbidden"
    return "zetaris_server_error" if status >= 500 else "zetaris_query_failed"


@dataclass
class QueryResult:
    sql: str
    columns: list
    rows: list
    total: int
    elapsed_ms: int
    attempts: int
    origin: str = "zetaris"  # or the sample snapshot that answered instead (app/adapters/sample_data.py)


def as_int(value):
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def as_str(value):
    return None if value is None or value == "" else str(value)


def sql_list(values):
    """Render values as a SQL IN list of string literals."""
    return ", ".join("'" + str(v).replace("'", "''") + "'" for v in values)


class ZetarisClient:
    def __init__(self, rest_url, org_id, api_key, *, timeout=90.0, retries=2, backoff=2.0, transport=None):
        if not api_key:
            raise ZetarisError("ZETARIS_API_KEY is not set", recoverable=False, code="zetaris_not_configured")
        self._url = rest_url.rstrip("/") + "/sql-editor/sqls/run"
        self._headers = {"Authorization": f"Bearer {api_key}", "X-Org-ID": str(org_id)}
        self._retries = retries
        self._backoff = backoff
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def query(self, sql, *, limit=100_000):
        statement = sql.strip().rstrip(";").strip()
        if ";" in statement:
            raise ValueError("Zetaris runs one SQL statement per request")
        error = None
        for attempt in range(1, self._retries + 2):
            started = time.monotonic()
            try:
                response = self._client.post(
                    self._url,
                    headers={**self._headers, "X-Request-ID": str(uuid.uuid4())},
                    json={"queryId": str(uuid.uuid4()), "sql": statement, "source": "SqlEditor", "limit": limit},
                )
            except httpx.TransportError as exc:
                error = ZetarisError(f"Zetaris unreachable ({type(exc).__name__})")
            else:
                if response.status_code < 400:
                    try:
                        body = response.json()
                    except ValueError:
                        body = None
                    if isinstance(body, dict):
                        columns = body.get("headers") or []
                        rows = [dict(zip(columns, row)) for row in body.get("data") or []]
                        elapsed = int((time.monotonic() - started) * 1000)
                        return QueryResult(statement, columns, rows, int(body.get("total") or len(rows)), elapsed, attempt)
                    error = ZetarisError(f"HTTP {response.status_code} with a body that isn't a JSON object",
                                         status=response.status_code, code="zetaris_server_error")
                else:
                    error = ZetarisError(f"HTTP {response.status_code}: {response.text[:300]}", status=response.status_code,
                                         recoverable=response.status_code >= 500,
                                         code=error_code(response.status_code, response.text))
                    if response.status_code < 500:
                        raise error
            if attempt <= self._retries:
                time.sleep(self._backoff * attempt)
        raise error
