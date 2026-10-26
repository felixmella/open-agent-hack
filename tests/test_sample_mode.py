"""Sample mode: the examples run on the recorded snapshot in data/sample with no network at all, and say so; the
snapshot answers only the agents' own queries for the comunas it holds; in live mode it stands in for Zetaris when
Zetaris fails in a way a retry could fix, and the run escalates that."""
import dataclasses
import json
import socket

import pytest

from app.adapters.sample_data import SampleData
from app.adapters.zetaris import ZetarisError
from app.config import ROOT, load_settings
from app.errors import RunError
from app.orchestration import loop
from app.orchestration.loop import run
from app.schemas import RunInput
from fakes import FakeZetaris

SAMPLE = ROOT / "data" / "sample"


@pytest.fixture
def no_network(monkeypatch):
    attempts = []

    def refuse(self, address, *args, **kwargs):
        attempts.append(address)
        raise OSError("network disabled in this test")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    return attempts


@pytest.fixture
def sample_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMPLE_MODE", "true")
    return dataclasses.replace(load_settings(), logs_dir=tmp_path / "logs", state_dir=tmp_path / "state",
                               output_dir=tmp_path / "output")


def example(n):
    return RunInput.model_validate_json((ROOT / "input_examples" / f"example_{n}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("n", [1, 2, 3, 4, 6])
def test_every_example_runs_on_the_snapshot_without_network(sample_settings, no_network, n):
    result = run(example(n), sample_settings, echo=False)
    assert result["mode"] == "sample" and result["data"]["source"] == "sample" and not no_network
    assert result["status"] == "success" and result["model_usage"]["calls"] == 0
    assert result["summary"]["comunas"] == len(json.loads((SAMPLE / "manifest.json").read_text("utf-8"))
                                                ["examples"][f"example_{n}.json"])
    assert result["summary"]["findings"] > 0 and result["summary"]["drafts"] > 0
    trace = [json.loads(line) for line in (sample_settings.logs_dir / f"trace-{result['run_id']}.jsonl")
             .read_text("utf-8").splitlines()]
    reads = [e for e in trace if e["action"] in ("register_comunas", "query_zetaris")]
    assert reads and all(e["data_origin"].startswith("sample snapshot recorded") for e in reads)


def test_the_snapshot_reproduces_the_demo_moment(sample_settings, no_network):
    result = run(example(2), sample_settings, echo=False)
    hualqui = next(c for c in result["comunas"] if c["name"] == "HUALQUI")
    infobox = next(f for f in hualqui["findings"] if f["target"] == "es" and f["claim"].get("location") == "infobox")
    assert infobox["claim"]["value"] == 26746 and infobox["class"] == "different_definition"
    assert not hualqui["critic"]["history"][0]["approved"] and hualqui["critic"]["history"][-1]["approved"]
    # Census 2002 for the three 2002 figures in Guaitecas's and Quirihue's articles; projections for Hualqui's two
    assert result["summary"]["discoveries"] == ["official_census2002", "official_projections"]


def test_a_comuna_outside_the_snapshot_is_refused(sample_settings, no_network):
    with pytest.raises(RunError) as caught:
        run(RunInput.model_validate({"scope": {"cuts": ["13101"]}}), sample_settings, echo=False)
    assert (caught.value.code, caught.value.stage, caught.value.status) == ("not_in_sample", "retrieve", 422)
    assert "HUALQUI" in caught.value.message and "13101" in caught.value.message


def test_the_snapshot_answers_the_agents_queries_only():
    sample = SampleData(SAMPLE)
    census = sample.query("SELECT cut, population FROM factsync.official_population "
                          "WHERE series = 'official_census' AND cut IN ('08105')")
    assert census.columns == ["cut", "population"] and {r["population"] for r in census.rows} == {"24333", "25795"}
    articles = sample.query("SELECT cut, title FROM factsync.eswiki_infobox WHERE cut IN ('08105') OR cut IS NULL")
    assert {r["cut"] for r in articles.rows} == {"08105", None} and articles.origin.startswith("sample snapshot")
    for sql in ("SELECT cut FROM factsync.official_population WHERE population > 10",
                "SELECT secret FROM factsync.official_population",
                "SELECT cut FROM factsync.unknown_view",
                "DROP SCHEMASTORE VIEW official_population FROM factsync"):
        with pytest.raises(ZetarisError) as caught:
            sample.query(sql)
        assert caught.value.code == "not_in_sample" and not caught.value.recoverable


class DownZetaris(FakeZetaris):
    def __init__(self, error):
        super().__init__()
        self.error = error

    def query(self, sql, limit=100_000):
        raise self.error


def live_settings(tmp_path):
    return dataclasses.replace(load_settings(sample_mode=False), logs_dir=tmp_path / "logs",
                               state_dir=tmp_path / "state", output_dir=tmp_path / "output")


def test_when_zetaris_is_down_the_snapshot_stands_in_and_the_run_escalates_it(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "ZetarisClient", lambda *a, **k: DownZetaris(ZetarisError("Zetaris unreachable")))
    run_input = RunInput.model_validate({"run_id": "test-fallback", "scope": {"cuts": ["08105"]},
                                         "options": {"use_llm": False}})
    result = run(run_input, live_settings(tmp_path), echo=False)
    assert result["mode"] == "live" and result["status"] == "partial"
    fallbacks = result["data"]["fallbacks"]
    assert {f["view"] for f in fallbacks} >= {"factsync.ine_census2024", "factsync.official_population"}
    assert all(f in result["escalations"] for f in fallbacks)
    trace = [json.loads(line) for line in (tmp_path / "logs" / "trace-test-fallback.jsonl").read_text("utf-8").splitlines()]
    assert sum(e["action"] == "fallback_to_sample" for e in trace) == len(fallbacks)
    assert result["summary"]["findings"] > 0


def test_a_configuration_error_is_not_hidden_by_the_snapshot(tmp_path, monkeypatch):
    unauthorized = ZetarisError("HTTP 401: bad token", status=401, recoverable=False, code="zetaris_unauthorized")
    monkeypatch.setattr(loop, "ZetarisClient", lambda *a, **k: DownZetaris(unauthorized))
    with pytest.raises(RunError) as caught:
        run(RunInput.model_validate({"scope": {"cuts": ["08105"]}, "options": {"use_llm": False}}),
            live_settings(tmp_path), echo=False)
    assert caught.value.code == "zetaris_unauthorized"
