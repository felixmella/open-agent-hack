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


def test_unexplained_figures_go_to_the_planner_while_an_official_source_is_unread(tmp_path):
    world, _, observed, comuna, findings, critic = hualqui(tmp_path, BASE)
    review = critic.review(comuna, findings, observed, 1, ["official_projections"])
    assert not review["approved"]
    fix = review["fix"]
    assert fix["target_agent"] == "Planner" and fix["check"] == "unread_official_source"
    assert sorted(f["value"] for f in fix["figures"]) == [20968, 26746]
    stuck = [review["results"][i] for i in fix["finding_ids"]]
    assert all(r["criteria"]["definition_discipline"] == 0 and not r["approved"] for r in stuck)
    rejected = [a for a in world.view("observations").assessments("comuna:cut:08105", agent="Critic")
                if a["data"]["status"] == "rejected"]
    assert len(rejected) == 2 and any(a["data"]["fix"] for a in rejected)


def test_with_projections_read_every_code_verdict_passes(tmp_path):
    _, _, observed, comuna, findings, critic = hualqui(tmp_path, BASE + ["official_projections"])
    review = critic.review(comuna, findings, observed, 1, [])
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
    review = critic.review(comuna, findings, observed, 1, [])
    assert review["fix"]["target_agent"] == "Analyst" and review["fix"]["check"] == "class_fit"
    assert review["results"][guessed["id"]]["criteria"]["definition_discipline"] == 0


def test_a_class_the_facts_rule_out_fails_whoever_made_it(tmp_path):
    _, _, observed, comuna, findings, critic = hualqui(tmp_path, BASE + ["official_projections"])
    statement = next(f for f in findings if f["claim"]["value"] == 20968 and f["aspect"] == "value")
    statement["class"] = "different_definition"
    review = critic.review(comuna, findings, observed, 1, [])
    result = review["results"][statement["id"]]
    assert not result["approved"] and result["failures"][0]["check"] == "class_allowed"
    assert result["failures"][0]["suggested_class"] == "cross_source_mismatch"


def test_invented_figures_in_an_explanation_cost_a_point(tmp_path):
    _, _, observed, comuna, findings, critic = hualqui(tmp_path, BASE + ["official_projections"])
    finding = next(f for f in findings if f["class"] == "outdated_vintage" and f["target"] == "en")
    finding["explanation"] += " About 31,000 people live there today."
    result = critic.review(comuna, findings, observed, 1, [])["results"][finding["id"]]
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
