"""Extractor: the model's claims are kept only when code finds the quote in the article and the figure in the quote;
references and history tables are read by code."""
from app.agents.extractor import Extractor
from app.agents.llm import AgentLLM
from app.agents.planner import Planner
from app.agents.retriever import Retriever
from app.engines.world_model import WorldModel
from app.orchestration.state import ComunaState
from app.schemas import RunInput
from app.tracing import Tracer
from fakes import FakeLLM, FakeZetaris

SOURCES = ["official_census", "wikipedia_es", "wikipedia_en"]


def extract(tmp_path, cut, name, llm=None):
    world, tracer = WorldModel(strip_suffixes=[", Chile"]), Tracer("t", tmp_path, echo=False)
    plan = Planner(FakeZetaris(), world, tracer).plan(RunInput(scope={"cuts": [cut]}))
    observed = set()
    Retriever(FakeZetaris(), world, tracer, "t", observed).fetch(plan, SOURCES)
    comuna = ComunaState(cut, name)
    Extractor(world, tracer, AgentLLM(llm, tracer, min_interval=0) if llm else None, "t").extract(comuna, observed)
    extracted = [o for o in world.view("observations").for_entity(comuna.entity_id)
                 if o["id"] in observed and o["provenance"].get("agent") == "Extractor"]
    return extracted, tracer


def claims(observations, language):
    return [o["payload"] for o in observations if o["source"]["language"] == language
            and o["payload"]["property"] == "population"]


def test_only_claims_whose_figure_and_year_are_in_their_sentence_are_kept(tmp_path):
    def reads(payload):
        if "Censo" not in " ".join(payload["sentences"].values()):
            return {"claims": []}
        assert payload["sentences"] == {"1": "Según el Censo de 2024, su población es de aproximadamente 25.795 "
                                             "habitantes"}
        return {"claims": [
            {"sentence": "1", "value_text": "25795", "year": 2024, "basis": "census"},    # kept, as written: 25.795
            {"sentence": "1", "value_text": "26.746", "year": 2024, "basis": "projection"},  # not in the sentence
            {"sentence": "1", "value_text": "25.795", "year": 2017, "basis": "census"},   # year not in the sentence
            {"sentence": "7", "value_text": "25.795", "year": 2024, "basis": "census"}]}  # no such sentence
    extracted, tracer = extract(tmp_path, "08105", "HUALQUI", FakeLLM(Extractor=reads))
    kept = claims(extracted, "es")
    assert [(c["value"], c["value_text"], c["stated_year"], c["method"]) for c in kept] == [(25795, "25.795", 2024, "llm")]
    summary = next(e for e in tracer.events if e["action"] == "extract_claims" and "Hualqui" in e["input_summary"]
                   and "ES" in e["input_summary"])["output_summary"]
    assert "rejected 3 by the quote check" in summary


def test_without_a_model_sentence_patterns_read_the_prose(tmp_path):
    extracted, _ = extract(tmp_path, "11203", "GUAITECAS")
    assert sorted((c["value"], c["stated_year"], c["location"]) for c in claims(extracted, "es")) == \
        [(1598, 2024, "lead"), (1843, 2017, "body")]
    assert all(c["method"] == "rules" for c in claims(extracted, "es"))


def test_history_tables_and_named_references_are_read_by_code(tmp_path):
    extracted, _ = extract(tmp_path, "11203", "GUAITECAS")
    history = [(c["stated_year"], c["value"]) for c in claims(extracted, "en") if c["location"] == "history_table"]
    assert history == [(2017, 1843), (2024, 1598)]
    citation = next(o["payload"] for o in extracted if o["source"]["language"] == "en"
                    and o["payload"]["property"] == "population_citation")
    assert citation["domains"] == ["ine.cl"] and citation["official"] and citation["years"] == []


def test_locality_figures_are_not_comuna_claims(tmp_path):
    extracted, _ = extract(tmp_path, "16201", "QUIRIHUE")
    assert 7952 not in {c["value"] for c in claims(extracted, "es")}
