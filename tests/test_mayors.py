"""The second fact, mayors, through the same loop: the Critic holds back a name no election read explains and sends
the Planner one election further back each round; a former mayor, a losing candidate and an unknown name each get
their class; a page whose mayor may have changed since the election is never called wrong; drafts cite SERVEL and
spell the winner as a page already does. Fakes serve SERVEL's real rows (tests/fakes_mayors.py)."""
import dataclasses
import json

import pytest

from app.config import load_settings
from app.engines.world_model import WorldModel
from app.knowledge import catalog, mayors
from app.orchestration.loop import run
from app.report.html import render_report
from app.schemas import RunInput
from fakes import FakeLLM
from fakes_mayors import MAYOR_HANDLERS, FakeMayorZetaris

MAYORS = {"run_id": "test-mayors", "fact": "mayor", "scope": {"cuts": ["06115", "05703", "16106", "07408"]}}


@pytest.fixture
def settings(tmp_path):
    return dataclasses.replace(load_settings(sample_mode=False), logs_dir=tmp_path / "logs",
                               state_dir=tmp_path / "state", output_dir=tmp_path / "output")


def go(settings, llm=None, world=None, **overrides):
    options = {"use_llm": llm is not None}
    run_input = RunInput.model_validate({**MAYORS, "options": options, **overrides})
    zetaris, world = FakeMayorZetaris(), world or WorldModel(strip_suffixes=[", Chile"])
    result = run(run_input, settings, zetaris=zetaris, llm_client=llm, world=world, echo=False, llm_interval=0)
    trace = [json.loads(line) for line in
             (settings.logs_dir / f"trace-{result['run_id']}.jsonl").read_text("utf-8").splitlines()]
    return result, trace, zetaris, world


def comuna(result, name):
    return next(c for c in result["comunas"] if c["name"] == name)


def page(entry, target):
    return next(f for f in entry["findings"] if f["target"] == target)


def test_the_critic_sends_the_planner_one_election_back_per_round(settings):
    result, trace, zetaris, _ = go(settings)
    assert result["fact"] == "mayor" and result["status"] == "success"
    assert result["summary"]["discoveries"] == ["servel_mayors_2021", "servel_mayors_2016", "servel_mayors_2012"]
    assert sum("year = 2021" in sql for sql in zetaris.sql) == 1  # each election read once, for every comuna
    first = next(e for e in trace if e["agent_name"] == "Critic" and e["action"] == "reject")
    assert first["round"] == 1 and first["target_agent"] == "Planner" and "SERVEL 2024" in first["fix"]["instruction"]

    rengo = page(comuna(result, "RENGO"), "en")  # its articles have no comuna code: matched by name
    assert rengo["class"] == "outdated_mayor" and rengo["status"] == "approved" and rengo["critic"]["score"] == 9
    assert "Carlos Ernesto Soto Gonzalez" in rengo["explanation"] and 2021 in rengo["match"]["won"]
    llay = page(comuna(result, "LLAILLAY"), "en")  # 'Mario Marillanca': elected in 2012, three elections back
    assert llay["class"] == "outdated_mayor" and llay["match"]["won"] == [2012]
    assert comuna(result, "LLAILLAY")["critic"]["rounds"] == 4
    pinto = comuna(result, "PINTO")
    assert page(pinto, "en")["class"] == "unknown_name" and page(pinto, "en")["status"] == "approved"
    assert any(c["claim"]["target"] == "es" and c["result"] == "consistent" for c in pinto["checks"])  # del Pino


def test_a_mayor_who_may_have_left_office_is_not_called_wrong(settings):
    result, _, _, _ = go(settings)
    yerbas = comuna(result, "YERBAS BUENAS")
    spanish = page(yerbas, "es")
    assert spanish["class"] == "not_elected" and spanish["proposal"]["check_first"]
    assert "Wikidata records the end of" in spanish["explanation"] and "2026-10-22" in spanish["explanation"]
    assert yerbas["drafts"]["eswiki"]["notes"][0].startswith("Check first")


