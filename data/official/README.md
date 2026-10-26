# Official data files

## `ine_projections_base2017_comunas.csv`

Population estimates and projections by comuna and year, 2002–2035 (one row per comuna and year: `cut`, `comuna`, `year`, `population`).

- **Source:** INE, *Estimaciones y proyecciones de la población de Chile 2002-2035 por comunas (base Censo 2017)*, workbook `estimaciones-y-proyecciones-2002-2035-comunas.xlsx`, downloaded October 2026 from <https://www.ine.gob.cl/docs/default-source/proyecciones-de-poblacion/cuadros-estadisticos/base-2017/estimaciones-y-proyecciones-2002-2035-comunas.xlsx>.
- **Changes:** FactSync Chile summed INE's figures over sex and single year of age to get one total per comuna and year, and zero-padded the comuna code (CUT) to five digits. This file was not produced or endorsed by INE, and any analysis built on it is ours, not INE's.
- **Licence:** [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), as required by INE's [open data terms](https://www.ine.gob.cl/terminos-de-uso-y-licencia-de-datos-abiertos). This file is shared under the same licence.
- **Regenerate:** `.venv\Scripts\python scripts\prepare_ine_projections.py`, then copy it into Zetaris with `scripts\upload_filestore.py`.

## `ine_census2002_comunas.csv`

The Census 2002 count of persons in each comuna (one row per comuna: `cut`, `comuna`, `population`), on today's comuna boundaries and codes.

- **Source:** INE, *Censo de Población y Vivienda 2002*, as INE's REDATAM server counts it from the census database: "Conteos", Personas by Comuna, the whole database (<https://redatam-ine.ine.cl/redbin/RpWebEngine.exe/Portal?BASE=CENSO_2002&lang=esp>), run on October 24, 2026. INE publishes no ready-made comuna table for 2002; this is its own processing of its own data.
- **Checks:** 346 comunas, and the counts add up to 15,116,435, the census's official national count. The comunas created after 2002 (Alto Hospicio, Alto Biobío, Cholchol, Hualpén) have their own count, so the comunas they were split from (Iquique, Santa Bárbara, Nueva Imperial, Talcahuano) are counted on today's smaller boundaries, not the 2002 ones.
- **Changes:** none beyond the format: FactSync Chile kept the code, name and count of each row. Not produced or endorsed by INE as a file.
- **Licence:** [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), under INE's [open data terms](https://www.ine.gob.cl/terminos-de-uso-y-licencia-de-datos-abiertos).
- **Regenerate:** `.venv\Scripts\python scripts\prepare_ine_census2002.py` (it refuses to write a table that doesn't add up), then `scripts\upload_filestore.py`.

## `servel_alcaldes_2012_2024.csv`

Every candidate in Chile's four most recent mayoral elections, in every comuna: one row per candidate per election (`year`, `election_date`, `cut`, `comuna`, `comuna_servel`, `region`, `lista`, `pacto`, `partido`, `nombres`, `primer_apellido`, `segundo_apellido`, `votos`, `elected`), 5,403 rows.

- **Source:** SERVEL (Servicio Electoral de Chile), the results workbooks of the elections of 28 October 2012, 23 October 2016, 15–16 May 2021 and 26–27 October 2024 (`2012_10_Alcaldes_DatosEleccion.xlsx`, `2016_10_Alcaldes_DatosEleccion.xlsx`, `2021_05_Alcaldes_Datos_Eleccion.xlsx`, `2024_10_Alcaldes_Datos_Eleccion.xlsx`), sheet "Votación por comuna", downloaded in October 2026. SERVEL's historical results page: <https://www.servel.cl/biblioteca-de-documentos/resultados-electorales-historicos/>.
- **Changes:** FactSync Chile kept every candidate's row as SERVEL gives it (names in capitals without accents; 2024 gives only the first given name), dropped the rows for blank and null votes, turned SERVEL's `Cargo = ALCALDE` into `elected`, and added each comuna's CUT and INE name: SERVEL's comuna names are resolved against INE's 346 comunas by their letters, with five aliases where the spellings differ (LLAY-LLAY / LLAILLAY, MARCHIGUE / MARCHIHUE, PAIHUANO / PAIGUANO, TREHUACO / TREGUACO, CABO DE HORNOS(EX-NAVARINO) / CABO DE HORNOS). Not produced or endorsed by SERVEL.
- **Checks:** each election has 346 comunas with exactly one winner each (1,164, 1,213, 1,450 and 1,576 candidates); the script writes nothing otherwise. Zetaris's view `factsync.servel_mayors` has the same rows and votes per election.
- **What it says:** who was elected, not who holds the office today. Resignations, removals, deaths, stand-ins and replacements chosen by the council don't appear in it.
- **Licence:** public electoral results published by SERVEL. SERVEL's results page states no licence or terms of use; FactSync cites SERVEL as the source of every figure and draft.
- **Regenerate:** `.venv\Scripts\python -I scripts\prepare_servel_mayors.py <folder with the four workbooks>`, then `scripts\upload_filestore.py data\official\servel_alcaldes_2012_2024.csv`.

The other census sources are not stored here: Zetaris reads them live from INE's public ArcGIS layers. Census 2024 and Census 2017 by comuna come from `zetaris/01_sources_create.sql` and `zetaris/02_official_create.sql`. The 2017 urban and rural population by comuna (layer `Comuna_Densid_Superficie`, 345 comunas; Antártica isn't in it) comes from `zetaris/02_official_create.sql`.
