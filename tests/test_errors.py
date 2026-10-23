"""Structured errors: a run that can't complete raises RunError (code, stage, recoverable, HTTP status), and still
leaves a trace and an error result; the Zetaris client turns HTTP failures into codes; the CLI prints the same JSON."""
import dataclasses
import json
import sys

import httpx
import pytest
from pydantic import ValidationError

import run as cli
from app.adapters.zetaris import ZetarisClient, ZetarisError
from app.agents.analyst import Analyst
from app.config import load_settings
from app.engines.world_model import WorldModel
from app.errors import RunError
from app.orchestration.loop import run
from app.schemas import RunInput
from fakes import FakeZetaris


@pytest.fixture
def settings(tmp_path):
    return dataclasses.replace(load_settings(sample_mode=False), logs_dir=tmp_path / "logs",
                               state_dir=tmp_path / "state", output_dir=tmp_path / "output")


def failing_run(settings, zetaris, scope=None):
    run_input = RunInput.model_validate({"run_id": "test-error", "scope": scope or {"cuts": ["08105"]},
                                         "options": {"use_llm": False}})
    with pytest.raises(RunError) as caught:
        run(run_input, settings, zetaris=zetaris, world=WorldModel(strip_suffixes=[", Chile"]), echo=False)
    error = caught.value
    trace = [json.loads(line) for line in (settings.logs_dir / "trace-test-error.jsonl").read_text("utf-8").splitlines()]
    written = json.loads((settings.output_dir / "test-error" / "result.json").read_text("utf-8"))
    assert written == error.result and written["status"] == "error" and written["error"] == error.to_dict()
    assert trace[-1]["action"] == "finish_run" and trace[-1]["status"] == "error"
    return error


class DownZetaris(FakeZetaris):
    def __init__(self, fail_on="factsync"):
        super().__init__()
        self.fail_on = fail_on

    def query(self, sql, limit=100_000):
        if self.fail_on in sql:
            raise ZetarisError("Zetaris unreachable (ConnectError)")
        return super().query(sql, limit)


def test_a_scope_that_matches_no_comuna_is_an_input_error(settings):
    error = failing_run(settings, FakeZetaris(), scope={"comunas": ["Atlantis"]})
    assert (error.code, error.stage, error.recoverable, error.status) == ("scope_unresolved", "plan", False, 422)


def test_an_unreachable_zetaris_is_recoverable_and_names_the_stage(settings):
    error = failing_run(settings, DownZetaris())
    assert (error.code, error.stage, error.recoverable, error.status) == ("zetaris_unreachable", "plan", True, 503)
    error = failing_run(settings, DownZetaris(fail_on="factsync.wikidata_population"))
    assert (error.code, error.stage) == ("zetaris_unreachable", "retrieve")


def test_a_bug_is_an_internal_error_at_the_stage_it_happened(settings, monkeypatch):
    monkeypatch.setattr(Analyst, "analyze", lambda *args, **kwargs: 1 / 0)
    error = failing_run(settings, FakeZetaris())
    assert (error.code, error.stage, error.recoverable, error.status) == ("internal_error", "analyze", False, 500)
    assert "ZeroDivisionError" in error.message


def test_a_run_id_must_be_a_safe_folder_name():
    for bad in ("..", ".", ".hidden", "a/b", "a\\b", "x" * 65):
        with pytest.raises(ValidationError):
            RunInput.model_validate({"run_id": bad, "scope": {"cuts": ["08105"]}})
    assert RunInput.model_validate({"run_id": "run-1.2_x", "scope": {"cuts": ["08105"]}}).run_id == "run-1.2_x"


def zetaris_answering(*responses):
    replies = iter(responses)

    def handler(request):
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply
    return ZetarisClient("http://zetaris.test/api/v1.0", "1", "key", transport=httpx.MockTransport(handler),
                         retries=1, backoff=0)


@pytest.mark.parametrize("responses, code, recoverable", [
    ([httpx.Response(401, text="bad token")], "zetaris_unauthorized", False),
    ([httpx.Response(400, text="no such view")], "zetaris_query_failed", False),
    ([httpx.Response(400, text='{"msg":"User \'X\' does not have privileges to execute \'SELECT\' on: `factsync`.`v`"}')],
     "zetaris_forbidden", False),
    ([httpx.Response(500, text="boom")] * 2, "zetaris_server_error", True),
    ([httpx.Response(200, text="<html>")] * 2, "zetaris_server_error", True),
    ([httpx.ConnectError("refused")] * 2, "zetaris_unreachable", True),
])
def test_the_zetaris_client_turns_failures_into_codes(responses, code, recoverable):
    with pytest.raises(ZetarisError) as caught:
        zetaris_answering(*responses).query("SELECT 1")
    assert (caught.value.code, caught.value.recoverable) == (code, recoverable)


def test_the_zetaris_client_retries_a_server_error():
    ok = httpx.Response(200, json={"headers": ["one"], "data": [["1"]], "total": 1})
    result = zetaris_answering(httpx.Response(503, text="busy"), ok).query("SELECT 1 AS one")
    assert result.rows == [{"one": "1"}] and result.attempts == 2


def test_a_missing_api_key_is_a_configuration_error():
    with pytest.raises(ZetarisError) as caught:
        ZetarisClient("http://zetaris.test/api/v1.0", "1", "")
    assert caught.value.code == "zetaris_not_configured" and not caught.value.recoverable


@pytest.mark.parametrize("content, problem", [(None, "can't read"), ('{"scope": {}}', "scope")])
def test_the_cli_prints_a_structured_error_for_bad_input(tmp_path, monkeypatch, capsys, content, problem):
    path = tmp_path / "input.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["run.py", str(path)])
    with pytest.raises(SystemExit) as exited:
        cli.main()
    body = json.loads(capsys.readouterr().out)
    assert exited.value.code == 2 and body["status"] == "error"
    assert body["error"]["code"] == "invalid_input" and problem in body["error"]["message"]
