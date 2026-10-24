"""Extractor: turns each article read this run into structured, provenance-stamped population claims.

Code reads what it can read reliably: the reference behind the infobox figure (named references resolved), the
{{Historical populations}} table, an infobox population field SQL couldn't read (read again from the article's own
infobox: comments, two figures in one field, several parameters on one line, an empty field), and the sentences that
hold a figure and talk about population. The model reads those sentences: which ones state the whole comuna's
population, with which figure, year and basis. Code checks every claim before it is kept: the figure (and its year)
must appear verbatim in its sentence, and the sentence verbatim in the article. Sentences go to the model in batches
small enough for one streamed request; when the model is unavailable, or a request fails, sentence patterns read those
sentences instead, and the claims say so.
"""
import re

from app.agents.llm import batched, model_note
from app.knowledge import catalog as sources_catalog
from app.knowledge.taxonomy import census_facts, is_official_domain
from app.knowledge.wikitext import (FIGURE, POPULATION_WORDS, article_passages, citation_facts, field_figures,
                                    field_references, historical_populations, infobox_parameters, parse_population,
                                    parse_year, quote_supported, resolve_reference, rule_claims, sentences,
                                    visible_text)

PROMPT = """FactSync Chile - Extractor.
Below are numbered sentences from a Wikipedia article about a Chilean comuna (and its infobox population field, if
given). List each one that states the population of the whole comuna: the figure exactly as written, the year it
refers to (null if none is given), and the basis it gives: "census", "projection" (also for an estimate) or
"unspecified". Leave out figures for towns, villages, men, women, households, urban or rural areas. Never compute,
round or correct a figure. If a critic_instruction is given, follow it.
JSON: {"claims": [{"sentence": "1", "value_text": "24,333", "year": 2017, "basis": "census"}]}"""

BASES = {"census", "projection", "estimate", "unspecified"}
# The infobox parameters for the population figure, its year, its reference and the urban population, by language.
INFOBOX_FIELDS = {
    "es": {"value": ("población", "poblacion"), "year": ("población_año", "población año", "censo"),
           "reference": ("población_post",), "urban": ("población_urb",)},
    "en": {"value": ("population_total",), "year": ("population_as_of",), "reference": ("population_footnotes",),
           "urban": ("population_urban",)},
}
# eswiki's Ficha de entidad subnacional shows Wikidata's population (P1082) when `población` is empty: one
# statement of the highest rank ({{Propiedad|P1082|rango_mayor=sí|uno=sí}}). enwiki's Infobox settlement doesn't.
FILLED_FROM_WIKIDATA = {"es"}


def checkable_years(census_years):
    """Years whose figures can be checked: the censuses whose counts some catalog source holds (read yet or not),
    plus the withdrawn one."""
    return set(census_years) | {int(y) for y in census_facts()["discredited"]}


def verbatim_figure(value_text, quote):
    """The figure as the quote writes it: value_text itself, or the quote's figure with the same value."""
    if value_text and value_text in (quote or ""):
        return value_text
    wanted = parse_population(value_text)
    for token in FIGURE.findall(quote or ""):
        if wanted is not None and parse_population(token) == wanted:
            return token
    return None


def qid(item):
    return str(item or "").rstrip("/").rsplit("/", 1)[-1] or None


def shown_statement(statements):
    """The Wikidata statement an infobox shows when it takes the population from Wikidata: the only statement of
    the highest rank (preferred, else normal); None when there are several."""
    ranked = [s for s in statements if "Deprecated" not in (s["payload"].get("rank") or "")]
    top = [s for s in ranked if "Preferred" in (s["payload"].get("rank") or "")] or ranked
    return top[0] if len(top) == 1 else None


def describe_readings(readings):
    """The infobox readings in a few words, for the trace."""
    first = readings[0]
    if first.get("missing"):
        return "infobox shows no figure"
    if first.get("value_from") == "wikidata":
        return f"infobox shows Wikidata's {first['value']:,}" if first.get("value") is not None else \
            "infobox shows a figure from Wikidata"
    return "infobox field read by code: " + ", ".join(f"{r['value']:,}" for r in readings)


