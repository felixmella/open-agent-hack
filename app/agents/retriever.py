"""Retriever: reads each planned source through its Zetaris view (one SQL statement per source per run) and
writes what it read into the World Model as provenance-stamped observations.

Records that lack a CUT (some Wikidata items and articles) are matched to comunas by name through the World Model
resolver; matches in the review band are reported, not merged.
"""
from collections import defaultdict

from app.adapters.zetaris import as_int, as_str, sql_list
from app.knowledge.wikitext import parse_population, parse_year
from app.tracing import utc_now

SOURCES = {
    "official_census": (
        "SELECT cut, comuna, source, definition, reference_year, population FROM factsync.official_population "
        "WHERE definition = 'census' AND cut IN ({cuts})"),
    "official_projections": (
        "SELECT cut, comuna, source, definition, reference_year, population FROM factsync.official_population "
        "WHERE definition = 'projection' AND cut IN ({cuts})"),
    "wikidata": (
        "SELECT wikidata_item, cut, label_es, statement_id, population, point_in_time, determination_method, rank, "
        "reference_url, stated_in FROM factsync.wikidata_population WHERE cut IN ({cuts}) OR cut IS NULL"),
    "wikipedia_es": (
        "SELECT cut, wikidata_item, title, revid, revision_timestamp, wikitext, value_raw, year_raw, reference_raw "
        "FROM factsync.eswiki_infobox WHERE cut IN ({cuts}) OR cut IS NULL"),
    "wikipedia_en": (
        "SELECT cut, wikidata_item, title, revid, revision_timestamp, wikitext, value_raw, year_raw, reference_raw "
        "FROM factsync.enwiki_infobox WHERE cut IN ({cuts}) OR cut IS NULL"),
}
VIEWS = {"official_census": "factsync.official_population", "official_projections": "factsync.official_population",
         "wikidata": "factsync.wikidata_population", "wikipedia_es": "factsync.eswiki_infobox",
         "wikipedia_en": "factsync.enwiki_infobox"}


def comuna_entity(cut, name):
    return {"type": "comuna", "name": name, "external_key": {"system": "cut", "id": cut}}


def observed(provenance, at):
    """Provenance with the time the content was observed (it doesn't change what was observed, so re-runs stay no-ops)."""
    return {**provenance, "observed_at": at or provenance["fetched_at"]}


