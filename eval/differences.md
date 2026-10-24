# Differences between the rules-only run and the model run

Same comunas, same recorded rows (eval/snapshot). Each difference is adjudicated in eval/adjudication.json.

| Id | Kind | Comuna | Page · location | Figure | Rules | Model | Evidence |
|---|---|---|---|---|---|---|---|
| d729ee86b | extraction | Canela | es · body | 2,000 (2000) | check: not checkable | not kept | La población de Canela Baja no supera los 2000 habitantes. |
| dffcf85c1 | extraction | Canela | es · body | 20,000 (no year) | check: not checkable | not kept | Se calcula que para el evento llegó aproximadamente una población flotante de 20.000 personas, visitantes que acamparon en terrenos aledaños a la parada oficial del Rally Dakar en un terreno municipal a la salida norte d |
| d6e2ae8a9 | extraction | Canela | es · body | 203 (2017) | check: not the comuna's figure | not kept | A 2017, en la localidad de Canela Baja habitaban 1918, en Canela Alta y Población La Manga 808, Huentelauquén Norte 798, Huentelauquén Sur 518, El Llano 223, Mincha Norte 214 y Los Rulos 203 personas. |
| d4e39f8ff | extraction | Canela | es · body | 9,084 (no year) | Likely error | not kept | La comuna administra un sistema de salud municipal, a cargo del Departamento de Salud de la Ilustre Municipalidad de Canela, cuenta con un consultorio urbano ubicado en Canela Baja y con 8 postas de salud rural (PSR), en |
| db63dd247 | verdict | Santo Domingo | wikidata · statement | 1,029,110 (point in time 2020-01-01) | Likely error | Unexplained mismatch (nvidia/nemotron-3.5-lightning-30b-a3b) | 1,029,110 is 78 times INE's Census 2024 count, 13,171: probably another place's figure (with the same name), an area larger than the comuna, or a unit slip. |
| d8b0c7bee | extraction | Pelluhue | es · body | 2,537 (no year) | check: not the comuna's figure | not kept | Un 39,6% (2.537 habitantes) corresponde a población rural, y un 60,4% (3.877 habitantes) corresponde a población urbana. |
| d9fc543d5 | extraction | Talcahuano | en · body | 1,873 (no year) | check: not the comuna's figure | not kept | With a population density of 1,873 inhabitants per square kilometre, it is the seventh most populated city of the country. |
| d28ae5bdd | extraction | Los Ángeles | es · body | 105,436 (2024 census) | Unexplained mismatch | not kept | Entre los datos estadísticos que nos entregó el censo de 2024 podemos decir que 105.436 habitantes son hombres y 114.005 mujeres, con un promedio de edad de 37,6 años. |
| d9f3ec389 | extraction | Los Ángeles | es · lead | 220,441 (2024 census) | Likely error | not kept | Es una de las ciudades con mayor crecimiento del país en las últimas décadas, alcanzando los 220.441 habitantes de acuerdo al censo de 2024 |
| d2e81b59d | extraction | Galvarino | es · body | 4,414 (no year) | check: not checkable | not kept | Aproximadamente el 36,8% de la población (4.414 habitantes) tiene más de 45 años |
| d540a66ce | extraction | Galvarino | es · body | 600 (no year) | check: not the comuna's figure | not kept | Solo el 5% de la población (600 habitantes) posee un título profesional, excluyendo títulos técnicos |
| df2e67bd4 | extraction | Galvarino | es · body | 7,077 (no year) | check: not checkable | not kept | La presencia de la comunidad mapuche es notable, constituyendo el 59% de la población, o sea, 7.077 habitantes |
| db711e11b | extraction | Galvarino | es · body | 7,797 (no year) | check: not checkable | not kept | En cuanto a creencias religiosas, el 65% de la población (7.797 habitantes) se declara creyente, con un 41% identificándose como católicos y un 24% como protestantes |
| ddaaa2ede | extraction | Chaitén | es · body | 1,637 (2017) | Unexplained mismatch | not kept | Al 2017 la ciudad tenía una población de 1637 personas |
| dd4c81c95 | extraction | Chaitén | es · body | 189 (2006) | check: not the comuna's figure | not kept | En 2006, la encuesta CASEN determinó que 189 personas en Chaitén eran consideradas como pobres y 244 como indigentes, representando el 2,95 % y el 3,81 % de la población comunal |
| def9a7478 | extraction | Chaitén | es · body | 4,065 (2002) | Likely error | not kept | El pueblo de Chaitén tenía, en 2002, una población de 4065 habitantes (2117 hombres y 1948 mujeres) y una cantidad de 1224 viviendas extendidas en una superficie de 1,92 km² |
| df9ac8a01 | extraction | Puente Alto | es · body | 500,000 (no year) | check: not checkable | not kept | Fundada como un pequeño pueblo rural a fines del con el nombre de «Pueblito de Las Arañas», fue en sus inicios pionera en las actividades vitivinícolas de la Región Metropolitana, pero debido al aumento y expansión de la |
| d7ae86064 | follow-on | Melipilla | en · infobox | 108,540 (2002 Census) | not kept | Internal inconsistency | The infobox gives 108,540 ('2002 Census'), while the lead already gives the 2017 census figure, 123,627. |
| d08baa347 | extraction | Melipilla | en · lead | 141,612 (2020 projection) | not kept | check: consistent | According to the 2017 census, the commune alone has 123,627 residents and is projected to have 141,612 residents by 2020. |
| d3fd960e7 | extraction | Melipilla | es · lead | 150,466 (2017 census) | Different definition | not kept | La comuna central, sin considerar el resto de la provincia, en 2025 tiene 150.466 habitantes (basado en el censo 2017 con 123.627 habitantes) . |

## The Critic's model flags

| Id | Comuna | Page | Figure | Class | Flag | Final |
|---|---|---|---|---|---|---|
| dc8854c96 | Galvarino | en | 12,469 | Internal inconsistency | class doubted on review: The infobox and historical populations table refer to different years (2016 and 2024), so there is no internal contradiction; the class internal_inconsistency does not fit. | approved |
| df0c57a75 | Melipilla | en | 108,540 | Internal inconsistency | class doubted on review: The 2002 and 2017 census figures do not contradict each other; they represent population counts from different years. | approved |
