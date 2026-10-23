# FactSync Chile

**FactSync Chile checks the population figure of each Chilean comuna in Spanish and English Wikipedia and in Wikidata against INE's official figures, works out why each one differs, and drafts a sourced correction for a human editor to review.**

It is a multi-agent system. A Planner, a Retriever, an Extractor, an Analyst, a Critic that can reject work and send it back, and an Editor share one World Model. Every source they compare is read through **Zetaris**, and every model call goes through **Meterless Nightshift** to **NVIDIA Nemotron**. FactSync never edits Wikipedia or Wikidata: it writes drafts, and a person reviews and applies them.

Built for the Open Agent Hackathon 2026, Track 1 (Fragmented Intelligence).

## Why

Chile counted its population in 2024 (INE, *Censo de Población y Vivienda 2024*). The public reference sources still disagree with that count, and with each other:

- Wikidata, which feeds search-engine panels and AI assistants, rarely has the 2024 figure. When we checked on Oct 22, 2026, only a handful of comunas carried it, and about 200 had no population at all.
- Wikipedia infoboxes mix census counts with INE projections, cite the 2012 census whose results INE withdrew, label a figure with the wrong year, or contradict their own article text.

Finding a number is easy. The hard part is explaining *why* two numbers differ: a projection is a different definition, not an error; a 2017 count is out of date but real; a 2012 count was never official. FactSync makes that call for each figure and shows its evidence, and a Critic must approve the call before anything is drafted.

## What a run produces

For each comuna in scope:

- **INE's official figures**: Census 2017, Census 2024 and, when needed, INE's projections.
- **Every figure the sources give, and a verdict on each one.** Each verdict carries a class from an 11-class taxonomy (for example *outdated vintage*, *different definition*, *withdrawn census*, *mislabelled vintage*, *internal inconsistency*), an explanation, the INE figures cited as evidence, a proposed correction, and the Critic's score out of 9.
- **Draft edits.** For Spanish Wikipedia, infobox lines with a `{{cita web}}` reference to INE and an edit summary in Spanish. For English Wikipedia, the infobox lines with `{{cite web}}`. For Wikidata, QuickStatements plus rank and qualifier notes.

Written to disk:

| File | What it is |
|---|---|
| `output/<run_id>/result.json` | The whole result: verdicts, evidence, Critic scores and history, drafts, escalations, model usage, structured errors |
| `output/<run_id>/report.html` | **The review queue**: one self-contained page with why each figure differs, the drafts with copy buttons, and what the agents did |
| `logs/trace-<run_id>.jsonl` | One JSON object per agent action: agent, action, target agent, round, status, confidence, retries, latency, the SQL sent to Zetaris, and for each model call the model requested, served and routed plus Nightshift's receipt id |
| `logs/world-model-<run_id>.jsonl` | The World Model's audit log for the run: every entity, observation and assessment written |

**Example (example 2, the demo moment).** Spanish Wikipedia gives Hualqui's population as 26,746 (2024). That figure matches no census count. In round 1, the Critic rejects calling it an error while an official source is still unread, and sends one fix to the Planner. The Planner adds INE's projections, the Retriever reads them through Zetaris, and 26,746 turns out to be **INE's projection for 2024, not a census count** (Census 2024 counted 25,795). The verdict changes to *different definition*, the Critic approves it, and the Editor drafts the correction.

## Quick start: sample mode (no services needed)

Sample mode runs the real agents on rows of the Zetaris views recorded for the four example inputs (`data/sample/`). It needs no Zetaris, no Nightshift and no network. Every model step takes its deterministic path, and the output says `"mode": "sample"`.

```powershell
git clone https://github.com/felixmella/open-agent-hack.git
cd open-agent-hack
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python run.py input_examples\example_2.json --sample
```

Then open `output\<run_id>\report.html`; the CLI prints the exact path. On macOS or Linux, use `.venv/bin/python` and forward slashes. `SAMPLE_MODE=true` in the environment does the same as `--sample`.

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

Run them in this order (add `--skip-exists` when re-running):

