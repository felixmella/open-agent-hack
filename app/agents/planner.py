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
from app.agents.llm import batched, model_note
from app.engines.world_model import normalize_name
from app.knowledge import catalog as sources_catalog
from app.knowledge import mayors
from app.knowledge.taxonomy import census_status

DISCOVERY_PROMPT = """FactSync Chile - Planner.
The Critic sent back population figures for Chilean comunas that the official figures read so far can't explain or
check. Each numbered figure lists its candidates: the unread sources whose coverage (definition and years) could.
"like_it" counts other figures with the same label, year and candidates. For EACH figure, choose the candidate that
fits it best, or null if none does. Decide from the figure's label, year and size and each source's coverage: you
can't know a source's figures before it is read, so never rule one out by guessing them.
JSON: {"choices": [{"figure": "1", "source": "<source id or null>", "reason": "<one short sentence>"}]}"""

MAYOR_DISCOVERY_PROMPT = """FactSync Chile - Planner.
The Critic sent back names that Wikipedia or Wikidata give as the mayor of a Chilean comuna and that SERVEL's election
results read so far can't explain: each matches no one elected, or no candidate at all, in the elections read. Each
numbered name lists its candidates: SERVEL elections not read yet. "like_it" counts other names with the same cues and
candidates; "year", when given, is a year the page itself points to (a reference's date, a term); a name without one
points to no year, so don't invent one. For EACH name, choose the election most likely to explain it (a former mayor
was most likely elected in the election before the latest one read, unless the page points to an earlier year), or
null if none could. You can't know an election's candidates before it is read, so never rule one out by guessing them.
JSON: {"choices": [{"figure": "1", "source": "<source id or null>", "reason": "<one short sentence>"}]}"""
PROMPTS = {"population": DISCOVERY_PROMPT, "mayor": MAYOR_DISCOVERY_PROMPT}


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
    fact: str = "population"


