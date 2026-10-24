-- =============================================================================
-- FactSync Chile: unified views over every source, keyed by comuna code (CUT).
-- Run as an ADMIN user after 01, 02 and 03. One statement per request.
--
--   official_population  every official INE figure with its series (the source the
--                        agents read it as), definition, scope and year: Census
--                        2024 and 2017 (series official_census), projections
--                        2002-2035 (official_projections), Census 2002
--                        (official_census2002), and the Census 2017 urban and
--                        rural population (official_census2017_area).
--   eswiki_infobox /     the population claim in each article's infobox (raw value,
--   enwiki_infobox       stated year, reference), extracted in SQL, next to the
--                        article text and revision, so one fetch serves both.
--   population_picture   one row per claim from every source (official INE,
--                        Wikidata, Wikipedia ES/EN), keyed by CUT, for exploring
--                        the whole picture in one query. The agents read the
--                        per-source views instead, one query per source.
--   source_catalog       every source the agents can read: its view, definition,
--                        scope and the years it covers, and whether a run reads it
--                        by default. The Planner reads it to plan a run, and to
--                        choose what to add when the Critic finds figures nothing
--                        read so far explains (discovery). Adding a source is one
--                        view plus one row here.
--
-- Gotchas: backslashes in regexes don't survive the trip to Zetaris's engine, so
-- the patterns avoid them ([ ] for a space, [|] for a pipe, [.,] for separators).
-- A query can't read the same REST-backed view twice (Spark reports a "resolved
-- attribute missing"), so the urban and rural rows come from one read, unpivoted
-- with stack().
-- Spanish ES article infoboxes use población / población_año / población_post;
-- English ones population_total / population_as_of / population_footnotes.
-- Other layouts (and the article body) are left to the Extractor agent.
-- =============================================================================

CREATE OR REPLACE SCHEMASTORE VIEW official_population WITH CONTAINER factsync AS
SELECT cut, comuna, 'official_census' AS series, 'INE Censo 2024' AS source, 'census' AS definition, 'comuna' AS scope, 2024 AS reference_year, cast(population AS bigint) AS population
FROM factsync.ine_census2024
UNION ALL
SELECT cut, comuna, 'official_census', 'INE Censo 2017', 'census', 'comuna', 2017, cast(population AS bigint)
FROM factsync.ine_census2017
UNION ALL
SELECT cut, comuna, 'official_projections', 'INE Proyecciones base 2017', 'projection', 'comuna', year, population
FROM factsync.ine_projections
UNION ALL
SELECT cut, comuna, 'official_census2002', 'INE Censo 2002', 'census', 'comuna', 2002, population
FROM factsync.ine_census2002
UNION ALL
SELECT cut, comuna, 'official_census2017_area', 'INE Censo 2017', 'census', area, 2017, cast(area_population AS bigint)
FROM factsync.ine_census2017_area
LATERAL VIEW stack(2, 'urban', urban, 'rural', rural) s AS area, area_population;

CREATE OR REPLACE SCHEMASTORE VIEW eswiki_infobox WITH CONTAINER factsync AS
SELECT
    cut,
    wikidata_item,
    title,
    revid,
    revision_timestamp,
    wikitext,
    trim(regexp_extract(wikitext, '(?m)^[ ]*[|][ ]*población[ ]*=[ ]*(.*)$', 1)) AS value_raw,
    trim(regexp_extract(wikitext, '(?m)^[ ]*[|][ ]*población_año[ ]*=[ ]*(.*)$', 1)) AS year_raw,
    trim(regexp_extract(wikitext, '(?m)^[ ]*[|][ ]*población_post[ ]*=[ ]*(.*)$', 1)) AS reference_raw
FROM factsync.eswiki_articles;

CREATE OR REPLACE SCHEMASTORE VIEW enwiki_infobox WITH CONTAINER factsync AS
SELECT
    cut,
    wikidata_item,
    title,
    revid,
    revision_timestamp,
    wikitext,
    trim(regexp_extract(wikitext, '(?m)^[ ]*[|][ ]*population_total[ ]*=[ ]*(.*)$', 1)) AS value_raw,
    trim(regexp_extract(wikitext, '(?m)^[ ]*[|][ ]*population_as_of[ ]*=[ ]*(.*)$', 1)) AS year_raw,
    trim(regexp_extract(wikitext, '(?m)^[ ]*[|][ ]*population_footnotes[ ]*=[ ]*(.*)$', 1)) AS reference_raw
FROM factsync.enwiki_articles;

