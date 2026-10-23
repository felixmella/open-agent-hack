"""Retriever: Zetaris rows (all values arrive as strings) become provenance-stamped World Model observations."""
from app.adapters.zetaris import QueryResult
from app.agents.planner import Plan
from app.agents.retriever import Retriever
from app.engines.world_model import WorldModel
from app.tracing import Tracer

ROWS = {
    "official_population": [
        {"cut": "08105", "comuna": "HUALQUI", "source": "INE Censo 2024", "definition": "census", "reference_year": "2024", "population": "25795"},
        {"cut": "08105", "comuna": "HUALQUI", "source": "INE Censo 2017", "definition": "census", "reference_year": "2017", "population": "24333"},
    ],
    "wikidata_population": [
        {"wikidata_item": "http://www.wikidata.org/entity/Q1", "cut": "08105", "label_es": "Hualqui", "statement_id": "s1",
         "population": "24333", "point_in_time": "2020-01-01", "determination_method": None, "rank": "NormalRank",
         "reference_url": "https://www.ine.gob.cl/", "stated_in": None},
        {"wikidata_item": "http://www.wikidata.org/entity/Q1", "cut": "08105", "label_es": "Hualqui", "statement_id": "s1",
         "population": "24333", "point_in_time": "2020-01-01", "determination_method": None, "rank": "NormalRank",
         "reference_url": None, "stated_in": "2017 Chile census"},
        {"wikidata_item": "http://www.wikidata.org/entity/Q2", "cut": None, "label_es": "Las Cabras", "statement_id": None,
         "population": None, "point_in_time": None, "determination_method": None, "rank": None, "reference_url": None,
         "stated_in": None},
    ],
    "eswiki_infobox": [
        {"cut": "08105", "wikidata_item": "Q1", "title": "Hualqui", "revid": "1", "revision_timestamp": "2026-01-01T00:00:00Z",
         "wikitext": "{{Ficha}}", "value_raw": "26.746", "year_raw": "2024", "reference_raw": ""},
        {"cut": None, "wikidata_item": "Q2", "title": "Las Cabras (Chile)", "revid": "2", "revision_timestamp": "2026-01-01T00:00:00Z",
         "wikitext": "{{Ficha}}", "value_raw": "24&nbsp;640", "year_raw": "[[Censo chileno de 2017|2017]]", "reference_raw": "<ref/>"},
    ],
}


class FakeZetaris:
    def __init__(self):
        self.sql = []

    def query(self, sql, limit=100_000):
        self.sql.append(sql)
        rows = next(rows for view, rows in ROWS.items() if f"factsync.{view}" in sql)
        return QueryResult(sql, list(rows[0]), rows, len(rows), 5, 1)


def setup(tmp_path):
    world = WorldModel(strip_suffixes=[", Chile"])
    for cut, name in (("08105", "HUALQUI"), ("06107", "LAS CABRAS")):
        world.upsert_entity(type="comuna", name=name, external_key={"system": "cut", "id": cut}, source={"kind": "official"})
    plan = Plan(cuts=["08105", "06107"], comunas={"08105": "HUALQUI", "06107": "LAS CABRAS"},
                sources=["official_census", "wikidata", "wikipedia_es"], reason="test")
    zetaris = FakeZetaris()
    return world, plan, zetaris, Retriever(zetaris, world, Tracer("t", tmp_path, echo=False), "t")


def test_one_sql_statement_per_source_and_one_observation_per_claim(tmp_path):
    world, plan, zetaris, retriever = setup(tmp_path)
    totals = retriever.fetch(plan)
    assert len(zetaris.sql) == 3 and all("'08105', '06107'" in sql for sql in zetaris.sql)
    assert totals["official_census"]["appended"] == 2
    assert totals["wikidata"]["observations"] == 2          # one statement (two references) + one item with no population
    assert totals["wikipedia_es"]["observations"] == 4      # article + infobox claim, for both comunas


def test_wikidata_references_are_grouped_and_missing_values_kept(tmp_path):
    world, plan, _, retriever = setup(tmp_path)
    retriever.fetch(plan)
    hualqui = world.view("observations").for_entity("comuna:cut:08105", kinds={"wikidata"})
    assert len(hualqui) == 1
    assert hualqui[0]["payload"]["references"] == ["2017 Chile census", "https://www.ine.gob.cl/"]
    assert hualqui[0]["payload"]["stated_year"] == 2020
    cabras = world.view("observations").for_entity("comuna:cut:06107", kinds={"wikidata"})
    assert cabras[0]["payload"] == {"property": "population", "value": None, "missing": True}


def test_records_without_a_cut_are_matched_by_name_and_values_parsed(tmp_path):
    world, plan, _, retriever = setup(tmp_path)
    retriever.fetch(plan)
    claims = [o for o in world.view("observations").for_entity("comuna:cut:06107", kinds={"wikipedia"})
              if o["payload"].get("property") == "population"]
    assert claims[0]["payload"]["value"] == 24640 and claims[0]["payload"]["stated_year"] == 2017
    assert "Las Cabras (Chile)" in world.entity("comuna:cut:06107")["aliases"]


def test_a_second_identical_run_changes_nothing(tmp_path):
    world, plan, _, retriever = setup(tmp_path)
    retriever.fetch(plan)
    shape = world.state_shape_canonical()
    totals = retriever.fetch(plan)
    assert all(t["appended"] == 0 for t in totals.values())
    assert world.state_shape_canonical() == shape
