-- =============================================================================
-- FactSync Chile: exploratory queries, two or three per source, read with the
-- app's read-only user. Results: docs/zetaris/exploration.md, written by
--   .venv\Scripts\python scripts\zetaris_explore.py zetaris\06_explore_select.sql --out docs\zetaris\exploration.md
-- Each source is a factsync view over a Zetaris REST table (INE ArcGIS layers,
-- Wikidata SPARQL, the MediaWiki API) or a file-store table (INE files).
-- A query can't read the same REST-backed view twice, so none self-joins.
-- =============================================================================

-- ---- INE Census 2024 (ArcGIS REST layer) ----

-- Q: INE Census 2024: how many comunas, and how many people in all?
SELECT count(*) AS comunas, sum(cast(population AS bigint)) AS people
FROM factsync.ine_census2024;

-- Q: INE Census 2024: the five most populous comunas
SELECT cut, comuna, region, population
FROM factsync.ine_census2024
ORDER BY cast(population AS bigint) DESC
LIMIT 5;

-- Q: INE Census 2024: people per region
SELECT region, count(*) AS comunas, sum(cast(population AS bigint)) AS people
FROM factsync.ine_census2024
GROUP BY region
ORDER BY people DESC;

-- ---- INE Census 2017 (ArcGIS REST layer) ----

-- Q: INE Census 2017: how many comunas, and how many people in all?
SELECT count(*) AS comunas, sum(cast(population AS bigint)) AS people
FROM factsync.ine_census2017;

-- Q: Census 2017 to 2024: the comunas that lost the most people (two sources joined on the comuna code)
SELECT c24.cut, c24.comuna, c17.population AS census_2017, c24.population AS census_2024,
       cast(c24.population AS bigint) - cast(c17.population AS bigint) AS change
FROM factsync.ine_census2024 c24
JOIN factsync.ine_census2017 c17 ON c17.cut = c24.cut
ORDER BY change
LIMIT 5;

-- ---- INE estimates and projections 2002-2035, base 2017 (file store, CSV) ----

-- Q: INE projections: years, comunas and rows covered
SELECT min(year) AS first_year, max(year) AS last_year, count(DISTINCT cut) AS comunas, count(*) AS rows_
FROM factsync.ine_projections;

-- Q: INE projections vs Census 2024: where the 2024 projection overshot the count the most
SELECT p.cut, p.comuna, p.population AS projection_2024, c.population AS census_2024,
       p.population - cast(c.population AS bigint) AS overshoot
FROM factsync.ine_projections p
JOIN factsync.ine_census2024 c ON c.cut = p.cut
WHERE p.year = 2024
ORDER BY overshoot DESC
LIMIT 5;

-- ---- INE Census 2002, today's comunas (file store, CSV prepared from REDATAM) ----

-- Q: INE Census 2002: how many comunas, and how many people in all? (INE: 15,116,435)
SELECT count(*) AS comunas, sum(population) AS people
FROM factsync.ine_census2002;

-- Q: Census 2002 to 2024: the fastest-growing comunas
SELECT c.cut, c.comuna, o.population AS census_2002, c.population AS census_2024,
       round(cast(c.population AS double) / o.population, 2) AS ratio
FROM factsync.ine_census2024 c
JOIN factsync.ine_census2002 o ON o.cut = c.cut
WHERE o.population > 0
ORDER BY ratio DESC
LIMIT 5;

-- ---- INE Census 2017, urban and rural (ArcGIS REST layer) ----

-- Q: Census 2017 urban/rural: comunas covered and the national rural share
SELECT count(*) AS comunas, sum(cast(rural AS bigint)) AS rural, sum(cast(population AS bigint)) AS people,
       round(100.0 * sum(cast(rural AS bigint)) / sum(cast(population AS bigint)), 1) AS rural_pct
FROM factsync.ine_census2017_area;

-- Q: Census 2017 urban/rural: the most rural comunas
SELECT cut, comuna, rural, population, round(100.0 * cast(rural AS bigint) / cast(population AS bigint), 1) AS rural_pct
FROM factsync.ine_census2017_area
WHERE cast(population AS bigint) > 0
ORDER BY rural_pct DESC
LIMIT 5;

-- ---- Wikidata (SPARQL endpoint, REST) ----

-- Q: Wikidata: comuna items, population statements, and items with none
SELECT count(DISTINCT wikidata_item) AS items, count(statement_id) AS statements,
       count(DISTINCT CASE WHEN statement_id IS NULL THEN wikidata_item END) AS items_without_population
FROM factsync.wikidata_population;

-- Q: Wikidata: population statements by point-in-time year
SELECT substr(point_in_time, 1, 4) AS year, count(*) AS statements
FROM factsync.wikidata_population
WHERE statement_id IS NOT NULL
GROUP BY substr(point_in_time, 1, 4)
ORDER BY statements DESC
LIMIT 8;

-- Q: Wikidata: statement ranks, and how many carry a reference
SELECT rank, count(*) AS statements, count(coalesce(reference_url, stated_in)) AS with_reference
FROM factsync.wikidata_population
WHERE statement_id IS NOT NULL
GROUP BY rank;

-- ---- Wikipedia ES (MediaWiki API, REST, 50 titles per request) ----

-- Q: Spanish Wikipedia: articles read, and how many infoboxes have a population field
SELECT count(*) AS articles, count(CASE WHEN value_raw <> '' THEN 1 END) AS with_population
FROM factsync.eswiki_infobox;

-- Q: Spanish Wikipedia: the year each infobox gives for its population
SELECT regexp_extract(year_raw, '((19|20)[0-9]{2})', 1) AS year, count(*) AS infoboxes
FROM factsync.eswiki_infobox
GROUP BY regexp_extract(year_raw, '((19|20)[0-9]{2})', 1)
ORDER BY infoboxes DESC
LIMIT 6;

-- ---- Wikipedia EN (MediaWiki API, REST, 50 titles per request) ----

-- Q: English Wikipedia: articles read, and how many infoboxes have a population field
SELECT count(*) AS articles, count(CASE WHEN value_raw <> '' THEN 1 END) AS with_population
FROM factsync.enwiki_infobox;

-- Q: English Wikipedia: what the infoboxes say their figure is from
SELECT year_raw AS population_as_of, count(*) AS infoboxes
FROM factsync.enwiki_infobox
GROUP BY year_raw
ORDER BY infoboxes DESC
LIMIT 6;
