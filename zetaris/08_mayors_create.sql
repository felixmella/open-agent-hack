-- =============================================================================
-- FactSync Chile: the second fact, mayors. SERVEL's mayoral election results
-- 2012-2024, and what Wikidata and the Spanish and English Wikipedias say about
-- each comuna's mayor; plus the source catalog of both facts.
-- Run as an ADMIN user after 01-04. One statement per request.
--
-- Sources
--   SERVEL (Servicio Electoral de Chile), mayoral elections of Oct 28, 2012,
--     Oct 23, 2016, May 15-16, 2021 and Oct 26-27, 2024: every candidate in
--     every comuna, with list, pact, party, votes and who was elected. Read
--     from SERVEL's workbooks by scripts/prepare_servel_mayors.py into
--     data/official/servel_alcaldes_2012_2024.csv (5,403 candidates; each
--     comuna name resolved to its CUT), copied into the file store by
--     scripts/upload_filestore.py (run both first).
--   Wikidata: SPARQL over all current communes of Chile (Q1840161) with every
--     head of government statement (P6): the person and its Spanish and
--     English labels, start and end time, rank and references. CC0.
--     Wikimedia requires an identifying User-Agent: replace the placeholder.
--   Wikipedia ES/EN: the mayor fields of each article's infobox, extracted in
--     SQL from the articles registered by 03 (ES Ficha de entidad subnacional:
--     dirigentes_títulos / dirigentes_nombres; EN Infobox settlement:
--     leader_title / leader_name / leader_party), next to the article text.
--
-- What SERVEL says is who was ELECTED. It doesn't say who holds the office today:
-- resignations, removals, deaths and stand-ins don't appear in it.
--
-- source_catalog moves here from 04 and gains a `fact` column (population or
-- mayor): the Planner reads only the sources of the fact a run checks.
-- =============================================================================

CREATE LIGHTNING FILESTORE TABLE servel_alcaldes_raw FROM FACTSYNC_FILES FORMAT CSV OPTIONS (
    path "dffs://factsync/servel_alcaldes_2012_2024.csv",
    header "true",
    inferSchema "true"
);

CREATE OR REPLACE SCHEMASTORE VIEW servel_mayors WITH CONTAINER factsync AS
SELECT
    cast(year AS int) AS year,
    cast(to_date(cast(election_date AS string)) AS string) AS election_date,
    lpad(cast(cut AS string), 5, '0') AS cut,
    comuna,
    comuna_servel,
    region,
    cast(lista AS string) AS lista,
    pacto,
    partido,
    nombres,
    primer_apellido,
    segundo_apellido,
    cast(votos AS bigint) AS votos,
    cast(elected AS boolean) AS elected
FROM factsync_files.servel_alcaldes_raw;

CREATE LIGHTNING REST TABLE wikidata_mayor_raw FROM FACTSYNC_REST REQUEST(
    endpoint "https://query.wikidata.org/sparql?query=SELECT+%3Fcomuna+%3Fcut+%3Flabel_es+%3Fst+%3Fperson+%3Fperson_es+%3Fperson_en+%3Fstart+%3Fend+%3Frank+%3FrefURL+%3FstatedIn+WHERE+%7B+%3Fcomuna+wdt%3AP31+wd%3AQ1840161.+FILTER+NOT+EXISTS+%7B+%3Fcomuna+wdt%3AP576+%3Fdissolved+%7D+OPTIONAL+%7B+%3Fcomuna+wdt%3AP6929+%3Fcut+%7D+OPTIONAL+%7B+%3Fcomuna+rdfs%3Alabel+%3Flabel_es+FILTER%28lang%28%3Flabel_es%29%3D%27es%27%29+%7D+OPTIONAL+%7B+%3Fcomuna+p%3AP6+%3Fst.+%3Fst+ps%3AP6+%3Fperson%3B+wikibase%3Arank+%3Frank.+OPTIONAL+%7B+%3Fperson+rdfs%3Alabel+%3Fperson_es+FILTER%28lang%28%3Fperson_es%29%3D%27es%27%29+%7D+OPTIONAL+%7B+%3Fperson+rdfs%3Alabel+%3Fperson_en+FILTER%28lang%28%3Fperson_en%29%3D%27en%27%29+%7D+OPTIONAL+%7B+%3Fst+pq%3AP580+%3Fstart+%7D+OPTIONAL+%7B+%3Fst+pq%3AP582+%3Fend+%7D+OPTIONAL+%7B+%3Fst+prov%3AwasDerivedFrom+%3Fref.+OPTIONAL+%7B+%3Fref+pr%3AP854+%3FrefURL+%7D+OPTIONAL+%7B+%3Fref+pr%3AP248+%3FstatedIn+%7D+%7D+%7D+%7D&format=json",
    method "get",
    response_type "json",
    http_encoding "URLENCODED"
) HEADER (
    user-agent "YOUR_APP_NAME YOUR_CONTACT_EMAIL"
) BODY ();

