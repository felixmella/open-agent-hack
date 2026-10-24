"""The World Model holds each comuna's picture: projections rebuilt from the log (never edited), rebuilt as of an
earlier point to compare runs ("since your last check"), and a count of the capabilities a run used."""
import copy
import dataclasses

from app.config import load_settings
from app.engines.world_model import WorldModel
from app.orchestration.loop import run
from app.schemas import RunInput
from fakes import FakeZetaris

HUALQUI = {"type": "comuna", "name": "HUALQUI", "external_key": {"system": "cut", "id": "08105"}}


def claim(value, revid):
    return {"entity": HUALQUI, "source": {"kind": "wikipedia", "name": "Wikipedia ES", "revid": revid},
            "property": "population", "value": value, "location": "infobox"}


def verdicts(observations, assessments):
    """A projection: the latest verdict on each claim, and how many assessments there are."""
    latest = {a["observation_id"]: a["data"]["class"] for a in assessments}
    return {"verdicts": {str(o["payload"]["value"]): latest.get(o["id"]) for o in observations},
            "assessments": len(assessments)}


def test_projections_are_rebuilt_from_the_log_never_edited():
    world = WorldModel()
    world.register_projection("verdicts", verdicts)
    world.ingest([claim(26746, 1)])
    obs = world.view("observations").for_entity("comuna:cut:08105")[0]["id"]
    world.assess(obs, agent="Analyst", run_id="r1", data={"class": "genuine_error"})
    world.assess(obs, agent="Analyst", run_id="r1", data={"class": "different_definition"})
    first = world.reproject("comuna:cut:08105")["projections"]["verdicts"]
    assert first == {"verdicts": {"26746": "different_definition"}, "assessments": 2}  # the later assessment wins
    assert world.reproject("comuna:cut:08105")["projections"]["verdicts"] == first  # deterministic
    assert [e["action"] for e in world.audit()].count("derived.rebuild") == 2


def test_the_picture_an_earlier_run_left_can_be_rebuilt_from_the_log():
    world = WorldModel()
    world.register_projection("verdicts", verdicts)
    world.ingest([claim(26746, 1)])
    old = world.view("observations").for_entity("comuna:cut:08105")[0]["id"]
    world.assess(old, agent="Analyst", run_id="r1", data={"class": "different_definition"})
    after_r1 = world.reproject("comuna:cut:08105")["projections"]["verdicts"]
    world.ingest([claim(25795, 2)])  # a later revision of the article
    new = next(o["id"] for o in world.view("observations").for_entity("comuna:cut:08105") if o["id"] != old)
    world.assess(new, agent="Analyst", run_id="r2", data={"class": "consistent"})
    runs = world.runs("comuna:cut:08105")
    assert [r for r, _ in runs] == ["r1", "r2"] and runs[0][1] < runs[1][1]
    assert world.project_as_of("comuna:cut:08105", runs[0][1])["verdicts"] == after_r1
    later = world.project_as_of("comuna:cut:08105", runs[1][1])["verdicts"]["verdicts"]
    assert later == {"26746": "different_definition", "25795": "consistent"}


def test_a_world_reports_the_capabilities_it_used_and_the_dormant_ones():
    world = WorldModel()
    world.ingest([claim(26746, 1)])
    capabilities = world.capabilities()
    assert capabilities["live"]["ingest"] == 1 and "relate" in capabilities["dormant"]
    world.upsert_entity(type="team", name="A", source={"kind": "manual"})
    world.upsert_entity(type="team", name="B", source={"kind": "manual"})
    a, b = (e["id"] for e in world.entities("team"))
    world.relate(from_id=a, type="plays", to_id=b, valid_from="2026-01-01T00:00:00Z", source={"kind": "manual"})
    assert world.capabilities()["live"]["relate"] == 1


class Edited(FakeZetaris):
    """Hualqui's Spanish article after an editor applied FactSync's draft: Census 2024's count, cited to INE."""

    def query(self, sql, limit=100_000):
        result = super().query(sql, limit)
        if "factsync.eswiki_infobox" in sql:
            rows = copy.deepcopy(result.rows)
            for row in rows:
                if row["cut"] == "08105":
                    row.update(revid="175999999", value_raw="25.795", year_raw="[[Censo chileno de 2024|2024]]",
                               reference_raw='<ref name="censo2024">{{cita web |url=https://censo2024.ine.gob.cl/'
                                             'resultados/ |título=Resultados Censo 2024}}</ref>',
                               wikitext=row["wikitext"].replace("| población = 26.746\n| población_año = 2024",
                                                                "| población = 25.795\n| población_año = 2024"))
            result = dataclasses.replace(result, rows=rows)
        return result


def test_an_edit_applied_since_the_last_check_reads_as_fixed(tmp_path):
    settings = dataclasses.replace(load_settings(sample_mode=False), logs_dir=tmp_path / "logs",
                                   state_dir=tmp_path / "state", output_dir=tmp_path / "output")
    world = WorldModel(strip_suffixes=[", Chile"])

    def check(run_id, zetaris):
        run_input = RunInput.model_validate({"run_id": run_id, "scope": {"cuts": ["08105"]},
                                             "options": {"use_llm": False}})
        result = run(run_input, settings, zetaris=zetaris, world=world, echo=False, llm_interval=0)
        return result["comunas"][0], result

    first, result = check("before-the-edit", FakeZetaris())
    assert first["since_last_check"] is None and result["summary"]["since_last_check"]["comunas_checked_before"] == 0
    assert first["picture"]["pages"]["eswiki"]["verdict"] == "different_definition"
    dormant = result["world_model"]["capabilities"]["dormant"]
    assert {"relate", "view:graph", "project_as_of"} <= set(dormant)  # a first check has nothing to compare

    second, result = check("after-the-edit", Edited())
    since = second["since_last_check"]
    assert since["previous_run"] == "before-the-edit"
    spanish = since["pages"]["eswiki"]
    assert spanish["outcome"] == "fixed" and (spanish["before"]["value"], spanish["now"]["value"]) == (26746, 25795)
    assert spanish["now"]["verdict"] == "consistent"
    assert since["pages"]["enwiki"]["outcome"] == "unchanged"
    assert result["summary"]["since_last_check"]["fixed"] == 1
    assert result["world_model"]["capabilities"]["live"]["project_as_of"] == 1
    assert result["status"] == "success"  # the review queue rendered
    page = (tmp_path / result["report_file"]).read_text(encoding="utf-8")
    assert "Since the last check" in page and "26,746 (2024) → 25,795" in page and "fixed since the last check" in page
    assert "eswiki" not in second["drafts"]  # nothing left to correct on that page
