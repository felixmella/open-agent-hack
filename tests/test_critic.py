"""The Critic's rubric on Hualqui's real figures: what it approves, what it sends back and to whom, and its draft
checks."""
from app.agents.analyst import Analyst
from app.agents.critic import Critic
from app.agents.editor import Editor
from app.agents.extractor import Extractor
from app.agents.llm import AgentLLM
from app.agents.planner import Planner
from app.agents.retriever import Retriever
from app.engines.world_model import WorldModel
from app.knowledge.catalog import BUILT_IN, normalize
from app.knowledge.matcher import official_table
from app.orchestration.state import ComunaState
from app.schemas import RunInput
from app.tracing import Tracer
from fakes import FakeLLM, FakeZetaris


def hualqui(tmp_path, sources, llm=None):
    world, tracer = WorldModel(strip_suffixes=[", Chile"]), Tracer("t", tmp_path, echo=False)
    plan = Planner(FakeZetaris(), world, tracer).plan(RunInput(scope={"cuts": ["08105"]}))
    observed, comuna = set(), ComunaState("08105", "HUALQUI")
    Retriever(FakeZetaris(), world, tracer, "t", observed).fetch(plan, sources)
    agent_llm = AgentLLM(llm, tracer, min_interval=0) if llm else None
    Extractor(world, tracer, agent_llm, "t").extract(comuna, observed)
    findings, _ = Analyst(world, tracer, agent_llm, "t").analyze(comuna, observed, 1, sources)
    return world, tracer, observed, comuna, findings, Critic(world, tracer, agent_llm, "t")


BASE = ["official_census", "wikidata", "wikipedia_es", "wikipedia_en"]


def unread(*sources):
    """Catalog rows of the official sources a run could still read."""
    catalog = normalize(BUILT_IN)
    return {s: catalog[s] for s in sources}


def test_unexplained_figures_go_to_the_planner_while_an_official_source_is_unread(tmp_path):
    world, _, observed, comuna, findings, critic = hualqui(tmp_path, BASE)
    review = critic.review(comuna, findings, observed, 1, unread("official_projections"))
    assert not review["approved"]
    fix = review["fix"]
    assert fix["target_agent"] == "Planner" and fix["check"] == "unread_official_source"
    assert sorted(f["value"] for f in fix["figures"]) == [20968, 26746]
    stuck = [review["results"][i] for i in fix["finding_ids"]]
    assert all(r["criteria"]["definition_discipline"] == 0 and not r["approved"] for r in stuck)
    # each finding's own instruction names its figure (a lone unexplained figure is sent back with this text)
    details = sorted(f["detail"] for r in stuck for f in r["failures"] if f["check"] == "unread_official_source")
    assert details[0].startswith("20,968 (Wikidata") and details[1].startswith("26,746 (Wikipedia ES")
    rejected = [a for a in world.view("observations").assessments("comuna:cut:08105", agent="Critic")
                if a["data"]["status"] == "rejected"]
    assert len(rejected) == 2 and any(a["data"]["fix"] for a in rejected)


def test_with_projections_read_every_code_verdict_passes(tmp_path):
    _, _, observed, comuna, findings, critic = hualqui(tmp_path, BASE + ["official_projections"])
    review = critic.review(comuna, findings, observed, 1, {})
    assert review["approved"], review["results"]
    spanish = next(f for f in findings if f["target"] == "es" and f["aspect"] == "value")
    assert spanish["class"] == "different_definition" and review["results"][spanish["id"]]["score"] == 9


def test_a_model_verdict_the_review_rejects_goes_back_to_the_analyst(tmp_path):
    def doubts_errors(payload):
        return {"reviews": [{"finding_id": f["finding_id"], "class_fits": f["class"] != "genuine_error",
                             "explanation_faithful": True, "note": "Nothing shows a typo; the figure's origin is unknown."}
                            for f in payload["findings"]]}
    _, _, observed, comuna, findings, critic = hualqui(tmp_path, BASE + ["official_projections"],
                                                       FakeLLM(Critic=doubts_errors))
    guessed = next(f for f in findings if f["method"] == "llm")
    assert guessed["class"] == "genuine_error" and guessed["claim"]["value"] == 20968
    review = critic.review(comuna, findings, observed, 1, {})
    assert review["fix"]["target_agent"] == "Analyst" and review["fix"]["check"] == "class_fit"
    assert review["results"][guessed["id"]]["criteria"]["definition_discipline"] == 0


def test_a_class_the_facts_rule_out_fails_whoever_made_it(tmp_path):
    _, _, observed, comuna, findings, critic = hualqui(tmp_path, BASE + ["official_projections"])
    statement = next(f for f in findings if f["claim"]["value"] == 20968 and f["aspect"] == "value")
    statement["class"] = "different_definition"
    review = critic.review(comuna, findings, observed, 1, {})
    result = review["results"][statement["id"]]
    assert not result["approved"] and result["failures"][0]["check"] == "class_allowed"
    assert result["failures"][0]["suggested_class"] == "cross_source_mismatch"


