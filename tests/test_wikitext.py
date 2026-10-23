"""Deterministic parsing of the infobox fields found in real comuna articles (October 2026 revisions)."""
from app.knowledge.wikitext import has_citation, parse_population, parse_year, strip_markup


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
