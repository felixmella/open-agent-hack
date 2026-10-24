"""Test doubles: a Zetaris that serves real rows recorded on Oct 23-24, 2026 (Hualqui, Guaitecas, Quirihue; article
text cut down to the passages that matter) and the source catalog, and a model that answers per agent from scripted
handlers."""
import itertools
import json
import re

from app.adapters.meterless import LLMError, LLMResult
from app.adapters.zetaris import QueryResult
from app.knowledge.catalog import BUILT_IN, COLUMNS
from app.knowledge.wikitext import rule_claims

COMUNAS = [("08105", "HUALQUI", "REGIÓN DEL BIOBÍO"), ("11203", "GUAITECAS", "REGIÓN DE AYSÉN"),
           ("16201", "QUIRIHUE", "REGIÓN DE ÑUBLE")]
CENSUS = {"08105": {2017: 24333, 2024: 25795}, "11203": {2017: 1843, 2024: 1598}, "16201": {2017: 11594, 2024: 11746}}
PROJECTIONS = {"08105": {2007: 22309, 2017: 25552, 2020: 26201, 2024: 26746},
               "11203": {2017: 1575, 2020: 1599, 2024: 1611}, "16201": {2017: 12076, 2020: 12192, 2024: 12241}}
CENSUS_2002 = {"08105": 18768, "11203": 1539, "16201": 11429}                       # INE REDATAM, today's boundaries
AREA_2017 = {"08105": (20889, 3444), "11203": (1705, 138), "16201": (9473, 2121)}  # urban, rural
INE_REF = ('<ref name="INE">{{Cite web |url= http://www.ine.cl/canales/chile_estadistico/censos_poblacion_vivienda/'
           'censo_pobl_vivi.php |title= National Statistics Institute |accessdate=13 December 2010}}</ref>')
WIKIDATA = [
    ("Q13079", "08105", "Hualqui", "s-hualqui-2020", "24333", "2020-01-01"),
    ("Q13079", "08105", "Hualqui", "s-hualqui-2007", "20968", "2007-01-01"),
    ("Q13069", "11203", "Guaitecas", None, None, None),
    ("Q56115", "16201", "Quirihue", None, None, None),
]
ESWIKI = [
    ("08105", "Q13079", "Hualqui", "175069356", "26.746", "2024", "",
     "{{Ficha de entidad subnacional\n| nombre = Hualqui\n| población = 26.746\n| población_año = 2024\n"
     "| población_post =\n}}\n'''Hualqui''' es una comuna de la provincia de Concepción.\n\n== Demografía ==\n"
     "[[Archivo:Hualqui.png|miniaturadeimagen|Panorámica]]\nSegún el [[Censo chileno de 2024|Censo de 2024]], su "
     "población es de aproximadamente\n&nbsp;25.795 habitantes.<ref>{{Cita web|url=https://www.bcn.cl/siit/"
     "reportescomunales/reporpdf.html?anno=2025&idcom=8105|título=Reportes}}</ref>Conservando características rurales."),
    ("11203", "Q13069", "Guaitecas", "175824791", "1843", "2017", "",
     "{{Ficha de entidad subnacional\n| población = 1843\n| población_año = 2017\n}}\n'''Guaitecas''' es una comuna. "
     "Según el [[Censo chileno de 2024|censo de 2024]], tiene una población de 1&nbsp;598 habitantes.<ref>{{Cita web|"
     "url=https://www.bcn.cl/siit/reportescomunales/comunas_v.html?anno=2025&idcom=11203|título=Guaitecas}}</ref>\n\n"
     "== Demografía ==\nSegún el [[Censo chileno de 2017|censo de 2017]] la comuna tiene una población de 1843 "
     "habitantes (1166 hombres y 677 mujeres)."),
    ("16201", "Q56115", "Quirihue", "175813057", "11.594", "[[Censo chileno de 2017|2017]]",
     "<ref name=censo17>[http://www.censo2017.cl/descargue-aqui-resultados-de-comunas/]</ref>",
     "{{Ficha de entidad subnacional\n| población = 11.594\n}}\n'''Quirihue''' es una comuna.\n\n== Demografía ==\n"
     "La comuna de Quirihue, según datos preliminares del censo abreviado de 2017, tiene una población de 11 594 "
     "habitantes, de los cuales 5 852 eran hombres.\n\n== Localidades ==\n* '''Quirihue''', 7952 habitantes."),
]
ENWIKI = [
    ("08105", "Q13079", "Hualqui", "1376112018", "24333", "2017 Census", '<ref name="INE"/>',
     "{{Infobox settlement\n| population_footnotes = <ref name=\"INE\"/>\n| population_total = 24333\n"
     "| population_as_of = 2017 Census\n}}\n'''Hualqui''' is a Chilean commune. It had a population of 24,333 "
     f"inhabitants according to the 2017 census.{INE_REF}"),
    ("11203", "Q13069", "Guaitecas", "1375958518", "1473", "2012 Census", '<ref name="INE"/>',
     "{{Infobox settlement\n| population_footnotes = <ref name=\"INE\"/>\n| population_total = 1473\n"
     f"| population_as_of = 2012 Census\n}}}}\n'''Guaitecas''' is a commune.{INE_REF}\n\n==Demographics==\n"
     "{{Historical populations\n|align=left\n|source={{cite web|url=https://www.ine.gob.cl/|title=Censo}}\n"
     "|percentages=pagr\n|1992 |1283\n|2002 |1539\n|2017 |1843\n|2024 |1598\n}}"),
    ("16201", "Q56115", "Quirihue", "1376581405", "11746", "2017 Census", '<ref name="CP"/>',
     "{{Infobox settlement\n| population_footnotes = <ref name=\"CP\"/>\n| population_total = 11746\n"
     "| population_as_of = 2017 Census\n}}\n'''Quirihue''' is a city. As per 2017 census, it had a population of "
     "11,746 inhabitants.\n\n==Geography==\nQuirihue is in Itata Province.<ref name=\"CP\">{{cite web|url=https://"
     "www.citypopulation.de/en/chile/mun/admin/itata/16201__quirihue/|title=Quirihue|access-date=1 April 2026}}</ref>"),
]


