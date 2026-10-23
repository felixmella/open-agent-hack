-- =============================================================================
-- FactSync Chile: unified views over every source, keyed by comuna code (CUT).
-- Run as an ADMIN user after 01, 02 and 03. One statement per request.
--
--   official_population  every official INE figure (Census 2024, Census 2017,
--                        projections 2002-2035) with its definition and year.
--   eswiki_infobox /     the population claim in each article's infobox (raw value,
--   enwiki_infobox       stated year, reference), extracted in SQL, next to the
--                        article text and revision, so one fetch serves both.
--   population_picture   one row per claim from every source (official INE,
--                        Wikidata, Wikipedia ES/EN): the fragmented picture the
--                        agents reconcile, in one SQL access point.
--
-- Gotcha: backslashes in regexes don't survive the trip to Zetaris's engine, so
-- the patterns avoid them ([ ] for a space, [|] for a pipe, [.,] for separators).
-- Spanish ES article infoboxes use población / población_año / población_post;
-- English ones population_total / population_as_of / population_footnotes.
-- Other layouts (and the article body) are left to the Extractor agent.
-- =============================================================================

CREATE OR REPLACE SCHEMASTORE VIEW official_population WITH CONTAINER factsync AS
SELECT cut, comuna, 'INE Censo 2024' AS source, 'census' AS definition, 2024 AS reference_year, cast(population AS bigint) AS population
FROM factsync.ine_census2024
UNION ALL
SELECT cut, comuna, 'INE Censo 2017', 'census', 2017, cast(population AS bigint)
FROM factsync.ine_census2017
UNION ALL
SELECT cut, comuna, 'INE Proyecciones base 2017', 'projection', year, population
FROM factsync.ine_projections;

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
SELECT cut, source, 'official' AS source_kind, definition AS stated_definition,
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
