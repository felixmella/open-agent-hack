"""Discovery from the source catalog: which unread sources could explain a figure (coverage), how the Planner chooses
among them with and without a model, how the Critic holds up a comuna whose claims nothing read can check, and what
the matcher makes of the new official figures (Census 2002, Census 2017 urban and rural). Real values, October 2026."""
import dataclasses
import json

from app.adapters.zetaris import ZetarisError
from app.agents.llm import AgentLLM
from app.agents.planner import Planner
from app.config import load_settings
from app.engines.world_model import WorldModel
from app.knowledge.catalog import BUILT_IN, could_explain, normalize
from app.knowledge.matcher import allowed_classes, assess_value
from app.orchestration.loop import run
from app.orchestration.state import Caps, RunState
from app.schemas import RunInput
from app.tracing import Tracer
from fakes import FakeLLM, FakeZetaris

CATALOG = normalize(BUILT_IN)
PROJECTIONS, CENSUS_2002, AREA = (CATALOG[s] for s in ("official_projections", "official_census2002",
                                                       "official_census2017_area"))


def table(census, projections=None, urban=None, rural=None):
    def records(key, definition, figures, **extra):
        return {y: {"obs_id": f"{key}-{y}", "source": "INE", "definition": definition, "year": y, "value": v, **extra}
                for y, v in (figures or {}).items()}
    return {"census": records("census", "census", census), "projection": records("projection", "projection", projections),
            "urban": records("urban", "census", urban, scope="urban"),
            "rural": records("rural", "census", rural, scope="rural")}


def claim(value, year=None, basis=None, role="current", source="Wikidata", location="statement", label=None):
    return {"id": f"{source}-{location}-{value}", "source_name": source, "location": location, "role": role,
            "value": value, "stated_year": year, "basis": basis, "label": label or (str(year) if year else "no year")}


HUALQUI = table({2017: 24333, 2024: 25795})
CHIGUAYANTE = table({2017: 85938, 2024: 85822})


def test_coverage_decides_which_unread_sources_could_explain_a_figure():
    wikidata_2007 = claim(20968, 2007)                                    # Hualqui's Wikidata 20,968 (2007)
    assert [could_explain(s, wikidata_2007, HUALQUI) for s in (PROJECTIONS, CENSUS_2002, AREA)] == [True, False, False]
    census_2002 = claim(1539, 2002, "census", role="historical", source="Wikipedia EN", location="history_table")
    assert [could_explain(s, census_2002, HUALQUI) for s in (PROJECTIONS, CENSUS_2002, AREA)] == [True, True, False]
    undated = claim(85863)                                                # Chiguayante's Wikidata 85,863, no date
    assert [could_explain(s, undated, CHIGUAYANTE) for s in (PROJECTIONS, CENSUS_2002, AREA)] == [True, True, True]
    above_total = claim(86000)                                            # bigger than the comuna: not a part of it
    assert not could_explain(AREA, above_total, CHIGUAYANTE)


def test_an_urban_figure_is_a_different_definition_in_an_infobox_and_a_check_in_prose():
    chiguayante = table({2017: 85938, 2024: 85822}, {2017: 90068}, urban={2017: 85863}, rural={2017: 75})
    verdict = assess_value(claim(85863), chiguayante)
    assert verdict["class"] == "different_definition" and verdict["match"]["scope"] == "urban"
    assert verdict["explanation"].startswith("85,863 is the urban population of the comuna in INE's Census 2017, not "
                                             "its total (85,938).")
    assert verdict["proposal"]["value"] == 85822  # the update is still the Census 2024 count
    # eswiki Curepto: "El pueblo mismo de Curepto tiene 3 389 habitantes, según el censo de 2017": the town, rightly
    curepto = table({2017: 9448, 2024: 9519}, {2017: 9582}, urban={2017: 3389}, rural={2017: 6059})
    town = assess_value(claim(3389, 2017, "census", role="historical", source="Wikipedia ES", location="body"), curepto)
    assert town["check"] == "the comuna's urban population" and "not the whole comuna" in town["explanation"]


def test_census_years_count_as_held_once_their_counts_are_read():
    sentence = claim(16970, 2002, "census", role="historical", source="Wikipedia ES", location="body")
    assert assess_value(sentence, table({2017: 17413, 2024: 18536})) is None  # Curacautín, before Census 2002 is read
    read = table({2002: 16970, 2017: 17413, 2024: 18536})
    assert assess_value(sentence, read)["class"] == "consistent"
    typo = assess_value({**sentence, "value": 16907}, read)
    assert typo["class"] == "genuine_error" and typo["near"]["year"] == 2002


def test_a_different_definition_stays_a_possible_guess_only_while_a_source_could_still_show_it():
    projections_read = table({2017: 24333, 2024: 25795}, {2007: 22309, 2024: 26746})
    # the urban and rural split is unread, but it is a 2017 count: it can't be what a 2007 figure shows
    assert "different_definition" not in allowed_classes(claim(20968, 2007), projections_read)
    assert "different_definition" in allowed_classes(claim(20968, 2017), projections_read)


def plan_for(zetaris, tmp_path, llm=None):
    tracer = Tracer("t", tmp_path, echo=False)
    planner = Planner(zetaris, WorldModel(strip_suffixes=[", Chile"]), tracer, llm)
    plan = planner.plan(RunInput(scope={"cuts": ["08105", "11203"]}))
    state = RunState("t", Caps(), {})
    return planner, plan, state, tracer


