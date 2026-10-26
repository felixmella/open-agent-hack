-- =============================================================================
-- FactSync Chile: checks and queries on the USL comuna_population
-- (07_usl_create.sql). Results: docs/zetaris/usl.md, written by
--   .venv\Scripts\python scripts\zetaris_explore.py zetaris\07_usl_select.sql --admin --out docs\zetaris\usl.md
-- USL and DQ commands run as admin.
-- =============================================================================

-- Verification: each USL table must hold as many rows as the factsync view it
-- activates from. One count per query: a query can't read the same REST-backed
-- view twice, directly and through the USL table activated from it.

-- Q: Verify: rows in the USL table comuna
SELECT count(*) AS usl_rows FROM lightning.metastore.factsync.comuna_population.comuna;

-- Q: Verify: rows in its view, factsync.ine_census2024
SELECT count(*) AS view_rows FROM factsync.ine_census2024;

-- Q: Verify: rows in the USL table official_figure
SELECT count(*) AS usl_rows FROM lightning.metastore.factsync.comuna_population.official_figure;

-- Q: Verify: rows in its view, factsync.official_population
SELECT count(*) AS view_rows FROM factsync.official_population;

-- Q: Verify: rows in the USL table population_claim, by source
SELECT source_name, count(*) AS usl_rows
FROM lightning.metastore.factsync.comuna_population.population_claim
GROUP BY source_name ORDER BY source_name;

-- Q: Verify: rows in its view, factsync.population_picture (published claims), by source
SELECT source, count(*) AS view_rows
FROM factsync.population_picture
WHERE source_kind = 'commons'
GROUP BY source ORDER BY source;

-- Q: USL in use: the official figures by series and definition
SELECT series, definition, scope, min(reference_year) AS from_year, max(reference_year) AS to_year, count(*) AS figures
FROM lightning.metastore.factsync.comuna_population.official_figure
GROUP BY series, definition, scope
ORDER BY series, scope;

-- Q: USL in use: how many Wikipedia infobox figures are, and aren't, INE's Census 2024 count
SELECT c.source_name, count(*) AS infobox_figures,
       sum(CASE WHEN c.value = f.population THEN 1 ELSE 0 END) AS census_2024_count,
       sum(CASE WHEN c.value IS NULL OR c.value <> f.population THEN 1 ELSE 0 END) AS something_else
FROM lightning.metastore.factsync.comuna_population.population_claim c
JOIN lightning.metastore.factsync.comuna_population.official_figure f
  ON f.cut = c.cut AND f.series = 'official_census' AND f.reference_year = 2024
WHERE c.source_name IN ('Wikipedia ES', 'Wikipedia EN')
GROUP BY c.source_name;

-- Q: USL in use: what each infobox figure equals among INE's official figures (the "why" in one join)
SELECT c.source_name,
       CASE WHEN f.series IS NULL THEN 'no official figure'
            WHEN f.series = 'official_projections' THEN 'an INE projection'
            ELSE concat(f.source_name, ' count') END AS equals,
       count(*) AS infobox_figures
FROM lightning.metastore.factsync.comuna_population.population_claim c
LEFT JOIN lightning.metastore.factsync.comuna_population.official_figure f
  ON f.cut = c.cut AND f.population = c.value AND f.scope = 'comuna'
WHERE c.source_name IN ('Wikipedia ES', 'Wikipedia EN')
GROUP BY c.source_name,
       CASE WHEN f.series IS NULL THEN 'no official figure'
            WHEN f.series = 'official_projections' THEN 'an INE projection'
            ELSE concat(f.source_name, ' count') END
ORDER BY c.source_name, infobox_figures DESC;

-- Q: USL in use: one comuna's whole picture (Hualqui), official and published
SELECT 'official' AS side, source_name, cast(reference_year AS string) AS year_, cast(population AS string) AS figure
FROM lightning.metastore.factsync.comuna_population.official_figure
WHERE cut = '08105' AND (reference_year IN (2002, 2017, 2024) AND scope = 'comuna')
UNION ALL
SELECT 'published', source_name, cast(stated_year AS string), value_raw
FROM lightning.metastore.factsync.comuna_population.population_claim
WHERE cut = '08105';

-- Q: Data quality: the rules on the USL (key and foreign-key constraints, and the registered rules)
LIST DQ USL lightning.metastore.factsync.comuna_population;

-- Q: Data quality: run cut_is_code on comuna (a five-digit code)
RUN DQ cut_is_code TABLE lightning.metastore.factsync.comuna_population.comuna;

-- Q: Data quality: run population_positive on official_figure (above zero; zero allowed for an urban or rural part)
RUN DQ population_positive TABLE lightning.metastore.factsync.comuna_population.official_figure;

-- Q: Data quality: run figure_is_a_number on population_claim (can the published figure be read as a number?)
RUN DQ figure_is_a_number TABLE lightning.metastore.factsync.comuna_population.population_claim;

-- Q: Data quality: the published figures that fail figure_is_a_number
SHOW DQ INVALID RECORD figure_is_a_number TABLE lightning.metastore.factsync.comuna_population.population_claim;

-- Q: Data quality: run the foreign key population_claim.cut -> comuna.cut (does every claim belong to an INE comuna?)
RUN DQ cut TABLE lightning.metastore.factsync.comuna_population.population_claim;

-- Q: Data quality: the claims that fail the foreign key
SHOW DQ INVALID RECORD cut TABLE lightning.metastore.factsync.comuna_population.population_claim;

-- Q: Data quality: run the primary key of population_claim (is every claim listed once?)
RUN DQ claim_id TABLE lightning.metastore.factsync.comuna_population.population_claim;