CREATE OR REPLACE SCHEMASTORE VIEW population_picture WITH CONTAINER factsync AS
SELECT cut, source, 'official' AS source_kind,
       CASE WHEN scope = 'comuna' THEN definition ELSE concat(definition, ' ', scope) END AS stated_definition,
       cast(reference_year AS string) AS stated_year_raw, reference_year AS stated_year,
       cast(population AS string) AS value_raw, population AS value,
       cast(NULL AS string) AS claim_ref, cast(NULL AS string) AS reference_raw, cast(NULL AS string) AS rank
FROM factsync.official_population
UNION ALL
SELECT cut, 'Wikidata', 'commons', determination_method,
       point_in_time, cast(substr(point_in_time, 1, 4) AS int),
       population, cast(population AS bigint),
       statement_id, coalesce(reference_url, stated_in), rank
FROM factsync.wikidata_population
WHERE statement_id IS NOT NULL
UNION ALL
SELECT cut, 'Wikipedia ES', 'commons', cast(NULL AS string),
       year_raw, cast(regexp_extract(year_raw, '((19|20)[0-9]{2})', 1) AS int),
       value_raw,
       CASE WHEN regexp_replace(regexp_replace(regexp_replace(value_raw, '<ref.*$', ''), '&nbsp;', ''), '[ ]', '') RLIKE '^[0-9]{1,3}([.,][0-9]{3})+$|^[0-9]+$'
            THEN cast(regexp_replace(regexp_replace(regexp_replace(regexp_replace(value_raw, '<ref.*$', ''), '&nbsp;', ''), '[ ]', ''), '[.,]', '') AS bigint) END,
       cast(revid AS string), reference_raw, cast(NULL AS string)
FROM factsync.eswiki_infobox
UNION ALL
SELECT cut, 'Wikipedia EN', 'commons', cast(NULL AS string),
       year_raw, cast(regexp_extract(year_raw, '((19|20)[0-9]{2})', 1) AS int),
       value_raw,
       CASE WHEN regexp_replace(regexp_replace(regexp_replace(value_raw, '<ref.*$', ''), '&nbsp;', ''), '[ ]', '') RLIKE '^[0-9]{1,3}([.,][0-9]{3})+$|^[0-9]+$'
            THEN cast(regexp_replace(regexp_replace(regexp_replace(regexp_replace(value_raw, '<ref.*$', ''), '&nbsp;', ''), '[ ]', ''), '[.,]', '') AS bigint) END,
       cast(revid AS string), reference_raw, cast(NULL AS string)
FROM factsync.enwiki_infobox;

CREATE OR REPLACE SCHEMASTORE VIEW source_catalog WITH CONTAINER factsync AS
SELECT 'official_census' AS source_id, 'factsync.official_population' AS view, 'official' AS kind, 'census' AS definition,
       'comuna' AS scope, 2017 AS years_from, 2024 AS years_to, true AS in_default_plan,
       'INE census counts of each comuna, Census 2017 and Census 2024: the official headcount.' AS description
UNION ALL
SELECT 'official_projections', 'factsync.official_population', 'official', 'projection', 'comuna', 2002, 2035, false,
       'INE estimates and projections of each comuna for every year 2002 to 2035 (base Census 2017): official figures, but modelled estimates, not a headcount.'
UNION ALL
SELECT 'official_census2002', 'factsync.official_population', 'official', 'census', 'comuna', 2002, 2002, false,
       'INE Census 2002 count of each comuna, on current comuna boundaries (from the 2002 census database).'
UNION ALL
SELECT 'official_census2017_area', 'factsync.official_population', 'official', 'census', 'urban_rural', 2017, 2017, false,
       'INE Census 2017 urban and rural population of each comuna: parts of a comuna, not its total.'
UNION ALL
SELECT 'wikidata', 'factsync.wikidata_population', 'commons', cast(NULL AS string), 'comuna', cast(NULL AS int), cast(NULL AS int), true,
       'Wikidata population statements of each comuna, with point in time, determination method, rank and references.'
UNION ALL
SELECT 'wikipedia_es', 'factsync.eswiki_infobox', 'commons', cast(NULL AS string), 'comuna', cast(NULL AS int), cast(NULL AS int), true,
       'Spanish Wikipedia comuna articles: infobox figure, reference and article text.'
UNION ALL
SELECT 'wikipedia_en', 'factsync.enwiki_infobox', 'commons', cast(NULL AS string), 'comuna', cast(NULL AS int), cast(NULL AS int), true,
       'English Wikipedia comuna articles: infobox figure, reference and article text.';
