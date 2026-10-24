"""The source catalog: every source the agents can read, what it holds (a definition and a scope) and the years it
covers. It lives in Zetaris as factsync.source_catalog, where the Planner reads it at the start of each run; BUILT_IN
is the same table, used when that view can't be read.

Coverage drives discovery. A figure that matches no official figure read so far could be explained only by a source
that covers the year the figure states (any year, when it states none), and an urban or rural population only by a
figure below the comuna's total. The Critic names those sources (`could_explain`), the Planner chooses among them.
"""
from app.knowledge.taxonomy import census_facts

BUILT_IN = [
    {"source_id": "official_census", "view": "factsync.official_population", "kind": "official", "definition": "census",
     "scope": "comuna", "years_from": 2017, "years_to": 2024, "in_default_plan": True,
     "description": "INE census counts of each comuna, Census 2017 and Census 2024: the official headcount."},
    {"source_id": "official_projections", "view": "factsync.official_population", "kind": "official",
     "definition": "projection", "scope": "comuna", "years_from": 2002, "years_to": 2035, "in_default_plan": False,
     "description": "INE estimates and projections of each comuna for every year 2002 to 2035 (base Census 2017): "
                    "official figures, but modelled estimates, not a headcount."},
    {"source_id": "official_census2002", "view": "factsync.official_population", "kind": "official",
     "definition": "census", "scope": "comuna", "years_from": 2002, "years_to": 2002, "in_default_plan": False,
     "description": "INE Census 2002 count of each comuna, on current comuna boundaries (from the 2002 census "
                    "database)."},
    {"source_id": "official_census2017_area", "view": "factsync.official_population", "kind": "official",
     "definition": "census", "scope": "urban_rural", "years_from": 2017, "years_to": 2017, "in_default_plan": False,
     "description": "INE Census 2017 urban and rural population of each comuna: parts of a comuna, not its total."},
    {"source_id": "wikidata", "view": "factsync.wikidata_population", "kind": "commons", "definition": None,
     "scope": "comuna", "years_from": None, "years_to": None, "in_default_plan": True,
     "description": "Wikidata population statements of each comuna, with point in time, determination method, rank "
                    "and references."},
    {"source_id": "wikipedia_es", "view": "factsync.eswiki_infobox", "kind": "commons", "definition": None,
     "scope": "comuna", "years_from": None, "years_to": None, "in_default_plan": True,
     "description": "Spanish Wikipedia comuna articles: infobox figure, reference and article text."},
    {"source_id": "wikipedia_en", "view": "factsync.enwiki_infobox", "kind": "commons", "definition": None,
     "scope": "comuna", "years_from": None, "years_to": None, "in_default_plan": True,
     "description": "English Wikipedia comuna articles: infobox figure, reference and article text."},
]
WIKIPEDIA = {"es": "wikipedia_es", "en": "wikipedia_en"}
COLUMNS = ("source_id", "view", "kind", "definition", "scope", "years_from", "years_to", "in_default_plan", "description")


def _int(value):
    return None if value in (None, "") else int(value)


def normalize(rows):
    """{source_id: row} from catalog rows, with years as ints and in_default_plan as a bool (Zetaris returns
    every value as a string)."""
    return {row["source_id"]: {**{k: row.get(k) for k in COLUMNS}, "years_from": _int(row.get("years_from")),
                               "years_to": _int(row.get("years_to")),
                               "in_default_plan": str(row.get("in_default_plan")).lower() == "true"}
            for row in rows}


def default_sources(catalog, languages):
    """The sources a run reads from the start: the catalog's default sources, Wikipedia only in the languages asked."""
    asked = {WIKIPEDIA[language] for language in languages}
    return [s for s, row in catalog.items() if row["in_default_plan"] and (s not in WIKIPEDIA.values() or s in asked)]


def census_years(catalog):
    """The census years whose comuna counts some catalog source holds, read yet or not: the years a history-table
    row or a sentence can be checked against once its source is read."""
    valid = set(census_facts()["valid"])
    return {year for row in catalog.values() if row["kind"] == "official" and row["definition"] == "census"
            and row["scope"] == "comuna" for year in range(row["years_from"], row["years_to"] + 1) if year in valid}


def could_explain(source, claim, table):
    """Whether a source's coverage could explain or check this figure: the source covers the year the figure states
    (or the figure states none), and a source of urban or rural population only a figure below the comuna's total."""
    value, year = claim.get("value"), claim.get("stated_year")
    if source.get("kind") != "official" or value is None:
        return False
    if year is not None and not source["years_from"] <= year <= source["years_to"]:
        return False
    if source["scope"] != "comuna":
        totals = table.get("census") or {}
        total = totals.get(source["years_from"]) or (totals[max(totals)] if totals else None)
        return total is not None and value < total["value"]
    return True


def coverage(source):
    """A source's coverage in words: 'census, 2002', 'projection, 2002-2035', 'census urban_rural, 2017'."""
    years = str(source["years_from"]) if source["years_from"] == source["years_to"] else \
        f"{source['years_from']}-{source['years_to']}"
    scope = "" if source["scope"] == "comuna" else f" {source['scope']}"
    return f"{source['definition']}{scope}, {years}"
