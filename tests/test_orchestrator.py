"""The orchestrator's loops with a fake model and Zetaris serving real rows: the Critic's rejection sends the Planner
to discover a source and changes a verdict; a finding the Critic keeps rejecting is escalated at the cap; without a
model, or with a broken one, every step falls back to code and the run still completes."""
import dataclasses
import json

import pytest

from app.config import load_settings
from app.engines.world_model import WorldModel
from app.orchestration.loop import run
from app.schemas import RunInput
from fakes import BrokenLLM, FakeLLM, FakeZetaris

EXAMPLE_2 = {"run_id": "test-example-2", "scope": {"cuts": ["08105", "11203", "16201"]}, "languages": ["es", "en"]}


@pytest.fixture
def settings(tmp_path):
    return dataclasses.replace(load_settings(sample_mode=False), logs_dir=tmp_path / "logs",
                               state_dir=tmp_path / "state", output_dir=tmp_path / "output")


def go(settings, llm, **overrides):
    run_input = RunInput.model_validate({**EXAMPLE_2, **overrides})
    zetaris, world = FakeZetaris(), WorldModel(strip_suffixes=[", Chile"])
    result = run(run_input, settings, zetaris=zetaris, llm_client=llm, world=world, echo=False, llm_interval=0)
    trace = [json.loads(line) for line in (settings.logs_dir / f"trace-{result['run_id']}.jsonl").read_text("utf-8").splitlines()]
    return result, trace, zetaris, world


def comuna(result, name):
    return next(c for c in result["comunas"] if c["name"] == name)


def finding(entry, target, aspect="value", location=None):
    return next(f for f in entry["findings"] if f["target"] == target and f["aspect"] == aspect
                and (location is None or f["claim"].get("location") == location))


def test_critic_rejection_sends_the_planner_to_projections_and_changes_hualquis_verdict(settings):
    result, trace, zetaris, world = go(settings, FakeLLM())
    reject = next(e for e in trace if e["agent_name"] == "Critic" and e["action"] == "reject")
    assert reject["round"] == 1 and reject["target_agent"] == "Planner" and "26,746" in reject["fix"]["instruction"]
    discovery = next(e for e in trace if e["action"] == "discover_source")
    assert "official_projections" in discovery["output_summary"]
    assert discovery["decided_by"]["model_served"] == "fake/nemotron" and discovery["decided_by"]["receipt_id"]
    assert sum("'projection'" in sql for sql in zetaris.sql) == 1
    assert result["summary"]["discoveries"] == ["official_projections"]

    hualqui = comuna(result, "HUALQUI")
    spanish = finding(hualqui, "es", location="infobox")
    assert spanish["class"] == "different_definition" and spanish["status"] == "approved"
    history = [a["data"]["class"] for a in world.view("observations").assessments("comuna:cut:08105", agent="Analyst")
               if a["data"]["id"] == spanish["id"]]
    assert history == ["genuine_error", "different_definition"]  # round 1 guess, round 2 after discovery
    assert hualqui["critic"]["rounds"] == 2 and not hualqui["critic"]["history"][0]["approved"]


def test_drafts_for_eswiki_enwiki_and_wikidata_cite_ine(settings):
    result, trace, _, _ = go(settings, FakeLLM())
    drafts = comuna(result, "HUALQUI")["drafts"]
    assert {"eswiki", "enwiki", "wikidata"} <= set(drafts)
    assert "| población = 25.795" in drafts["eswiki"]["wikitext"] and "cita web" in drafts["eswiki"]["wikitext"]
    assert "| population_total = 25795" in drafts["enwiki"]["wikitext"]
    assert drafts["wikidata"]["quickstatements"].startswith("Q13079|P1082|25795|P585|+2024-00-00T00:00:00Z/9|P459|Q39825")
    assert all(d["status"] == "approved" for k, d in drafts.items() if k in ("eswiki", "enwiki", "wikidata"))
    assert all("censo2024.ine.gob.cl" in (d.get("wikitext") or d.get("quickstatements"))
               for k, d in drafts.items() if k in ("eswiki", "enwiki", "wikidata"))
    assert result["summary"]["drafts"] == 9
    llm_events = [e for e in trace if e["action"].startswith("llm_")]
    assert llm_events and all(e["model"] and e["routed_model"] and e["receipt_id"] for e in llm_events)


def test_a_finding_the_critic_keeps_rejecting_is_escalated_at_the_cap(settings):
    def insists_on_a_projection(payload):
        return {"verdicts": [{"claim_id": c["claim_id"], "class": "different_definition",
                              "explanation": f"{c['value']:,} is probably an INE projection.", "confidence": 0.6}
                             for c in payload["claims"]]}
    result, trace, _, _ = go(settings, FakeLLM(Analyst=insists_on_a_projection))
    hualqui = comuna(result, "HUALQUI")
    assert hualqui["status"] == "partial" and hualqui["critic"]["rounds"] == 3
    fixes = [h["fix"]["target_agent"] for h in hualqui["critic"]["history"] if h["fix"]]
    assert fixes == ["Planner", "Analyst", "Analyst"]
    escalated = [f for f in hualqui["findings"] if f["status"] == "escalated"]
    assert [f["claim"]["value"] for f in escalated] == [20968]
    assert result["escalations"][0]["finding_id"] == escalated[0]["id"]
    assert any(e["action"] == "escalate" and e["target_agent"] == "human" for e in trace)
    assert "eswiki" in hualqui["drafts"]  # the approved findings still get their drafts


def test_without_a_model_every_step_takes_its_deterministic_path(settings):
    result, trace, _, _ = go(settings, None, options={"use_llm": False})
    assert result["model_usage"]["calls"] == 0
    assert result["summary"]["discoveries"] == ["official_projections"]
    assert finding(comuna(result, "HUALQUI"), "es", location="infobox")["class"] == "different_definition"
    assert comuna(result, "GUAITECAS")["drafts"]["explanation_by"] == {"method": "rules"}
    assert result["summary"]["drafts"] == 9


def test_a_failing_model_is_traced_and_replaced_by_code(settings):
    result, trace, _, _ = go(settings, BrokenLLM())
    fallbacks = [e for e in trace if e["status"] == "fallback"]
    assert fallbacks and all("Nightshift request failed" in e["output_summary"] for e in fallbacks)
    assert set(result["model_usage"]["fallbacks"]) >= {"Extractor", "Analyst", "Critic", "Planner", "Editor"}
    assert result["summary"]["findings"] > 0 and result["summary"]["drafts"] == 9
