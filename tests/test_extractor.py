"""Extractor: the model's claims are kept only when code finds the quote in the article and the figure in the quote;
references, history tables and the infobox fields SQL can't read are read by code."""
from app.adapters.zetaris import QueryResult
from app.agents.analyst import Analyst, build_claims
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
INFOBOX_SOURCES = ["official_census", "wikidata", "wikipedia_es"]


class OneComuna:
    """Zetaris answering for one comuna: its census counts, Wikidata statements and Spanish article (real values,
    articles cut down to the infobox)."""

    def __init__(self, cut, name, census, statements, wikitext, value_raw=None, year_raw=None, reference_raw=None):
        self.cut, self.name, self.census, self.statements = cut, name, census, statements
        self.article = {"cut": cut, "wikidata_item": "http://www.wikidata.org/entity/Q1", "title": name.title(),
                        "revid": "1", "revision_timestamp": "2026-10-01T00:00:00Z", "wikitext": wikitext,
                        "value_raw": value_raw, "year_raw": year_raw, "reference_raw": reference_raw}

    def query(self, sql, limit=100_000):
        if "factsync.ine_census2024" in sql:
            rows = [{"cut": self.cut, "comuna": self.name, "region": "R"}]
        elif "factsync.official_population" in sql:
            rows = [] if "'projection'" in sql else [
                {"cut": self.cut, "comuna": self.name, "source": f"INE Censo {year}", "definition": "census",
                 "reference_year": str(year), "population": str(value)} for year, value in self.census.items()]
        elif "factsync.wikidata_population" in sql:
            rows = [{"wikidata_item": "http://www.wikidata.org/entity/Q1", "cut": self.cut, "label_es": self.name,
                     "statement_id": f"s{i}" if value else None, "population": value, "point_in_time": time,
                     "determination_method": None, "rank": "NormalRank" if value else None, "reference_url": None,
                     "stated_in": None} for i, (value, time) in enumerate(self.statements or [(None, None)])]
        elif "factsync.eswiki_infobox" in sql:
            rows = [self.article]
        else:
            rows = []
        return QueryResult(sql, list(rows[0]) if rows else [], rows, len(rows), 3, 1)


def read_infobox(tmp_path, zetaris):
    world, tracer = WorldModel(strip_suffixes=[", Chile"]), Tracer("t", tmp_path, echo=False)
    plan = Planner(zetaris, world, tracer).plan(RunInput(scope={"cuts": [zetaris.cut]}))
    observed = set()
    Retriever(zetaris, world, tracer, "t", observed).fetch(plan, INFOBOX_SOURCES)
    comuna = ComunaState(zetaris.cut, zetaris.name)
    Extractor(world, tracer, None, "t").extract(comuna, observed)
    readings = [o for o in world.view("observations").for_entity(comuna.entity_id) if o["id"] in observed
                and o["provenance"].get("agent") == "Extractor" and o["payload"].get("location") == "infobox"
                and o["payload"].get("property") == "population"]
    return readings, world, tracer, comuna, observed


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


def test_an_empty_infobox_field_shows_wikidatas_figure(tmp_path):
    # eswiki Tierra Amarilla: no población value; the rendered infobox shows Wikidata's 14,019 (its Census 2017 count)
    zetaris = OneComuna("03103", "TIERRA AMARILLA", {2017: 14019, 2024: 11846}, [("14019", "2017-01-01T00:00:00Z")],
                        "{{Ficha de entidad subnacional\n| nombre = Tierra Amarilla\n| población_año = [[Censo chileno "
                        "de 2017|2017]]\n}}\n'''Tierra Amarilla''' es una comuna.",
                        year_raw="[[Censo chileno de 2017|2017]]")
    readings, world, tracer, comuna, observed = read_infobox(tmp_path, zetaris)
    [reading] = readings
    assert reading["payload"]["value"] == 14019 and reading["payload"]["value_from"] == "wikidata"
    assert reading["payload"]["stated_year"] == 2017 and reading["payload"]["method"] == "rules"
    statement = world.store.get_observation(reading["provenance"]["wikidata_observation"])
    assert statement["source"]["kind"] == "wikidata" and statement["payload"]["value"] == 14019
    assert reading["provenance"]["article_observation"]  # the article revision it was read from
    assert any("infobox shows Wikidata's 14,019" in e["output_summary"] for e in tracer.events
               if e["action"] == "extract_claims")
    findings, _ = Analyst(world, tracer, None, "t").analyze(comuna, observed, 1, INFOBOX_SOURCES)
    infobox = [f for f in findings if f["target"] == "es" and f["aspect"] == "value"]
    assert [f["class"] for f in infobox] == ["outdated_vintage"]
    assert infobox[0]["explanation"].startswith("The infobox has no figure of its own and shows Wikidata's: 14,019")
    assert not [f for f in findings if f["target"] == "es" and f["aspect"] == "sourcing"]


