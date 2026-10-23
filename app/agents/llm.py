"""The agents' path to the model: one call budget per run, pacing between calls, a trace event for every call (with
the model Nightshift says answered, and whether it replayed a cached answer), and None on any failure so the caller
takes its deterministic path instead.

Each request must score below Nightshift's quality-race floor, or Nightshift buffers it until its 45 s deadline kills
it (see app/adapters/meterless.py). Payloads go out as compact JSON, and agents with more to send split it with
`batched` into requests that `fit`.
"""
import json
import time
from collections import Counter

from app.adapters.meterless import QUALITY_RACE_FLOOR, LLMError, nightshift_difficulty, parse_json

JSON_ONLY = "Reply with one JSON object only: no prose, no code fences."
RETRY = "Reply with the JSON object only."
DIFFICULTY_LIMIT = QUALITY_RACE_FLOOR - 0.05  # headroom for the JSON retry's extra message


def request_text(payload):
    return json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))


def fits(payload):
    """Whether a payload makes a request Nightshift answers by streaming (below its quality-race floor)."""
    return nightshift_difficulty(request_text(payload)) < DIFFICULTY_LIMIT


def batched(items, payload_for):
    """Split items, in order, into groups whose payload (`payload_for(group)`) fits one request. An item too large
    on its own still gets a request of its own."""
    groups, current = [], []
    for item in items:
        if current and not fits(payload_for(current + [item])):
            groups.append(current)
            current = []
        current.append(item)
    return groups + [current] if current else groups


class AgentLLM:
    def __init__(self, client, tracer, *, max_calls=60, min_interval=1.0, sleep=time.sleep):
        self.client = client
        self.tracer = tracer
        self.max_calls = max_calls
        self.min_interval = min_interval
        self._sleep = sleep
        self._last = 0.0
        self.calls = 0
        self.fallbacks = Counter()
        self.served = Counter()
        self.routed = Counter()
        self.by_agent = Counter()
        self.requested = Counter()
        self.cached = Counter()

    @property
    def available(self):
        return self.client is not None and self.calls < self.max_calls

    def ask_json(self, agent, action, system, payload, *, target_agent=None, round_no=None, max_tokens=8000,
                 validate=None):
        """Ask for a JSON object. Returns (data, last LLMResult), or None when there is no model, the budget is
        spent, the call fails, or `validate` rejects the reply; each case is traced."""
        if self.client is None:
            return None
        if self.calls >= self.max_calls:
            self.fallbacks[agent] += 1
            self.tracer.event(agent, action, status="fallback", target_agent=target_agent, round_no=round_no,
                              output_summary=f"model call budget spent ({self.max_calls} calls); deterministic path")
            return None
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            self._sleep(wait)
        text = request_text(payload)
        messages = [{"role": "system", "content": f"{system}\n\n{JSON_ONLY}"}, {"role": "user", "content": text}]
        self.calls += 1
        data, results, problem = None, [], None
        try:
            results.append(self.client.chat(messages, temperature=0.1, max_tokens=max_tokens))
            try:
                data = parse_json(results[-1].text)
            except ValueError:  # one more try, asking for the JSON alone (the bad reply stays out: it would make
                # the request large enough to be buffered, and an identical request could be replayed from cache)
                results.append(self.client.chat(messages + [{"role": "user", "content": RETRY}],
                                                temperature=0.1, max_tokens=max_tokens))
                data = parse_json(results[-1].text)
            if not isinstance(data, dict):
                raise ValueError("the reply is not a JSON object")
            problem = validate(data) if validate else None
        except (LLMError, ValueError, TypeError, KeyError) as exc:
            problem = f"{type(exc).__name__}: {str(exc)[:400]}"
        finally:
            self._last = time.monotonic()
        for result in results:
            self.served[result.model_served or "unknown"] += 1
            self.routed[result.routed_model or "unknown"] += 1
            self.requested[result.model_requested] += 1
            self.by_agent[agent] += 1
            cache = getattr(result, "cache_status", None)
            if cache and cache != "miss":
                self.cached[cache] += 1
            self.tracer.event(agent, f"llm_{action}",
                              input_summary=f"{len(text):,} chars of context (Nightshift difficulty "
                                            f"{nightshift_difficulty(text):.2f})",
                              output_summary=("[replayed from Nightshift's cache] " if cache == "exact" else "")
                                             + result.text[:160].replace("\n", " "),
                              target_agent=target_agent, round_no=round_no, llm=result, retry_count=result.attempts - 1,
                              status="success" if not problem else "invalid", nightshift_cache=cache)
        if problem:
            self.fallbacks[agent] += 1
            self.tracer.event(agent, action, status="fallback", target_agent=target_agent, round_no=round_no,
                              output_summary=f"model reply unusable ({problem}); deterministic path")
            return None
        return data, results[-1]

    def usage(self):
        return {"calls": sum(self.by_agent.values()), "requests": self.calls, "by_agent": dict(self.by_agent),
                "requested_model": dict(self.requested), "served_model": dict(self.served),
                "routed_model": dict(self.routed), "nightshift_cache": dict(self.cached),
                "fallbacks": dict(self.fallbacks), "budget": self.max_calls}


def model_note(result):
    """Provenance for something a model wrote: which model Nightshift says answered, and its receipt."""
    if result is None:
        return {"method": "rules"}
    note = {"method": "llm", "model_requested": result.model_requested, "model_served": result.model_served,
            "routed_model": result.routed_model, "receipt_id": result.receipt_id}
    if getattr(result, "cache_status", None) not in (None, "miss"):
        note["nightshift_cache"] = result.cache_status
    return note
