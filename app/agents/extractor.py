"""Extractor: turns each article read this run into structured, provenance-stamped population claims.

Code reads what it can read reliably: the reference behind the infobox figure (named references resolved), the
{{Historical populations}} table, and the sentences that hold a figure and talk about population. The model reads
those sentences: which ones state the whole comuna's population, with which figure, year and basis. Code checks
every claim before it is kept: the figure (and its year) must appear verbatim in its sentence, and the sentence
verbatim in the article. When the model is unavailable, sentence patterns take
its place, and the claims say so.
"""
import re

from app.agents.llm import model_note
from app.knowledge.taxonomy import census_facts, is_official_domain
from app.knowledge.wikitext import (FIGURE, POPULATION_WORDS, article_passages, citation_facts, historical_populations,
                                    parse_population, quote_supported, resolve_reference, rule_claims, sentences,
                                    visible_text)

PROMPT = """FactSync Chile - Extractor.
Below are numbered sentences from a Wikipedia article about a Chilean comuna (and its infobox population field, if
given). List each one that states the population of the whole comuna: the figure exactly as written, the year it
refers to (null if none is given), and the basis it gives: "census", "projection" (also for an estimate) or
"unspecified". Leave out figures for towns, villages, men, women, households, urban or rural areas. Never compute,
round or correct a figure. If a critic_instruction is given, follow it.
JSON: {"claims": [{"sentence": "1", "value_text": "24,333", "year": 2017, "basis": "census"}]}"""

BASES = {"census", "projection", "estimate", "unspecified"}


def checkable_years():
    """Years whose figures can be checked: the censuses FactSync holds, plus the withdrawn one."""
    facts = census_facts()
    return set(facts["held_by_factsync"]) | {int(y) for y in facts["discredited"]}


def verbatim_figure(value_text, quote):
    """The figure as the quote writes it: value_text itself, or the quote's figure with the same value."""
    if value_text and value_text in (quote or ""):
        return value_text
    wanted = parse_population(value_text)
    for token in FIGURE.findall(quote or ""):
        if wanted is not None and parse_population(token) == wanted:
            return token
    return None