def test_invented_figures_in_an_explanation_cost_a_point(tmp_path):
    _, _, observed, comuna, findings, critic = hualqui(tmp_path, BASE + ["official_projections"])
    finding = next(f for f in findings if f["class"] == "outdated_vintage" and f["target"] == "en")
    finding["explanation"] += " About 31,000 people live there today."
    result = critic.review(comuna, findings, observed, 1, {})["results"][finding["id"]]
    assert result["score"] == 8 and result["failures"][0]["check"] == "explanation"


def test_drafts_are_checked_for_figure_source_and_wording(tmp_path):
    world, tracer, observed, comuna, findings, critic = hualqui(tmp_path, BASE + ["official_projections"])
    table = official_table([o for o in world.view("observations").for_entity(comuna.entity_id) if o["id"] in observed])
    drafts = Editor(world, tracer, None, "t").draft(comuna, findings, table, 1)
    evidence = [e for f in findings for e in f["evidence"]]
    assert "| población = 25.795" in drafts["eswiki"]["wikitext"]
    assert critic.review_draft(comuna, "eswiki", drafts["eswiki"], drafts["explanation"], evidence, table, 1)["approved"]
    assert critic.review_draft(comuna, "wikidata", drafts["wikidata"], drafts["explanation"], evidence, table, 1)["approved"]
    padded = {**drafts["eswiki"], "edit_summary": drafts["eswiki"]["edit_summary"] + " Unos 27.500 habitantes."}
    review = critic.review_draft(comuna, "eswiki", padded, drafts["explanation"], evidence, table, 1)
    assert not review["checks"]["figures_faithful"] and "27,500" in review["instruction"]
    wrong_source = {**drafts["eswiki"], "wikitext": drafts["eswiki"]["wikitext"].replace("censo2024.ine.gob.cl", "example.org")}
    assert not critic.review_draft(comuna, "eswiki", wrong_source, drafts["explanation"], evidence, table, 1)["approved"]
    # Spanish Wikipedia often groups thousands with a non-breaking space, and the Editor keeps the article's style
    spaced = {**drafts["eswiki"], "wikitext": drafts["eswiki"]["wikitext"].replace("25.795", "25&nbsp;795")}
    review = critic.review_draft(comuna, "eswiki", spaced, drafts["explanation"], evidence, table, 1)
    assert review["checks"]["figure"] and review["approved"]


def test_the_critics_model_sees_the_digit_comparison_behind_a_typo_verdict(tmp_path):
    llm, tracer = FakeLLM(), Tracer("t", tmp_path, echo=False)
    critic = Critic(WorldModel(), tracer, AgentLLM(llm, tracer, min_interval=0), "t")
    finding = {"id": "fnd_1", "class": "genuine_error", "method": "llm", "explanation": "25,413 is likely a typo.",
               "claim": {"source_name": "Wikipedia ES", "location": "body", "value": 25413, "value_raw": "25.413",
                         "label": "2017 census"},
               "evidence": [{"kind": "official", "source": "INE Censo 2017", "definition": "census", "year": 2017,
                             "value": 17413}],
               "digits": {"official": 17413, "year": 2017, "slip": 2}}
    table = {"census": {2017: {"value": 17413}, 2024: {"value": 18536}}, "projection": {}}
    critic.judge(ComunaState("09203", "CURACAUTÍN"), [finding], table, 1)
    [(_, payload)] = [call for call in llm.calls if call[0] == "Critic"]
    assert payload["findings"][0]["digit_check"] == \
        "25,413 and INE's Census 2017 count 17,413 differ in two neighbouring digits only"


def test_a_comuna_of_60_people_gets_its_draft_approved(tmp_path):
    critic = Critic(WorldModel(), Tracer("t", tmp_path, echo=False), None, "t")
    table = {"census": {2017: {"value": 138, "year": 2017, "obs_id": "a"}, 2024: {"value": 60, "year": 2024, "obs_id": "b"}},
             "projection": {}}
    draft = {"target": "eswiki", "correction": {"value": 60, "source_key": "census_2024"},
             "wikitext": "| población = 60\n| población_año = [[Censo chileno de 2024|2024]]\n| población_post = "
                         "<ref name=\"censo2024\">{{cita web |url=https://censo2024.ine.gob.cl/resultados/ "
                         "|fechaacceso=23 de octubre de 2026}}</ref>",
             "edit_summary": "Población según el Censo 2024 del INE: 60 hab. (antes 138: cifra de un censo anterior)."}
    evidence = [{"kind": "official", "value": 60, "year": 2024}, {"kind": "claim", "value": 138}]
    review = critic.review_draft(ComunaState("12202", "ANTÁRTICA"), "eswiki", draft, "Census 2024 counted 60.",
                                 evidence, table, 1)
    assert review["approved"] and review["checks"]["figure"] and review["checks"]["summary"]


def test_years_a_cited_reference_names_count_as_evidence():
    from app.agents.critic import allowed_figures, figures_in
    assert figures_in("1&nbsp;472 y 10 186 y 2.017") == {1472, 10186, 2017}
    citation = {"kind": "citation", "source": "ine.cl", "location": "infobox reference", "years": [2007]}
    assert 2007 in allowed_figures([citation]) and 2007 not in allowed_figures([])
