"""Meterless Nightshift client (OpenAI-compatible).

Nightshift routes each request itself (model ids are routing hints), so every result records the model we asked for,
the model that answered and Nightshift's receipt. Never infer the serving model from the request.

Chat calls stream by default. Nightshift abandons a cloud request whose response headers take longer than 45 s
(`provider_deadline`; CLOUD_FETCH_DEADLINE_MS in its providers.js bounds time-to-headers only). A plain reply sends
its headers only after the model has finished thinking, which Nemotron 3.5 does at length on every request; a
streamed reply starts at once, so long reasoning no longer runs into that deadline.

Every request also sends `meterless-tier-split: off`. By default Nightshift splits a request it takes for code (our
JSON-shaped prompts) into a `planning` and a `code_patch` phase: two model calls, whose internal calls can still hit the
deadline. Off, each request is one phase on one lane, so one call answers it and the receipt describes that call.
"""
import json
import re
import time
from dataclasses import dataclass, field

import httpx
from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError

APP_HEADERS = {"meterless-app": "open-agent-hack", "meterless-scope": "user", "meterless-tier-split": "off"}


class LLMError(RuntimeError):
    pass


class ProviderError(RuntimeError):
    """An error reply from Nightshift on the streaming path: the HTTP status (None mid-stream) and the parsed body."""

    def __init__(self, status_code, body):
        super().__init__(f"HTTP {status_code}" if status_code else "error frame")
        self.status_code = status_code
        self.body = body if isinstance(body, dict) else {"error": {"message": str(body)[:300]}}


@dataclass
class LLMResult:
    text: str
    model_requested: str
    model_served: str | None
    routed_model: str | None
    receipt_id: str | None
    latency_ms: int
    attempts: int
    message: dict = field(default_factory=dict)
    tool_calls: list = field(default_factory=list)
    receipt_requested_model: str | None = None
    provider_model: str | None = None
    winning_route: str | None = None
    usage: dict = field(default_factory=dict)


def receipt(reply):
    return (getattr(reply, "model_extra", None) or {}).get("meterless") or {}


def routed_model(reply):
    return receipt(reply).get("routed_model")


