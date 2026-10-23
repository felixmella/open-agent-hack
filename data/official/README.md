# Official data files

## `ine_projections_base2017_comunas.csv`

Population estimates and projections by comuna and year, 2002–2035 (one row per comuna and year: `cut`, `comuna`, `year`, `population`).

- **Source:** INE, *Estimaciones y proyecciones de la población de Chile 2002-2035 por comunas (base Censo 2017)*, workbook `estimaciones-y-proyecciones-2002-2035-comunas.xlsx`, downloaded October 2026 from <https://www.ine.gob.cl/docs/default-source/proyecciones-de-poblacion/cuadros-estadisticos/base-2017/estimaciones-y-proyecciones-2002-2035-comunas.xlsx>.
- **Changes:** FactSync Chile summed INE's figures over sex and single year of age to get one total per comuna and year, and zero-padded the comuna code (CUT) to five digits. This file was not produced or endorsed by INE, and any analysis built on it is ours, not INE's.
- **Licence:** [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), as required by INE's [open data terms](https://www.ine.gob.cl/terminos-de-uso-y-licencia-de-datos-abiertos). This file is shared under the same licence.
- **Regenerate:** `.venv\Scripts\python scripts\prepare_ine_projections.py`, then copy it into Zetaris with `scripts\upload_filestore.py`.

The census sources (Census 2024 and Census 2017 by comuna) are not stored here: Zetaris reads them live from INE's public ArcGIS layers (see `zetaris/01_sources_create.sql` and `zetaris/02_official_create.sql`).