def official_rows(series, cut):
    """(source, definition, scope, year, value) for one comuna in one series of factsync.official_population."""
    if series == "official_census":
        return [(f"INE Censo {year}", "census", "comuna", year, value) for year, value in sorted(CENSUS[cut].items())]
    if series == "official_projections":
        return [("INE Proyecciones base 2017", "projection", "comuna", year, value)
                for year, value in sorted(PROJECTIONS[cut].items())]
    if series == "official_census2002":
        return [("INE Censo 2002", "census", "comuna", 2002, CENSUS_2002[cut])]
    if series == "official_census2017_area":
        urban, rural = AREA_2017[cut]
        return [("INE Censo 2017", "census", "urban", 2017, urban), ("INE Censo 2017", "census", "rural", 2017, rural)]
    raise AssertionError(f"unexpected series {series}")


def wikipedia_rows(rows):
    return [{"cut": cut, "wikidata_item": item, "title": title, "revid": revid,
             "revision_timestamp": "2026-10-01T00:00:00Z", "wikitext": text, "value_raw": value, "year_raw": year,
             "reference_raw": ref} for cut, item, title, revid, value, year, ref, text in rows]


class FakeZetaris:
    """Serves the views by name, honouring the CUT list and the census/projection filter, and records the SQL."""

    def __init__(self, cuts=None):
        self.cuts = set(cuts or CENSUS)
        self.sql = []

    def query(self, sql, limit=100_000):
        self.sql.append(sql)
        wanted = set(re.findall(r"'(\d{5})'", sql)) or self.cuts
        if "factsync.source_catalog" in sql:
            rows = [{c: None if row[c] is None else str(row[c]).lower() if isinstance(row[c], bool) else str(row[c])
                     for c in COLUMNS} for row in BUILT_IN]
        elif "factsync.ine_census2024" in sql:
            rows = [{"cut": c, "comuna": n, "region": r} for c, n, r in COMUNAS]
        elif "factsync.official_population" in sql:
            series = re.search(r"series = '(\w+)'", sql).group(1)
            rows = [{"cut": cut, "comuna": name, "source": source, "definition": definition, "scope": scope,
                     "reference_year": str(year), "population": str(value)}
                    for cut, name, _ in COMUNAS if cut in wanted
                    for source, definition, scope, year, value in official_rows(series, cut)]
        elif "factsync.wikidata_population" in sql:
            rows = [{"wikidata_item": f"http://www.wikidata.org/entity/{item}", "cut": cut, "label_es": label,
                     "statement_id": statement, "population": value, "point_in_time": time,
                     "determination_method": None, "rank": "NormalRank" if statement else None, "reference_url": None,
                     "stated_in": None} for item, cut, label, statement, value, time in WIKIDATA if cut in wanted]
        elif "factsync.eswiki_infobox" in sql:
            rows = [r for r in wikipedia_rows(ESWIKI) if r["cut"] in wanted]
        elif "factsync.enwiki_infobox" in sql:
            rows = [r for r in wikipedia_rows(ENWIKI) if r["cut"] in wanted]
        else:
            raise AssertionError(f"unexpected SQL: {sql}")
        return QueryResult(sql, list(rows[0]) if rows else [], rows, len(rows), 3, 1)