def test_a_parameter_sharing_its_line_is_read_by_code(tmp_path):
    # eswiki La Unión: '|altitud=26|población = 38036', which the view's regex misses (38,036 = Census 2017)
    zetaris = OneComuna("14201", "LA UNIÓN", {2017: 38036, 2024: 38907}, [("39447", "2017-01-01T00:00:00Z")],
                        "{{Ficha de entidad subnacional\n|unidad = [[Comuna de Chile|Comuna]]\n|altitud=26|población"
                        "          = 38036\n|población_año      = [[Censo chileno de 2017|2017]]\n}}",
                        year_raw="[[Censo chileno de 2017|2017]]")
    [reading], world, _, comuna, observed = read_infobox(tmp_path, zetaris)
    assert (reading["payload"]["value"], reading["payload"]["stated_year"]) == (38036, 2017)
    assert "value_from" not in reading["payload"]
    context = world.context(comuna.entity_id, intent="t", include=lambda o: o["id"] in observed)
    claims, _ = build_claims(context["observations"])
    infobox = [c for c in claims if c["target"] == "es" and c["location"] == "infobox"]
    assert [(c["value"], c["method"], c["label"]) for c in infobox] == [(38036, "rules", "2017")]  # SQL's is replaced


def test_two_figures_in_one_field_become_two_claims(tmp_path):
    # eswiki La Cruz: '22.098<br/>25.301 (2020)', the first for población_año (2017)
    field = "22.098<br/>25.301 (2020)"
    zetaris = OneComuna("05504", "LA CRUZ", {2017: 22098, 2024: 24939}, [("22098", "2017-01-01T00:00:00Z")],
                        f"{{{{Ficha de entidad subnacional\n| población = {field}\n| población_año = [[Censo chileno "
                        f"de 2017|2017]]\n}}}}", value_raw=field, year_raw="[[Censo chileno de 2017|2017]]")
    readings, *_ = read_infobox(tmp_path, zetaris)
    assert sorted((r["payload"]["value"], r["payload"]["stated_year"], r["payload"]["value_text"]) for r in readings) \
        == [(22098, 2017, "22.098"), (25301, 2020, "25.301 (2020)")]
    assert all(r["payload"]["value_raw"] == field for r in readings)  # the whole field, as the drafts replace it


def test_an_empty_field_with_nothing_in_wikidata_shows_no_figure(tmp_path):
    # eswiki Cabrero: población empty, población_urb = 21492, and no population statement in Wikidata
    zetaris = OneComuna("08303", "CABRERO", {2017: 28573, 2024: 31256}, None,
                        "{{Ficha de entidad subnacional\n| población = \n| población_año = 2017\n| población_urb = "
                        "21492\n| población_post = <ref name=\"INE12\">{{cita web |título=Resultados Censo 2017}}</ref>"
                        "\n}}", year_raw="2017", reference_raw='<ref name="INE12">{{cita web}}</ref>')
    [reading], world, tracer, comuna, observed = read_infobox(tmp_path, zetaris)
    assert reading["payload"]["missing"] and reading["payload"]["value"] is None
    assert (reading["payload"]["urban_field"], reading["payload"]["urban_value"]) == ("población_urb", 21492)
    findings, _ = Analyst(world, tracer, None, "t").analyze(comuna, observed, 1, INFOBOX_SOURCES)
    assert [f["class"] for f in findings if f["target"] == "es"] == ["missing_value"]


def test_a_locality_figure_in_the_text_does_not_contradict_the_infobox(tmp_path):
    # eswiki Canela: 203 people in one locality in 2017 is not the comuna's 2017 figure
    zetaris = OneComuna("04202", "CANELA", {2017: 9093, 2024: 9639}, [("9093", "2017-01-01T00:00:00Z")],
                        "{{Ficha de entidad subnacional\n| población = 9093\n| población_año = 2017\n}}\n"
                        "'''Canela''' es una comuna.\n\n== Demografía ==\nSegún el censo de 2017, la localidad de "
                        "Mincha Sur tenía una población de 203 habitantes.",
                        value_raw="9093", year_raw="2017")
    _, world, tracer, comuna, observed = read_infobox(tmp_path, zetaris)
    findings, checks = Analyst(world, tracer, None, "t").analyze(comuna, observed, 1, INFOBOX_SOURCES)
    assert [c["result"] for c in checks if c["claim"].get("value") == 203] == ["not the comuna's figure"]
    assert not [f for f in findings if f["aspect"] == "consistency"]
