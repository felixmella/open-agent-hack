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

All were recorded live: every source through Zetaris, every model call through Nightshift, answered by `nvidia/nemotron-3.5-lightning-30b-a3b`. Each compares the comunas with national batch `20261024c` ("since the last check"). Examples 1 to 4 were recorded on Oct 24, 2026, when no page had changed since that batch. Example 5 was recorded on Oct 26, after four of FactSync's drafts had been applied by hand.

| Folder | Scope | Findings | Drafts | Critic rejections | Sources discovered | Model calls | Time |
|---|---|---|---|---|---|---|---|
| [`example_1`](example_1/) | Curacautín | 8 | 3 | 2 | projections, Census 2002 | 20 | 12 min |
| [`example_1_rerun`](example_1_rerun/) | Curacautín, again | 8 | 3 | 2 | projections, Census 2002, urban/rural | 23 (3 fell back to code) | 18 min |
| [`example_2`](example_2/) | Hualqui, Guaitecas, Quirihue | 19 | 9 | 3 | Census 2002, projections | 20 | 12 min |
| [`example_3`](example_3/) | the Aysén region (10 comunas) | 39 | 24 | 7 | Census 2002, projections | 38 | 29 min |
| [`example_4`](example_4/) | Saavedra, Cholchol, La Pintana, Paredones (by name) | 17 | 11 | 4 | Census 2002, projections, urban/rural | 23 | 14 min |
| [`example_5`](example_5/) | Coltauco, Rengo, Llay-Llay, after real edits | 7 | 7 | 4 | Census 2002, projections | 17 | 11 min |

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
- **Example 5: fixed since the last check.** On Oct 26, a human editor applied three of the national batch's drafts, checking each figure against INE first:
  - Coltauco's Census 2024 count on Wikidata, at preferred rank ([diff](https://www.wikidata.org/w/index.php?title=Q3847&diff=2561107700&oldid=2550671928));
  - Rengo's Spanish infobox ([diff](https://es.wikipedia.org/w/index.php?title=Rengo&diff=176011339&oldid=175858789));
  - Llay-Llay's English infobox ([diff](https://en.wikipedia.org/w/index.php?title=Llay-Llay&diff=1382101060&oldid=1376738169)).

  The next run rebuilt each comuna's picture as of the national batch and compared it with today's. It reports **4 pages fixed**: the three edited, plus Coltauco's Spanish infobox, which shows Wikidata's figure (19,597 → 21,373). The other 5 pages are unchanged (`since_last_check` in `result.json`, `compare_runs` in the trace). The pages' remaining findings, such as Rengo's English infobox and its withdrawn 2012 figure, are still in the queue. The input is `input.json` in the folder.

## The national batch

[`national/`](national/) holds a run over all 346 comunas, one region per run, with the agents on their deterministic paths (no model calls; the whole country through the model would take days). [`national/summary.md`](national/summary.md) has the numbers the README quotes. Each region's folder has its review queue, result, trace and audit log.
