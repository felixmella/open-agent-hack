# Output examples

Real runs of FactSync Chile, kept as evidence. Each folder holds what the run wrote, unchanged:

| File | What it is |
|---|---|
| `report.html` | The review queue. Download and open it in a browser, or follow the rendered link in [`index.html`](index.html) once GitHub Pages serves this repository |
| `result.json` | The whole result: verdicts, evidence, Critic scores and history, discoveries, drafts, escalations, what changed since the last check, model usage, the World Model capabilities used |
| `trace.jsonl` | The agents' trace: one JSON object per action. Zetaris SQL, row counts and latency; for each model call the model requested, the model Nightshift says served it, the receipt's routed model and receipt id; Critic rejections, fixes and discovery choices |
| `world-model-audit.jsonl` | The World Model's audit log for the run: every entity, observation, assessment and rebuild written |
| `about.json` | The input, the run id, the commit the code was at, and when it ran |

Every source was read live through Zetaris, and every model call went through Meterless Nightshift to NVIDIA Nemotron. FactSync never reads this folder: the files are for readers. They are regenerated with `scripts/record_examples.py`.

## The runs

All were recorded on Oct 24, 2026, live: every source through Zetaris, every model call through Nightshift, answered by `nvidia/nemotron-3.5-lightning-30b-a3b`. Each compares the comunas with national batch `20261024c` ("since the last check"); no page had changed since it.

| Folder | Scope | Findings | Drafts | Critic rejections | Sources discovered | Model calls | Time |
|---|---|---|---|---|---|---|---|
| [`example_1`](example_1/) | Curacautín | 8 | 3 | 2 | projections, Census 2002 | 20 | 12 min |
| [`example_1_rerun`](example_1_rerun/) | Curacautín, again | 8 | 3 | 2 | projections, Census 2002, urban/rural | 23 (3 fell back to code) | 18 min |
| [`example_2`](example_2/) | Hualqui, Guaitecas, Quirihue | 19 | 9 | 3 | Census 2002, projections | 20 | 12 min |
| [`example_3`](example_3/) | the Aysén region (10 comunas) | 39 | 24 | 7 | Census 2002, projections | 38 | 29 min |
| [`example_4`](example_4/) | Saavedra, Cholchol, La Pintana, Paredones (by name) | 17 | 11 | 4 | Census 2002, projections, urban/rural | 23 | 14 min |

What to look at in each:

- **Example 1: Curacautín.**
  - Round 1: the Critic rejects four figures that match nothing read and holds back two claims about the 2002 census. Nemotron chooses the projections for four figures and Census 2002 for two, with a reason for each (`llm_choose_sources` in the trace).
  - Round 2: the Critic offers the urban and rural populations for Wikidata's undated 16,418. Nemotron declines: they are parts of a comuna, not its total. The decline is in the trace.
  - Round 3: all 8 findings are approved at 9/9, including the typo 25,413 for the 2017 count 17,413.
  - This run's code predates the timeline line that shows declines (added after it, in `69fc780`).
- **Example 1, rerun.** The same input an hour later, on the code at `fe90599`.
  - Three model steps failed: two Nightshift provider errors after a retry, and one reply with no usable choices. Code took over at each, and the trace says so.
  - Code chose the sources by cues, including the urban/rural split. The run reached **the same 8 verdicts**.
- **Example 2: the demo moment.**
  1. Spanish Wikipedia gives Hualqui 26,746 (2024), which matches no census count. The Critic rejects both of Hualqui's unexplained figures and holds back the 2002 figures in Guaitecas's and Quirihue's articles.
  2. Nemotron adds Census 2002 for three figures and the projections for two.
  3. In round 2, 26,746 is INE's 2024 projection, a different definition, and Wikidata's 20,968 (2007) stays unexplained. Everything is approved, and 9 drafts are written.
- **Example 3: a whole region.** Ten comunas, the Planner pooling discovery across them, 24 drafts.
- **Example 4: names.** Comunas given by name ("Saavedra (Chile)") are resolved by the World Model's entity resolver. All three on-demand sources are read.

## The national batch

[`national/`](national/) holds a run over all 346 comunas, one region per run, with the agents on their deterministic paths (no model calls; the whole country through the model would take days). [`national/summary.md`](national/summary.md) has the numbers the README quotes. Each region's folder has its review queue, result, trace and audit log.
