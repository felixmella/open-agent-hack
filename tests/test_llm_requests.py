"""Requests to Nightshift stay below its quality-race floor (or Nightshift buffers them until its 45 s deadline), and
answers Nightshift replays from its cache are traced as such."""
import dataclasses
import json

import pytest

from app.adapters.meterless import QUALITY_RACE_FLOOR, nightshift_difficulty
from app.agents.llm import DIFFICULTY_LIMIT, batched, fits, request_text
from app.config import load_settings
from app.engines.world_model import WorldModel
from app.orchestration.loop import run
from app.schemas import RunInput
from fakes import FakeLLM, FakeZetaris

EXAMPLE_2 = {"run_id": "test-requests", "scope": {"cuts": ["08105", "11203", "16201"]}, "languages": ["es", "en"]}


@pytest.fixture
def settings(tmp_path):
    return dataclasses.replace(load_settings(sample_mode=False), logs_dir=tmp_path / "logs",
                               state_dir=tmp_path / "state", output_dir=tmp_path / "output")


def go(settings, llm):
    result = run(RunInput.model_validate(EXAMPLE_2), settings, zetaris=FakeZetaris(), llm_client=llm,
                 world=WorldModel(strip_suffixes=[", Chile"]), echo=False, llm_interval=0)
    trace = [json.loads(line) for line in (settings.logs_dir / f"trace-{result['run_id']}.jsonl").read_text("utf-8").splitlines()]
    return result, trace


def test_the_difficulty_estimate_follows_nightshifts_heuristic():
    assert nightshift_difficulty("x" * 1440) == pytest.approx(0.6)          # length alone reaches the floor
    assert nightshift_difficulty("x" * 1200) == pytest.approx(0.5)
    assert nightshift_difficulty("x" * 1200 + " and then ") > 0.6 - 1e-9    # multi-step phrasing adds 0.1
    assert nightshift_difficulty("SELECT 1" + "x" * 600) == pytest.approx(0.2 + 608 / 2400)
    assert nightshift_difficulty("ok") == 0.0                                # short prompts score lower
    assert DIFFICULTY_LIMIT < QUALITY_RACE_FLOOR


def test_batches_keep_every_request_below_the_floor_and_keep_order():
    items = [{"text": "y" * 300, "n": i} for i in range(12)]
    groups = batched(items, lambda group: {"items": group})
    assert len(groups) > 1 and [i["n"] for g in groups for i in g] == list(range(12))
    assert all(fits({"items": g}) for g in groups)
    huge = [{"text": "z" * 3000}]
    assert batched(huge, lambda group: {"items": group}) == [huge]  # too large on its own: still sent, alone


def test_every_agent_request_in_a_run_scores_below_the_quality_race_floor(settings):
    llm = FakeLLM()
    result, trace = go(settings, llm)
    sizes = [nightshift_difficulty(request_text(payload)) for _, payload in llm.calls]
    assert sizes and max(sizes) < DIFFICULTY_LIMIT
    reviews = [p for agent, p in llm.calls if agent == "Critic" and p["comuna"] == "HUALQUI"]
    assert len(reviews) > 1  # Hualqui's findings no longer fit one review request
    calls = [e for e in trace if e["action"].startswith("llm_")]
    assert calls and all("Nightshift difficulty" in e["input_summary"] for e in calls)
    assert result["summary"]["drafts"] == 9


def test_an_answer_replayed_from_nightshifts_cache_is_traced_as_such(settings):
    class CachedLLM(FakeLLM):
        def chat(self, messages, **kwargs):
            return dataclasses.replace(super().chat(messages, **kwargs), cache_status="exact")

    result, trace = go(settings, CachedLLM())
    calls = [e for e in trace if e["action"].startswith("llm_")]
    assert calls and all(e["nightshift_cache"] == "exact" for e in calls)
    assert all(e["output_summary"].startswith("[replayed from Nightshift's cache]") for e in calls)
    assert result["model_usage"]["nightshift_cache"] == {"exact": len(calls)}
    discovery = result["discoveries"][0]
    assert discovery["method"] == "llm" and discovery["nightshift_cache"] == "exact"
