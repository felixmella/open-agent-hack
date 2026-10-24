"""Planner: turns the run's scope into a plan of comunas and sources.

It reads the source catalog from Zetaris (factsync.source_catalog: every source the agents can read, its definition
and the years it covers), registers every comuna from INE's census list as a World Model entity (keyed by CUT),
resolves the scope (codes, a region, or names) against that list, and plans the catalog's default sources.

Discovery: when the Critic sends back figures that nothing read so far explains or checks, each with the unread
sources whose coverage could (its candidates), the Planner chooses which to read now. The model makes the choice and
justifies it; without one, code picks by each figure's cues (a census year it names, a non-census year, a figure
below the comuna's total). A source the Planner turns down isn't offered again in that run.
"""
from dataclasses import dataclass, field

from app.adapters.zetaris import ZetarisError, as_str
from app.agents.llm import fits, model_note
from app.engines.world_model import normalize_name
from app.knowledge import catalog as sources_catalog
from app.knowledge.taxonomy import census_status

DISCOVERY_PROMPT = """FactSync Chile - Planner.
The Critic sent back population figures for Chilean comunas that the official figures read so far can't explain or
check. Each figure lists its candidates: the unread sources whose coverage (definition and years) could. Choose the
sources to read now, at most {limit}, from sources_available. Decide from each figure's label, year and size and each
source's coverage: you can't know a source's figures before it is read, so never rule one out by guessing them.
Choose none only if no candidate fits any figure.
JSON: {{"sources": [{{"source": "<source id>", "reason": "<one sentence: which figures it could explain, and why>"}}]}}"""


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
    catalog: dict = field(default_factory=lambda: sources_catalog.normalize(sources_catalog.BUILT_IN))


def fit(source, figure):
    """How well a source's coverage fits a figure's cues, lower first: a census of the very year the figure names,
    projections for a figure that names a year no census was held in or calls itself an estimate, and a part of the
    comuna (urban or rural) for a figure below the comuna's total."""
    year, basis = figure.get("year"), figure.get("basis")
    if source["definition"] == "projection":
        return 0 if basis == "projection" or (year and census_status(year) != "valid") else 1
    if source["scope"] == "comuna":
        return 0 if year == source["years_from"] == source["years_to"] else 2
    return 1