CREATE OR REPLACE SCHEMASTORE VIEW wikidata_mayor WITH CONTAINER factsync AS
SELECT
    b.comuna.value AS wikidata_item,
    b.cut.value AS cut,
    b.label_es.value AS label_es,
    b.st.value AS statement_id,
    b.person.value AS person_item,
    b.person_es.value AS person_label_es,
    b.person_en.value AS person_label_en,
    substr(b.start.value, 1, 10) AS start_time,
    substr(b.end.value, 1, 10) AS end_time,
    regexp_extract(b.rank.value, '#(.*)$', 1) AS rank,
    b.refURL.value AS reference_url,
    -- Zetaris infers the JSON's fields from the live answer, and no P6 statement has a "stated in" (P248)
    -- reference yet, so the field doesn't exist (FIELD_NOT_FOUND): kept as NULL until one does.
    cast(NULL AS string) AS stated_in
FROM factsync_rest.wikidata_mayor_raw
LATERAL VIEW explode(results.bindings) AS b;

CREATE OR REPLACE SCHEMASTORE VIEW eswiki_mayor WITH CONTAINER factsync AS
SELECT
    cut,
    wikidata_item,
    title,
    revid,
    revision_timestamp,
    wikitext,
    trim(regexp_extract(wikitext, '(?m)^[ ]*[|][ ]*dirigentes_títulos[ ]*=[ ]*(.*)$', 1)) AS office_raw,
    trim(regexp_extract(wikitext, '(?m)^[ ]*[|][ ]*dirigentes_nombres[ ]*=[ ]*(.*)$', 1)) AS name_raw,
    cast(NULL AS string) AS party_raw
FROM factsync.eswiki_articles;

CREATE OR REPLACE SCHEMASTORE VIEW enwiki_mayor WITH CONTAINER factsync AS
SELECT
    cut,
    wikidata_item,
    title,
    revid,
    revision_timestamp,
    wikitext,
    trim(regexp_extract(wikitext, '(?m)^[ ]*[|][ ]*leader_title[ ]*=[ ]*(.*)$', 1)) AS office_raw,
    trim(regexp_extract(wikitext, '(?m)^[ ]*[|][ ]*leader_name[ ]*=[ ]*(.*)$', 1)) AS name_raw,
    trim(regexp_extract(wikitext, '(?m)^[ ]*[|][ ]*leader_party[ ]*=[ ]*(.*)$', 1)) AS party_raw
FROM factsync.enwiki_articles;

CREATE OR REPLACE SCHEMASTORE VIEW source_catalog WITH CONTAINER factsync AS
SELECT 'official_census' AS source_id, 'population' AS fact, 'factsync.official_population' AS view, 'official' AS kind, 'census' AS definition,
       'comuna' AS scope, 2017 AS years_from, 2024 AS years_to, true AS in_default_plan,
       'INE census counts of each comuna, Census 2017 and Census 2024: the official headcount.' AS description
