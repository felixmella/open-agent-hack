# Sponsor technology in FactSync Chile

FactSync Chile checks two facts about each of Chile's 346 comunas in Spanish and English Wikipedia and in Wikidata against their systems of record: the population against INE's official figures, and the mayor against SERVEL's election results. It explains why each one differs and drafts sourced corrections for a human editor. Six agents (Planner, Retriever, Extractor, Analyst, Critic, Editor) work over three sponsor technologies, and each one carries weight:

- **Zetaris** is the only way the agents read data. It holds every source as a view and tells the Planner which sources exist.
- **The Meterless World Model engine** is the agents' shared state, the picture of each comuna, and its memory between runs.
- **Meterless Nightshift**, routing to **NVIDIA Nemotron**, is the only model provider. Every call is traced with its receipt.

## Zetaris: the data layer

**Every source is a Zetaris view.** The agents compare eight public sources. None is copied into the app: Zetaris reads them live, and the INE and SERVEL files sit in its file store.

| Source | How Zetaris reads it | View |
|---|---|---|
| INE Census 2024, by comuna | REST table over INE's ArcGIS layer | `factsync.ine_census2024` |
| INE Census 2017, by comuna, and its urban and rural split | REST tables over two INE ArcGIS layers | `factsync.ine_census2017`, `factsync.ine_census2017_area` |
| INE Census 2002, by comuna | file store (counted on INE's REDATAM server by `scripts/prepare_ine_census2002.py`) | `factsync.ine_census2002` |
| INE estimates and projections 2002–2035, by comuna | file store (INE's workbook, aggregated) | `factsync.ine_projections` |
| Wikidata population statements | REST table over the SPARQL endpoint, flattened with `LATERAL VIEW explode` | `factsync.wikidata_population` |
| Spanish and English Wikipedia articles | 12 REST tables over the MediaWiki API, 50 titles each | `factsync.eswiki_infobox`, `factsync.enwiki_infobox`; for mayors `factsync.eswiki_mayor`, `factsync.enwiki_mayor` |
| SERVEL mayoral elections 2012, 2016, 2021, 2024: every candidate | file store (SERVEL's four workbooks, keyed by comuna code by `scripts/prepare_servel_mayors.py`) | `factsync.servel_mayors` |
| Wikidata head of government statements (P6) | REST table over the SPARQL endpoint | `factsync.wikidata_mayor` |

**Unified views are the data products the agents use.**
- `factsync.official_population` puts every official figure in one shape: series, definition, scope, year and value.
- The infobox views extract the population fields in SQL, next to each article's wikitext and revision.
- `factsync.population_picture` puts every claim from every source in one table keyed by comuna code, for exploring the whole picture in one query.

**A source catalog in Zetaris drives discovery.** `factsync.source_catalog` lists every source with the fact it is about, its definition, scope and the years it covers. The Planner reads it at the start of each run (one traced SQL statement) and plans the default sources of the run's fact from it.

When the Critic finds figures that nothing read so far explains, it names the unread catalog sources whose coverage could explain each one. The Planner then chooses among them, Nemotron with a reason or code by the figure's cues, and the Retriever reads them with one generic query. Adding a source means adding one view and one catalog row, with no new code. The catalog covers four official population series and four elections. Two of the series, INE's Census 2002 and the 2017 urban/rural split, were added during the hackathon because the articles cite them. For mayors, a run reads the 2024 election by default; when a page names someone no election read explains, the Critic sends the Planner back for the 2021, 2016 and 2012 elections, one per round.

**A Unified Semantic Layer with data-quality rules.** The USL `comuna_population` (namespace
`lightning.metastore.factsync`, DDL in `zetaris/07_usl_create.sql`) declares the model behind the views: `comuna`
(INE's list, the system of record), `official_figure` and `population_claim`, both with a foreign key to `comuna`.
Each table is activated from the view the agents read. Zetaris generates the key and foreign-key rules; three more are
registered (`cut_is_code`, `population_positive`, `figure_is_a_number`) and run with `RUN DQ`. The use case, the
exploratory queries per source, the USL checks and rule results, and our reflections on the USL (time saved against a
hand-coded version, and a requirement for Zetaris) are in [`docs/zetaris/`](zetaris/README.md). A second USL,
`comuna_mayor` (`zetaris/09_mayors_usl_create.sql`), does the same for mayors: `comuna`, `election_result` and
`mayor_claim`, with four registered rules; it took about an hour, reusing everything the first fact built.

**The app reads with a read-only user.** Following the advice of Zetaris's CTO, the app's key belongs to a General-role user that holds SELECT on the `factsync` view namespace and nothing else. The admin key is used only by the setup scripts. `scripts/verify_readonly.py` shows that the app's key sees as many rows as the admin key in every view, and is refused on the source tables underneath.

**Everything Zetaris does is checked and traced.**
- Each new object was verified by comparing its row counts with the source (`zetaris/README.md`). For example, Census 2002 has 346 comunas and 15,116,435 persons, the census's national total.
- Every query a run sends is in its trace with its SQL, row count and latency.

## The Meterless engine: World Model

`app/engines/world_model/` implements the Meterless World Model engine spec in Python. It is FactSync's shared state, not a side component: every agent reads and writes the comunas through it.

**Comunas are entities.**
- Each comuna is keyed by its INE code (`comuna:cut:08105`).
- The resolver matches records that have no code by name, in similarity bands. Uncertain matches go to a human.

**Every source row and every claim is an observation.**
- Each one is append-only and carries its provenance: the view and SQL it came from, the article revision, the agent and the run. A write without provenance is rejected.
- A rerun that reads the same content appends nothing; an edited article appends a new observation.

**Every agent's judgment is an assessment.** The Analyst's verdicts, the Critic's scores and fixes, escalations and draft statuses are all appended and attributed to an agent, a run and a round, and never edited.

**Context payloads.** The Analyst and the Critic get budgeted context payloads from the engine, and each payload is traced.

**The comuna picture is a projection the engine holds.**
- FactSync registers `comuna_picture` with the engine. For each page, it holds the figure shown as the current population and the verdict on it, plus findings, drafts and escalations.
- Mayor runs register a second projection, `mayor_picture`: per page, the name shown as the mayor and the verdict on it. One store holds both facts about each comuna; each projection reads only its own fact's assessments.
- The engine rebuilds it from the log; it is never edited in place.

**Point-in-time reconstruction powers "since your last check".**
- The engine can rebuild any projection over the log as it stood at an earlier audit sequence (`project_as_of`).
- At the end of each run, FactSync rebuilds each comuna's picture as of the previous run that checked it and compares the two, page by page: fixed, changed, unchanged, new or gone.
- The review queue shows the result. After an editor applies a draft, the next run shows that page as fixed.
- This happened for real: on Oct 26 three of the national batch's drafts were applied by hand (Coltauco on Wikidata,
  Rengo's Spanish infobox, Llay-Llay's English infobox). The next run ([`output_examples/example_5`](../output_examples/example_5/))
  reported 4 pages fixed: those three, plus Coltauco's Spanish infobox, which shows Wikidata's figure.

**The test:**
- `tests/test_world_model_conformance.py` ports the engine's official conformance suite one-to-one: sid-001, sid-002, band-001, prov-001, idem-001, idem-002, bitemp-001, audit-001. All 8 pass.
- `tests/test_world_model_factsync.py` covers FactSync's own uses: keying by code, idempotent reruns, resolution, context payloads and append-only assessments.
- `tests/test_world_model_picture.py` covers projections, point-in-time rebuilds and capability counts. One test applies FactSync's own draft to Hualqui's Spanish infobox and sees it reported as fixed.

**Live and dormant capabilities.**
- Each run counts its calls per engine capability and lists them in `result.json` (`world_model.capabilities`) and on the review queue.
- `relate` and the graph view are dormant: they pass the conformance check bitemp-001, but no FactSync feature uses them yet.

## Meterless Nightshift: the AI provider

Every model call goes through Nightshift's OpenAI-compatible API (`app/adapters/meterless.py`) and sends `meterless-app: open-agent-hack` and `meterless-scope: user`. The NVIDIA key lives only in Nightshift; the app never sees it.

Nightshift decides the route, so the app never assumes which model answered. Each call's trace event records:
- the model requested;
- the model Nightshift says served the call;
- the receipt's routed model and receipt id;
- whether Nightshift replayed the answer from its cache.

Each run's `result.json` totals these by agent.

Three adaptations, found by reading Nightshift's own engine code, keep the model in the loop:
1. **Streaming.** Nightshift abandons a cloud request whose response headers take longer than 45 seconds, and Nemotron reasons at length before answering. A streamed reply sends its headers at once, so the app streams.
2. **`meterless-tier-split: off`.** By default Nightshift splits JSON-shaped prompts into a planning and a code-patch phase, two model calls. With the header, one call answers one request, and the receipt describes that call.
3. **Requests sized below the quality race.** Nightshift scores each request's difficulty from its length and wording. At 0.6 or more it runs a buffered best-of-N "quality race", which dies at the 45-second limit. `nightshift_difficulty()` mirrors that score. The agents split their work into requests that stay below it: sentence batches, finding batches, and grouped discovery requests.

On a provider error, a call is retried once. Any model failure (an error, an empty or invalid reply, a spent budget) sends that step down its deterministic path, and the trace says so. A run always completes.

## NVIDIA: where Nemotron contributes

The model is `nvidia/nemotron-3.5-lightning-30b-a3b`, reached only through Nightshift. Five agents use it for judgment, and code checks every output:

| Agent | What Nemotron does | What code checks |
|---|---|---|
| Extractor | Reads the sentences that mention a population and says which state the whole comuna's population, with which figure, year and basis | The figure and year must appear verbatim in the sentence, and the sentence verbatim in the article |
| Analyst | Classifies the figures the matcher can't settle | The Critic recomputes which classes the facts allow |
| Critic | Judges whether each judgment-class verdict fits and whether its explanation is faithful | The rubric's facts are recomputed from the World Model |
| Planner | Chooses, per figure, which catalog source to read on discovery, and says why | Only candidates the Critic named are accepted |
| Editor | Writes edit summaries and the reviewer's explanation | The draft's figures, citation and wording are checked; the figures and sources in the drafts come from templates |

For mayors, the same agents ask Nemotron different questions:

| Agent | What Nemotron does | What code checks |
|---|---|---|
| Analyst | Decides which SERVEL candidate an uncertain name refers to ("Max Luksic" is Maximiliano Luksic Lederer), or, when none, what the name probably is: a stand-in, a misspelling, vandalism | The person must be one of the candidates listed; the class then follows from that person's record in SERVEL's results, never from the model |
| Planner | Chooses which earlier election to read for a name the elections read can't explain, with a reason | Only elections the Critic named are accepted |
| Critic | Judges whether "not elected" and "unknown name" verdicts fit, and whether their explanations are faithful | The rubric recomputes the match from SERVEL's rows |
| Editor | Writes the summaries and explanation, and restores the accents SERVEL's capitals drop | The name must have exactly SERVEL's letters; the wording must not call a page wrong (SERVEL shows who was elected, not who holds the office) |

Its main job is reading. Articles are full of figures that aren't the comuna's population (men only, a town, people
enrolled in the health system), which sentence patterns keep and turn into false findings. `eval/` measures this: the
same 11 comunas from the same recorded rows, with and without Nemotron, every difference adjudicated with its
evidence. On disputed figures from article text, Nemotron was right 16 times to the patterns' once, and five false or
misleading findings never reached the reviewer ([results](../eval/results.md), which also list where it was weaker).

## What was unique

- **One pattern, two facts.** The loop, the caps, the World Model and the Zetaris catalog are shared; a fact is a module (its official source as views, a taxonomy, each agent's reading of it). The second fact, mayors against SERVEL, went from SERVEL's workbooks to live national results in an afternoon.

- **Discovery from a catalog in Zetaris.** The Planner chooses sources from a table Zetaris holds, by coverage, and new official sources need only a view and a catalog row. A real case: it added Census 2002 when articles cited it, and found that Spanish Wikipedia gives Coltauco 17,121 people in 2002 where INE counted 16,228.
- **The World Model as memory between runs.** Point-in-time reconstruction turns a one-off audit into something editors rerun, and shows what was fixed since the last check: after three real edits, the next run reported 4 pages fixed.
- **A USL whose rules run where the data lives:** foreign keys to INE's comuna list and registered data-quality rules, activated from the same views the agents read. The app reads with a read-only Zetaris user, checked by a script.
- **Nightshift internals worked out and documented:** the 45-second time-to-headers deadline, the tier split, and the quality-race floor. This let a slow-reasoning model take part in a six-agent loop without its calls timing out.
