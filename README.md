# FactSync Chile

**FactSync Chile checks what Spanish and English Wikipedia and Wikidata say about each of Chile's 346 comunas against the official record: its population against INE's census, and its mayor against SERVEL's election results. It works out why each page differs, and drafts a sourced correction for a human editor to review.**

It is for the Wikipedia and Wikidata editors who keep Chile's comuna pages up to date by hand. Six agents work together: a Planner, a Retriever, an Extractor, an Analyst, a Critic that can reject work and send it back, and an Editor. They share one Meterless World Model. Every source they compare is read through **Zetaris**, and every model call goes through **Meterless Nightshift** to **NVIDIA Nemotron**. FactSync never edits Wikipedia or Wikidata: it writes drafts, and a person reviews and applies them.

The same agents check both facts. A fact is a module: its official source registered in Zetaris, a taxonomy of why pages differ, and each agent's reading of it. Population came first; mayors took an afternoon. The pattern fits any knowledge base that drifts from its system of record.

Built for the Open Agent Hackathon 2026, **Track 1: Solving Fragmented Intelligence**.

**See it work without running anything:**
- **[Demo video](https://drive.google.com/file/d/1g2-rFbYHHKEmtUeC5HOJ_52xPl6URa8E/view?usp=sharing)** (3:42; built from real outputs of live runs, with a synthetic voice).
- **[The review queues, online](https://felixmella.github.io/open-agent-hack/output_examples/)**: every live run's review queue opens in the browser, for example [example 2](https://felixmella.github.io/open-agent-hack/output_examples/example_2/report.html) (the Critic rejects, a source is discovered, the verdict changes), [example 5](https://felixmella.github.io/open-agent-hack/output_examples/example_5/report.html) (fixed since the last check, after real edits) and [example 6](https://felixmella.github.io/open-agent-hack/output_examples/example_6/report.html) (mayors: a former mayor, a nickname, vandalism, a stand-in).
- [`output_examples/`](output_examples/): live runs with the model, each with its review queue (`report.html`), its `result.json`, the agents' trace and the World Model's audit log.
- [`output_examples/national/`](output_examples/national/) and [`national_mayors/`](output_examples/national_mayors/): all 346 comunas, region by region, for each fact.
- [`eval/results.md`](eval/results.md): what Nemotron does, measured; [`eval/mayors_spot_check.md`](eval/mayors_spot_check.md): 20 random mayor verdicts checked by hand.
- [`docs/sponsor-technology.md`](docs/sponsor-technology.md): how Zetaris, the World Model engine, Nightshift and Nemotron are used.
- [`docs/zetaris/`](docs/zetaris/README.md): the Unified Semantic Layer in Zetaris, its data-quality rules, live query results for every source, and our reflections on the USL.

## Why

### Population

Chile counted its population in 2024 (INE, *Censo de Población y Vivienda 2024*). The public references haven't caught up, and they disagree with each other. A national run on Oct 24, 2026 (all 346 comunas; agents on their deterministic paths, so no model) found:

- **666 of 728 current population figures (92%)** shown across Spanish Wikipedia, English Wikipedia and Wikidata are not INE's Census 2024 count.
- 212 Spanish infoboxes still show the Census 2017 count. 186 English infoboxes give a figure attributed to the 2012 census, whose results INE withdrew, and 29 still show the 2002 count.
- Wikidata, which many search panels, apps and AI systems reuse, has no population for 196 comunas, and only 2 have Census 2024's count, correctly dated. Some Spanish infoboxes have no figure of their own and show Wikidata's, so Wikidata's staleness reaches the article.
- Some figures are something else entirely:
  - INE projections labelled as census counts;
  - a census year that never existed;
  - typos;
  - another place's population (Wikidata gives Santo Domingo, a town of 13,171, the Dominican capital's 1,029,110).

Finding a number is easy. The hard part is saying *why* two numbers differ. A projection is a different definition, not an error. A 2017 count is out of date but real. A 2012 count was never official. FactSync makes that call for every figure and shows its evidence, and a Critic must approve the call before anything is drafted. The full summary is in [`output_examples/national/summary.md`](output_examples/national/summary.md).

### Mayors

Chile elected its mayors on 26–27 October 2024, two years ago this week (SERVEL, the electoral service). A national run on Oct 26, 2026 (all 346 comunas, deterministic paths) found:

- **160 of the 272 English Wikipedia infoboxes that name a mayor (59%)** don't name the one elected in 2024. 50 name the mayor last elected in 2021, 55 in 2016, and 18 in 2012, three terms ago. Rengo's still names Carlos Soto, elected in 2012, 2016 and 2021; SERVEL's 2024 results elected Enrique del Barrio.
- Spanish Wikipedia is closer: 23 of 286 (8%).
- Wikidata, which search panels and AI assistants reuse, names a mayor for 5 comunas. Arica's is the mayor elected in 2012.
- 24 names match no candidate SERVEL lists for their comuna from 2012 on: a mayor from before 2012, a stand-in (Chimbarongo's Spanish infobox says "alcalde suplente"), or what looks like vandalism ("Wyatt Mathis" in Pinto's English article, "Joey Meehan" in Florida's).

The hard part is again saying *why*: a former mayor, a nickname ("Max Luksic" is SERVEL's Maximiliano Luksic Lederer), a compound surname, a candidate who lost, or vandalism. And SERVEL says who was elected, not who holds the office today. In Yerbas Buenas both Wikipedias name a candidate who lost in 2024, and Wikidata records the elected mayor's term ending on Oct 22, 2026: the office may have changed hands. FactSync never calls such a page wrong; its draft asks the editor to check first. The summary is in [`output_examples/national_mayors/summary.md`](output_examples/national_mayors/summary.md), and 20 random verdicts checked by hand are all right ([`eval/mayors_spot_check.md`](eval/mayors_spot_check.md)).

## What a run produces

For each comuna in scope:

- **INE's official figures:** Census 2017 and 2024, plus whatever the agents chose to read on the way: INE's projections, Census 2002, the 2017 urban and rural population.
- **A verdict on every figure the sources give.** Each carries:
  - a class from an 11-class taxonomy, for example *outdated vintage*, *different definition*, *withdrawn census*, *mislabelled vintage* or *internal inconsistency*;
  - an explanation and the INE figures cited as evidence;
  - a proposed correction;
  - the Critic's score out of 9.
- **Draft edits.** Spanish Wikipedia gets infobox lines with a `{{cita web}}` reference to INE and an edit summary in Spanish. English Wikipedia gets the infobox lines with `{{cite web}}`. Wikidata gets QuickStatements, plus notes on rank and qualifiers.
- **Since the last check:** what changed on each page since the previous run that checked the comuna (fixed, changed, unchanged), rebuilt by the World Model from its log. In [example 5](output_examples/example_5/), recorded after three of FactSync's drafts were applied by hand on Wikipedia and Wikidata, it reports 4 pages fixed.

Written to disk:

| File | What it is |
|---|---|
| `output/<run_id>/result.json` | The whole result: verdicts, evidence, Critic scores and history, discoveries, drafts, escalations, model usage, the World Model's capabilities used, structured errors |
| `output/<run_id>/report.html` | **The review queue:** one self-contained page with why each figure differs, the drafts with copy buttons, what changed since the last check, and what the agents did |
| `logs/trace-<run_id>.jsonl` | One JSON object per agent action: agent, action, target agent, round, status, confidence, retries, latency, the SQL sent to Zetaris. Each model call also records the model requested, served and routed, and Nightshift's receipt id |
| `logs/world-model-<run_id>.jsonl` | The World Model's audit log for the run: every entity, observation, assessment and rebuild written |

**Example (example 2, the demo moment).**
1. Spanish Wikipedia gives Hualqui's population as 26,746 (2024), which matches no census count.
2. In round 1, the Critic refuses to let the Analyst call it anything while an official source that could explain it is unread. It sends one fix to the Planner.
3. The Planner chooses INE's projections for that figure, and Census 2002 for the 2002 figures in the other two comunas' articles. The Retriever reads both through Zetaris.
4. 26,746 turns out to be **INE's projection for 2024, not a census count** (Census 2024 counted 25,795). The verdict changes to *different definition*, the Critic approves it, and the Editor drafts the correction.

## Quick start: sample mode (no services needed)

Sample mode runs the real agents on rows of the Zetaris views recorded for the four example inputs (`data/sample/`). It needs no Zetaris, no Nightshift and no network. Every model step takes its deterministic path, and the output says `"mode": "sample"`.

```powershell
git clone https://github.com/felixmella/open-agent-hack.git
cd open-agent-hack
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python run.py input_examples\example_2.json --sample
```

Then open `output\<run_id>\report.html`; the CLI prints the exact path. On macOS or Linux, use `.venv/bin/python` and forward slashes. Setting `SAMPLE_MODE=true` in the environment does the same as `--sample`.

## Full setup (live)

**You need:**

- Python 3.11 or later (developed on 3.13).
- The Zetaris platform running locally in Docker (the hackathon's participant setup). Its REST API is at `http://localhost:8888/api/v1.0`.
- Meterless Nightshift with an NVIDIA lane seated with `nvidia/nemotron-3.5-lightning-30b-a3b`. The NVIDIA key lives only in Nightshift (Setup → Providers); this app never sees it.

**1. Settings.** Copy `.env.example` to `.env` and fill it in. `.env` is gitignored; never commit it.

| Setting | What it is |
|---|---|
| `ZETARIS_REST_URL`, `ZETARIS_ORG_ID` | Zetaris REST endpoint and organisation (`1` on a local install) |
| `ZETARIS_API_KEY` | The key of the app's **read-only** Zetaris user (step 3) |
| `ZETARIS_APP_USER` | That user's login e-mail |
| `ZETARIS_ADMIN_API_KEY` | An admin key, used only by the setup scripts in `zetaris/` |
| `ZETARIS_USER_AGENT` | An app name and contact e-mail. Wikimedia requires one, and Zetaris sends it when it calls the Wikidata and Wikipedia APIs |
| `METERLESS_BASE_URL`, `METERLESS_RUNTIME_TOKEN` | From the Nightshift Console (`http://127.0.0.1:8088/v1` by default) |
| `METERLESS_MODEL` | The model to request: `nvidia/nemotron-3.5-lightning-30b-a3b` |
| `SAMPLE_MODE` | `true` to run on the sample data |

**2. Register the sources in Zetaris.** Run each script as admin, dry run first:

```powershell
.venv\Scripts\python scripts\zetaris_sql.py zetaris\01_sources_create.sql --dry-run
.venv\Scripts\python scripts\zetaris_sql.py zetaris\01_sources_create.sql
```

The order, what each step creates, and how each object was checked against its source are in [`zetaris/README.md`](zetaris/README.md). In short:
1. INE Census 2024 and Wikidata (`01`).
2. The two INE files, prepared by `scripts/prepare_ine_projections.py` and `scripts/prepare_ine_census2002.py`, then copied into the file store by `scripts/upload_filestore.py`.
3. Census 2017 with its urban/rural split, the projections and Census 2002 (`02`).
4. Wikipedia (`03`).
5. The unified views and the source catalog (`04`).

**3. Create the read-only app user.** The agents only read, so they use a General-role (view-only) Zetaris user:

1. In the Zetaris web UI, create the user under Management → Users, and create an API key for it.
2. Put that key and the user's e-mail in `.env` (`ZETARIS_API_KEY`, `ZETARIS_APP_USER`).
3. Run `zetaris/05_readonly_grants.sql` as above. It grants SELECT on the `factsync` views and nothing else.
4. Check it with `.venv\Scripts\python scripts\verify_readonly.py`. Through the app's key, each view must show as many rows as through the admin key, a source table under the views must be refused, and the user must hold nothing beyond SELECT.

**4. Smoke test.** `.venv\Scripts\python scripts\smoke_test.py` checks that:

- the Zetaris UI answers and REST SQL runs;
- Nightshift lists the model and Nemotron replies;
- a tool call goes from Nemotron through Zetaris and back.

## Running it

### Command line

```powershell
.venv\Scripts\python run.py input_examples\example_2.json
```

An input names the comunas to check, by comuna code (CUT), by region, or by name (names are resolved by the World Model's entity resolver):

```json
{"scope": {"cuts": ["08105", "11203", "16201"]}, "languages": ["es", "en"],
 "options": {"max_critic_rounds": 2, "use_llm": true}}
```

- `"fact": "mayor"` checks each comuna's mayor against SERVEL's election results instead of its population (the
  default is `"population"`): `{"fact": "mayor", "scope": {"cuts": ["06115", "05703"]}}`.
- `{"scope": {"region": "Aysén"}}` checks a whole region.
- `{"scope": {"comunas": ["Saavedra (Chile)", "Cholchol"]}}` checks comunas by name.
- `"use_llm": false` runs every agent on its deterministic path. Useful for fast checks: a live run takes 35–50 s that way, against about 12 minutes for example 2 with the model (20 model calls).
- An optional `run_id` names the run.

The examples:

1. Curacautín: a typo, a 2012 figure, and a mis-dated Wikidata value.
2. Hualqui, Guaitecas and Quirihue: the demo moment.
3. The Aysén region: 10 comunas.
4. Four comunas given by name (Saavedra, Cholchol, La Pintana, Paredones).

Example 5 is a rerun of three comunas after real edits ([`output_examples/example_5`](output_examples/example_5/)).
Example 6 (`input_examples/example_6.json`) checks **mayors** in eight comunas, one case each: former mayors last
elected in 2021, 2016 and 2012 (Rengo, Coltauco, Llay-Llay), one up to date (Hualqui), a nickname (Huechuraba),
vandalism (Pinto), a stand-in (Chimbarongo), and a mayor who may have left office (Yerbas Buenas).

The CLI prints progress and a summary. It exits with 0 on success, 1 if the run fails, and 2 if the input is invalid. A failed run prints a structured error, `{"status": "error", "error": {"code", "message", "stage", "recoverable"}}`, and still leaves its trace and an error `result.json`.

### HTTP API

```powershell
.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000
```

| Endpoint | What it does |
|---|---|
| `POST /run` | Runs FactSync on the input in the body and answers with the result. With `?wait=false` it answers `202` at once and runs in the background. |
| `GET /runs` | Recent runs |
| `GET /runs/{run_id}` | A run's result, or `{"status": "running"}` while it runs |
| `GET /runs/{run_id}/report` | The run's review queue (HTML) |
| `GET /runs/{run_id}/trace` | The run's trace so far (JSON lines) |
| `GET /health` | The mode, and whether Zetaris (`SELECT 1`) and Nightshift (model list) answer. It makes no model call. |
| `GET /docs` | Interactive OpenAPI docs |

```bash
curl -X POST localhost:8000/run -H "Content-Type: application/json" -d @input_examples/example_1.json
```

On Windows PowerShell, write `curl.exe`. The API runs one run at a time: a second `POST` while a run is going gets `409`. Errors use the same JSON as the CLI, with HTTP status 422 (invalid input or unresolved scope), 404, 409, 503 (Zetaris unreachable) or 500.

### Docker

```powershell
docker build -t factsync .

# live: Zetaris and Nightshift run on the host
docker run --rm -p 8000:8000 --env-file .env `
  -e ZETARIS_REST_URL=http://host.docker.internal:8888/api/v1.0 `
  -e METERLESS_BASE_URL=http://host.docker.internal:8088/v1 factsync

# sample mode with no network at all
docker run --rm --network none -e SAMPLE_MODE=true factsync python run.py input_examples/example_2.json

# the tests
docker run --rm factsync pytest
```

To keep a container's runs, mount `output`, `logs` and `state` (`-v ${PWD}/output:/app/output`, and the same for the other two). No secret is baked into the image.

### Other scripts

- `scripts/batch_national.py --tag <tag> [--fact mayor]` runs all 346 comunas, one region per run, and writes a summary (`output/national-<tag>/summary.md`). By default the agents take their deterministic paths, since the whole country through Nightshift would take days; the summary says which way it ran.
- `scripts/spot_check_mayors.py --tag <tag>` draws a seeded random sample of a mayor batch's verdicts, with their evidence, for checking by hand.
- `scripts/record_examples.py` records the live output examples into `output_examples/`.
- `scripts/evaluate.py` runs the evaluation in `eval/`.
- `scripts/zetaris_explore.py <file>_select.sql --out <file>.md` runs a file of queries against Zetaris and records each one with its live result (`docs/zetaris/`).

## How it works

```
input.json ─► Planner ◄── source catalog (Zetaris) ──plan──► Retriever ──one SQL per source──► Zetaris views
                 ▲                                             │ observations + provenance
     discovery:  │                                             ▼
     choose from │          World Model (comunas, observations, assessments, the comuna picture, audit log)
     the catalog │                                             │ context payloads
                 └──────── Analyst ◄── Extractor (article text → verified claims)
                              │ findings (class, evidence, confidence)
                              ▼
                           Critic ── one specific fix per round, ≤2 rounds ──► Planner | Extractor | Analyst
                              │ approved (or escalated to a human)
                              ▼
                           Editor ── drafts ──► Critic (draft review, ≤1 revision)
                              ▼
          World Model rebuilds each comuna's picture, and the picture at the last check: what changed since
                              ▼
              result.json + report.html + logs/trace-<run>.jsonl + logs/world-model-<run>.jsonl
```

| Agent | What it does | Model use |
|---|---|---|
| Planner | Reads the source catalog in Zetaris and resolves the scope (comuna codes, a region, or names through the World Model's resolver). **Discovery:** when the Critic sends back figures that nothing read so far explains, each with the unread sources whose coverage could, the Planner chooses which to read. | Chooses a source per figure, with a reason |
| Retriever | Runs one SQL statement per source per run against the Zetaris views, and writes each row into the World Model as an observation stamped with its view, SQL, fetch time, agent and run. Records without a comuna code are matched by name. | None |
| Extractor | Code reads the infobox reference, the *Historical populations* table and the sentences that mention a population. The model labels those sentences as claims (figure, year, census or projection). **Code keeps a claim only if its figure and year appear verbatim in the sentence, and the sentence verbatim in the article.** | Reads article text |
| Analyst | A deterministic matcher compares each claim with every official figure read: census counts, projections, urban and rural populations, and census-validity facts such as the withdrawn 2012 census and censuses Chile never held. The model is asked only about the claims the matcher can't settle. | Ambiguous cases only |
| Critic | Scores every finding on a 9-point rubric (evidence fidelity, definition discipline, correction sourcing) and approves at 7 or more. Otherwise it sends **one specific fix** to the agent responsible: the Planner, the Extractor or the Analyst. It holds back a comuna whose claims nothing read can check while a catalog source could. After 2 rounds, what still fails goes to a human. It also reviews every draft. | Judges class fit and faithfulness; the facts are recomputed by code |
| Editor | Builds the wikitext, citations and QuickStatements from templates, so every figure and source in a draft is the approved one. The model writes the edit summaries and the explanation for the reviewer, and the Critic checks them. | Wording |

**Two facts, one loop.** A run checks one fact, population or mayor. The loop, the caps, the World Model and the
Zetaris catalog are the same for both; a fact brings its official source as Zetaris views, its taxonomy, and each
agent's reading of it (`app/agents/mayors.py` on top of `app/knowledge/mayors.py` and `names.py`). For mayors:

| Agent | What it does for mayors |
|---|---|
| Planner | Plans SERVEL's 2024 election, Wikidata's head of government statements and both infoboxes; on discovery, chooses which earlier election to read for a name nothing read explains |
| Retriever | Reads each election as one query on `factsync.servel_mayors` (every candidate, with votes and whether elected) |
| Extractor | Reads each infobox's mayor field: the name, the text in brackets (a party, "alcalde suplente"), a linked article |
| Analyst | Compares each name with every candidate read, accents, particles, nicknames and SERVEL's single given name in 2024 allowed for; Nemotron decides who an uncertain name refers to, and code derives the class from that person's record |
| Critic | The same 9-point rubric. A name no election read explains is held back while an earlier election is unread, so the Planner walks back one election per round: 2024, then 2021, 2016 and 2012 |
| Editor | Drafts the infobox lines with a SERVEL citation, spelling the winner as a page already does; every draft asks the editor to check the office hasn't changed hands since the election |

Every loop is capped: Critic rounds, discovery steps, draft revisions, and model calls per run. Any model failure (an error, an empty or invalid reply, a spent budget) sends that step down its deterministic path, and the trace says so. A run always completes.

**Discovery from the Zetaris catalog.** `factsync.source_catalog` lists every source, what it holds and the years it covers:
- Census 2017 and 2024 are read by default.
- INE's projections 2002–2035, Census 2002 and the Census 2017 urban/rural split are read only when the agents need them.

When a figure matches nothing read, or a claim names a year nothing read covers, the Critic sends it to the Planner with its candidate sources. The Planner chooses a source per figure: Nemotron gives a reason for each choice, and without the model, code picks by the figure's cues (a census year it names, a year no census was held in, a figure below the comuna's total). Discovery can take more than one round. In the live run of example 1, Curacautín's undated 16,418 matched nothing in the projections or Census 2002. In round 2 the Critic offered the urban and rural populations, and Nemotron declined: they are "parts, not the total", and 16,418 is close to the comuna's total. So the figure stays an unexplained mismatch. One real catch: once Census 2002 was read, Spanish Wikipedia's 2002 figure for Coltauco (17,121) turned out not to be INE's count (16,228).

**The World Model (Meterless engine).** `app/engines/world_model/` implements the Meterless World Model engine spec in Python. It is the agents' shared state:

- Comunas are entities keyed by comuna code (`comuna:cut:08105`). The resolver matches names, and flags uncertain matches for review.
- Every source row and every extracted claim is an append-only observation with provenance; writes without a source are rejected.
- Every agent's assessment is appended and attributed, never edited in place.
- Each agent gets a budgeted context payload, which is traced.
- **The comuna picture is a projection the engine holds.** For each page, it holds the figure shown as the current population and the verdict on it, rebuilt from the log.
- **The engine rebuilds it as of any earlier point.** Comparing the picture at the previous check with today's shows what was fixed since, so FactSync is something editors rerun, not a one-off audit.
- Each run reports the engine capabilities it used and the dormant ones (`result.json`, `world_model.capabilities`). `relate` and the graph view pass conformance but no feature uses them yet.

It passes the engine's 8 official conformance checks, ported one-to-one in `tests/test_world_model_conformance.py`: sid-001, sid-002, band-001, prov-001, idem-001, idem-002, bitemp-001 and audit-001. FactSync's own uses are tested in `tests/test_world_model_factsync.py` and `tests/test_world_model_picture.py`.

**Zetaris.**
- Every source the agents compare is a Zetaris view in the `factsync` container. The official INE figures, Wikidata and both Wikipedias are virtualised from public APIs and from INE files in the file store.
- The agents read the per-source views, one query per source. `factsync.official_population` holds every official series in one shape, and `factsync.population_picture` puts every claim from every source in one table keyed by comuna code, for exploration.
- A Unified Semantic Layer, `comuna_population`, declares the model behind those views: INE's comuna list, every official figure and every published figure, with foreign keys to the comuna list and data-quality rules that Zetaris runs. Its DDL, checks, the exploratory queries per source and our reflections on it are in [`docs/zetaris/`](docs/zetaris/README.md).
- The app reads with a read-only user. Agent state stays local, in the World Model's SQLite store in `state/`.

**Nightshift.**
- The app requests `nvidia/nemotron-3.5-lightning-30b-a3b` through Nightshift's OpenAI-compatible API. Every request sends `meterless-app: open-agent-hack` and `meterless-scope: user`.
- Nightshift decides the route, so each trace event records the model requested, the model Nightshift says served the call, the receipt's routed model and the receipt id. It also records when Nightshift replayed an answer from its cache.

Three adaptations keep the model in the loop despite Nightshift's 45-second limit on time to first byte (`app/adapters/meterless.py`):

- Chat calls stream.
- Every request sends `meterless-tier-split: off`.
- Agents keep each request below the size at which Nightshift switches to a buffered best-of-N "quality race", splitting larger work into batches.

More detail: [`docs/sponsor-technology.md`](docs/sponsor-technology.md).

## What Nemotron does

Nemotron's main job is reading. Articles are full of figures that aren't the comuna's population, and sentence patterns can't tell them apart:

| Sentence (Spanish Wikipedia) | Sentence patterns | Nemotron |
|---|---|---|
| "… 105.436 habitantes son hombres y 114.005 mujeres …" (Los Ángeles) | unexplained mismatch: a false finding | men only: not kept |
| "Al 2017 la ciudad tenía una población de 1637 personas" (Chaitén) | unexplained mismatch: a false finding | the town, not the comuna: not kept |
| "… población inscrita validada en servicios de salud municipal FONASA de 9.084 personas (98 %)" (Canela) | likely a typo: a false finding | people enrolled in health care: not kept |

[`eval/`](eval/) measures this: the same 11 comunas from the same recorded Zetaris rows, with and without Nemotron, every difference adjudicated against its evidence ([results](eval/results.md)).
- On disputed figures read from article text, Nemotron was right 16 times to the patterns' once, and five false or misleading findings never reached the reviewer.
- It also chooses which catalog source to read for each unexplained figure, with a reason, and declines sources that can't explain it. It judges the Analyst's verdicts, and words the drafts. Code checks every answer it gives.
- Where it was weaker: it missed one real typo (Los Ángeles) that the patterns caught, and its verdict on Santo Domingo was vaguer than the matcher's.
- It is slow (114 calls and 78 minutes for those 11 comunas), so the national numbers come from the deterministic path, and the model works on the comunas a reviewer is looking at.
- Separately, a random sample of 25 of the national run's verdicts was checked against the pages and INE's figures: all 25 are right.

For mayors ([example 6](output_examples/example_6/)), Nemotron decides what a name means, and code derives the verdict from SERVEL's rows:
- it confirmed that "Max Luksic" (Huechuraba's Spanish infobox) is SERVEL's MAXIMILIANO LUKSIC LEDERER, so the page is up to date;
- it read "Wyatt Mathis" (Pinto's English infobox) as vandalism, and "Alejando Arenas Arenas (ALCALDE SUPLENTE)" (Chimbarongo's Spanish one) as a stand-in;
- it chose which earlier election to read, with a reason, and wrote the drafts' summaries and the reviewer's explanation.

Code accepts only a person among the candidates it listed, and the class always follows from that person's record. Once the model contradicted itself: for Yerbas Buenas's Spanish infobox it answered "no listed candidate" while its own explanation named one. The Critic recomputed the match, refused the class, and, its rounds used up, sent the page to a human instead of drafting. This part is shown in example 6, not measured: the national mayor numbers come from the deterministic path, and 20 of its verdicts were checked by hand.

The adjudication was done by Claude (the coding assistant), and every judgment lists its evidence for checking.

## Tests

```powershell
.venv\Scripts\python -m pytest
```

175 tests. They use a fake model and a fake Zetaris serving rows recorded from the real views (`tests/fakes.py`, and `tests/fakes_mayors.py` with SERVEL's real rows), and need no services. They cover:

- the World Model's 8 conformance checks, its projections, point-in-time rebuilds and capability counts;
- the matcher, the wikitext parser, the Extractor's verbatim checks and the Critic's rubric;
- discovery from the catalog: coverage, the Planner's choice with and without a model, and the Critic holding back unchecked claims;
- the orchestrator's loops: rejection → discovery → changed verdict, the cap leading to escalation, no model at all, and a broken model;
- a draft applied to an article, seen as fixed on the next run;
- request sizing for Nightshift, and structured errors;
- sample mode with the network blocked, including the fallback from live Zetaris to the snapshot;
- the review queue page, the API, `metadata.json`, and the Zetaris setup runner (a multi-table `COMPILE USL` goes as one statement);
- mayors: the name matcher on real cases (compound surnames, nicknames, typos, SERVEL's one given name in 2024), the Critic walking the Planner back one election per round, a mayor who may have left office, drafts that cite SERVEL and spell the winner as a page does, the model deciding who a name is (and an answer naming no listed candidate ignored), wording that calls a page wrong sent back, and the two facts kept apart in the World Model.

## Project layout

```
app/adapters/          zetaris.py (REST client) · meterless.py (Nightshift client) · sample_data.py (snapshot + fallback)
app/agents/            planner · retriever · extractor · analyst · critic · editor · llm (budget, pacing, tracing)
                       mayors (each agent's reading of the second fact)
app/engines/world_model/   the World Model engine
app/knowledge/         taxonomy · matcher · catalog · picture · wikitext   (+ data/reference/chile_censuses.json)
                       mayors · names   (+ data/reference/chile_municipal_elections.json)
app/orchestration/     loop.py (the state machine) · state.py (run state and caps)
app/report/            the review queue (Jinja2 template)
app/main.py            the HTTP API          run.py   the CLI
zetaris/               Lightning SQL that registers the sources, views and catalog, the read-only grants, the two USLs, and a log of what was run
scripts/               zetaris_sql · upload_filestore · build_wikipedia_sql · prepare_ine_projections · prepare_ine_census2002 ·
                       prepare_servel_mayors · snapshot_sample_data · verify_readonly · batch_national · spot_check_mayors ·
                       record_examples · evaluate · smoke_test
data/                  official/ (INE and SERVEL files) · reference/ (census and election facts) · sample/ (recorded view rows)
input_examples/        five example inputs     output_examples/   live runs, the national batches     eval/   the evaluation
docs/                  sponsor-technology.md · zetaris/ (the USL write-up and live query results)   metadata.json   the project in machine-readable form
```

## Limitations

- **One model.** Nightshift routed every request to Nemotron 3.5 Lightning, so all agents use it. There is no separate critic model; the Critic's rubric is code, with the model judging class fit and faithfulness.
- **Model calls are slow.** Lightning reasons at length, so a call takes 20–80 s, and example 2 with the model takes about 12 minutes. `use_llm: false` gives the deterministic result in under a minute. The national numbers above come from that deterministic path.
- **Coverage of Wikipedia.** FactSync reads the article linked from each comuna's Wikidata item: 294 Spanish and 287 English articles for 346 comunas. A comuna whose item links no article (often because the article is attached to the town's item) isn't read.
- **What can be checked.** FactSync holds the 2017 and 2024 census counts and reads INE's projections for 2002–2035, Census 2002 and the 2017 urban/rural split when needed. Figures for other years (the 1992 census, for example) are reported as *not checkable* rather than judged. INE's base-2002 projections, which some articles probably quote for 2005–2016, are no longer published by INE, so those figures stay unexplained.
- **Census 2002 on today's boundaries.** INE's REDATAM gives the 2002 count for today's comunas. Iquique, Santa Bárbara, Nueva Imperial and Talcahuano lost territory to comunas created in 2004, so an article quoting their 2002 count on the old boundaries reads as unexplained.
- **Sample data** covers the 17 comunas of the four examples, recorded on Oct 24, 2026. Any other scope is refused in sample mode.
- **Drafts only.** FactSync never edits Wikipedia or Wikidata, and its drafts are meant to be reviewed. QuickStatements can't set ranks, so the Wikidata notes say what to do by hand.
- **Mayors: elected, not current.** SERVEL's results say who was elected, not who holds the office today. Resignations, removals, deaths, stand-ins and replacements chosen by the council are invisible to them, so FactSync never calls a page's mayor wrong: a name SERVEL can't explain is "unknown", and every draft asks the editor to check that the office hasn't changed hands. Where Wikidata records the end of the elected mayor's term, the drafts say so first.
- **Mayors: names.** SERVEL writes names in capitals without accents, and in 2024 gives only the first given name. A draft spells the winner as one of the comuna's pages already does when one names them; otherwise the model restores the accents, checked letter by letter against SERVEL, or the draft asks the editor to check the spelling. Wikidata drafts for mayors are instructions, not QuickStatements: P6 needs the person's own Wikidata item, which most mayors don't have.
- **Mayors: what was measured.** `eval/` measures the model on population figures only. For mayors, a random sample of the national run's verdicts was checked by hand ([`eval/mayors_spot_check.md`](eval/mayors_spot_check.md)); the model's own part on mayors is shown in example 6, not measured.

## AI and model usage

- **In the product:** NVIDIA Nemotron 3.5 Lightning (`nvidia/nemotron-3.5-lightning-30b-a3b`), reached only through Meterless Nightshift. It:
  - reads article sentences;
  - classifies ambiguous figures;
  - judges the Analyst's findings;
  - chooses the sources to add on discovery;
  - writes the edit summaries and explanations.

  Code checks each of these outputs, and every one has a deterministic fallback. The traces record which model Nightshift says answered each call, with its receipt id.
- **In development:** the code was written with Claude Code (Anthropic), using Claude Opus 5.5. Commits carry a `Co-Authored-By: Claude` trailer. Cursor was not used.

## Pre-existing work

None. The idea, the code and the data preparation all date from the hackathon's build window; the first commit is from Oct 22, 2026 (UTC). Open-source libraries are listed in `requirements.txt`. The Meterless World Model specification and its conformance cases are attributed in [`NOTICE`](NOTICE).

## Licence, data and attribution

- **Code:** [Apache License 2.0](LICENSE). See [`NOTICE`](NOTICE).
- **The World Model engine** implements the Meterless World Model specification, and `tests/test_world_model_conformance.py` ports its official conformance cases (github.com/Meterless/Meterless, Apache-2.0).
- **INE data** (census counts for 2002, 2017 and 2024, the 2017 urban/rural split, projections 2002–2035): [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), under INE's [open data terms](https://www.ine.gob.cl/terminos-de-uso-y-licencia-de-datos-abiertos). The files in `data/official/` are described in its README.
- **SERVEL data** (mayoral election results 2012–2024, `data/official/servel_alcaldes_2012_2024.csv`): public electoral results published by SERVEL; its results page states no licence, and FactSync cites SERVEL as the source (see [`data/official/README.md`](data/official/README.md)).
- **Wikidata:** [CC0](https://creativecommons.org/publicdomain/zero/1.0/).
- **Wikipedia article text** (in `data/sample/`, `eval/snapshot/`, and in the outputs' quotes): [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Each row names its article and revision, so the authors can be found in that revision's history.
- **Python dependencies:** `requirements.txt`.