def fit(source, figure):
    """How well a source's coverage fits a figure's cues, lower first: a census of the very year the figure names,
    projections for a figure that names a year no census was held in or calls itself an estimate, and a part of the
    comuna (urban or rural) for a figure below the comuna's total."""
    year, basis = figure.get("year"), figure.get("basis")
    if source["definition"] == "projection":
        return 0 if basis == "projection" or (year and census_status(year) != "valid") else 1
    if source["scope"] == "comuna":
        return 0 if year == source["years_from"] == source["years_to"] else 2
    return 0 if basis == "census" else 1  # a census figure smaller than the comuna: likely a part of it


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
        fact = run_input.fact
        sources = sources_catalog.default_sources(catalog, run_input.languages, fact)
        if not any(catalog[s]["kind"] == "official" for s in sources):
            raise ScopeError(f"the source catalog lists no official {fact} source to read by default")
        plan = Plan(cuts=cuts, comunas={c: comunas[c]["name"] for c in cuts}, sources=sources, reason=how,
                    unresolved=unresolved, reviews=reviews, catalog=catalog, fact=fact)
        status = "success" if not (unresolved or reviews) else "partial"
        self.tracer.event(self.name, "create_plan", input_summary=scope.model_dump_json(exclude_none=True),
                          output_summary=f"{how}; fact: {fact}; sources: {', '.join(sources)}; on demand: "
                                         + ", ".join(s for s, row in sources_catalog.of_fact(catalog, fact).items()
                                                     if row["kind"] == "official" and s not in sources)
                                         + (f"; unresolved: {unresolved}" if unresolved else "")
                                         + (f"; needs review: {reviews}" if reviews else ""),
                          target_agent="Retriever", status=status)
        return plan

    def open_sources(self, plan, state):
        """Official sources the run could still read, with their catalog rows: not read yet, not declined, and the
        discovery cap not reached."""
        if len(state.discoveries) >= state.caps.max_discoveries:
            return {}
        return {s: row for s, row in sources_catalog.of_fact(plan.catalog, plan.fact).items()
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

        groups = {}  # figures with the same cues get one decision
        for request in requests:
            candidates = tuple(s for s in request["candidates"] if s in options)
            if candidates:
                groups.setdefault((request.get("year"), request.get("basis"), candidates), []).append(request)
        groups = list(groups.values())

        def entry(group):
            item = {k: group[0][k] for k in ("comuna", "value", "shown_in", "label", "year", "basis", "size")
                    if group[0].get(k) is not None}
            item["candidates"] = [s for s in group[0]["candidates"] if s in options]
            return {**item, "like_it": len(group) - 1} if len(group) > 1 else item

        def payload(batch):
            used = [s for s in options if any(s in entry(g)["candidates"] for g in batch)]
            return {"figures": {str(i): entry(g) for i, g in enumerate(batch, 1)},
                    "sources_read": {s: sources_catalog.coverage(plan.catalog[s]) for s in plan.sources
                                     if plan.catalog[s]["kind"] == "official"},
                    "sources_available": {s: f"{options[s]['description']} Coverage: "
                                             f"{sources_catalog.coverage(options[s])}." for s in used}}

        def valid(data):
            choices = data.get("choices")
            if not isinstance(choices, list) or not all(isinstance(c, dict) for c in choices):
                return "no 'choices' list"
            unknown = [c.get("source") for c in choices if c.get("source") not in (*options, None)]
            return f"unknown source(s) {unknown}" if unknown else None

        picks, notes = {}, {}  # source -> [(figure, why)] in the order chosen; source -> who chose it
        refusals, refused_by = [], None  # the model's reasons for choosing no source for a figure
        for batch in batched(groups, payload):  # requests small enough to stream (see app/agents/llm.py)
            reply = self.llm.ask_json(self.name, "choose_sources", PROMPTS[plan.fact], payload(batch),
                                      target_agent="Retriever", round_no=round_no, validate=valid) if self.llm else None
            if reply:
                for choice in reply[0]["choices"]:
                    number = str(choice.get("figure"))
                    why = str(choice.get("reason") or "")[:300]
                    if not choice.get("source"):
                        refusals.append(why)
                        refused_by = model_note(reply[1])
                    elif number.isdigit() and 1 <= int(number) <= len(batch):
                        picks.setdefault(choice["source"], []).extend((f, why) for f in batch[int(number) - 1])
                        notes.setdefault(choice["source"], model_note(reply[1]))
            else:
                for source, chosen in self.by_cues([f for g in batch for f in g], options, plan.fact).items():
                    picks.setdefault(source, []).extend(chosen)
                    notes.setdefault(source, {"method": "rules"})
        if not picks:
            reason = next((r for r in refusals if r.strip()), None) or "no candidate fits these figures"
            note = refused_by or {"method": "rules"}
            for option in options:
                state.declined[option] = reason
            state.declines.append({"round": round_no, "sources": list(options), "reason": reason, "requests": requests,
                                   **note})
            self.tracer.event(self.name, "discover_source", round_no=round_no, status="declined",
                              input_summary=f"{len(requests)} figure(s); candidates: {', '.join(options)}",
                              output_summary=f"declined {', '.join(options)}: {reason}", decided_by=note)
            return []
        order = list(options)
        added = []
        for source in sorted(picks, key=lambda s: (-len(picks[s]), order.index(s)))[:limit]:
            served = [figure for figure, _ in picks[source]]
            note = notes[source]
            if note["method"] == "llm":  # the model's reason for its first figure, and how many it chose this for
                reasons = list(dict.fromkeys(why.strip() for _, why in picks[source] if why and why.strip()))
                reason = (reasons[0] if reasons else "chosen by the model") + \
                    (f" (chosen for {len(served)} figures)" if len(served) > 1 else "")
            else:
                reason = (f"by coverage ({sources_catalog.coverage(options[source])}), the best fit for {len(served)} "
                          f"figure(s), e.g. {mayors.shown(served[0]['value'])} ('{served[0]['label']}')")
            plan.sources.append(source)
            state.discoveries.append({"round": round_no, "source": source, "reason": reason, "requests": served, **note})
            self.tracer.event(self.name, "discover_source", input_summary=f"chosen for {len(served)} of {len(requests)} "
                              f"figure(s): " + "; ".join(f"{r['comuna']} {mayors.shown(r['value'])} ({r['shown_in']}, '{r['label']}')"
                                                         for r in served[:4]),
                              output_summary=f"add {source}: {reason}", target_agent="Retriever", round_no=round_no,
                              decided_by=note)
            added.append(source)
        return added

    @staticmethod
    def by_cues(requests, options, fact="population"):
        """The deterministic choice: for each figure, the candidate whose coverage best fits its cues (catalog order
        breaks ties). Returns {source: [(figure, None)]}: the reason is the fit itself."""
        order = list(options)
        fits = mayors.fit if fact == "mayor" else fit
        picks = {}
        for request in requests:
            candidates = [s for s in request["candidates"] if s in options]
            if candidates:
                best = min(candidates, key=lambda s: (fits(options[s], request), order.index(s)))
                picks.setdefault(best, []).append((request, None))
        return picks
