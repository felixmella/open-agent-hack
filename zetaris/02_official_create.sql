-- =============================================================================
-- FactSync Chile: register the other official INE sources in Zetaris.
-- Run as an ADMIN user after 01_sources_create.sql. One statement per request.
--
-- Sources
--   INE Census 2017, population by comuna: INE's public ArcGIS feature layer
--     Cifras_Comunas_2017 (346 rows; COMUNA is the CUT, without the leading
--     zero below region 10, so the view zero-pads it to 5 digits).
--   INE estimates and projections 2002-2035 (base Censo 2017), by comuna and
--     year: INE's official workbook, aggregated by
--     scripts/prepare_ine_projections.py into
--     data/official/ine_projections_base2017_comunas.csv and copied into the
--     Zetaris file store by scripts/upload_filestore.py (run both first).
--   INE Census 2002, population by comuna on today's boundaries and codes:
--     counted on INE's REDATAM census database by
--     scripts/prepare_ine_census2002.py into
--     data/official/ine_census2002_comunas.csv, then copied into the file store
--     by scripts/upload_filestore.py (346 comunas, 15,116,435 persons).
--   INE Census 2017, urban and rural population by comuna: INE's public ArcGIS
--     layer Comuna_Densid_Superficie (345 rows: Antartica is not in it;
--     COMUNA lacks the leading zero below region 10).
--   Licence: CC BY-SA 4.0 (INE open data terms
--     https://www.ine.gob.cl/terminos-de-uso-y-licencia-de-datos-abiertos).
-- =============================================================================

CREATE LIGHTNING REST TABLE ine_census2017_raw FROM FACTSYNC_REST REQUEST(
    endpoint "https://services5.arcgis.com/hUyD8u3TeZLKPe4T/arcgis/rest/services/Cifras_Comunas_2017/FeatureServer/0/query?where=1%3D1&returnGeometry=false&f=json&outFields=COMUNA%2CNOM_COMUNA%2CNOM_REGION%2CTOTAL_PERS%2CHOMBRES%2CMUJERES%2CTOTAL_VIVI",
    method "get",
    response_type "json",
    http_encoding "URLENCODED"
) HEADER (
) BODY ();

CREATE OR REPLACE SCHEMASTORE VIEW ine_census2017 WITH CONTAINER factsync AS
SELECT
    lpad(cast(f.attributes.COMUNA AS string), 5, '0') AS cut,
    f.attributes.NOM_COMUNA AS comuna,
    f.attributes.NOM_REGION AS region,
    f.attributes.TOTAL_PERS AS population,
    f.attributes.HOMBRES AS men,
    f.attributes.MUJERES AS women,
    f.attributes.TOTAL_VIVI AS dwellings
FROM factsync_rest.ine_census2017_raw
LATERAL VIEW explode(features) AS f;

CREATE LIGHTNING DATABASE FACTSYNC_FILES DESCRIBE BY "FactSync Chile official files, INE projections base 2017";

CREATE LIGHTNING FILESTORE TABLE ine_projections_raw FROM FACTSYNC_FILES FORMAT CSV OPTIONS (
    path "dffs://factsync/ine_projections_base2017_comunas.csv",
    header "true",
    inferSchema "true"
);

CREATE OR REPLACE SCHEMASTORE VIEW ine_projections WITH CONTAINER factsync AS
SELECT
    lpad(cast(cut AS string), 5, '0') AS cut,
    comuna,
    cast(year AS int) AS year,
    cast(population AS bigint) AS population
FROM factsync_files.ine_projections_raw;

CREATE LIGHTNING FILESTORE TABLE ine_census2002_raw FROM FACTSYNC_FILES FORMAT CSV OPTIONS (
    path "dffs://factsync/ine_census2002_comunas.csv",
    header "true",
    inferSchema "true"
);

CREATE OR REPLACE SCHEMASTORE VIEW ine_census2002 WITH CONTAINER factsync AS
SELECT
    lpad(cast(cut AS string), 5, '0') AS cut,
    comuna,
    cast(population AS bigint) AS population
FROM factsync_files.ine_census2002_raw;

CREATE LIGHTNING REST TABLE ine_census2017_area_raw FROM FACTSYNC_REST REQUEST(
    endpoint "https://services5.arcgis.com/hUyD8u3TeZLKPe4T/arcgis/rest/services/Comuna_Densid_Superficie/FeatureServer/0/query?where=1%3D1&returnGeometry=false&f=json&outFields=COMUNA%2CNOM_COMUNA%2CT_POB_U%2CT_POB_R%2CT_POB",
    method "get",
    response_type "json",
    http_encoding "URLENCODED"
) HEADER (
) BODY ();

CREATE OR REPLACE SCHEMASTORE VIEW ine_census2017_area WITH CONTAINER factsync AS
SELECT
    lpad(cast(f.attributes.COMUNA AS string), 5, '0') AS cut,
    f.attributes.NOM_COMUNA AS comuna,
    f.attributes.T_POB_U AS urban,
    f.attributes.T_POB_R AS rural,
    f.attributes.T_POB AS population
FROM factsync_rest.ine_census2017_area_raw
LATERAL VIEW explode(features) AS f;
