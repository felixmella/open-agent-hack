"""Deterministic parsing of the infobox fields found in real comuna articles (October 2026 revisions)."""
from app.knowledge.wikitext import (article_passages, citation_facts, has_citation, historical_populations,
                                    parse_population, parse_year, quote_supported, resolve_reference, rule_claims,
                                    strip_markup)


def test_population_formats_seen_in_the_articles():
    assert parse_population("26.746") == 26746            # eswiki Hualqui
    assert parse_population("24&nbsp;640") == 24640       # eswiki Las Cabras
    assert parse_population("8 448") == 8448              # eswiki Pemuco
    assert parse_population("36,219") == 36219            # enwiki Isla de Maipo
    assert parse_population("1843 <ref>{{cita web|título=Censo}}</ref>") == 1843


def test_fields_that_are_not_a_clean_number_are_left_to_the_extractor():
    assert parse_population("11.611 censo 2017") is None   # enwiki Cholchol: a year in the value
    assert parse_population("") is None
    assert parse_population("{{formatnum:12345}}") is None


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
