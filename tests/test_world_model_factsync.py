"""The World Model doing FactSync's jobs: comunas keyed by CUT, provenance-stamped claims from every source,
idempotent re-runs, name resolution for records without a CUT, and context payloads for the agents."""
import pytest

from app.engines.world_model import ProvenanceError, WorldModel

HUALQUI = {"type": "comuna", "name": "HUALQUI", "external_key": {"system": "cut", "id": "08105"}}


def official(value, year, definition):
    return {"entity": HUALQUI, "source": {"kind": "official", "name": f"INE {definition} {year}"},
            "provenance": {"view": "factsync.official_population", "fetched_at": "2026-10-23T03:00:00Z"},
            "property": "population", "value": value, "stated_year": year, "definition": definition}


def eswiki(value, year, revid):
    return {"entity": {"type": "comuna", "name": "Hualqui", "external_key": {"system": "cut", "id": "08105"}},
            "source": {"kind": "wikipedia", "name": "Wikipedia ES", "revid": revid},
            "provenance": {"view": "factsync.eswiki_infobox", "fetched_at": "2026-10-23T03:00:05Z"},
            "property": "population", "value": value, "stated_year": year, "location": "infobox"}


def test_claims_land_on_one_comuna_keyed_by_cut():
    world = WorldModel()
    result = world.ingest([official(25795, 2024, "census"), official(26746, 2024, "projection"), eswiki(26746, 2024, 1)])
    assert result.entities_created == ["comuna:cut:08105"]
    assert len(result.appended) == 3
    entity = world.entity("comuna:cut:08105")
    assert entity["name"] == "HUALQUI" and entity["aliases"] == ["Hualqui"]
    assert world.store.get_derived("comuna:cut:08105")["by_source_kind"] == {"official": 2, "wikipedia": 1}


def test_rerun_with_new_fetch_time_is_a_noop_but_a_new_revision_appends():
    world = WorldModel()
    world.ingest([eswiki(26746, 2024, 1)])
    refetched = eswiki(26746, 2024, 1)
    refetched["provenance"]["fetched_at"] = "2026-10-24T09:00:00Z"
    assert world.ingest([refetched]).changed is False
    assert world.ingest([eswiki(25795, 2024, 2)]).changed is True


def test_claims_without_provenance_are_rejected():
    claim = eswiki(26746, 2024, 1)
    claim.pop("source")
    with pytest.raises(ProvenanceError):
        WorldModel().ingest([claim])


def test_names_without_a_cut_resolve_by_similarity_with_disambiguators_stripped():
    world = WorldModel(strip_suffixes=[", Chile"])
    for cut, name in (("09116", "SAAVEDRA"), ("06107", "LAS CABRAS"), ("13111", "LA GRANJA")):
        world.upsert_entity(type="comuna", name=name, external_key={"system": "cut", "id": cut}, source={"kind": "official"})
    assert world.resolver.resolve("comuna", name="Saavedra (Chile)").entity_id == "comuna:cut:09116"
    assert world.resolver.resolve("comuna", name="Las Cabras, Chile").entity_id == "comuna:cut:06107"
    assert world.resolver.resolve("comuna", name="La Grana").decision in ("auto-merge", "review")
    assert world.resolver.resolve("comuna", name="Puerto Montt").decision == "new"


def test_context_payload_is_structured_and_reports_what_was_left_out():
    world = WorldModel()
    world.ingest([official(25795, 2024, "census"), eswiki(26746, 2024, 1)])
    obs = world.view("observations").for_entity("comuna:cut:08105", kinds={"wikipedia"})[0]
    world.assess(obs["id"], agent="Analyst", data={"class": "different_definition", "status": "proposed"})
    context = world.context("comuna:cut:08105", intent="analyze", budget_chars=10_000)
    assert context["entity"]["id"] == "comuna:cut:08105"
    assert context["trace"]["selected"] == 2 and context["trace"]["truncated"] is False
    assert context["assessments"][0]["data"]["class"] == "different_definition"
    small = world.context("comuna:cut:08105", intent="analyze", budget_chars=10)
    assert small["trace"]["selected"] == 1 and small["trace"]["truncated"] is True


def test_assessments_are_append_only_and_later_ones_supersede():
    world = WorldModel()
    world.ingest([eswiki(26746, 2024, 1)])
    obs_id = world.view("observations").for_entity("comuna:cut:08105")[0]["id"]
    world.assess(obs_id, agent="Analyst", data={"class": "genuine_error", "status": "proposed"}, round_no=1)
    world.assess(obs_id, agent="Analyst", data={"class": "different_definition", "status": "proposed"}, round_no=2)
    assert len(world.store.assessments(observation_id=obs_id)) == 2
    latest = world.view("observations").latest_assessments("comuna:cut:08105")[obs_id]
    assert latest["data"]["class"] == "different_definition"
    assert [e["action"] for e in world.audit()].count("assessment.add") == 2
