# National batch mayors-20261026b: mayors

346 comunas in 16 regions; agents on their deterministic paths (name matcher, rule-based Critic, templates): no model calls.

Of 563 pages that name a mayor across the three sources, **184 (33%)** don't name the mayor SERVEL says was elected in October 2024. SERVEL records who was elected, not who holds the office today, so some of these may be right (a stand-in, a replacement): every draft asks the editor to check.

| Source | Pages naming a mayor | The 2024 winner | Someone else | Names no one | Not read | Who else |
|---|---|---|---|---|---|---|
| Spanish Wikipedia | 286 | 263 | 23 (8%) | 6 | 54 | former mayor, last elected 2021 11, no one SERVEL lists (stand-in, misspelling or vandalism?) 9, a candidate never elected 2012-2024 2, former mayor, last elected 2016 1 |
| English Wikipedia | 272 | 112 | 160 (59%) | 15 | 59 | former mayor, last elected 2016 55, former mayor, last elected 2021 50, a candidate never elected 2012-2024 22, former mayor, last elected 2012 18, no one SERVEL lists (stand-in, misspelling or vandalism?) 15 |
| Wikidata | 5 | 4 | 1 (20%) | 341 | 0 | former mayor, last elected 2012 1 |

**Discovery.** Elections the Planner added from the Zetaris catalog when the Critic sent names back: servel_mayors_2021 in 16 of 16 regions, for 187 names; servel_mayors_2016 in 15 of 16 regions, for 123 names; servel_mayors_2012 in 15 of 16 regions, for 67 names.

**The office may have changed hands** (Wikidata records the end of the 2024 winner's term): Yerbas Buenas (Spanish Wikipedia), Yerbas Buenas (English Wikipedia).

**Names SERVEL doesn't have** (24), for a human to look at:

- La Higuera (04104), English Wikipedia: 'Sylvia Clavería Mondaca'
- Rinconada (05303), English Wikipedia: 'Juan Pablo Galdames Burgos'
- Nogales (05506), Spanish Wikipedia: 'Leslie Pacheco Matte' (Ind.)
- Las Cabras (06107), Spanish Wikipedia: 'Claudio Andres Osorio Benavides'
- Chimbarongo (06303), Spanish Wikipedia: 'Alejando Arenas Arenas' (ALCALDE SUPLENTE)
- Nancagua (06305), Spanish Wikipedia: 'Gabriel Ahumada Díaz'
- Empedrado (07104), Spanish Wikipedia: 'Juan Nicolas de la luna'
- Pelluhue (07203), English Wikipedia: 'Carlos Zúñiga Villaseñor'
- Chiguayante (08103), English Wikipedia: 'Tomás Solís Nava'
- Florida (08104), English Wikipedia: 'Joey Meehan'
- Contulmo (08204), English Wikipedia: 'Eduardo Aguayo Thiele'
- Mulchén (08305), English Wikipedia: 'Nicolas Benjamin Cuevas Cuevas'
- Lautaro (09108), English Wikipedia: 'Renato Hauri'
- Melipeuco (09110), Spanish Wikipedia: 'Vicente Alexander Sepúlveda Saldias'
- Perquenco (09113), Spanish Wikipedia: 'Ariel Aedo Nuñez'
- Ercilla (09204), English Wikipedia: 'Ramón Vilches Álvarez'
- Lonquimay (09205), English Wikipedia: 'Guillermo Vásquez Veroiza'
- Victoria (09211), English Wikipedia: 'Aaron Taylor'
- San Gregorio (12104), Spanish Wikipedia: 'Jeannette Andrade Luis' (PDC)
- Bulnes (16102), English Wikipedia: 'Rodrigo De La Puente Acuña'
- Pinto (16106), English Wikipedia: 'Wyatt Mathis'
- Yungay (16109), English Wikipedia: 'Angel Castro Medina' (PDC)
- Quirihue (16201), English Wikipedia: 'Tomás Irribarra De La Torre'
- Coihueco (16302), Spanish Wikipedia: 'Wilson Palma Jeldres'

*Names no one:* an infobox whose mayor field is empty, or a Wikidata item without a head of government (P6) statement.

*Not read:* FactSync reads the Wikipedia article linked from each comuna's Wikidata item; a comuna whose item links no article isn't counted.

Runs:

- `national-mayors-20261026b-01-tarapaca`: success, 7 comunas, 9 findings, 9 drafts (output/national-mayors-20261026b-01-tarapaca/report.html)
- `national-mayors-20261026b-02-antofagasta`: success, 9 comunas, 13 findings, 13 drafts (output/national-mayors-20261026b-02-antofagasta/report.html)
- `national-mayors-20261026b-03-atacama`: success, 9 comunas, 13 findings, 13 drafts (output/national-mayors-20261026b-03-atacama/report.html)
- `national-mayors-20261026b-04-coquimbo`: success, 15 comunas, 26 findings, 26 drafts (output/national-mayors-20261026b-04-coquimbo/report.html)
- `national-mayors-20261026b-05-valparaiso`: success, 38 comunas, 47 findings, 47 drafts (output/national-mayors-20261026b-05-valparaiso/report.html)
- `national-mayors-20261026b-06-libertador-general-bernardo-o-higgi`: success, 33 comunas, 58 findings, 58 drafts (output/national-mayors-20261026b-06-libertador-general-bernardo-o-higgi/report.html)
- `national-mayors-20261026b-07-maule`: success, 30 comunas, 55 findings, 55 drafts (output/national-mayors-20261026b-07-maule/report.html)
- `national-mayors-20261026b-08-biobio`: success, 33 comunas, 62 findings, 57 drafts (output/national-mayors-20261026b-08-biobio/report.html)
- `national-mayors-20261026b-09-la-araucania`: success, 32 comunas, 61 findings, 61 drafts (output/national-mayors-20261026b-09-la-araucania/report.html)
- `national-mayors-20261026b-10-los-lagos`: success, 30 comunas, 42 findings, 42 drafts (output/national-mayors-20261026b-10-los-lagos/report.html)
- `national-mayors-20261026b-11-aysen-del-general-carlos-ibanez-del`: success, 10 comunas, 18 findings, 18 drafts (output/national-mayors-20261026b-11-aysen-del-general-carlos-ibanez-del/report.html)
- `national-mayors-20261026b-12-magallanes-y-de-la-antartica-chilen`: success, 11 comunas, 17 findings, 17 drafts (output/national-mayors-20261026b-12-magallanes-y-de-la-antartica-chilen/report.html)
- `national-mayors-20261026b-13-metropolitana-de-santiago`: success, 52 comunas, 66 findings, 66 drafts (output/national-mayors-20261026b-13-metropolitana-de-santiago/report.html)
- `national-mayors-20261026b-14-los-rios`: success, 12 comunas, 18 findings, 18 drafts (output/national-mayors-20261026b-14-los-rios/report.html)
- `national-mayors-20261026b-15-arica-y-parinacota`: success, 4 comunas, 5 findings, 5 drafts (output/national-mayors-20261026b-15-arica-y-parinacota/report.html)
- `national-mayors-20261026b-16-nuble`: success, 21 comunas, 44 findings, 43 drafts (output/national-mayors-20261026b-16-nuble/report.html)