def parse_json(text):
    """Parse a JSON object or array from a model reply, tolerating code fences and surrounding prose."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\}|\[.*\])", cleaned, re.S)
        if not match:
            raise ValueError("no JSON in the model reply")
        return json.loads(match.group(1))


def failure_detail(error):
    """What Nightshift said about a failed request: its error detail and the route it tried, when it gives them."""
    detail = f"{type(error).__name__}"
    body = getattr(error, "body", None)
    if not isinstance(body, dict):
        response = getattr(error, "response", None)
        try:
            body = response.json() if response is not None else {}
        except ValueError:
            body = {}
    problem = body.get("error") if isinstance(body.get("error"), dict) else {}
    route = body.get("meterless") if isinstance(body.get("meterless"), dict) else {}
    if getattr(error, "status_code", None):
        detail += f" HTTP {error.status_code}"
    detail += f": {problem.get('meterless_detail') or problem.get('message') or str(error)[:200]}"
    if route:
        detail += (f" (requested_model={route.get('requested_model')}, provider_model={route.get('provider_model')}"
                   f", routed_model={route.get('routed_model')})")
    return detail


def _retryable(error):
    status = getattr(error, "status_code", None)
    return status is None or status == 429 or status >= 500


def _body(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return {"error": {"message": raw[:300].decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)[:300]}}


def _from_completion(reply):
    choice = (reply.get("choices") or [{}])[0]
    return {"text": (choice.get("message") or {}).get("content") or "", "model": reply.get("model"),
            "meterless": reply.get("meterless") or {}, "usage": reply.get("usage") or {},
            "finish_reason": choice.get("finish_reason")}


class NightshiftClient:
    def __init__(self, base_url, token, model, *, timeout=90.0, stream_timeout=180.0, retries=1, backoff=4.0,
                 transport=None):
        if not token:
            raise LLMError("METERLESS_RUNTIME_TOKEN is not set")
        self.model = model
        self._retries = retries
        self._backoff = backoff
        self._client = OpenAI(api_key=token, base_url=base_url, default_headers=APP_HEADERS, timeout=timeout,
                              max_retries=0)
        self._chat_url = base_url.rstrip("/") + "/chat/completions"
        self._http = httpx.Client(headers={**APP_HEADERS, "Authorization": f"Bearer {token}"}, transport=transport,
                                  timeout=httpx.Timeout(stream_timeout, connect=10.0))

    def models(self):
        return [m.id for m in self._client.models.list()]

    def chat(self, messages, *, temperature=0.2, max_tokens=1500, tools=None, stream=None):
        """One chat completion. Streams unless tools are given (or stream=False)."""
        if not (not tools if stream is None else stream):
            return self._chat_plain(messages, temperature, max_tokens, tools)
        body = {"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens,
                "stream": True}
        error = None
        for attempt in range(1, self._retries + 2):
            started = time.monotonic()
            try:
                reply = self._stream(body)
            except (ProviderError, httpx.TransportError) as exc:
                error = exc
                if not _retryable(exc) or attempt > self._retries:
                    break
                time.sleep(self._backoff * attempt)
                continue
            text, meterless = reply["text"].strip(), reply["meterless"]
            if not text:
                raise LLMError(f"Nightshift returned an empty reply (finish_reason={reply['finish_reason']}); the "
                               f"model's hidden reasoning probably used the whole max_tokens={max_tokens}")
            return LLMResult(
                text=text,
                model_requested=self.model,
                model_served=reply["model"] or meterless.get("routed_model"),
                routed_model=meterless.get("routed_model"),
                receipt_id=meterless.get("receipt_id"),
                latency_ms=int((time.monotonic() - started) * 1000),
                attempts=attempt,
                message={"role": "assistant", "content": text},
                receipt_requested_model=meterless.get("requested_model"),
                provider_model=meterless.get("provider_model"),
                winning_route=(meterless.get("winning_route") or {}).get("model"),
                usage=reply["usage"] or meterless.get("usage") or {},
            )
        raise LLMError(f"Nightshift request failed after {attempt} attempt(s): {failure_detail(error)}")

    def _stream(self, body):
        """Send a streaming request and gather the reply: the content deltas, the model the last frames name (the
        first ones say meterless/auto) and the receipt. A JSON body instead of an event stream is read as one reply."""
        with self._http.stream("POST", self._chat_url, json=body) as response:
            if response.status_code >= 400:
                raise ProviderError(response.status_code, _body(response.read()))
            if "application/json" in response.headers.get("content-type", ""):
                return _from_completion(json.loads(response.read()))
            parts, model, meterless, usage, finish = [], None, {}, {}, None
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                if chunk.get("error"):
                    raise ProviderError(None, chunk)
                if chunk.get("model") and not str(chunk["model"]).startswith("meterless/"):
                    model = chunk["model"]
                meterless = chunk.get("meterless") or meterless
                usage = chunk.get("usage") or usage
                for choice in chunk.get("choices") or []:
                    parts.append((choice.get("delta") or {}).get("content") or "")
                    finish = choice.get("finish_reason") or finish
            return {"text": "".join(parts), "model": model, "meterless": meterless, "usage": usage,
                    "finish_reason": finish}

    def _chat_plain(self, messages, temperature, max_tokens, tools):
        error = None
        for attempt in range(1, self._retries + 2):
            started = time.monotonic()
            try:
                reply = self._client.chat.completions.create(
                    model=self.model, messages=messages, temperature=temperature, max_tokens=max_tokens,
                    **({"tools": tools} if tools else {}))
            except (RateLimitError, APITimeoutError, APIConnectionError, APIError) as exc:
                error = exc
                if attempt <= self._retries:
                    time.sleep(self._backoff * attempt)
                continue
            message = reply.choices[0].message
            meterless = receipt(reply)
            return LLMResult(
                text=(message.content or "").strip(),
                model_requested=self.model,
                model_served=reply.model,
                routed_model=meterless.get("routed_model"),
                receipt_id=meterless.get("receipt_id"),
                latency_ms=int((time.monotonic() - started) * 1000),
                attempts=attempt,
                message=message.model_dump(exclude_none=True),
                tool_calls=list(message.tool_calls or []),
                receipt_requested_model=meterless.get("requested_model"),
                provider_model=meterless.get("provider_model"),
                winning_route=(meterless.get("winning_route") or {}).get("model"),
                usage=reply.usage.model_dump(exclude_none=True) if reply.usage else {},
            )
        raise LLMError(f"Nightshift request failed after {self._retries + 1} attempts: {failure_detail(error)}")

    def chat_json(self, messages, **kwargs):
        """Ask for JSON; if the reply doesn't parse, ask once more for JSON only. Returns (data, [results])."""
        first = self.chat(messages, **kwargs)
        try:
            return parse_json(first.text), [first]
        except ValueError:
            retry = self.chat(messages + [{"role": "assistant", "content": first.text},
                                          {"role": "user", "content": "That was not valid JSON. Reply with the JSON only."}],
                              **kwargs)
            return parse_json(retry.text), [first, retry]