class Extractor:
    name = "Extractor"

    def __init__(self, world, tracer, llm, run_id):
        self.world = world
        self.tracer = tracer
        self.llm = llm
        self.run_id = run_id

    def extract(self, comuna, observed, *, round_no=0, instruction=None):
        """Read every article of this comuna read this run; returns the number of claims kept."""
        mine = [o for o in self.world.view("observations").for_entity(comuna.entity_id, kinds={"wikipedia"})
                if o["id"] in observed]
        articles = [o for o in mine if o["payload"].get("document") == "article"]
        kept = 0
        for article in articles:
            infobox = next((o for o in mine if o["source"] == article["source"] and o["payload"].get("location") == "infobox"
                            and o["payload"].get("extracted_by") == "zetaris"), None)
            observations, summary = self._read(comuna, article, infobox, round_no, instruction)
            result = self.world.ingest(observations, actor=self.name)
            observed.update(result.appended + result.unchanged)
            kept += sum(1 for o in observations if o.get("property") == "population")
            self.tracer.event(self.name, "extract_claims", input_summary=f"{article['source']['name']} '{article['source']['title']}' "
                              f"rev {article['source'].get('revid')}", output_summary=summary, target_agent="WorldModel",
                              round_no=round_no, engine="world_model",
                              status="success" if "rejected 0" in summary else "partial")
        return kept

    def _read(self, comuna, article, infobox, round_no, instruction):
        source, wikitext = article["source"], article["payload"].get("wikitext") or ""
        entity = {"type": "comuna", "name": comuna.name, "external_key": {"system": "cut", "id": comuna.cut}}
        base = {"agent": self.name, "run_id": self.run_id, "article_observation": article["id"],
                "observed_at": article["provenance"].get("observed_at")}
        observations = []
        if infobox:
            reference = resolve_reference(infobox["payload"].get("reference_raw"), wikitext)
            facts = citation_facts(reference)
            observations.append({"entity": entity, "source": source, "provenance": {**base, "method": "rules"},
                                 "property": "population_citation", "location": "infobox",
                                 "reference_text": reference[:1500], "years": facts["years"], "domains": facts["domains"],
                                 "official": any(is_official_domain(d) for d in facts["domains"])})
        rows = historical_populations(wikitext)
        table = [r for i, r in enumerate(rows) if r["year"] in checkable_years() or i == len(rows) - 1]
        for row in table:
            observations.append({"entity": entity, "source": source, "provenance": {**base, "method": "rules"},
                                 "property": "population", "location": "history_table", "extracted_by": self.name,
                                 "method": "rules", "value": row["value"], "value_text": str(row["value"]),
                                 "stated_year": row["year"], "basis": "census", "quote": row["raw"], "verified": True})
        claims, note, rejected, candidates = self._prose(comuna, source, wikitext, infobox, round_no, instruction)
        for claim in claims:
            observations.append({"entity": entity, "source": source, "provenance": {**base, **note},
                                 "property": "population", "extracted_by": self.name, "method": note["method"],
                                 **claim, "verified": True})
        summary = (f"{len(claims)} prose claim(s) kept ({note['method']}) from {candidates} candidate sentence(s), "
                   f"rejected {len(rejected)} by the quote check; {len(table)} history-table row(s); "
                   f"infobox reference: {', '.join(observations[0]['domains']) if infobox and observations[0]['domains'] else 'none found'}")
        if rejected:
            summary += "; rejected: " + "; ".join(f"{r.get('value_text')!r} ({r.get('why')})" for r in rejected[:3])
        return observations, summary

    def _prose(self, comuna, source, wikitext, infobox, round_no, instruction):
        passages = article_passages(wikitext)
        candidates = candidate_sentences(passages)
        unread = infobox and infobox["payload"].get("value") is None and infobox["payload"].get("value_raw")
        if unread:
            field = " ".join(visible_text(f"{infobox['payload'].get('value_raw') or ''} "
                                          f"{infobox['payload'].get('stated_year_raw') or ''}").split())
            candidates["infobox"] = {"text": field, "location": "infobox"}
        if not candidates:
            return [], {"method": "rules"}, [], 0
        payload = {"comuna": comuna.name, "article": source["title"],
                   "sentences": {key: c["text"] for key, c in candidates.items()}}
        if instruction:
            payload["critic_instruction"] = instruction
        reply = self.llm.ask_json(
            self.name, "extract_claims", PROMPT, payload, target_agent="WorldModel", round_no=round_no,
            validate=lambda d: None if isinstance(d.get("claims"), list) else "no 'claims' list",
        ) if self.llm else None
        if reply:
            note, raw_claims = model_note(reply[1]), []
            for raw in reply[0]["claims"]:
                sentence = candidates.get(str(raw.get("sentence"))) if isinstance(raw, dict) else None
                raw_claims.append({**raw, "quote": sentence["text"], "location": sentence["location"]} if sentence
                                  else {"value_text": raw.get("value_text") if isinstance(raw, dict) else None,
                                        "quote": None})
        else:
            note, raw_claims = {"method": "rules"}, rule_claims(passages)
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
                         "basis": basis, "quote": re.sub(r"\s+", " ", quote)})
        return kept, note, rejected, len(candidates)


def candidate_sentences(passages):
    """Numbered sentences that hold a figure and talk about population: what the model labels."""
    candidates = {}
    for passage in passages:
        for sentence in sentences(passage["text"]):
            if FIGURE.search(sentence) and POPULATION_WORDS.search(sentence):
                candidates[str(len(candidates) + 1)] = {
                    "text": sentence, "location": "lead" if passage["section"] == "lead" else "body"}
    return candidates