def agent_of(messages):
    return re.match(r"FactSync Chile - (\w+)", messages[0]["content"]).group(1)


class FakeLLM:
    """A model that answers from per-agent handlers (payload -> reply dict), recording every call."""

    def __init__(self, **handlers):
        self.handlers = {**DEFAULTS, **handlers}
        self.calls = []
        self._ids = itertools.count(1)

    def chat(self, messages, **kwargs):
        agent = agent_of(messages)
        payload = json.loads(messages[1]["content"])
        self.calls.append((agent, payload))
        reply = self.handlers[agent](payload)
        return LLMResult(text=json.dumps(reply, ensure_ascii=False), model_requested="fake/nemotron",
                         model_served="fake/nemotron", routed_model="fake/nemotron",
                         receipt_id=f"rcpt_fake_{next(self._ids)}", latency_ms=1, attempts=1)


class BrokenLLM:
    def chat(self, messages, **kwargs):
        raise LLMError("Nightshift request failed after 2 attempts: APIConnectionError")


def extractor_reads_with_rules(payload):
    """Labels the numbered sentences the way the sentence patterns would."""
    return {"claims": [{"sentence": key, **{k: c[k] for k in ("value_text", "year", "basis")}}
                       for key, text in payload["sentences"].items()
                       for c in rule_claims([{"section": "body", "text": text}])]}


def analyst_guesses_error(payload):
    """A first guess that calls every unexplained figure an error, and follows the Critic when told."""
    verdicts = []
    for claim in payload["claims"]:
        if claim.get("critic_instruction"):
            cls = "cross_source_mismatch" if "cross_source_mismatch" in claim["critic_instruction"] else claim["candidates"][0]
        else:
            cls = "genuine_error"
        verdicts.append({"claim_id": claim["claim_id"], "class": cls,
                         "explanation": f"{claim['value']:,} matches no official census figure.", "confidence": 0.5})
    return {"verdicts": verdicts}


def critic_agrees(payload):
    return {"reviews": [{"finding_id": f["finding_id"], "class_fits": True, "explanation_faithful": True, "note": ""}
                        for f in payload["findings"]]}


def planner_adds_projections(payload):
    """Projections for the figures they could explain, and the source each other figure names first."""
    chosen = {"official_projections": "A 2024 figure that is no census count may be INE's projection for 2024."}
    for figure in payload["figures"]:
        if "official_projections" not in figure["candidates"]:
            chosen.setdefault(figure["candidates"][0], f"It could check {figure['value']:,} ('{figure['label']}').")
    return {"sources": [{"source": s, "reason": r} for s, r in chosen.items() if s in payload["sources_available"]]}


def editor_writes(payload):
    figure = payload["new_figure"]["value"]
    return {"es_summary": f"Población según el Censo 2024 del INE: {figure} habitantes.",
            "en_summary": f"Population per INE's 2024 census: {figure:,}.",
            "explanation": f"The Census 2024 count is {figure:,}; the drafts use it, cited to INE."}


DEFAULTS = {"Extractor": extractor_reads_with_rules, "Analyst": analyst_guesses_error, "Critic": critic_agrees,
            "Planner": planner_adds_projections, "Editor": editor_writes}
