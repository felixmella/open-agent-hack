"""Names as Wikipedia, Wikidata and SERVEL write them: real cases from the comuna pages (Oct 26, 2026)."""
import pytest

from app.knowledge.names import compare, parse_field, person, same_letters, title_case


@pytest.mark.parametrize("written, servel, level", [
    ("Enrique Alfonso del Barrio Hernández", ("ENRIQUE", "DEL BARRIO", "HERNANDEZ"), "same"),  # 2024: one given name
    ("Carlos Soto", ("CARLOS ERNESTO", "SOTO", "GONZALEZ"), "same"),                         # no second surname
    ("Jorge Del Pozo Pastene", ("JORGE", "DEL POZO", "PASTENE"), "same"),
    ("Johnnson Guiñez Núñez", ("JOHNNSON", "GUIÑEZ", "NUÑEZ"), "same"),
    ("Max Luksic", ("MAXIMILIANO", "LUKSIC", "LEDERER"), "likely"),                         # a short form
    ("Alejando Arenas Arenas", ("ALEJANDRO", "ARENAS", "ARENAS"), "likely"),                # a typo
    ("Viviana Díaz Mesa", ("VIVIANA ESCARLETTE", "DIAZ", "MEZA"), "likely"),                # a short surname, one off
    ("Carlos Soto Sotomayor", ("CARLOS", "SOTO", "PEREZ"), "partial"),                      # another second surname
    ("Pedro Soto", ("CARLOS", "SOTO", "PEREZ"), "partial"),                                 # a relative?
    ("Wyatt Mathis", ("JAIRO", "DEL PINO", "LEMA"), "none"),
    ("Carlos Soto", ("ENRIQUE", "DEL BARRIO", "HERNANDEZ"), "none"),
])
def test_how_a_written_name_fits_a_servel_person(written, servel, level):
    assert compare(written, person(*servel))["level"] == level


def test_an_infobox_field_comes_apart_into_name_notes_and_linked_article():
    field = parse_field("[[Jairo del Pino Lema|Jairo del Pino]] ([[Partido Republicano de Chile (2019)|REP]])")
    assert field == {"name": "Jairo del Pino", "notes": ["REP"], "others": [], "linked": "Jairo del Pino Lema"}
    stand_in = parse_field("Alejando Arenas Arenas (ALCALDE SUPLENTE)")
    assert stand_in["name"] == "Alejando Arenas Arenas" and stand_in["notes"] == ["ALCALDE SUPLENTE"]
    assert parse_field("Ana Pérez<ref>{{cite web|url=x}}</ref><br>Juan Díaz (concejal)")["others"] == ["Juan Díaz"]
    assert parse_field("<!-- etc. -->")["name"] is None


def test_servel_capitals_become_a_name_but_accents_need_a_source():
    assert title_case("ENRIQUE DEL BARRIO HERNANDEZ") == "Enrique del Barrio Hernandez"
    assert same_letters("Enrique del Barrio Hernández", "ENRIQUE DEL BARRIO HERNANDEZ")
    assert not same_letters("Enrique Alfonso del Barrio Hernández", "ENRIQUE DEL BARRIO HERNANDEZ")