class Retriever:
    name = "Retriever"

    def __init__(self, zetaris, world, tracer, run_id, observed=None):
        self.zetaris = zetaris
        self.world = world
        self.tracer = tracer
        self.run_id = run_id
        self.observed = set() if observed is None else observed  # ids of every observation this run read

    def fetch(self, plan, sources=None):
        totals = {}
        for source in sources or plan.sources:
            result = self.zetaris.query(SOURCES[source].format(cuts=sql_list(plan.cuts)))
            provenance = {"view": VIEWS[source], "sql": result.sql, "fetched_at": utc_now(), "run_id": self.run_id,
                          "agent": self.name}
            observations, matched, reviews = getattr(self, f"_{source.split('_')[0]}")(source, result.rows, plan, provenance)
            self.tracer.event(self.name, "query_zetaris", input_summary=f"{source} for {len(plan.cuts)} comunas",
                              output_summary=f"{len(result.rows)} rows -> {len(observations)} observations"
                                             + (f"; {matched} matched by name" if matched else ""),
                              target_agent="WorldModel", sql=result.sql, rows=len(result.rows),
                              latency_ms=result.elapsed_ms, retry_count=result.attempts - 1)
            ingest = self.world.ingest(observations, actor=self.name)
            self.observed.update(ingest.appended + ingest.unchanged)
            self.tracer.event(self.name, "ingest_world_model", input_summary=f"{len(observations)} {source} observations",
                              output_summary=f"appended {len(ingest.appended)}, unchanged {len(ingest.unchanged)}, "
                                             f"entities created {len(ingest.entities_created)}, "
                                             f"updated {len(ingest.entities_updated)}"
                                             + (f", merge reviews {len(ingest.reviews) + len(reviews)}" if ingest.reviews or reviews else ""),
                              target_agent="WorldModel", status="success" if not (ingest.reviews or reviews) else "partial",
                              engine="world_model")
            totals[source] = {"rows": len(result.rows), "observations": len(observations),
                              "appended": len(ingest.appended), "unchanged": len(ingest.unchanged),
                              "reviews": ingest.reviews + reviews}
        return totals

    def _match(self, cut, name, plan):
        """The plan comuna a record belongs to: by CUT, or by name when the record has none."""
        if cut:
            return (cut, False, None) if cut in plan.comunas else (None, False, None)
        if not name:
            return None, False, None
        resolution = self.world.resolver.resolve("comuna", name=name)
        if resolution.decision in ("exact", "auto-merge"):
            matched = resolution.entity_id.rsplit(":", 1)[1]
            return (matched, True, None) if matched in plan.comunas else (None, False, None)
        if resolution.decision == "review":
            return None, False, {"name": name, "candidate": resolution.matched_name, "similarity": resolution.similarity}
        return None, False, None

    def _official(self, source, rows, plan, provenance):
        observations = [{
            "entity": comuna_entity(r["cut"], plan.comunas[r["cut"]]),
            "source": {"kind": "official", "name": r["source"], "definition": r["definition"]},
            "provenance": observed(provenance, None),
            "property": "population", "value": as_int(r["population"]), "stated_year": as_int(r["reference_year"]),
            "definition": r["definition"],
        } for r in rows if r["cut"] in plan.comunas]
        return observations, 0, []

    def _wikidata(self, source, rows, plan, provenance):
        statements, items, matched, reviews = defaultdict(list), {}, 0, []
        for r in rows:
            cut, by_name, review = self._match(as_str(r["cut"]), as_str(r["label_es"]), plan)
            if review:
                reviews.append(review)
            if not cut:
                continue
            matched += by_name
            items[r["wikidata_item"]] = (cut, as_str(r["label_es"]) or plan.comunas[cut])
            if r["statement_id"]:
                statements[(r["wikidata_item"], r["statement_id"])].append(r)
        observations = []
        for (item, statement), refs in sorted(statements.items()):
            first = refs[0]
            observations.append({
                "entity": comuna_entity(*items[item]),
                "source": {"kind": "wikidata", "name": "Wikidata", "item": item, "statement": statement},
                "provenance": observed(provenance, None),
                "property": "population", "value": as_int(first["population"]),
                "stated_year": parse_year(first["point_in_time"]), "point_in_time": as_str(first["point_in_time"]),
                "determination_method": as_str(first["determination_method"]),
                "rank": as_str(first["rank"]),
                "references": sorted({as_str(r["reference_url"]) or as_str(r["stated_in"]) for r in refs} - {None}),
            })
        with_statements = {item for item, _ in statements}
        for item, (cut, label) in sorted(items.items()):
            if item not in with_statements:
                observations.append({
                    "entity": comuna_entity(cut, label),
                    "source": {"kind": "wikidata", "name": "Wikidata", "item": item},
                    "provenance": observed(provenance, None),
                    "property": "population", "value": None, "missing": True,
                })
        return observations, matched, reviews

    def _wikipedia(self, source, rows, plan, provenance):
        language = source.rsplit("_", 1)[1]
        observations, matched, reviews = [], 0, []
        for r in rows:
            cut, by_name, review = self._match(as_str(r["cut"]), as_str(r["title"]), plan)
            if review:
                reviews.append(review)
            if not cut:
                continue
            matched += by_name
            entity = comuna_entity(cut, as_str(r["title"]) or plan.comunas[cut])
            article = {"kind": "wikipedia", "name": f"Wikipedia {language.upper()}", "language": language,
                       "title": r["title"], "revid": as_str(r["revid"])}
            at_revision = observed(provenance, as_str(r["revision_timestamp"]))
            observations.append({"entity": entity, "source": article, "provenance": at_revision,
                                 "document": "article", "revision_timestamp": as_str(r["revision_timestamp"]),
                                 "wikitext": r["wikitext"] or ""})
            observations.append({"entity": entity, "source": article, "provenance": at_revision,
                                 "property": "population", "location": "infobox", "extracted_by": "zetaris",
                                 "value_raw": as_str(r["value_raw"]), "value": parse_population(r["value_raw"]),
                                 "stated_year_raw": as_str(r["year_raw"]), "stated_year": parse_year(r["year_raw"]),
                                 "reference_raw": as_str(r["reference_raw"])})
        return observations, matched, reviews
