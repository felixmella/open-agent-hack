-- =============================================================================
-- FactSync Chile: register the official and Wikimedia sources in Zetaris.
-- Run as an ADMIN user (CREATE statements are admin-only). One statement per
-- request. The app itself later queries the views with a read-only user.
--
-- Sources
--   INE Census 2024, population by comuna: INE's public ArcGIS feature layer
--     COMUNA_DPA_INDICADORES (346 rows, keyed by CUT), the layer behind INE's
--     official census dashboard. Licence: INE open data terms
--     (https://www.ine.gob.cl/terminos-de-uso-y-licencia-de-datos-abiertos).
--   Wikidata: SPARQL over all current (not dissolved) communes of Chile
--     (Q1840161) with every population statement (P1082) and its point in
--     time, determination method, rank and references. CC0.
--     Wikimedia requires an identifying User-Agent: replace the placeholder.
-- =============================================================================

CREATE LIGHTNING DATABASE FACTSYNC_REST DESCRIBE BY "FactSync Chile REST sources, INE Census 2024 and Wikidata";

CREATE SCHEMASTORE CONTAINER factsync;

CREATE LIGHTNING REST TABLE ine_census2024_raw FROM FACTSYNC_REST REQUEST(
    endpoint "https://services5.arcgis.com/hUyD8u3TeZLKPe4T/arcgis/rest/services/CENSO2024_V2_gdb/FeatureServer/0/query?where=1%3D1&returnGeometry=false&f=json&outFields=CUT%2CREGION%2CPROVINCIA%2CCOMUNA%2CInd_005_TPob%2CInd_006_THom%2CInd_007_TMuj%2CInd_001_TViv%2CInd_002_THog",
    method "get",
    response_type "json",
    http_encoding "URLENCODED"
) HEADER (
) BODY ();

CREATE SCHEMASTORE VIEW ine_census2024 WITH CONTAINER factsync AS
SELECT
    lpad(cast(f.attributes.CUT AS string), 5, '0') AS cut,
    f.attributes.COMUNA AS comuna,
    f.attributes.REGION AS region,
    f.attributes.Ind_005_TPob AS population,
    f.attributes.Ind_006_THom AS men,
    f.attributes.Ind_007_TMuj AS women,
    f.attributes.Ind_001_TViv AS dwellings,
    f.attributes.Ind_002_THog AS households
FROM factsync_rest.ine_census2024_raw
LATERAL VIEW explode(features) AS f;

CREATE LIGHTNING REST TABLE wikidata_population_raw FROM FACTSYNC_REST REQUEST(
    endpoint "https://query.wikidata.org/sparql?query=SELECT+%3Fcomuna+%3Fcut+%3Flabel_es+%3Fst+%3Fpop+%3Ftime+%3Fmethod+%3Frank+%3FrefURL+%3FstatedIn+WHERE+%7B+%3Fcomuna+wdt%3AP31+wd%3AQ1840161.+FILTER+NOT+EXISTS+%7B+%3Fcomuna+wdt%3AP576+%3Fdissolved+%7D+OPTIONAL+%7B+%3Fcomuna+wdt%3AP6929+%3Fcut+%7D+OPTIONAL+%7B+%3Fcomuna+rdfs%3Alabel+%3Flabel_es+FILTER%28lang%28%3Flabel_es%29%3D%27es%27%29+%7D+OPTIONAL+%7B+%3Fcomuna+p%3AP1082+%3Fst.+%3Fst+ps%3AP1082+%3Fpop%3B+wikibase%3Arank+%3Frank.+OPTIONAL+%7B+%3Fst+pq%3AP585+%3Ftime+%7D+OPTIONAL+%7B+%3Fst+pq%3AP459+%3Fmethod+%7D+OPTIONAL+%7B+%3Fst+prov%3AwasDerivedFrom+%3Fref.+OPTIONAL+%7B+%3Fref+pr%3AP854+%3FrefURL+%7D+OPTIONAL+%7B+%3Fref+pr%3AP248+%3FstatedIn+%7D+%7D+%7D+%7D&format=json",
    method "get",
    response_type "json",
    http_encoding "URLENCODED"
) HEADER (
    user-agent "YOUR_APP_NAME YOUR_CONTACT_EMAIL"
) BODY ();

CREATE SCHEMASTORE VIEW wikidata_population WITH CONTAINER factsync AS
SELECT
    b.comuna.value AS wikidata_item,
    b.cut.value AS cut,
    b.label_es.value AS label_es,
    b.st.value AS statement_id,
    b.pop.value AS population,
    substr(b.time.value, 1, 10) AS point_in_time,
    b.method.value AS determination_method,
    regexp_extract(b.rank.value, '#(.*)$', 1) AS rank,
    b.refURL.value AS reference_url,
    b.statedIn.value AS stated_in
FROM factsync_rest.wikidata_population_raw
LATERAL VIEW explode(results.bindings) AS b;