def test_drafts_cite_servel_and_spell_the_winner_as_a_page_does(settings):
    result, _, _, _ = go(settings)
    rengo = comuna(result, "RENGO")
    draft = rengo["drafts"]["enwiki"]
    assert "| leader_name = Enrique Alfonso del Barrio Hernández<ref" in draft["wikitext"]  # the Spanish page's spelling
    assert mayors.official_source(2024)["url"] in draft["wikitext"] and draft["status"] == "approved"
    assert any("they don't say who holds the office today" in n for n in draft["notes"])
    assert draft["correction"]["person"] == "ENRIQUE DEL BARRIO HERNANDEZ" and draft["correction"]["spelled_from"] == "page"
    assert "| leader_name = Jairo del Pino Lema<ref" in comuna(result, "PINTO")["drafts"]["enwiki"]["wikitext"]


def test_the_model_decides_who_a_name_is_and_code_derives_the_class(settings):
    llm = FakeLLM(**MAYOR_HANDLERS)
    result, trace, _, _ = go(settings, llm)
    asked = [p for agent, p in llm.calls if agent == "Analyst"]
    assert asked and all("candidates" in c for p in asked for c in p["claims"])
    pinto = page(comuna(result, "PINTO"), "en")
    assert pinto["class"] == "unknown_name" and pinto["method"] == "llm" and pinto["reading"] == "vandalism"
    assert pinto["model"]["model_served"] == "fake/nemotron"
    discovery = next(e for e in trace if e["action"] == "discover_source")
    assert discovery["decided_by"]["method"] == "llm" and "servel_mayors_2021" in discovery["output_summary"]
    assert result["summary"]["discoveries"][0] == "servel_mayors_2021"


def test_a_model_answer_naming_no_listed_candidate_is_ignored(settings):
    def invents(payload):
        return {"verdicts": [{"claim_id": c["claim_id"], "same_person_as": "p_someone_else", "explanation": "x",
                              "confidence": 0.9} for c in payload["claims"]]}
    result, _, _, _ = go(settings, FakeLLM(**{**MAYOR_HANDLERS, "Analyst": invents}))
    pinto = page(comuna(result, "PINTO"), "en")
    assert pinto["class"] == "unknown_name" and pinto["method"] == "matcher (model gave no usable verdict)"


def test_a_second_mayor_run_compares_with_the_first_and_leaves_population_alone(settings):
    world = WorldModel(strip_suffixes=[", Chile"])
    go(settings, world=world, run_id="mayors-first")
    result, _, _, _ = go(settings, world=world, run_id="mayors-second")
    since = comuna(result, "RENGO")["since_last_check"]
    assert since["previous_run"] == "mayors-first" and since["pages"]["enwiki"]["outcome"] == "unchanged"
    population = world.reproject("comuna:cut:06115")["projections"]["comuna_picture"]
    assert population["run_id"] is None  # mayor assessments never enter the population picture


def test_the_catalog_plans_each_fact_from_its_own_sources():
    built_in = catalog.normalize(catalog.BUILT_IN)
    assert catalog.default_sources(built_in, ["es", "en"]) == ["official_census", "wikidata", "wikipedia_es",
                                                                "wikipedia_en"]
    assert catalog.default_sources(built_in, ["en"], "mayor") == ["servel_mayors_2024", "wikidata_mayor",
                                                                  "wikipedia_en_mayor"]
    assert 2024 in catalog.census_years(built_in) and 2021 not in catalog.census_years(built_in)


def test_the_review_queue_speaks_of_mayors(settings):
    result, _, _, _ = go(settings)
    page_html = render_report(result, generated_at="2026-10-26 00:00 UTC")
    assert "mayors checked against SERVEL" in page_html and "SERVEL 2024 · elected" in page_html
    assert "Former mayor" in page_html and "Election results: SERVEL" in page_html


def test_a_draft_that_calls_the_page_wrong_is_sent_back(settings):
    def judges(payload):
        name = payload["elected"]["name"].title()
        return {"name": name, "es_summary": f"Corrige el nombre incorrecto: {name} (SERVEL).",
                "en_summary": f"Fix the wrong mayor: {name} (SERVEL).", "explanation": f"The page is wrong; {name}."}
    result, trace, _, _ = go(settings, FakeLLM(**{**MAYOR_HANDLERS, "Editor": judges}))
    review = next(e for e in trace if e["action"] == "review_draft" and e["status"] == "rejected")
    assert "caveat" in review["output_summary"]
    pinto = comuna(result, "PINTO")
    assert pinto["drafts"]["enwiki"]["status"] == "escalated" and pinto["critic"]["draft_reviews"][0]["enwiki"][
        "instruction"].endswith("say how it differs from SERVEL's results.")