class Extractor:
    name = "Extractor"

    def __init__(self, world, tracer, llm, run_id, census_years=None):
        self.world = world
        self.tracer = tracer
        self.llm = llm
        self.run_id = run_id
        if census_years is None:  # the census years of the built-in catalog
            census_years = sources_catalog.census_years(sources_catalog.normalize(sources_catalog.BUILT_IN))
        self.census_years = census_years

    def extract(self, comuna, observed, *, round_no=0, instruction=None):
        """Read every article of this comuna read this run; returns the number of claims kept."""
        mine = [o for o in self.world.view("observations").for_entity(comuna.entity_id, kinds={"wikipedia"})
                if o["id"] in observed]
        articles = [o for o in mine if o["payload"].get("document") == "article"]
        wikidata = [o for o in self.world.view("observations").for_entity(comuna.entity_id, kinds={"wikidata"})
                    if o["id"] in observed]
        kept = 0
        for article in articles:
            infobox = next((o for o in mine if o["source"] == article["source"] and o["payload"].get("location") == "infobox"
                            and o["payload"].get("extracted_by") == "zetaris"), None)
            observations, summary = self._read(comuna, article, infobox, wikidata, round_no, instruction)
            result = self.world.ingest(observations, actor=self.name)
            observed.update(result.appended + result.unchanged)
            kept += sum(1 for o in observations if o.get("property") == "population")
            self.tracer.event(self.name, "extract_claims", input_summary=f"{article['source']['name']} '{article['source']['title']}' "
                              f"rev {article['source'].get('revid')}", output_summary=summary, target_agent="WorldModel",
                              round_no=round_no, engine="world_model",
                              status="success" if "rejected 0" in summary else "partial")
        return kept

    def _read(self, comuna, article, infobox, wikidata, round_no, instruction):
        source, wikitext = article["source"], article["payload"].get("wikitext") or ""
        entity = {"type": "comuna", "name": comuna.name, "external_key": {"system": "cut", "id": comuna.cut}}
        base = {"agent": self.name, "run_id": self.run_id, "article_observation": article["id"],
                "observed_at": article["provenance"].get("observed_at")}
        observations, readings = [], []
        if infobox:
            reference = resolve_reference(field_references(infobox["payload"].get("value_raw"),
                                                            infobox["payload"].get("reference_raw")), wikitext)
            facts = citation_facts(reference)
            observations.append({"entity": entity, "source": source, "provenance": {**base, "method": "rules"},
                                 "property": "population_citation", "location": "infobox",
                                 "reference_text": reference[:1500], "years": facts["years"], "domains": facts["domains"],
                                 "official": any(is_official_domain(d) for d in facts["domains"])})
            if infobox["payload"].get("value") is None:
                readings = self._infobox(entity, source, base, wikitext, infobox, wikidata)
                observations += readings
        rows = historical_populations(wikitext)
        years = checkable_years(self.census_years)
        table = [r for i, r in enumerate(rows) if r["year"] in years or i == len(rows) - 1]
        for row in table:
            observations.append({"entity": entity, "source": source, "provenance": {**base, "method": "rules"},
                                 "property": "population", "location": "history_table", "extracted_by": self.name,
                                 "method": "rules", "value": row["value"], "value_text": str(row["value"]),
                                 "stated_year": row["year"], "basis": "census", "quote": row["raw"], "verified": True})
        claims, rejected, candidates = self._prose(comuna, source, wikitext, None if readings else infobox, round_no,
                                                   instruction)
        methods = set()
        for claim in claims:
            note = claim.pop("note")
            methods.add(note["method"])
            observations.append({"entity": entity, "source": source, "provenance": {**base, **note},
                                 "property": "population", "extracted_by": self.name, "method": note["method"],
                                 **claim, "verified": True})
        methods = "+".join(sorted(methods)) or "none"
        summary = (f"{len(claims)} prose claim(s) kept ({methods}) from {candidates} candidate sentence(s), "
                   f"rejected {len(rejected)} by the quote check; {len(table)} history-table row(s); "
                   f"infobox reference: {', '.join(observations[0]['domains']) if infobox and observations[0]['domains'] else 'none found'}")
        if readings:
            summary += "; " + describe_readings(readings)
        if rejected:
            summary += "; rejected: " + "; ".join(f"{r.get('value_text')!r} ({r.get('why')})" for r in rejected[:3])
        return observations, summary

    def _infobox(self, entity, source, base, wikitext, infobox, wikidata):
        """The infobox population field read again from the article's own infobox, when SQL found it empty or
        couldn't parse it: one observation per figure in the field; or, when the field is empty, what the infobox
        shows instead (Wikidata's figure on eswiki, or nothing). [] when code can't read the field either: the
        model then gets it."""
        names = INFOBOX_FIELDS[source["language"]]
        params = infobox_parameters(wikitext)

        def field(key):
            return next(((n, params[n]) for n in names[key] if params.get(n)), (names[key][0], ""))

        (name, raw), (_, year_raw), (_, reference) = field("value"), field("year"), field("reference")
        reading = {"entity": entity, "source": source, "provenance": {**base, "method": "rules"},
                   "property": "population", "location": "infobox", "extracted_by": self.name, "method": "rules",
                   "field": name, "reference_raw": reference or None, "verified": True}
        if raw:
            return [{**reading, "value": value, "value_text": text, "value_raw": raw,
                     "stated_year": year or (parse_year(year_raw) if i == 0 else None),
                     "stated_year_raw": str(year) if year else (year_raw or None) if i == 0 else None}
                    for i, (value, text, year) in enumerate(field_figures(raw))]
        reading.update(value=None, stated_year_raw=year_raw or None, stated_year=parse_year(year_raw))
        urban_name, urban = field("urban")
        if parse_population(urban) is not None:
            reading.update(urban_field=urban_name, urban_value=parse_population(urban), quote=f"{urban_name} = {urban}")
        if source["language"] not in FILLED_FROM_WIKIDATA:
            return [{**reading, "missing": True}]
        reading["value_from"] = "wikidata"
        items = {qid(o["source"].get("item")) for o in wikidata}
        item = qid(infobox["payload"].get("wikidata_item")) or (next(iter(items)) if len(items) == 1 else None)
        mine = [o for o in wikidata if item and qid(o["source"].get("item")) == item]
        statements = [o for o in mine if o["payload"].get("value") is not None]
        if mine and not statements:  # Wikidata has no population either: the infobox shows none
            return [{**reading, "missing": True, "wikidata_item": item}]
        shown = shown_statement(statements)
        if not shown:  # Wikidata not read, or several statements of the same rank: which one shows can't be told
            return [{**reading, "wikidata_item": item, "statements": len(statements)}]
        year = shown["payload"].get("stated_year")
        return [{**reading, "provenance": {**reading["provenance"], "wikidata_observation": shown["id"]},
                 "value": shown["payload"]["value"], "wikidata_item": item,
                 "wikidata_statement": shown["source"].get("statement"),
                 "stated_year": reading["stated_year"] or year,
                 "stated_year_raw": reading["stated_year_raw"] or (str(year) if year else None)}]

    def _prose(self, comuna, source, wikitext, infobox, round_no, instruction):
        passages = article_passages(wikitext)
        candidates = candidate_sentences(passages)
        unread = infobox and infobox["payload"].get("value") is None and infobox["payload"].get("value_raw")
        if unread:
            field = " ".join(visible_text(f"{infobox['payload'].get('value_raw') or ''} "
                                          f"{infobox['payload'].get('stated_year_raw') or ''}").split())
            candidates["infobox"] = {"text": field, "location": "infobox"}
        if not candidates:
            return [], [], 0

        def payload(keys):
            body = {"comuna": comuna.name, "article": source["title"],
                    "sentences": {key: candidates[key]["text"] for key in keys}}
            if instruction:
                body["critic_instruction"] = instruction[:300]
            return body

        groups = batched(list(candidates), payload)
        raw_claims, failed = [], []
        for keys in groups:
            reply = self.llm.ask_json(
                self.name, "extract_claims", PROMPT, payload(keys), target_agent="WorldModel", round_no=round_no,
                validate=lambda d: None if isinstance(d.get("claims"), list) else "no 'claims' list",
            ) if self.llm else None
            if not reply:
                failed.append(keys)
                continue
            note = model_note(reply[1])
            for raw in reply[0]["claims"]:
                key = str(raw.get("sentence")) if isinstance(raw, dict) else None
                sentence = candidates[key] if key in keys else None
                raw_claims.append({**raw, "quote": sentence["text"], "location": sentence["location"], "note": note}
                                  if sentence else {"value_text": raw.get("value_text") if isinstance(raw, dict) else None,
                                                    "quote": None})
        rules = {"method": "rules"}
        if len(failed) == len(groups):  # no model reading at all: patterns over the whole article
            raw_claims = [{**c, "note": rules} for c in rule_claims(passages)]
        else:  # patterns over the sentences whose request failed
            raw_claims += [{**c, "note": rules} for keys in failed for c in rule_claims(
                [{"section": candidates[k]["location"], "text": candidates[k]["text"]}
                 for k in keys if candidates[k]["location"] != "infobox"])]
        kept, rejected, seen = [], [], set()
        for raw in raw_claims:
            year = raw.get("year")
            try:
                year = int(year) if year not in (None, "", "null") else None
            except (TypeError, ValueError):
                year = None
            quote = str(raw.get("quote") or "").strip()
            value_text = verbatim_figure(str(raw.get("value_text") or "").strip(), quote)
            value = parse_population(value_text) if value_text else None
            check = [candidates["infobox"]] if raw.get("location") == "infobox" else passages
            if value is None or not quote_supported(quote, check, value_text, year):
                rejected.append({"value_text": raw.get("value_text"),
                                 "why": "no sentence given" if not quote else "figure or year not verbatim in the sentence"
                                 if value is not None else "no clean figure"})
                continue
            key = (value, year, raw["location"])
            if key in seen:
                continue
            seen.add(key)
            basis = raw.get("basis") if raw.get("basis") in BASES else "unspecified"
            kept.append({"location": raw["location"], "value": value, "value_text": value_text, "stated_year": year,
                         "basis": basis, "quote": re.sub(r"\s+", " ", quote), "note": raw["note"]})
        return kept, rejected, len(candidates)


def candidate_sentences(passages):
    """Numbered sentences that hold a figure and talk about population: what the model labels."""
    candidates = {}
    for passage in passages:
        for sentence in sentences(passage["text"]):
            if FIGURE.search(sentence) and POPULATION_WORDS.search(sentence):
                candidates[str(len(candidates) + 1)] = {
                    "text": sentence, "location": "lead" if passage["section"] == "lead" else "body"}
    return candidates
