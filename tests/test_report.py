"""The review queue page: rendered from the run's result (as returned, or read back from result.json), self-contained,
escaped, and showing what a reviewer needs: why each figure differs, the drafts, and what the agents did."""
import copy
import dataclasses
import json
import re

import pytest

from app.config import load_settings
from app.engines.world_model import WorldModel
from app.orchestration.loop import run
from app.report.html import render_report
from app.schemas import RunInput
from fakes import FakeLLM, FakeZetaris


@pytest.fixture
def result(tmp_path):
    settings = dataclasses.replace(load_settings(sample_mode=False), logs_dir=tmp_path / "logs",
                                   state_dir=tmp_path / "state", output_dir=tmp_path / "output")
    run_input = RunInput.model_validate({"run_id": "test-report", "scope": {"cuts": ["08105", "11203", "16201"]}})
    return run(run_input, settings, zetaris=FakeZetaris(), llm_client=FakeLLM(),
               world=WorldModel(strip_suffixes=[", Chile"]), echo=False, llm_interval=0), tmp_path


def test_every_run_writes_its_review_queue(result):
    result, tmp_path = result
    assert result["report_file"].endswith("output/test-report/report.html")
    page = (tmp_path / "output" / "test-report" / "report.html").read_text(encoding="utf-8")
    assert "<title>FactSync Chile review queue · test-report</title>" in page


def test_the_page_shows_why_figures_differ_and_the_drafts(result):
    page = render_report(result[0])
    for text in ("Hualqui", "Guaitecas", "Quirihue", "Different definition", "Withdrawn census", "26.746",
                 "INE projection 2024", "Spanish Wikipedia", "English Wikipedia", "Wikidata",
                 "| población = 25.795", "| population_total = 25795", "Q13079|P1082|25795",
                 "censo2024.ine.gob.cl", "fake/nemotron", "INE projections 2002–2035 · added by the Planner"):
        assert text in page, text
    assert "&lt;ref name=&#34;censo2024&#34;&gt;" in page or "&lt;ref name=&quot;censo2024&quot;&gt;" in page
    timeline = page.split("How the agents got here", 1)[1].split("</ol>", 1)[0]
    assert "rejected Hualqui" in timeline and "added INE projections" in timeline and "approved Hualqui after the fix" in timeline


def test_the_page_loads_nothing_from_the_network(result):
    page = render_report(result[0])
    assert not re.search(r"<script[^>]+src=|<link[^>]+stylesheet|@import|<img[^>]+src=\"http", page)


def test_a_result_read_back_from_json_renders_the_same_figures(result):
    page = render_report(json.loads(json.dumps(result[0], default=str)), generated_at="now")
    assert page == render_report(result[0], generated_at="now")


def test_text_from_sources_is_escaped(result):
    tampered = copy.deepcopy(result[0])
    tampered["comunas"][0]["findings"][0]["explanation"] = "<script>alert(1)</script>"
    page = render_report(tampered)
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_a_failed_run_renders_its_error():
    page = render_report({"run_id": "r1", "status": "error", "mode": "live", "trace_file": "logs/trace-r1.jsonl",
                          "error": {"code": "zetaris_unreachable", "message": "Zetaris unreachable (ConnectError)",
                                    "stage": "plan", "recoverable": True}})
    assert "This run could not complete" in page and "zetaris_unreachable" in page and "Trying again may succeed" in page