UNION ALL
SELECT 'official_projections', 'population', 'factsync.official_population', 'official', 'projection', 'comuna', 2002, 2035, false,
       'INE estimates and projections of each comuna for every year 2002 to 2035 (base Census 2017): official figures, but modelled estimates, not a headcount.'
UNION ALL
SELECT 'official_census2002', 'population', 'factsync.official_population', 'official', 'census', 'comuna', 2002, 2002, false,
       'INE Census 2002 count of each comuna, on current comuna boundaries (from the 2002 census database).'
UNION ALL
SELECT 'official_census2017_area', 'population', 'factsync.official_population', 'official', 'census', 'urban_rural', 2017, 2017, false,
       'INE Census 2017 urban and rural population of each comuna: parts of a comuna, not its total.'
UNION ALL
SELECT 'wikidata', 'population', 'factsync.wikidata_population', 'commons', cast(NULL AS string), 'comuna', cast(NULL AS int), cast(NULL AS int), true,
       'Wikidata population statements of each comuna, with point in time, determination method, rank and references.'
UNION ALL
SELECT 'wikipedia_es', 'population', 'factsync.eswiki_infobox', 'commons', cast(NULL AS string), 'comuna', cast(NULL AS int), cast(NULL AS int), true,
       'Spanish Wikipedia comuna articles: infobox figure, reference and article text.'
UNION ALL
SELECT 'wikipedia_en', 'population', 'factsync.enwiki_infobox', 'commons', cast(NULL AS string), 'comuna', cast(NULL AS int), cast(NULL AS int), true,
       'English Wikipedia comuna articles: infobox figure, reference and article text.'
UNION ALL
SELECT 'servel_mayors_2024', 'mayor', 'factsync.servel_mayors', 'official', 'election', 'comuna', 2024, 2024, true,
       'SERVEL results of the mayoral election of Oct 26-27, 2024 in each comuna: every candidate, party and votes, and who was elected (term from Dec 6, 2024).'
UNION ALL
SELECT 'servel_mayors_2021', 'mayor', 'factsync.servel_mayors', 'official', 'election', 'comuna', 2021, 2021, false,
       'SERVEL results of the mayoral election of May 15-16, 2021 in each comuna: every candidate, party and votes, and who was elected (term Jun 28, 2021 to Dec 6, 2024).'
UNION ALL
SELECT 'servel_mayors_2016', 'mayor', 'factsync.servel_mayors', 'official', 'election', 'comuna', 2016, 2016, false,
       'SERVEL results of the mayoral election of Oct 23, 2016 in each comuna: every candidate, party and votes, and who was elected (term Dec 6, 2016 to Jun 28, 2021).'
UNION ALL
SELECT 'servel_mayors_2012', 'mayor', 'factsync.servel_mayors', 'official', 'election', 'comuna', 2012, 2012, false,
       'SERVEL results of the mayoral election of Oct 28, 2012 in each comuna: every candidate, party and votes, and who was elected (term Dec 6, 2012 to Dec 6, 2016).'
UNION ALL
SELECT 'wikidata_mayor', 'mayor', 'factsync.wikidata_mayor', 'commons', cast(NULL AS string), 'comuna', cast(NULL AS int), cast(NULL AS int), true,
       'Wikidata head of government statements (P6) of each comuna, with the person, start and end time, rank and references.'
UNION ALL
SELECT 'wikipedia_es_mayor', 'mayor', 'factsync.eswiki_mayor', 'commons', cast(NULL AS string), 'comuna', cast(NULL AS int), cast(NULL AS int), true,
       'Spanish Wikipedia comuna articles: the mayor named in the infobox (dirigentes_nombres), and the article text.'
UNION ALL
SELECT 'wikipedia_en_mayor', 'mayor', 'factsync.enwiki_mayor', 'commons', cast(NULL AS string), 'comuna', cast(NULL AS int), cast(NULL AS int), true,
       'English Wikipedia comuna articles: the mayor named in the infobox (leader_name, leader_party), and the article text.';
