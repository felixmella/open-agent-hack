"""Meterless Nightshift client (OpenAI-compatible).

Nightshift routes each request itself (model ids are routing hints), so every result records the model we asked for,
the model that answered and Nightshift's receipt. Never infer the serving model from the request.
"""
import json
import re
import time
from dataclasses import dataclass, field

from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError

APP_HEADERS = {"meterless-app": "open-agent-hack", "meterless-scope": "user"}


class LLMError(RuntimeError):
    pass


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


class NightshiftClient:
    def __init__(self, base_url, token, model, *, timeout=90.0, retries=1, backoff=4.0):
        if not token:
            raise LLMError("METERLESS_RUNTIME_TOKEN is not set")
        self.model = model
        self._retries = retries
        self._backoff = backoff
        self._client = OpenAI(api_key=token, base_url=base_url, default_headers=APP_HEADERS, timeout=timeout,
                              max_retries=0)

    def models(self):
        return [m.id for m in self._client.models.list()]

    def chat(self, messages, *, temperature=0.2, max_tokens=1500, tools=None):
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
            return LLMResult(
                text=(message.content or "").strip(),
                model_requested=self.model,
                model_served=reply.model,
                routed_model=routed_model(reply),
                receipt_id=receipt(reply).get("receipt_id"),
                latency_ms=int((time.monotonic() - started) * 1000),
                attempts=attempt,
                message=message.model_dump(exclude_none=True),
                tool_calls=list(message.tool_calls or []),
            )
        raise LLMError(f"Nightshift request failed after {self._retries + 1} attempts: {type(error).__name__}: {str(error)[:200]}")

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
