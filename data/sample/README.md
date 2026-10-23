# Sample data

Rows of FactSync's Zetaris views for the four example inputs (17 comunas), recorded from a live Zetaris by `scripts/snapshot_sample_data.py`. The script runs the Planner and the Retriever, so these are the agents' own queries, and keeps every row exactly as Zetaris returned it (values as strings). The date is in `manifest.json` (`recorded_at`), and each file lists the SQL that produced it.

FactSync reads these files in two cases:

- **Sample mode** (`SAMPLE_MODE=true`, or `run.py --sample`): no Zetaris, no Nightshift, no network. Every model step takes its deterministic path, and the result says `"mode": "sample"`. Sample runs keep their own World Model store (`state/world-factsync-sample.sqlite`).
- **Live mode, as a fallback**: when a Zetaris query fails in a way a retry could fix (unreachable, a server error), these rows answer it if they cover it. The run traces this (`fallback_to_sample`), escalates it, and lists it under `data.fallbacks` in the result.

These are inputs, not outputs: every verdict and draft is computed from these rows by the agents at run time. A scope outside the 17 comunas is refused (`not_in_sample`), never guessed.

| File | Zetaris view | Contents |
|---|---|---|
| `ine_census2024.json` | `factsync.ine_census2024` | All 346 comunas (code, name, region): the Planner's comuna list |
| `official_population.json` | `factsync.official_population` | INE Census 2017 and 2024 counts and INE projections 2002–2035 for the 17 comunas |
| `wikidata_population.json` | `factsync.wikidata_population` | Wikidata population statements for the 17 comunas, plus the items that have no comuna code (the Retriever matches those by name) |
| `eswiki_infobox.json`, `enwiki_infobox.json` | `factsync.eswiki_infobox`, `factsync.enwiki_infobox` | Spanish and English Wikipedia articles for the 17 comunas (wikitext at the recorded revision, with the infobox population fields), plus the articles that have no comuna code |

## Licences and attribution

- INE census figures and population projections: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), under INE's [open data terms](https://www.ine.gob.cl/terminos-de-uso-y-licencia-de-datos-abiertos).
- Wikidata statements: [CC0](https://creativecommons.org/publicdomain/zero/1.0/).
- Wikipedia article text: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Each row gives the article's title, revision id (`revid`) and revision time; its authors are listed in the history of that revision, at `https://es.wikipedia.org/w/index.php?oldid=<revid>` (Spanish) or `https://en.wikipedia.org/w/index.php?oldid=<revid>` (English). The text is unchanged.

## Regenerate

```powershell
.venv\Scripts\python scripts\snapshot_sample_data.py
```

It needs a running Zetaris with the `factsync` views (see the main README).
