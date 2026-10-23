"""The Nightshift client's streaming path, against recorded frame shapes (Nightshift 1.2.1, October 2026)."""
import json

import httpx
import pytest

from app.adapters.meterless import LLMError, NightshiftClient

MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"


def frame(payload):
    return "data: " + json.dumps(payload) + "\n\n"


def sse(*payloads, done=True):
    return "".join(frame(p) for p in payloads) + ("data: [DONE]\n\n" if done else "")


def client(handler, **kwargs):
    return NightshiftClient("http://nightshift.test/v1", "token", MODEL, transport=httpx.MockTransport(handler),
                            backoff=0, **kwargs)


def chunk(model, **fields):
    return {"id": "c1", "object": "chat.completion.chunk", "model": model, **fields}


STREAM = sse(
    chunk("meterless/auto", choices=[{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]),
    chunk("meterless/auto", choices=[{"index": 0, "delta": {"content": '{"ok": '}, "finish_reason": None}]),
    chunk("meterless/auto", choices=[{"index": 0, "delta": {"content": "true}"}, "finish_reason": None}]),
    chunk(MODEL, choices=[{"index": 0, "delta": {}, "finish_reason": None}], meterless_deliberation={"consensus": {}}),
    chunk(MODEL, meterless={"receipt_id": "rcpt_1", "routed_model": MODEL, "requested_model": MODEL,
                            "provider_model": "meterless/auto", "winning_route": {"model": MODEL}}),
)


def test_a_streamed_reply_is_gathered_with_the_serving_model_and_receipt():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        assert request.headers["meterless-app"] == "open-agent-hack"
        assert request.headers["meterless-tier-split"] == "off"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=STREAM)

    result = client(handler).chat([{"role": "user", "content": "hi"}], max_tokens=4000)
    assert seen["stream"] is True and seen["max_tokens"] == 4000
    assert result.text == '{"ok": true}'
    assert result.model_served == MODEL and result.routed_model == MODEL and result.receipt_id == "rcpt_1"
    assert result.provider_model == "meterless/auto" and result.winning_route == MODEL


def test_a_json_body_to_a_streaming_request_is_read_as_one_reply():
    body = {"model": MODEL, "choices": [{"message": {"role": "assistant", "content": "ready"}, "finish_reason": "stop"}],
            "meterless": {"receipt_id": "rcpt_2", "routed_model": MODEL}}
    result = client(lambda r: httpx.Response(200, json=body)).chat([{"role": "user", "content": "hi"}])
    assert result.text == "ready" and result.receipt_id == "rcpt_2"


def test_a_server_error_is_retried_once_then_reported_with_nightshifts_detail():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(502, json={"error": {"message": "Meterless provider request failed.",
                                                   "meterless_detail": "provider_deadline"}})

    with pytest.raises(LLMError, match="provider_deadline"):
        client(handler).chat([{"role": "user", "content": "hi"}])
    assert len(calls) == 2


def test_a_client_error_is_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, json={"error": {"message": "bad request"}})

    with pytest.raises(LLMError, match="bad request"):
        client(handler).chat([{"role": "user", "content": "hi"}])
    assert len(calls) == 1


def test_an_empty_reply_is_an_error_not_a_blank_answer():
    empty = sse(chunk("meterless/auto", choices=[{"index": 0, "delta": {"role": "assistant"}, "finish_reason": "length"}]))
    with pytest.raises(LLMError, match="empty reply"):
        client(lambda r: httpx.Response(200, headers={"content-type": "text/event-stream"}, text=empty)).chat(
            [{"role": "user", "content": "hi"}])


def test_an_error_frame_mid_stream_is_raised():
    broken = sse(chunk("meterless/auto", choices=[{"index": 0, "delta": {"content": "par"}}]),
                 {"error": {"message": "upstream reset", "meterless_detail": "provider_error"}}, done=False)
    with pytest.raises(LLMError, match="provider_error"):
        client(lambda r: httpx.Response(200, headers={"content-type": "text/event-stream"}, text=broken),
               retries=0).chat([{"role": "user", "content": "hi"}])
