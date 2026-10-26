# Mayors: a hand check of 20 random verdicts

The national mayor run of Oct 26, 2026 (`output_examples/national_mayors/`, all 346 comunas, agents on their
deterministic paths) gave 562 verdicts on pages that name someone as mayor: Spanish and English Wikipedia infoboxes
and Wikidata statements. `scripts/spot_check_mayors.py --tag mayors-20261026b --n 20 --seed 1026` drew 20 of them at
random. Each was checked by hand against the page's field as written and SERVEL's rows in
`data/official/servel_alcaldes_2012_2024.csv`.

**All 20 have the right class.** Two notes on their wording follow the table. The check was done by Claude (the coding
assistant), and every row lists its evidence so it can be checked again.

| # | Comuna, page | Name as written | Verdict | SERVEL | Right? |
|---|---|---|---|---|---|
| 1 | La Higuera, EN | Sylvia Clavería Mondaca | unknown name | no candidate of that name 2012–2024; elected: Galleguillos 2012/16/21, Aquea 2024 | yes (note 1) |
| 2 | Curacaví, EN | Juan Pablo Barros Basso | former mayor | won 2012, 2016, 2021; Hernández Villanueva won 2024 | yes (note 2) |
| 3 | Curarrehue, EN | Abel Painefilo Barriga | former mayor | won 2012, 2016, 2021; Parra Calabrano won 2024 | yes |
| 4 | Santiago, EN | Mario Desbordes | up to date | Desbordes Jiménez won 2024 | yes |
| 5 | Cunco, ES | Cristian Moraga Lagos | up to date | won 2024 | yes |
| 6 | Hualpén, EN | Katherine Torres Machuca | former mayor | won 2016; Rivera Morales won 2021 and 2024 | yes |
| 7 | Lo Barnechea, ES | Felipe Alessandri | up to date | Alessandri Vergara won 2024 | yes |
| 8 | Puente Alto, EN | Matias Toledo | up to date | Toledo Herrera won 2024 | yes |
| 9 | San Carlos, EN | Hugo Naim Gebrie Asfura | former mayor | won 2012, 2016; Méndez Venegas won 2024 | yes |
| 10 | Los Muermos, ES | Emilio González Burgos | up to date | won 2012, 2016, 2024 | yes |
| 11 | Yungay, EN | Angel Castro Medina | unknown name | no candidate of that name 2012–2024; elected: Inostroza 2012, Cifuentes 2016/21/24 | yes (note 1) |
| 12 | Peumo, EN | Carlos Aliaga | former mayor | Aliaga Donoso won 2021, lost 2024 (4,910 to 6,441) | yes |
| 13 | Coltauco, EN | Ruben Jorquera Vidal | former mayor | won 2012, 2016, lost 2024 | yes |
| 14 | Puente Alto, ES | Matías Toledo | up to date | Toledo Herrera won 2024 | yes |
| 15 | Hualaihué, EN | Freddy Ibacache Muñoz | former mayor | won 2012, 2016; Espinoza Ojeda won 2021 and 2024 | yes |
| 16 | Villarrica, ES | Pablo Astete Mermoud | up to date | won 2012, 2016, 2024 | yes |
| 17 | Laja, EN | Vladimir Fica Toledo | up to date | won 2016, 2024 | yes |
| 18 | Gorbea, ES | Jorge Andrés Romero Martínez | up to date | won 2021 as JORGE ANDRES, 2024 as ANDRES ROMERO MARTINEZ (one person) | yes |
| 19 | Villarrica, EN | Pablo Astete Mermoud | up to date | as 16 | yes |
| 20 | Alto Hospicio, EN | Patricio Ferreira | up to date | Ferreira Rivera won 2021 and 2024 | yes |

**Note 1: unknown names.** Both names match no candidate SERVEL lists for their comuna from 2012 on, so the class is
right. They are probably mayors from before 2012, which SERVEL's four elections can't show. The explanations offered "a
stand-in or a replacement, a misspelling, or vandalism" but not that. The code now adds "a mayor from before 2012"
(after this run was recorded).

**Note 2: former mayors' terms.** An explanation names the elections the person won among those read when the Critic
approved it. Curacaví's says Barros Basso "was elected mayor in 2021", which is true, but he also won in 2012 and 2016:
those elections were read later in the run, for other comunas.

**What this sample doesn't cover.** It checks the deterministic path that produced the national numbers. The model's
part on mayors (deciding who an uncertain name refers to, reading a name SERVEL doesn't have) is shown in example 6
(`output_examples/example_6/`), not measured: `eval/results.md` measures the model on population figures only.

**How the matcher was fixed before this run.** The first national run (tag `mayors-20261026`, not kept) called 14
Spanish names unknown. Checking them showed three were the elected mayor, split in two by SERVEL's spelling: Cabildo's
mayor is "ALBERTO PATRICIO ALIAGA DIAZ" in 2012–2021 and "PATRICIO ALIAGA DIAZ" in 2024; Chaitén's and Huasco's
likewise. People are now one person when both surnames agree and one row's given names include the other's
(`app/knowledge/mayors.py`, `people`), and the run was repeated. 9 Spanish names remain unknown.
