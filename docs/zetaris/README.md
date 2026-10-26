# Building with Zetaris: FactSync Chile's Unified Semantic Layer

This document follows the "Build with Zetaris" evaluation criteria: part 1 builds and checks the Unified Semantic Layer
(USL), part 2 reflects on it. Every query result referred to here was produced live, and is kept unedited in
[`exploration.md`](exploration.md) (sources) and [`usl.md`](usl.md) (the USL), written by `scripts/zetaris_explore.py`.

## 1a. The use case and its sources

**Use case.** Chile counted its population in 2024, but the public references most people read have not caught up:
666 of the 728 current population figures in Spanish and English Wikipedia and Wikidata are not INE's Census 2024
count. FactSync Chile's agents work out why each figure differs and draft a sourced correction for the volunteer
editors who maintain the 346 comuna pages. Answering "why does this figure differ?" needs every official series INE
has published and every figure the public sources show, side by side, keyed by comuna.

**Sources (10, of 3 kinds), all read live by Zetaris** (the last two for the second fact, mayors: part 1d):

| Source | Publisher | Kind | Zetaris object |
|---|---|---|---|
| Census 2024, by comuna | INE | ArcGIS REST layer | `factsync_rest.ine_census2024_raw` → `factsync.ine_census2024` |
| Census 2017, by comuna | INE | ArcGIS REST layer | `factsync.ine_census2017` |
| Census 2017, urban and rural | INE | ArcGIS REST layer | `factsync.ine_census2017_area` |
| Estimates and projections 2002–2035, base 2017 | INE | CSV in the file store (from INE's workbook) | `factsync_files.ine_projections_raw` → `factsync.ine_projections` |
| Census 2002, on today's comunas | INE | CSV in the file store (counted on INE's REDATAM server) | `factsync.ine_census2002` |
| Population statements | Wikidata | SPARQL endpoint, REST | `factsync.wikidata_population` |
| Comuna articles, Spanish | Wikipedia | MediaWiki API, REST, 6 tables of 50 titles | `factsync.eswiki_articles` → `factsync.eswiki_infobox` |
| Comuna articles, English | Wikipedia | MediaWiki API, REST, 6 tables of 50 titles | `factsync.enwiki_articles` → `factsync.enwiki_infobox` |
| Mayoral elections 2012, 2016, 2021, 2024: every candidate | SERVEL | CSV in the file store (from SERVEL's four workbooks) | `factsync_files.servel_alcaldes_raw` → `factsync.servel_mayors` |
| Head of government statements (P6) | Wikidata | SPARQL endpoint, REST | `factsync.wikidata_mayor` |

The DDL is in [`zetaris/`](../../zetaris/) (`01`–`04`), with a log of what was run and how each object was checked
against its source in [`zetaris/README.md`](../../zetaris/README.md).

## 1b. Onboarding, checks and exploration

Each source was registered as a Lightning REST or file-store table, flattened by a view (`LATERAL VIEW explode` over
the JSON), and checked by comparing its rows with a direct call to the source or with the CSV: for example Census
2024 has 346 comunas and 18,480,432 people, equal to INE's API, and Census 2002 has 346 comunas and 15,116,435 people,
the census's national count. The app reads them with a read-only General-role user, which `scripts/verify_readonly.py`
checks.

[`zetaris/06_explore_select.sql`](../../zetaris/06_explore_select.sql) asks 18 exploratory questions, two or three per
source, all through the read-only user. Results in [`exploration.md`](exploration.md). A few answers:

- INE's 2024 projection overshot the census count most in Santiago (544,388 projected, 438,856 counted) and Puente
  Alto: a projection is a different figure, which is why FactSync must tell the two apart.
- Sierra Gorda lost 86% of its people between the 2017 and 2024 censuses (10,186 to 1,472).
- Wikidata has 194 population statements for 355 comuna items, and 198 items have none; only 6 statements have
  preferred rank, and 55 carry a reference.
- 227 Spanish infoboxes date their figure 2017; English infoboxes mostly say "2012 Census", a census INE withdrew.

## 1c. The USL: `comuna_population`

**DDL:** [`zetaris/07_usl_create.sql`](../../zetaris/07_usl_create.sql). The USL lives in namespace
`lightning.metastore.factsync` and has three tables:

```sql
COMPILE USL IF NOT EXISTS comuna_population DEPLOY NAMESPACE lightning.metastore.factsync DDL
CREATE TABLE comuna (
    cut varchar(5) NOT NULL PRIMARY KEY,
    comuna varchar(100) NOT NULL,
    region varchar(100)
);
CREATE TABLE official_figure (
    figure_id varchar(80) NOT NULL PRIMARY KEY,
    cut varchar(5) NOT NULL FOREIGN KEY REFERENCES comuna(cut),
    series varchar(40) NOT NULL,
    source_name varchar(40),
    definition varchar(20),
    scope varchar(20),
    reference_year int,
    population bigint
);
CREATE TABLE population_claim (
    claim_id varchar(200) NOT NULL PRIMARY KEY,
    cut varchar(5) NOT NULL FOREIGN KEY REFERENCES comuna(cut),
    source_name varchar(20) NOT NULL,
    stated_year int,
    value_raw varchar(2000),
    value bigint,
    claim_ref varchar(100),
    rank varchar(20)
);
```

- `comuna` is INE's list of comunas: the system of record every other row must point to.
- `official_figure` holds every official INE figure; `population_claim` every figure the public sources publish.
- Each table is activated from the `factsync` view the agents already read, so the USL and the agents see the same
  governed SQL.
- **Data-quality rules:** the key and foreign-key constraints Zetaris generates from the DDL, plus three registered
  rules: `cut_is_code` (a five-digit comuna code), `population_positive` (official figures above zero) and
  `figure_is_a_number` (a published figure that can be read as a number).

**Verified.** Each USL table holds exactly the rows of the view it activates from: `comuna` 346, `official_figure`
13,492, `population_claim` 775 (Wikidata 194, Wikipedia ES 294, Wikipedia EN 287). Queries 1–6 in [`usl.md`](usl.md).

**The USL in use** (queries 7–10 in [`usl.md`](usl.md)):
- the official series it holds, with their definitions and years;
- how many Wikipedia infobox figures are INE's Census 2024 count: 32 of 281 in Spanish, 27 of 280 in English;
- what each infobox figure equals among INE's official figures, in one join: 200 of 281 Spanish infobox figures are the Census 2017 count, 25 an INE projection and 42 no official figure at all; in English, 33 are the 2002 count and 197 match no official figure (most are the withdrawn 2012 census);
- one comuna's whole picture, official and published, in one query (Hualqui: Spanish Wikipedia's 26,746 for 2024 is
  INE's 2024 projection, not the census count of 25,795).

**Data-quality rules, run** (queries 11–18 in [`usl.md`](usl.md)):

| Rule | Table | Kind | Records | Valid | Invalid | What the invalid records are |
|---|---|---|---:|---:|---:|---|
| `cut_is_code` | comuna | registered | 346 | 346 | 0 | |
| `population_positive` | official_figure | registered | 13,492 | 13,492 | 0 | (see below) |
| `figure_is_a_number` | population_claim | registered | 775 | 761 | 14 | Spanish infoboxes whose figure SQL can't read: `{{formatnum\|240000}}`, a stray tab, two figures split by `<br/>`, an HTML comment inside the field, empty fields |
| `cut` (foreign key) | population_claim | generated | 775 | 748 | 27 | claims from Wikidata comuna items that have no comuna code (P6929), and the articles linked to them |
| `claim_id` (primary key) | population_claim | generated | 775 | 757 | 18 | Wikidata statements listed more than once, one row per reference: the SPARQL view returns a row for each (query 17 shows Q13037's statement twice) |

The rules found real problems in the published data, and one in our own rule: the first `population_positive`
(`population > 0`) flagged 53 official figures, all real zeros (26 fully rural comunas have no urban population, 27
fully urban ones no rural population). The rule was corrected with `UPDATE DQ` to allow zero for an urban or rural
part, and now passes all 13,492. The 14 unreadable figures are why FactSync's Extractor re-reads an infobox from its
wikitext when SQL can't parse it; the 27 orphans are claims the agents never see, because a claim without a comuna
code can't be tied to an INE comuna.

## 1d. A second fact, a second USL: `comuna_mayor`

FactSync's claim is that the pattern fits any public fact that drifts from its system of record. The second fact is
each comuna's mayor, checked against SERVEL's election results. In Zetaris it took one file-store table, three views
and a second USL (`zetaris/08_mayors_create.sql`, `09_mayors_usl_create.sql`):

- `factsync.servel_mayors`: SERVEL's four mayoral elections, 5,403 candidates keyed by comuna code.
- `factsync.wikidata_mayor`: Wikidata's head of government statements, over SPARQL.
- `factsync.eswiki_mayor` and `enwiki_mayor`: the infobox mayor fields, extracted in SQL from the article views the
  population fact already reads (no new REST tables).
- `factsync.source_catalog` gained a `fact` column and seven rows. The Planner reads only the sources of the fact a
  run checks; the three earlier elections are read on demand, when a name needs explaining.

**DDL:** [`zetaris/09_mayors_usl_create.sql`](../../zetaris/09_mayors_usl_create.sql): tables `comuna`,
`election_result` (every candidate, with `first_surname`, votes and whether elected) and `mayor_claim` (who each public
source names), both with a foreign key to `comuna`. Foreign keys across two USLs are untested, so this USL has its own
copy of the comuna list. Four registered rules: `comuna_code_5_digits`, `votes_not_negative`, `elected_is_flag`, and
`mayor_named` (does the source name anyone?).

**Verified** ([`usl_mayors.md`](usl_mayors.md), queries 1–9): `election_result` holds the view's 1,164 / 1,213 /
1,450 / 1,576 candidates for 2012 / 2016 / 2021 / 2024, with 346 elected each year, and no comuna has other than
exactly one winner in any election (a check no row rule can express, so it is a query). `mayor_claim` holds 287
English, 294 Spanish and 355 Wikidata rows: 271, 285 and **5** of them name someone. Wikidata records a mayor for 5 of
355 comuna items.

**What SQL alone can and can't say** (query 11). Joining each infobox with the 2024 winner's first surname finds
107 of 264 English infoboxes and 235 of 274 Spanish ones that contain it. That is a first pass, and the agents need
more: the join can't tell a former mayor from a vandal, a nickname ("Max Luksic" for Maximiliano Luksic Lederer) from
another person, or a stand-in from a mistake, and it loses the 20 articles whose Wikidata item has no comuna code
(Rengo among them), which the agents match by name. Those judgments are the agents' work, on the same views.

**The second fact's data layer took about an hour**, from SERVEL's workbooks to a verified USL with its rules,
reusing everything the first fact had built: the file store and its upload script, the Wikipedia article views, the
catalog, the read-only user (its grant covers the new views; `scripts/verify_readonly.py` checks all ten). The one
surprise: Zetaris infers a REST table's JSON fields from the live answer, so a field no Wikidata statement uses yet
(`statedIn`) doesn't exist, and the view must not name it (`FIELD_NOT_FOUND`).

## 2a. Time saved against a hand-coded approach

**What it took with Zetaris.** The data layer behind the agents (four SQL files: two INE ArcGIS layers, the Wikidata
endpoint, 12 MediaWiki batch tables, the unified views) was written and checked in about 90 minutes on the evening of
Oct 22 (commits `2bf1491` to `d43195b`). Later additions were each a view plus a catalog row: Census 2002 and the
urban/rural split, the source catalog, and this USL. The agents' Retriever is one generic query per source, with no
per-source client code.

**A hand-coded part, for comparison.** [`hand_coded_comparison.py`](hand_coded_comparison.py) answers one question the
USL answers in one query (query 8 in [`usl.md`](usl.md)): how many Spanish infobox figures are INE's Census 2024 count.
It needs 52 lines of Python: three HTTP APIs with three response formats, batching of 50 titles, the wikitext field
regex, number parsing, and a join on the comuna code done in a dictionary. It found 281 infobox figures, 32 of them
the Census 2024 count and 249 something else: exactly the USL's answer. The USL answer is a 9-line `SELECT` over two
tables with keys, and every other question about the same data reuses the same tables, rules included.

The hand-coded script was faster (14 seconds against about 80 for the USL query), because it fetches only what this
one question needs, while every USL query re-reads all its live sources: the case for the snapshot requirement in 2c.

**Our estimate.** Hand-coding the whole data layer (clients for each API with retries and batching, a local store,
joins, a read-only access path, and data-quality checks) would have taken two to three days; with Zetaris it took
about a day spread over the week, including the platform's learning curve. The bigger saving is in what follows: a new
official source is a view and a catalog row, so the agents learned Census 2002 and the urban/rural split without a
line of client code.

**Where it cost time.** About two hours went on platform gotchas (part 2c), and queries over REST-backed views re-read
the APIs every time (15–20 s for each Wikipedia view), which a hand-coded cache would avoid.

## 2b. Where a USL helps, and where it doesn't, in this kind of work

I'm a student, so "my work" is projects like this one: combining public datasets that were never meant to be joined,
and explaining where they disagree. For that, a USL replaces most of the glue code I would otherwise write for every
project, and leaves the interesting part, the reasoning about why sources differ.

**It helps** wherever someone maintains reference data against a system of record and has to explain the
differences:
- one schema with declared keys across public APIs, files and databases, instead of one client per source;
- foreign keys that make orphans visible: a published figure whose comuna code INE doesn't know fails a rule instead
  of vanishing in a join;
- rules that run where the data lives, so the same checks apply to every consumer, agents included;
- descriptions on every table, which an agent's planner can read.

**It doesn't help (yet)** with:
- history: FactSync's "since the last check" needs to know what a page said last week, and the USL only knows now,
  so the history lives in the app's World Model engine;
- slow live sources: every query re-reads the APIs, which makes interactive exploration slow;
- free text: extracting the figure a sentence states is reading, not SQL, and stays with the Extractor agent and
  Nemotron.

**A project that benefited:** we forecast that a second fact's data layer would take half a day with the USL instead of
two to three days by hand. We then built it: Chile's mayors, against SERVEL's election results (part 1d). It took
about an hour, because everything the first fact built was reused. The next fact anyone would add, here or in a
company wiki checked against its ERP, is the same shape: a table keyed to the system of record, and a rule or two.

## 2c. Making the USL stronger: a requirement

**Requirement: snapshots and history for USL tables over live sources.**

*Problem.* A USL table over a REST source is always "now". Agents that check facts need yesterday too: what did this
page say at the last check, which rows changed, and did the data-quality results get better or worse? Today each team
builds that history outside Zetaris (FactSync built it in its World Model engine), and every query re-reads the
source APIs, which makes queries slow and results irreproducible.

*Proposal.*
- `SNAPSHOT USL TABLE <table>` stores the activated rows with `snapshot_id`, `taken_at` and per-row provenance (source
  URL, fetch time, ETag or revision).
- `SELECT ... FROM <table> AS OF SNAPSHOT <id> | TIMESTAMP <t>` reads a snapshot.
- `DIFF USL TABLE <table> BETWEEN <a> AND <b>` returns added, removed and changed rows by primary key.
- `RUN DQ ... AS OF SNAPSHOT <id>` keeps data-quality results per snapshot, so a dashboard can chart them.
- A schedule (`REFRESH ... EVERY 1 DAY`) and a retention policy.

*Why it matters.* It turns a USL into an auditable record: an agent can cite the snapshot its evidence came from, a
reviewer can reproduce it, and "what changed since the last check" becomes one query. It also makes slow API sources
fast to query.

*Smaller fixes we'd ask for, all hit in this project:*
- The USL DDL rejects a column named `source` with "Invalid DDL statement" and no position; name the offending
  token.
- REST tables need pagination and batching: the MediaWiki API takes 50 titles per request, so we generated 12 tables
  and a `UNION ALL`.
- A query can't read the same REST-backed view twice (Spark's "resolved attribute missing").
- Backslashes in regular expressions don't survive the trip to the engine.
- Every value comes back as a string over the REST API.
- Praise where due: activation's schema check names each mismatched column and suggests the exact `COALESCE` fix.

*Mock of the feature on this USL:*

```sql
SNAPSHOT USL TABLE lightning.metastore.factsync.comuna_population.population_claim;
SELECT d.change, d.cut, d.before_value, d.after_value
FROM DIFF USL TABLE lightning.metastore.factsync.comuna_population.population_claim
     BETWEEN SNAPSHOT 'national-20261024' AND SNAPSHOT 'example_5-20261026' d
WHERE d.change = 'changed';
-- would return, for example, Rengo's Spanish infobox: 58825 -> 63620
```
