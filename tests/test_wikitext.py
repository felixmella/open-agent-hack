"""Deterministic parsing of the infobox fields found in real comuna articles (October 2026 revisions)."""
from app.knowledge.wikitext import (article_passages, citation_facts, field_figures, has_citation,
                                    historical_populations, infobox_parameters, parse_population, parse_year,
                                    quote_supported, resolve_reference, rule_claims, strip_markup)


def test_population_formats_seen_in_the_articles():
    assert parse_population("26.746") == 26746            # eswiki Hualqui
    assert parse_population("24&nbsp;640") == 24640       # eswiki Las Cabras
    assert parse_population("8 448") == 8448              # eswiki Pemuco
    assert parse_population("36,219") == 36219            # enwiki Isla de Maipo
    assert parse_population("1843 <ref>{{cita web|título=Censo}}</ref>") == 1843


def test_formatnum_is_unwrapped():
    assert parse_population("{{formatnum|240000}}") == 240000   # eswiki Concepción
    assert parse_population("{{formatnum|255823}}") == 255823   # eswiki Ñuñoa
    assert parse_population("{{formatnum:12345}}") == 12345


def test_html_comments_are_not_part_of_the_figure():
    # eswiki Mejillones: 13,467 is its Census 2017 count
    assert parse_population('13467 <!-- no agregar &+"nbsp" : el número es leído para calcular la densidad de '
                            'población -->') == 13467
    assert strip_markup("2017 <!-- censo -->") == "2017"


def test_fields_that_are_not_a_clean_number_are_left_to_the_extractor():
    assert parse_population("11.611 censo 2017") is None   # enwiki Cholchol: a year in the value
    assert parse_population("") is None
    assert parse_population("22.098<br/>25.301 (2020)") is None


def test_two_figures_in_one_field_each_with_its_own_year():
    # eswiki La Cruz: the Census 2017 count, then a figure for 2020
    assert field_figures("22.098<br/>25.301 (2020)") == [(22098, "22.098", None), (25301, "25.301 (2020)", 2020)]
    assert field_figures("38036") == [(38036, "38036", None)]
    assert field_figures("7750<ref>{{cite web |title= Censo 2017}}</ref>") == [(7750, "7750", None)]
    assert field_figures("aprox. 5000") == []


def test_infobox_parameters_on_one_line_after_a_map_and_a_comment():
    # eswiki La Unión: two parameters on one line, which the view's line-anchored regex misses
    la_union = ("{{Ficha de entidad subnacional\n|unidad = [[Comuna de Chile|Comuna]]\n|altitud=26|población          "
                "= 38036\n|población_año      = [[Censo chileno de 2017|2017]]\n}}\n'''La Unión''' es una comuna.")
    params = infobox_parameters(la_union)
    assert params["población"] == "38036" and params["población_año"] == "[[Censo chileno de 2017|2017]]"
    # eswiki Las Condes: the map's JSON closes '}}' before the population fields
    las_condes = ('{{Ficha de entidad subnacional\n| mapa = <mapframe width="250" height="215"> \n[{"type": '
                  '"ExternalData",\n "properties": {\n "fill": "#4D87CA"}}]\n</mapframe>\n| población = 294&nbsp;838\n}}')
    assert infobox_parameters(las_condes)["población"] == "294&nbsp;838"
    # enwiki Isla de Pascua: a comment opens the population line
    isla = "{{Infobox settlement\n| name = Isla de Pascua\n<!-- population ---------------->| population_total = 7750\n}}"
    assert infobox_parameters(isla)["population_total"] == "7750"
    assert infobox_parameters("No infobox here.") == {}


def test_years_from_links_and_labels():
    assert parse_year("[[Censo chileno de 2017|2017]]") == 2017
    assert parse_year("2012 Census") == 2012
    assert parse_year("11.611 censo 2017") == 2017
    assert parse_year("") is None


def test_citations():
    assert has_citation('<ref name=censo17>{{cita web |url=http://www.censo2017.cl/}}</ref>')
    assert has_citation('<ref name="INE"/>')
    assert not has_citation("")
    assert not has_citation("{{cr}}")                    # eswiki Lautaro: citation needed


def test_strip_markup_keeps_visible_text():
    assert strip_markup("[[Censo chileno de 2024|censo de 2024]] 1&nbsp;598") == "censo de 2024 1 598"


def test_named_references_resolve_to_their_definition():
    article = 'Text.<ref name="INE">{{cite web |url=http://www.ine.cl/censos |accessdate=8 September 2010}}</ref>'
    resolved = resolve_reference('<ref name="INE"/>', article)
    assert "ine.cl/censos" in resolved
    assert citation_facts(resolved) == {"years": [], "domains": ["ine.cl"]}  # the access date is not a vintage
    assert citation_facts("{{cita web|url=http://www.censo2017.cl/x}}")["years"] == [2017]


def test_historical_populations_table():
    table = "{{Historical populations\n|align=left\n|source={{cite web|url=x|title=y}}\n|1992 |1283\n|2017 |1,843\n}}"
    assert [(r["year"], r["value"]) for r in historical_populations(table)] == [(1992, 1283), (2017, 1843)]


def test_passages_keep_prose_about_population_and_skip_lists_and_images():
    article = ("{{Ficha\n| población = 1\n}}\nIntro sin cifras.\n\n== Demografía ==\n[[Archivo:x.png|thumb|foto]]\n"
               "Según el [[Censo chileno de 2024|censo de 2024]], tiene 1&nbsp;598 habitantes.<ref>x</ref> Fin.\n"
               "* Melinka, 1411 habitantes.")
    passages = article_passages(article)
    assert passages == [{"section": "Demografía", "text": "Según el censo de 2024, tiene 1 598 habitantes. Fin."}]
    assert [(c["value"], c["year"]) for c in rule_claims(passages)] == [(1598, 2024)]
    assert quote_supported("tiene 1 598 habitantes", passages, "1 598")
    assert not quote_supported("tiene 1 598 habitantes", passages, "1 598", 2017)


def test_rule_claims_find_years_written_around_the_census():
    passages = [{"section": "Demographics", "text": "According to the 2002 INE census, Aysén had 22,353 inhabitants. "
                                                    "Paredones tiene una población de 6695 habitantes (INE 2002)."}]
    assert [(c["value"], c["year"], c["basis"]) for c in rule_claims(passages)] == \
        [(22353, 2002, "census"), (6695, 2002, "unspecified")]


def test_rule_claims_take_the_census_named_nearest_the_figure():
    # eswiki Canela: the 2017 census, then the 2002 one for an older figure
    sentence = ("De acuerdo a los datos del Censo de Población y Vivienda de 2017, la comuna de Canela posee 9.093 "
                "habitantes, disminuyendo de los 9379 señalados en el censo de 2002")
    assert [(c["value"], c["year"]) for c in rule_claims([{"section": "Demografía", "text": sentence}])] == [(9093, 2017)]


def test_rule_claims_read_long_census_names_and_estimates():
    algarrobo = ("Según los datos recolectados en el censo del Instituto Nacional de Estadísticas del año 2012, la comuna "
                 "posee una superficie de 176 km² y una población de 10 119 habitantes")
    rio_claro = "La comuna de Río Claro abarca una superficie de 430,5 km² y una población de 13.032 habitantes (estimado a 2009)"
    claims = rule_claims([{"section": "Demografía", "text": f"{algarrobo}. {rio_claro}."}])
    assert [(c["value"], c["year"], c["basis"]) for c in claims] == [(10119, 2012, "census"), (13032, 2009, "projection")]
