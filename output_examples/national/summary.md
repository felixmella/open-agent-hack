# National batch 20261024c

346 comunas in 16 regions; agents on their deterministic paths (matcher, rule-based Critic, templates): no model calls.

Of 728 current population figures shown across the three sources, **666 (92%)** are not INE's Census 2024 count (correctly labelled).

| Source | Comunas with a figure | Census 2024 count | Differs | No figure | Not read | Why it differs |
|---|---|---|---|---|---|---|
| Spanish Wikipedia | 291 | 35 | 256 (88%) | 1 | 54 | Outdated 217, Different definition 21, Likely error 9, Unexplained mismatch 7, Mislabelled vintage 2 |
| English Wikipedia | 287 | 25 | 262 (91%) | 0 | 59 | Withdrawn census 186, Outdated 52, Unexplained mismatch 8, Different definition 7, Mislabelled vintage 6, Nonexistent census 3 |
| Wikidata | 150 | 2 | 148 (99%) | 196 | 0 | Outdated 138, Likely error 6, Mislabelled vintage 4 |

**4 Spanish Wikipedia infoboxes have no population figure of their own and show Wikidata's** (Outdated 4); they are counted above under the figure they show. Their template fills an empty population field from Wikidata, so Wikidata's staleness reaches the article, and correcting Wikidata's statement corrects the infobox too.

**Discovery.** Sources the Planner added from the Zetaris catalog when the Critic sent figures back: official_census2002 in 16 of 16 regions, for 449 figures; official_projections in 16 of 16 regions, for 153 figures; official_census2017_area in 8 of 16 regions, for 19 figures.

**Figures attributed to the 2002 census**, checked against INE's Census 2002 count once the Planner added it: Consistent 357, Outdated 28, Unexplained mismatch 19, not the comuna's figure 10, Likely error 4, Different definition 1.

**72 figures could not be checked**, for want of an official figure for their year: no year: 29, 1992: 14, 1865: 2, 2000: 2, 1920: 2, 1895: 2, 1970: 2, 1990: 1, 1854: 1, 1874: 1, 2001: 1, 1985: 1, 1978: 1, 1972: 1, 1897: 1, 1885: 1, 1882: 1, 1836: 1, 1930: 1, 1907: 1, 1940: 1, 1960: 1, 1842: 1, 1843: 1, 1918: 1, 1875: 1.

**Since the last check** of 346 comunas, per page: unchanged 925.

*No figure:* the source shows no population figure: a Wikidata item without a population statement, or an infobox whose population field is empty (with nothing in Wikidata to fill it on Spanish Wikipedia).

*Not read:* FactSync reads the Wikipedia article linked from each comuna's Wikidata item (the `factsync.eswiki_articles` and `enwiki_articles` views). A comuna whose item links no article, often because the article is attached to the town's item instead, isn't counted. An infobox whose population field SQL can't read is read again from the article's wikitext, so it is counted under the figure the infobox shows (its own, Wikidata's, or none).

Runs:

- `national-20261024c-01-tarapaca`: success, 7 comunas, 33 findings, 17 drafts (output/national-20261024c-01-tarapaca/report.html)
- `national-20261024c-02-antofagasta`: success, 9 comunas, 23 findings, 16 drafts (output/national-20261024c-02-antofagasta/report.html)
- `national-20261024c-03-atacama`: success, 9 comunas, 31 findings, 20 drafts (output/national-20261024c-03-atacama/report.html)
- `national-20261024c-04-coquimbo`: success, 15 comunas, 56 findings, 37 drafts (output/national-20261024c-04-coquimbo/report.html)
- `national-20261024c-05-valparaiso`: success, 38 comunas, 118 findings, 91 drafts (output/national-20261024c-05-valparaiso/report.html)
- `national-20261024c-06-libertador-general-bernardo-o-higgins`: success, 33 comunas, 121 findings, 91 drafts (output/national-20261024c-06-libertador-general-bernardo-o-higgins/report.html)
- `national-20261024c-07-maule`: success, 30 comunas, 106 findings, 80 drafts (output/national-20261024c-07-maule/report.html)
- `national-20261024c-08-biobio`: success, 33 comunas, 165 findings, 96 drafts (output/national-20261024c-08-biobio/report.html)
- `national-20261024c-09-la-araucania`: success, 32 comunas, 166 findings, 90 drafts (output/national-20261024c-09-la-araucania/report.html)
- `national-20261024c-10-los-lagos`: success, 30 comunas, 112 findings, 66 drafts (output/national-20261024c-10-los-lagos/report.html)
- `national-20261024c-11-aysen-del-general-carlos-ibanez-del-camp`: success, 10 comunas, 39 findings, 24 drafts (output/national-20261024c-11-aysen-del-general-carlos-ibanez-del-camp/report.html)
- `national-20261024c-12-magallanes-y-de-la-antartica-chilena`: success, 11 comunas, 53 findings, 32 drafts (output/national-20261024c-12-magallanes-y-de-la-antartica-chilena/report.html)
- `national-20261024c-13-metropolitana-de-santiago`: success, 52 comunas, 207 findings, 127 drafts (output/national-20261024c-13-metropolitana-de-santiago/report.html)
- `national-20261024c-14-los-rios`: success, 12 comunas, 47 findings, 27 drafts (output/national-20261024c-14-los-rios/report.html)
- `national-20261024c-15-arica-y-parinacota`: success, 4 comunas, 11 findings, 10 drafts (output/national-20261024c-15-arica-y-parinacota/report.html)
- `national-20261024c-16-nuble`: success, 21 comunas, 78 findings, 60 drafts (output/national-20261024c-16-nuble/report.html)
