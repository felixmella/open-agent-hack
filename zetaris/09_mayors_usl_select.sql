-- =============================================================================
-- FactSync Chile: checks and queries on the USL comuna_mayor
-- (09_mayors_usl_create.sql). Results: docs/zetaris/usl_mayors.md, written by
--   .venv\Scripts\python scripts\zetaris_explore.py zetaris\09_mayors_usl_select.sql --admin --out docs\zetaris\usl_mayors.md
-- USL and DQ commands run as admin.
-- =============================================================================

-- Verification: each USL table must hold as many rows as the factsync views it
-- activates from. One count per query (a query can't read the same REST-backed
-- view twice).

-- Q: Verify: rows in the USL table comuna
SELECT count(*) AS usl_rows FROM lightning.metastore.factsync.comuna_mayor.comuna;

-- Q: Verify: rows in its view, factsync.ine_census2024
SELECT count(*) AS view_rows FROM factsync.ine_census2024;

-- Q: Verify: rows in the USL table election_result, by election
SELECT election_year, count(*) AS candidates, sum(CASE WHEN elected = 'true' THEN 1 ELSE 0 END) AS elected
FROM lightning.metastore.factsync.comuna_mayor.election_result
GROUP BY election_year ORDER BY election_year;

-- Q: Verify: rows in its view, factsync.servel_mayors, by election (the CSV has 1,164 / 1,213 / 1,450 / 1,576)
SELECT year, count(*) AS candidates, sum(CASE WHEN elected THEN 1 ELSE 0 END) AS elected
FROM factsync.servel_mayors
GROUP BY year ORDER BY year;

-- Q: Verify: rows in the USL table mayor_claim, by source
SELECT source_name, count(*) AS usl_rows, sum(CASE WHEN name_raw IS NOT NULL AND trim(name_raw) <> '' THEN 1 ELSE 0 END) AS naming_someone
FROM lightning.metastore.factsync.comuna_mayor.mayor_claim
GROUP BY source_name ORDER BY source_name;

-- Q: Verify: articles in factsync.eswiki_mayor
SELECT count(*) AS view_rows FROM factsync.eswiki_mayor;

-- Q: Verify: articles in factsync.enwiki_mayor
SELECT count(*) AS view_rows FROM factsync.enwiki_mayor;

-- Q: Verify: Wikidata comuna items and head of government statements in factsync.wikidata_mayor
SELECT count(DISTINCT wikidata_item) AS items, count(DISTINCT statement_id) AS statements FROM factsync.wikidata_mayor;

-- Q: Data quality: exactly one winner per comuna and election (no row expected)
SELECT cut, election_year, sum(CASE WHEN elected = 'true' THEN 1 ELSE 0 END) AS winners
FROM lightning.metastore.factsync.comuna_mayor.election_result
GROUP BY cut, election_year
HAVING sum(CASE WHEN elected = 'true' THEN 1 ELSE 0 END) <> 1;

-- Q: USL in use: re-elected or new? 2024's mayors by how many of the four elections they won
SELECT terms_won, count(*) AS mayors_elected_in_2024
FROM (
  SELECT w.cut, count(DISTINCT e.election_year) AS terms_won
  FROM lightning.metastore.factsync.comuna_mayor.election_result w
  JOIN lightning.metastore.factsync.comuna_mayor.election_result e
    ON e.cut = w.cut AND e.candidate = w.candidate AND e.elected = 'true'
  WHERE w.election_year = 2024 AND w.elected = 'true'
  GROUP BY w.cut
) t
GROUP BY terms_won ORDER BY terms_won;

-- Q: USL in use: does each infobox name the 2024 winner's first surname? (a first pass in SQL alone; the agents decide who the name is)
SELECT c.source_name, count(*) AS infoboxes,
       sum(CASE WHEN c.name_raw IS NULL OR trim(c.name_raw) = '' THEN 1 ELSE 0 END) AS name_no_one,
       sum(CASE WHEN instr(translate(upper(c.name_raw), 'ÁÉÍÓÚÜÑ', 'AEIOUUN'), w.surname) > 0 THEN 1 ELSE 0 END) AS has_winners_surname,
       sum(CASE WHEN trim(coalesce(c.name_raw, '')) <> '' AND instr(translate(upper(c.name_raw), 'ÁÉÍÓÚÜÑ', 'AEIOUUN'), w.surname) = 0 THEN 1 ELSE 0 END) AS someone_else
FROM lightning.metastore.factsync.comuna_mayor.mayor_claim c
JOIN (SELECT cut, first_surname AS surname
      FROM lightning.metastore.factsync.comuna_mayor.election_result
      WHERE election_year = 2024 AND elected = 'true') w
  ON w.cut = c.cut
WHERE c.source_name IN ('Wikipedia ES', 'Wikipedia EN')
GROUP BY c.source_name;

-- Q: USL in use: one comuna's whole picture (Rengo), elected and published
SELECT 'elected' AS side, cast(election_year AS string) AS year_, candidate AS name, cast(votes AS string) AS votes
FROM lightning.metastore.factsync.comuna_mayor.election_result
WHERE cut = '06115' AND elected = 'true'
UNION ALL
SELECT 'published', source_name, name_raw, claim_ref
FROM lightning.metastore.factsync.comuna_mayor.mayor_claim
WHERE cut = '06115';

-- Q: Data quality: the rules on the USL (key and foreign-key constraints, and the registered rules)
LIST DQ USL lightning.metastore.factsync.comuna_mayor;

-- Q: Data quality: run comuna_code_5_digits on comuna
RUN DQ comuna_code_5_digits TABLE lightning.metastore.factsync.comuna_mayor.comuna;

-- Q: Data quality: run votes_not_negative on election_result
RUN DQ votes_not_negative TABLE lightning.metastore.factsync.comuna_mayor.election_result;

-- Q: Data quality: run elected_is_flag on election_result
RUN DQ elected_is_flag TABLE lightning.metastore.factsync.comuna_mayor.election_result;

-- Q: Data quality: run mayor_named on mayor_claim (does the source name anyone?)
RUN DQ mayor_named TABLE lightning.metastore.factsync.comuna_mayor.mayor_claim;

-- Q: Data quality: the claims that name no one
SHOW DQ INVALID RECORD mayor_named TABLE lightning.metastore.factsync.comuna_mayor.mayor_claim;

-- Q: Data quality: run the foreign key mayor_claim.cut -> comuna.cut (does every claim belong to an INE comuna?)
RUN DQ cut TABLE lightning.metastore.factsync.comuna_mayor.mayor_claim;

-- Q: Data quality: run the foreign key election_result.cut -> comuna.cut
RUN DQ cut TABLE lightning.metastore.factsync.comuna_mayor.election_result;

-- Q: Data quality: run the primary key of election_result (is every candidate listed once per election?)
RUN DQ result_id TABLE lightning.metastore.factsync.comuna_mayor.election_result;
