# What the model adds: results

Eleven comunas were run twice from the same recorded Zetaris rows (`snapshot/`, Oct 24, 2026). The first run has every agent on its deterministic path; the second has Nemotron 3.5 Lightning through Nightshift wherever the agents use it. The comunas are Galvarino, Melipilla, Talcahuano, Canela, Chaitén, Los Ángeles, Pelluhue, Puente Alto and Santo Domingo, chosen because they are rich in hard cases, plus San Fabián and Caldera as plain ones. The method is in [README.md](README.md). Every difference is listed with its evidence in [differences.md](differences.md) and judged in [adjudication.json](adjudication.json).

**The judgments were made by Claude, the AI coding assistant that built FactSync, not by an independent annotator.** Each one cites the sentence or the figures it rests on, so it can be checked.

## The two runs

| | Rules only | With the model |
|---|---|---|
| Findings | 70 | 65 |
| Figures in article text judged | 48 (12 became findings) | 32 (6 became findings) |
| Critic rejections | 14 | 10 |
| Sources discovered | projections, Census 2002 (round 1); urban/rural (round 2) | all three in round 1 |
| Drafts (all passed the Critic's checks) | 31 | 31 |
| Escalations | 0 | 0 |
| Model calls | 0 | 114, all answered by `nvidia/nemotron-3.5-lightning-30b-a3b` (Extractor 25, Analyst 29, Critic 45, Planner 4, Editor 11); no fallbacks |
| Time | 1 s | 78 min |

## The differences, judged

| Kind | Model right | Rules right | Both right |
|---|---|---|---|
| Extraction: a figure in the text only one run kept | 16 | 1 | 1 |
| Verdict: the same figure, classified differently | 0 | 1 | 0 |
| Follow-on: a finding that exists because of an extraction difference | 1 | 0 | 0 |
| **Of these, differences that changed what the reviewer sees (a finding)** | **6** | **2** | 0 |

The Critic's model doubted 2 verdicts. Both flags were wrong, but understandably so: see below.

**Where the model helps: it reads what a sentence is about.**
- The patterns keep any figure next to "habitantes". The model dropped 14 figures that aren't the comuna's population:
  - localities (Canela Baja, Los Rulos);
  - "the city" and "the town" of Chaitén;
  - men only (Los Ángeles);
  - the rural share (Pelluhue);
  - a density (Talcahuano);
  - a poverty count (Chaitén);
  - Galvarino's over-45s, graduates, Mapuche and believers;
  - people enrolled in the municipal health system (Canela);
  - festival visitors (Canela).
- Four of those had become false "likely error" or "unexplained" findings in the rules run (the health-system count, the men, and Chaitén's city and town), which a reviewer would have had to dismiss by hand.
- A fifth false finding was on a correct sentence. Melipilla's "en 2025 tiene 150.466 habitantes (basado en el censo 2017...)" is INE's 2025 projection; the patterns took its year from "censo 2017" and called it a projection labelled as a census count.
- The model also read figures correctly where the patterns mislabelled them. Melipilla's English lead gives a 2017 census count and a 2020 projection: the model confirmed the projection, and found that the English infobox still shows the 2002 figure.

**Where it doesn't:**
- It dropped Los Ángeles's "220.441 habitantes de acuerdo al censo de 2024", a real typo: INE counted 219,441, which is the article's own men plus women. The sentence speaks of the city, and the model took it for the town; the rules caught it.
- For Santo Domingo's Wikidata figure of 1,029,110, the rules' verdict is more precise: 78 times INE's count, probably another place's figure. The model's "unexplained mismatch" is true but vaguer.
- Its edit summaries read better than the templates, but can blur details. Canela's summary says the old figure was a "proyección 2017"; it is INE's 2020 projection, labelled 2017. The Critic checks that every figure in a summary is one the evidence holds; it doesn't check such nuances.

**The Critic's two flags.** It doubted two *internal inconsistency* verdicts: an infobox showing an older figure than a newer census count the article itself gives (Galvarino, Melipilla). The model read the class description of that time, "the article contradicts itself", literally. Two figures for different years don't contradict each other, so the doubt was fair. The verdicts were right, and each lost only a point (8/9). The class description has since been reworded to say what the class covers.

**Discovery.** Both runs added the same three sources. The model chose all three in the first round. By cues, code left the urban/rural split for the second round. The model's reasons are in the trace (`runs/model/trace.jsonl`, `llm_choose_sources`); some are thin. Its reason for an undated figure cites a year the figure doesn't have.

**What it costs.** 114 calls and 78 minutes, against one second, for 11 comunas. So the national numbers come from the deterministic path, and the model is for the comunas a reviewer is working on.

## The headline, spot-checked

Separately, 25 current-figure verdicts from the national batch (`20261024c`, rules only) were drawn at random (seed 2024). Each was checked against the page's own fields, parsed again from the article's wikitext, or against Wikidata's statements, and against INE's figures: [headline_sample.md](headline_sample.md). **All 25 are right.** The sample covers 6 outdated Census 2017 counts, 9 withdrawn 2012 figures, 1 outdated 2002 count, 4 outdated Wikidata statements, 3 up-to-date figures, 1 unexplained mismatch and 1 projection labelled with the wrong year. Twenty-five is a small sample: it shows the headline isn't built on misreadings, not an exact error rate.

## Reading it

The deterministic path is right about the arithmetic and fast enough for the whole country. The model's value is reading text: it removed most of the noise and false findings that sentence patterns create, at the cost of one missed typo, while code still checks every figure it keeps against the sentence and INE. On the hard verdicts the model was not better than the matcher. The design keeps code in charge of facts and gives the model the reading, which this evaluation supports.

*Runs: `runs/rules` and `runs/model`, both recorded on Oct 24, 2026, from the code at commit `5b79107`. The rules and the model share the matcher, so the matcher changes made afterwards (`bdf3b7f`) don't change what this comparison measures.*