1. `zetaris/01_sources_create.sql`: INE Census 2024 by comuna (INE's ArcGIS REST API) and Wikidata population statements (SPARQL).
2. `scripts/upload_filestore.py`: copies `data/official/ine_projections_base2017_comunas.csv` into the Zetaris file store (with `docker cp` into the driver container).
3. `zetaris/02_official_create.sql`: INE Census 2017 (ArcGIS) and INE's population projections 2002–2035 (file store).
4. `zetaris/03_wikipedia_create.sql`: each comuna's Spanish and English Wikipedia article (MediaWiki API, 50 titles per request). It is generated by `scripts/build_wikipedia_sql.py`.
5. `zetaris/04_unified_create.sql`: the unified views. `factsync.official_population` holds every official figure with its definition and year. `factsync.eswiki_infobox` and `factsync.enwiki_infobox` hold infobox fields extracted in SQL. `factsync.population_picture` puts every claim from every source in one view, keyed by comuna code.

**3. Create the read-only app user.** The agents only read, so they use a General-role (view-only) Zetaris user:

1. In the Zetaris web UI, create the user under Management → Users, and create an API key for it.
2. Put that key and the user's e-mail in `.env` (`ZETARIS_API_KEY`, `ZETARIS_APP_USER`).
3. Run `zetaris/05_readonly_grants.sql` as above. It grants SELECT on the `factsync` views and nothing else.
4. Check it with `.venv\Scripts\python scripts\verify_readonly.py`. Through the app's key, each view must show as many rows as through the admin key.

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

- `{"scope": {"region": "Aysén"}}` checks a whole region.
- `{"scope": {"comunas": ["Saavedra (Chile)", "Cholchol"]}}` checks comunas by name.
- `"use_llm": false` runs every agent on its deterministic path. It's useful for fast checks; a live run like that takes 35–50 s, against about 15 minutes for example 2 with the model.
- An optional `run_id` names the run.

The four examples are:

1. Curacautín: a typo, a 2012 figure, and a mis-dated Wikidata value.
2. Hualqui, Guaitecas and Quirihue: the demo moment.
3. The Aysén region: 10 comunas.
4. Four comunas given by name.

The CLI prints progress and a summary, and exits with 0 on success, 1 if the run fails, and 2 if the input is invalid. A failed run prints a structured error, `{"status": "error", "error": {"code", "message", "stage", "recoverable"}}`, and still leaves its trace and an error `result.json`.

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

Mount `output`, `logs` and `state` (`-v ${PWD}/output:/app/output`, and the same for the other two) to keep a container's runs. No secret is baked into the image.

### National batch

```powershell
.venv\Scripts\python scripts\batch_national.py --tag 20261023
```

It runs all 346 comunas, one region per run, and writes `output/national-<tag>/summary.json` and `summary.md`. For each source, the summary counts how many current figures are INE's Census 2024 count and why the others differ. By default the agents take their deterministic paths, since the whole country through Nightshift would take days; the summary says which way it ran.

## How it works

```
input.json ─► Planner ──plan──► Retriever ──one SQL per source──► Zetaris views
                 ▲                  │ observations + provenance
     discovery:  │                  ▼
     add source  │        World Model (comunas, claims, assessments, audit log)
                 │                  │ context payloads
                 └── Analyst ◄── Extractor (article text → verified claims)
                        │ findings (class, evidence, confidence)
                        ▼
                     Critic ── one specific fix per round, ≤2 rounds ──► Planner | Extractor | Analyst
                        │ approved (or escalated to a human)
                        ▼
                     Editor ── drafts ──► Critic (draft review, ≤1 revision)
                        ▼
              result.json + report.html + logs/trace-<run>.jsonl + logs/world-model-<run>.jsonl
```

| Agent | What it does | Model use |
|---|---|---|
| Planner | Resolves the scope (comuna codes, a region, or names through the World Model's resolver) and picks the sources. **Discovery:** when the Critic says a figure can't be classified while an official source is unread, the Planner chooses which source to add and justifies it. | Chooses the source to add |
| Retriever | Runs one SQL statement per source per run against the Zetaris views, and writes each row into the World Model as an observation stamped with view, SQL, fetch time, agent and run. Records without a comuna code are matched by name. | None |
| Extractor | Code reads the infobox reference, the *Historical populations* table and the sentences that state a population. The model labels those sentences as claims (figure, year, census or projection). **Code keeps a claim only if its figure and year appear verbatim in the sentence, and the sentence verbatim in the article.** | Reads article text |
| Analyst | A deterministic matcher compares each claim with every official figure (census counts, projections, census-validity facts such as the withdrawn 2012 census and censuses Chile never held). The model is asked only about the claims the matcher can't settle. | Ambiguous cases only |
| Critic | Scores every finding on a 9-point rubric (evidence fidelity, definition discipline, correction sourcing) and approves at 7 or more. Otherwise it sends **one specific fix** to the agent responsible: the Planner, the Extractor or the Analyst. After 2 rounds, what still fails goes to a human. It also reviews every draft. | Judges class fit and faithfulness; the facts are recomputed by code |
| Editor | Builds the wikitext, citations and QuickStatements from templates, so every figure and source in a draft is the approved one. The model writes the edit summaries and the explanation for the reviewer, and the Critic checks them. | Wording |

Every loop is capped: Critic rounds, discovery steps, draft revisions, and model calls per run. Any model failure (an error, an empty or invalid reply, a spent budget) sends that step down its deterministic path, and the trace says so. A run always completes.

**The World Model (Meterless engine).** `app/engines/world_model/` implements the Meterless World Model engine spec in Python. It is the agents' shared state:

- Comunas are entities keyed by comuna code (`comuna:cut:08105`), and the resolver matches names (and flags uncertain matches for review).
- Every source row and every extracted claim is an append-only observation with provenance; writes without a source are rejected.
- Every agent's assessment is appended and attributed, never edited in place.
- Each agent gets a budgeted context payload, which is traced.
- Each run's audit log is exported to `logs/`.

It passes the engine's 8 official conformance checks, ported one-to-one in `tests/test_world_model_conformance.py`: sid-001, sid-002, band-001, prov-001, idem-001, idem-002, bitemp-001 and audit-001.

**Zetaris.** Every source the agents compare is a Zetaris view in the `factsync` container. The official INE figures, Wikidata and both Wikipedias are virtualised from public APIs and from INE's file, and joined by comuna code in `factsync.population_picture`. The app reads them with a read-only user. Agent state stays local: the World Model's SQLite store in `state/`.

**Nightshift.** The app requests `nvidia/nemotron-3.5-lightning-30b-a3b` through Nightshift's OpenAI-compatible API. Every request sends `meterless-app: open-agent-hack` and `meterless-scope: user`. Nightshift decides the route, so each trace event records the model requested, the model Nightshift says served the call, the receipt's routed model and the receipt id. It also records when Nightshift replayed an answer from its cache. Three adaptations keep the model in the loop despite Nightshift's 45-second limit on time to first byte (`app/adapters/meterless.py`):

- Chat calls stream.
- Every request sends `meterless-tier-split: off`.
- Agents keep each request below the size at which Nightshift switches to a buffered best-of-N "quality race", splitting larger work into batches.

## Tests

```powershell
.venv\Scripts\python -m pytest
```

98 tests. They use a fake model and a fake Zetaris serving rows recorded from the real views (`tests/fakes.py`), and need no services. They cover:

- the World Model's 8 conformance checks;
- the matcher, the wikitext parser, the Extractor's verbatim checks and the Critic's rubric;
- the orchestrator's loops: rejection → discovery → changed verdict, the cap leading to escalation, no model at all, and a broken model;
- request sizing for Nightshift;
- structured errors;
- sample mode with the network blocked, including the fallback from live Zetaris to the snapshot;
- the review queue page and the API.

## Project layout

```
app/adapters/          zetaris.py (REST client) · meterless.py (Nightshift client) · sample_data.py (snapshot + fallback)
app/agents/            planner · retriever · extractor · analyst · critic · editor · llm (budget, pacing, tracing)
app/engines/world_model/   the World Model engine
app/knowledge/         taxonomy · matcher · wikitext parsing   (+ data/reference/chile_censuses.json)
app/orchestration/     loop.py (the state machine) · state.py (run state and caps)
app/report/            the review queue (Jinja2 template)
app/main.py            the HTTP API          run.py   the CLI
zetaris/               Lightning SQL that registers the sources and views, and the read-only grants
scripts/               zetaris_sql · upload_filestore · build_wikipedia_sql · prepare_ine_projections ·
                       snapshot_sample_data · verify_readonly · batch_national · smoke_test
data/                  official/ (INE projections file) · reference/ (census facts) · sample/ (recorded view rows)
input_examples/        four example inputs            tests/   98 tests
```

## Limitations

- **One model.** Nightshift 1.2.1 routed every request to Nemotron 3.5 Lightning whatever we asked for, so all agents use it. There is no separate critic model; the Critic's rubric is code, with the model judging class fit and faithfulness.
- **Model calls are slow.** Lightning reasons at length, so a call takes 20–80 s, and example 2 with the model takes about 15 minutes. `use_llm: false` gives the deterministic result in under a minute.
- **Coverage of Wikipedia.** FactSync reads the article linked from each comuna's Wikidata item: 294 Spanish and 287 English articles for 346 comunas. A comuna whose item links no article, often because the article is attached to the town's item, isn't read.
- **What can be checked.** FactSync holds the 2017 and 2024 census counts and INE's projections for 2002–2035. Historical figures from other years (the 2002 census, for example) are reported as *not checkable* rather than judged.
- **Sample data** covers the 17 comunas of the four examples, recorded on Oct 23, 2026. Any other scope is refused in sample mode.
- **Drafts only.** FactSync never edits Wikipedia or Wikidata, and its drafts are meant to be reviewed: QuickStatements can't set ranks, so the Wikidata notes say what to do by hand.

## AI and model usage

- **In the product:** NVIDIA Nemotron 3.5 Lightning (`nvidia/nemotron-3.5-lightning-30b-a3b`), reached only through Meterless Nightshift. It reads article sentences, classifies ambiguous figures, judges the Analyst's findings, chooses the source to add on discovery, and writes the edit summaries and explanations. Code checks each of these outputs, and every one has a deterministic fallback. The traces record which model Nightshift says answered each call, with its receipt id.
- **In development:** the code was written with Claude Code (Anthropic), using Claude Opus 5.5. Commits carry a `Co-Authored-By: Claude` trailer. Cursor was not used.

## Data sources and licences

- INE census counts (2017, 2024) and population projections 2002–2035 by comuna: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), under INE's [open data terms](https://www.ine.gob.cl/terminos-de-uso-y-licencia-de-datos-abiertos). The projections file in `data/official/` is aggregated from INE's workbook (see its README).
- Wikidata: [CC0](https://creativecommons.org/publicdomain/zero/1.0/).
- Wikipedia article text, in `data/sample/` and in the drafts' context: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Each row names its article and revision, so the authors can be found in that revision's history.
- Python dependencies: `requirements.txt`.
