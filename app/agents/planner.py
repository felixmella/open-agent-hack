"""Planner: turns the run's scope into a plan of comunas and sources.

It registers every comuna from INE's census list as a World Model entity (keyed by CUT), resolves the scope (codes,
a region, or names) against that list, and picks the sources to read. Population projections are not in the
default plan: they are added only when the Critic finds figures the sources read so far can't explain (discovery),
and the model chooses and justifies which source to add.
"""
from dataclasses import dataclass, field

from app.adapters.zetaris import as_str
from app.agents.llm import fits, model_note
from app.engines.world_model import normalize_name

DEFAULT_SOURCES = ["official_census", "wikidata"]
WIKIPEDIA_SOURCES = {"es": "wikipedia_es", "en": "wikipedia_en"}
CATALOG = {
    "official_census": "INE census counts by comuna: Census 2017 and Census 2024 (the official headcount).",
    "official_projections": "INE estimates and projections by comuna for every year 2002-2035 (base Census 2017): "
                            "official figures, but modelled estimates rather than a headcount.",
    "wikidata": "Wikidata population statements for each comuna, with point in time, method, rank and references.",
    "wikipedia_es": "Spanish Wikipedia comuna articles: infobox figure, reference and article text.",
    "wikipedia_en": "English Wikipedia comuna articles: infobox figure, reference and article text.",
}
OFFICIAL_SOURCES = ["official_census", "official_projections"]

DISCOVERY_PROMPT = """FactSync Chile - Planner.
The Critic found population figures for Chilean comunas that match no official figure in the sources read so far.
Choose the ONE additional source most likely to explain them, from the sources available, or null if none could.
JSON: {"source": "<source id or null>", "reason": "<one or two sentences: why this source could explain these figures>"}"""


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

    def __init__(self, zetaris, world, tracer, llm=None):
        self.zetaris = zetaris
        self.world = world
        self.tracer = tracer
        self.llm = llm

    def register_comunas(self):
        result = self.zetaris.query("SELECT cut, comuna, region FROM factsync.ine_census2024")
        comunas = {r["cut"]: {"name": as_str(r["comuna"]), "region": as_str(r["region"])} for r in result.rows}
        source = {"kind": "official", "name": "INE Censo 2024", "view": "factsync.ine_census2024"}
        for cut, info in sorted(comunas.items()):
            self.world.upsert_entity(type="comuna", name=info["name"], external_key={"system": "cut", "id": cut},
                                     attrs={"region": info["region"]}, source=source, actor=self.name)
        self.tracer.event(self.name, "register_comunas", input_summary="INE Census 2024 comuna list",
                          output_summary=f"{len(comunas)} comunas registered in the World Model (keyed by CUT)"
                                         + (f" (rows from the {result.origin})" if result.origin != "zetaris" else ""),
                          target_agent="WorldModel", sql=result.sql, rows=len(result.rows), latency_ms=result.elapsed_ms,
                          data_origin=result.origin)
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

    def open_sources(self, plan, state):
        """Official sources the run could still read: not read yet, not declined, and the discovery cap not reached."""
        if len(state.discoveries) >= state.caps.max_discoveries:
            return []
        return [s for s in OFFICIAL_SOURCES if s not in plan.sources and s not in state.declined]

    def discover(self, plan, requests, state, round_no):
        """Discovery: choose one more source to read for the figures the Critic says nothing read so far explains.
        Returns the source added, or None."""
        options = {s: CATALOG[s] for s in self.open_sources(plan, state)}
        if not options:
            self.tracer.event(self.name, "discover_source", round_no=round_no, status="skipped",
                              output_summary="no official source left to add (all read, declined or cap reached)")
            return None
        def payload(figures, described=True):
            body = {"unexplained_figures": figures,
                    "sources_read": {s: CATALOG[s] for s in plan.sources} if described else plan.sources,
                    "sources_available": options}
            if len(figures) < len(requests):
                body["more_unexplained_figures"] = len(requests) - len(figures)
            return body

        body = payload(requests)  # one decision for every figure: shrink the request until it can stream
        if not fits(body):
            body = payload(requests, described=False)
        while not fits(body) and len(body["unexplained_figures"]) > 1:
            body = payload(body["unexplained_figures"][:-1], described=False)
        reply = self.llm.ask_json(
            self.name, "choose_source", DISCOVERY_PROMPT, body, target_agent="Retriever", round_no=round_no,
            validate=lambda d: None if d.get("source") in (*options, None) else f"unknown source {d.get('source')!r}",
        ) if self.llm else None
        if reply:
            source, reason, note = reply[0].get("source"), str(reply[0].get("reason") or "")[:500], model_note(reply[1])
        else:
            source = next(iter(options))
            reason, note = "deterministic fallback: the official source not yet read", {"method": "rules"}
        if source is None:
            for option in options:
                state.declined[option] = reason
            self.tracer.event(self.name, "discover_source", round_no=round_no, status="declined",
                              input_summary=f"{len(requests)} unexplained figure(s)", output_summary=reason)
            return None
        plan.sources.append(source)
        state.discoveries.append({"round": round_no, "source": source, "reason": reason, "requests": requests, **note})
        self.tracer.event(self.name, "discover_source", input_summary=f"{len(requests)} unexplained figure(s): "
                          + "; ".join(f"{r['comuna']} {r['value']:,} ({r['source']})" for r in requests[:4]),
                          output_summary=f"add {source}: {reason}", target_agent="Retriever", round_no=round_no,
                          decided_by=note)
        return source