class Planner:
    name = "Planner"

    def __init__(self, zetaris, world, tracer, llm=None):
        self.zetaris = zetaris
        self.world = world
        self.tracer = tracer
        self.llm = llm

    def read_catalog(self):
        """The source catalog, from Zetaris; the built-in copy when the view can't be read (traced)."""
        sql = f"SELECT {', '.join(sources_catalog.COLUMNS)} FROM factsync.source_catalog"
        try:
            result = self.zetaris.query(sql)
            catalog = sources_catalog.normalize(result.rows)
            if not any(row["kind"] == "official" and row["in_default_plan"] for row in catalog.values()):
                raise ZetarisError("it lists no official source to read by default", code="catalog_unusable")
        except ZetarisError as exc:
            self.tracer.event(self.name, "read_catalog", status="fallback", sql=sql, rows=0,
                              output_summary=f"factsync.source_catalog unusable ({exc.code}: {str(exc)[:120]}); using "
                                             f"the built-in catalog of {len(sources_catalog.BUILT_IN)} sources")
            return sources_catalog.normalize(sources_catalog.BUILT_IN)
        official = [s for s, row in catalog.items() if row["kind"] == "official"]
        self.tracer.event(self.name, "read_catalog", input_summary="factsync.source_catalog",
                          output_summary=f"{len(catalog)} sources, {len(official)} official: "
                                         + ", ".join(f"{s} ({sources_catalog.coverage(catalog[s])})" for s in official)
                                         + (f" (rows from the {result.origin})" if result.origin != "zetaris" else ""),
                          sql=result.sql, rows=len(result.rows), latency_ms=result.elapsed_ms, data_origin=result.origin)
        return catalog

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
        catalog = self.read_catalog()
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
        sources = sources_catalog.default_sources(catalog, run_input.languages)
        plan = Plan(cuts=cuts, comunas={c: comunas[c]["name"] for c in cuts}, sources=sources, reason=how,
                    unresolved=unresolved, reviews=reviews, catalog=catalog)
        status = "success" if not (unresolved or reviews) else "partial"
        self.tracer.event(self.name, "create_plan", input_summary=scope.model_dump_json(exclude_none=True),
                          output_summary=f"{how}; sources: {', '.join(sources)}; on demand: "
                                         + ", ".join(s for s, row in catalog.items() if row["kind"] == "official"
                                                     and s not in sources)
                                         + (f"; unresolved: {unresolved}" if unresolved else "")
                                         + (f"; needs review: {reviews}" if reviews else ""),
                          target_agent="Retriever", status=status)
        return plan

    def open_sources(self, plan, state):
        """Official sources the run could still read, with their catalog rows: not read yet, not declined, and the
        discovery cap not reached."""
        if len(state.discoveries) >= state.caps.max_discoveries:
            return {}
        return {s: row for s, row in plan.catalog.items()
                if row["kind"] == "official" and s not in plan.sources and s not in state.declined}

    def discover(self, plan, requests, state, round_no):
        """Discovery: choose which sources to read for the figures the Critic sent back, from the candidates each
        figure names. Returns the sources added: none when the Planner declines or nothing is left to add."""
        open_now = self.open_sources(plan, state)
        wanted = {s for r in requests for s in r["candidates"]}
        options = {s: row for s, row in open_now.items() if s in wanted}
        limit = state.caps.max_discoveries - len(state.discoveries)
        if not options or limit <= 0:
            self.tracer.event(self.name, "discover_source", round_no=round_no, status="skipped",
                              output_summary="no candidate source left to add (all read, declined or cap reached)")
            return []

        def payload(figures, described=True):
            body = {"figures": [{k: v for k, v in f.items() if v is not None} for f in figures],
                    "sources_read": {s: plan.catalog[s]["description"] for s in plan.sources} if described
                    else plan.sources,
                    "sources_available": {s: f"{row['description']} Coverage: {sources_catalog.coverage(row)}."
                                          for s, row in options.items()}}
            if len(figures) < len(requests):
                body["more_figures"] = len(requests) - len(figures)
            return body

        body = payload(requests)  # one decision for every figure: shrink the request until it can stream
        if not fits(body):
            body = payload(requests, described=False)
        while not fits(body) and len(body["figures"]) > 1:
            body = payload(requests[:len(body["figures"]) - 1], described=False)

        def valid(data):
            chosen = data.get("sources")
            if not isinstance(chosen, list):
                return "no 'sources' list"
            unknown = [c.get("source") if isinstance(c, dict) else c for c in chosen
                       if not isinstance(c, dict) or c.get("source") not in options]
            return f"unknown source(s) {unknown}" if unknown else None

        reply = self.llm.ask_json(self.name, "choose_sources", DISCOVERY_PROMPT.format(limit=limit), body,
                                  target_agent="Retriever", round_no=round_no, validate=valid) if self.llm else None
        if reply:
            note = model_note(reply[1])
            chosen = {}
            for item in reply[0]["sources"]:
                chosen.setdefault(item["source"], str(item.get("reason") or "")[:500])
            chosen = list(chosen.items())[:limit]
        else:
            note = {"method": "rules"}
            chosen = self.by_cues(requests, options, limit)
        if not chosen:
            reason = "the model chose no source: none of the candidates fits these figures"
            for option in options:
                state.declined[option] = reason
            self.tracer.event(self.name, "discover_source", round_no=round_no, status="declined",
                              input_summary=f"{len(requests)} figure(s); candidates: {', '.join(options)}",
                              output_summary=reason, decided_by=note)
            return []
        added = []
        for source, reason in chosen:
            served = [r for r in requests if source in r["candidates"]]
            plan.sources.append(source)
            state.discoveries.append({"round": round_no, "source": source, "reason": reason, "requests": served, **note})
            self.tracer.event(self.name, "discover_source", input_summary=f"{len(served)} of {len(requests)} figure(s): "
                              + "; ".join(f"{r['comuna']} {r['value']:,} ({r['shown_in']}, '{r['label']}')"
                                          for r in served[:4]),
                              output_summary=f"add {source}: {reason}", target_agent="Retriever", round_no=round_no,
                              decided_by=note)
            added.append(source)
        return added

    @staticmethod
    def by_cues(requests, options, limit):
        """The deterministic choice: for each figure, the candidate whose coverage best fits its cues (catalog order
        breaks ties); every source chosen once, at most `limit`."""
        order = list(options)
        chosen = {}
        for request in requests:
            candidates = [s for s in request["candidates"] if s in options]
            if not candidates:
                continue
            best = min(candidates, key=lambda s: (fit(options[s], request), order.index(s)))
            chosen.setdefault(best, [])
            chosen[best].append(request)
        picked = sorted(chosen, key=order.index)[:limit]
        return [(s, f"deterministic choice by coverage: fits {len(chosen[s])} figure(s), e.g. "
                    f"{chosen[s][0]['value']:,} ('{chosen[s][0]['label']}'), best of {', '.join(chosen[s][0]['candidates'])}")
                for s in picked]
