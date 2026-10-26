"""The HTTP API, with a fake model and Zetaris serving real rows: runs in the foreground and in the background, one at
a time, with structured errors, and the result, review queue and trace of each run."""
import dataclasses
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.engines.world_model import WorldModel
from app.main import create_app
from app.orchestration.loop import run
from fakes import FakeLLM, FakeZetaris

EXAMPLE_2 = {"scope": {"cuts": ["08105", "11203", "16201"]}, "languages": ["es", "en"]}


@pytest.fixture
def settings(tmp_path):
    return dataclasses.replace(load_settings(sample_mode=False), logs_dir=tmp_path / "logs",
                               state_dir=tmp_path / "state", output_dir=tmp_path / "output")


def fake_runner(settings, gate=None):
    def runner(run_input):
        if gate:
            gate.wait(10)
        return run(run_input, settings, zetaris=FakeZetaris(), llm_client=FakeLLM(),
                   world=WorldModel(strip_suffixes=[", Chile"]), echo=False, llm_interval=0)
    return runner


def test_a_run_returns_its_result_and_serves_its_report_and_trace(settings):
    client = TestClient(create_app(settings, fake_runner(settings)))
    response = client.post("/run", json={**EXAMPLE_2, "run_id": "api-1"})
    assert response.status_code == 200
    result = response.json()
    assert result["run_id"] == "api-1" and result["status"] == "success" and result["summary"]["drafts"] == 9
    assert client.get("/runs/api-1").json() == result
    report = client.get("/runs/api-1/report")
    assert report.status_code == 200 and "text/html" in report.headers["content-type"] and "Hualqui" in report.text
    trace = client.get("/runs/api-1/trace")
    assert trace.headers["content-type"].startswith("application/x-ndjson")
    assert '"action": "start_run"' in trace.text and '"action": "finish_run"' in trace.text
    assert [r["run_id"] for r in client.get("/runs").json()["runs"]] == ["api-1"]


def test_bad_input_and_unknown_runs_get_structured_errors(settings):
    client = TestClient(create_app(settings, fake_runner(settings)))
    response = client.post("/run", json={"scope": {"cuts": ["08105"], "region": "Aysén"}})
    assert response.status_code == 422
    assert response.json()["status"] == "error" and response.json()["error"]["code"] == "invalid_input"
    assert "scope" in response.json()["error"]["message"]
    for run_id in ("missing", "%2E%2E", ".hidden"):
        response = client.get(f"/runs/{run_id}")
        assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"


def test_a_run_that_cannot_complete_answers_with_its_error_and_keeps_it(settings):
    client = TestClient(create_app(settings, fake_runner(settings)))
    response = client.post("/run", json={"run_id": "api-bad", "scope": {"comunas": ["Atlantis"]}})
    assert response.status_code == 422
    body = response.json()
    assert body["run_id"] == "api-bad" and body["error"]["code"] == "scope_unresolved" and not body["error"]["recoverable"]
    assert client.get("/runs/api-bad").json()["status"] == "error"
    assert "This run could not complete" in client.get("/runs/api-bad/report").text


def test_a_background_run_answers_202_and_a_second_run_waits_its_turn(settings):
    gate = threading.Event()
    client = TestClient(create_app(settings, fake_runner(settings, gate)))
    started = client.post("/run?wait=false", json={**EXAMPLE_2, "run_id": "api-bg"})
    assert started.status_code == 202 and started.json()["links"]["report"] == "/runs/api-bg/report"
    assert client.get("/runs/api-bg").json()["status"] == "running"
    assert "still running" in client.get("/runs/api-bg/report").text
    busy = client.post("/run", json=EXAMPLE_2)
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "busy" and busy.json()["error"]["recoverable"]
    gate.set()
    for _ in range(100):
        if client.get("/runs/api-bg").json()["status"] != "running":
            break
        time.sleep(0.1)
    assert client.get("/runs/api-bg").json()["status"] == "success"
    assert client.post("/run", json={**EXAMPLE_2, "run_id": "api-next"}).status_code == 200


def test_health_in_sample_mode_checks_the_sample_data(settings):
    client = TestClient(create_app(dataclasses.replace(settings, sample_mode=True), fake_runner(settings)))
    health = client.get("/health").json()
    assert health["mode"] == "sample" and health["status"] == "ok" and health["checks"]["sample_data"]["comunas"] == 24


def test_health_reports_what_is_unreachable(settings):
    offline = dataclasses.replace(settings, zetaris_rest_url="http://127.0.0.1:9/api/v1.0",
                                  meterless_base_url="http://127.0.0.1:9/v1")
    health = TestClient(create_app(offline, fake_runner(settings))).get("/health").json()
    assert health["status"] == "degraded" and health["mode"] == "live"
    assert health["checks"]["zetaris"]["ok"] is False and health["checks"]["nightshift"]["ok"] is False