REQUESTS = [  # Hualqui's two unexplained figures and Guaitecas's 2002 row, as the Critic sends them
    {"comuna": "HUALQUI", "value": 26746, "shown_in": "Wikipedia ES infobox", "label": "2024", "year": 2024,
     "basis": None, "candidates": ["official_projections"]},
    {"comuna": "HUALQUI", "value": 20968, "shown_in": "Wikidata statement", "label": "point in time 2007-01-01",
     "year": 2007, "basis": None, "candidates": ["official_projections"]},
    {"comuna": "GUAITECAS", "value": 1539, "shown_in": "Wikipedia EN history_table",
     "label": "2002 (Historical populations table)", "year": 2002, "basis": "census",
     "candidates": ["official_projections", "official_census2002"]},
]


def test_the_planner_reads_the_catalog_from_zetaris(tmp_path):
    zetaris = FakeZetaris()
    planner, plan, _, tracer = plan_for(zetaris, tmp_path)
    assert any("factsync.source_catalog" in sql for sql in zetaris.sql)
    assert plan.sources == ["official_census", "wikidata", "wikipedia_es", "wikipedia_en"]
    read = next(e for e in tracer.events if e["action"] == "read_catalog")
    assert read["status"] == "success" and "official_census2002 (census, 2002)" in read["output_summary"]


def test_without_the_catalog_view_the_planner_uses_its_own_copy(tmp_path):
    class NoCatalog(FakeZetaris):
        def query(self, sql, limit=100_000):
            if "source_catalog" in sql:
                raise ZetarisError("HTTP 400: Table or view not found", status=400, recoverable=False,
                                   code="zetaris_query_failed")
            return super().query(sql, limit)
    _, plan, _, tracer = plan_for(NoCatalog(), tmp_path)
    assert set(plan.catalog) == {row["source_id"] for row in BUILT_IN}
    assert next(e for e in tracer.events if e["action"] == "read_catalog")["status"] == "fallback"


def test_without_a_model_the_planner_chooses_by_each_figures_cues(tmp_path):
    planner, plan, state, tracer = plan_for(FakeZetaris(), tmp_path)
    added = planner.discover(plan, REQUESTS, state, 1)
    assert added == ["official_projections", "official_census2002"]  # a 2002 census row -> Census 2002, not projections
    assert [d["method"] for d in state.discoveries] == ["rules", "rules"]
    assert plan.sources[-2:] == added
    assert not planner.open_sources(plan, state).keys() & set(added)


def test_the_model_chooses_and_explains_or_declines_and_is_not_asked_again(tmp_path):
    tracer = Tracer("t", tmp_path, echo=False)
    llm = FakeLLM(Planner=lambda p: {"sources": [{"source": "official_census2002",
                                                  "reason": "Only the 2002 count can check a 2002 census row."}]})
    planner, plan, state, _ = plan_for(FakeZetaris(), tmp_path, AgentLLM(llm, tracer, min_interval=0))
    assert planner.discover(plan, REQUESTS, state, 1) == ["official_census2002"]
    (agent, payload), = llm.calls
    assert set(payload["sources_available"]) == {"official_projections", "official_census2002"}
    assert "Coverage: census, 2002." in payload["sources_available"]["official_census2002"]
    assert state.discoveries[0]["model_served"] == "fake/nemotron"

    declining = FakeLLM(Planner=lambda p: {"sources": []})
    planner, plan, state, _ = plan_for(FakeZetaris(), tmp_path, AgentLLM(declining, tracer, min_interval=0))
    assert planner.discover(plan, REQUESTS, state, 1) == []
    assert set(state.declined) == {"official_projections", "official_census2002"}
    assert planner.discover(plan, REQUESTS, state, 2) == [] and len(declining.calls) == 1


def test_a_claim_nothing_read_can_check_holds_up_approval_until_its_source_is_read(tmp_path):
    settings = dataclasses.replace(load_settings(sample_mode=False), logs_dir=tmp_path / "logs",
                                   state_dir=tmp_path / "state", output_dir=tmp_path / "output")
    result = run(RunInput.model_validate({"run_id": "guaitecas", "scope": {"cuts": ["11203"]},
                                          "options": {"use_llm": False}}),
                 settings, zetaris=FakeZetaris(), world=WorldModel(strip_suffixes=[", Chile"]), echo=False, llm_interval=0)
    guaitecas = result["comunas"][0]
    first = guaitecas["critic"]["history"][0]
    assert not first["approved"] and first["fix"]["check"] == "unchecked_claims"
    assert first["fix"]["figures"][0]["value"] == 1539 and "official_census2002" in first["fix"]["figures"][0]["candidates"]
    assert result["summary"]["discoveries"] == ["official_census2002"]
    row = next(c for c in guaitecas["checks"] if c["claim"].get("value") == 1539)
    assert row["result"] == "consistent" and "Census 2002" in row["note"]
    trace = [json.loads(line) for line in (tmp_path / "logs" / "trace-guaitecas.jsonl").read_text("utf-8").splitlines()]
    assert any(e["action"] == "query_zetaris" and "series = 'official_census2002'" in e.get("sql", "") for e in trace)
