"""Planner: turns the run's scope into a plan of comunas and sources.

It registers every comuna from INE's census list as a World Model entity (keyed by CUT), resolves the scope (codes,
a region, or names) against that list, and picks the sources to read. Population projections are not in the
default plan: they are added only when the Analyst finds a figure the censuses can't explain (discovery).
"""
from dataclasses import dataclass, field

from app.adapters.zetaris import as_str
from app.engines.world_model import normalize_name

DEFAULT_SOURCES = ["official_census", "wikidata"]
WIKIPEDIA_SOURCES = {"es": "wikipedia_es", "en": "wikipedia_en"}


class ScopeError(ValueError):
    pass


@dataclass
class Plan:
    cuts: list
    comunas: dict  # cut -> INE name
    sources: list
    reason: str
    unresolved: list = field(default_factory=list)
    reviews: list = field(default_factory=list)


class Planner:
    name = "Planner"

    def __init__(self, zetaris, world, tracer):
        self.zetaris = zetaris
        self.world = world
        self.tracer = tracer

    def register_comunas(self):
        result = self.zetaris.query("SELECT cut, comuna, region FROM factsync.ine_census2024")
        comunas = {r["cut"]: {"name": as_str(r["comuna"]), "region": as_str(r["region"])} for r in result.rows}
        source = {"kind": "official", "name": "INE Censo 2024", "view": "factsync.ine_census2024"}
        for cut, info in sorted(comunas.items()):
            self.world.upsert_entity(type="comuna", name=info["name"], external_key={"system": "cut", "id": cut},
                                     attrs={"region": info["region"]}, source=source, actor=self.name)
        self.tracer.event(self.name, "register_comunas", input_summary="INE Census 2024 comuna list",
                          output_summary=f"{len(comunas)} comunas registered in the World Model (keyed by CUT)",
                          target_agent="WorldModel", sql=result.sql, rows=len(result.rows), latency_ms=result.elapsed_ms)
        return comunas

    def plan(self, run_input):
        comunas = self.register_comunas()
        scope = run_input.scope
        unresolved, reviews = [], []
        if scope.cuts:
            cuts = [c for c in scope.cuts if c in comunas]
            unresolved = [c for c in scope.cuts if c not in comunas]
            how = f"{len(cuts)} comuna code(s) given"
        elif scope.region:
            wanted = normalize_name(scope.region)
            cuts = sorted(c for c, info in comunas.items() if wanted in normalize_name(info["region"] or ""))
            how = f"region '{scope.region}': {len(cuts)} comunas"
        else:
            cuts = []
            for name in scope.comunas:
                resolution = self.world.resolver.resolve("comuna", name=name)
                if resolution.decision in ("exact", "auto-merge"):
                    cuts.append(resolution.entity_id.rsplit(":", 1)[1])
                elif resolution.decision == "review":
                    reviews.append({"name": name, "candidate": resolution.matched_name, "similarity": resolution.similarity})
                else:
                    unresolved.append(name)
            how = f"{len(scope.comunas)} name(s) resolved to {len(cuts)} comunas"
        if not cuts:
            raise ScopeError(f"the scope matched no comuna ({how}; unresolved: {unresolved or reviews})")
        sources = DEFAULT_SOURCES + [WIKIPEDIA_SOURCES[lang] for lang in run_input.languages]
        plan = Plan(cuts=cuts, comunas={c: comunas[c]["name"] for c in cuts}, sources=sources, reason=how,
                    unresolved=unresolved, reviews=reviews)
        status = "success" if not (unresolved or reviews) else "partial"
        self.tracer.event(self.name, "create_plan", input_summary=scope.model_dump_json(exclude_none=True),
                          output_summary=f"{how}; sources: {', '.join(sources)}"
                                         + (f"; unresolved: {unresolved}" if unresolved else "")
                                         + (f"; needs review: {reviews}" if reviews else ""),
                          target_agent="Retriever", status=status)
        return plan
