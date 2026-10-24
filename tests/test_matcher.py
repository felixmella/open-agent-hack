"""The deterministic matcher on real cases found in October 2026 (figures from INE and the live articles)."""
from app.knowledge.matcher import (allowed_classes, assess_consistency, assess_sourcing, assess_value,
                                   assess_wikidata_item)


def table(census, projections=None):
    def records(definition, figures, source):
        return {y: {"obs_id": f"{definition}-{y}", "source": source, "definition": definition, "year": y, "value": v}
                for y, v in figures.items()}
    return {"census": records("census", census, "INE Censo"),
            "projection": records("projection", projections or {}, "INE Proyecciones base 2017")}


def claim(value, year=None, basis=None, role="current", source="Wikipedia ES", location="infobox", label=None, **extra):
    return {"id": f"{source}-{location}-{value}", "source_name": source, "location": location, "role": role,
            "value": value, "stated_year": year, "basis": basis, "label": label or (str(year) if year else None), **extra}


HUALQUI = table({2017: 24333, 2024: 25795}, {2020: 26201, 2024: 26746})
JUAN_FERNANDEZ = table({2017: 926, 2024: 904})
CURACAUTIN = table({2017: 17413, 2024: 18536})
QUIRIHUE = table({2017: 11594, 2024: 11746})


def test_a_2024_projection_is_a_different_definition_once_projections_are_read():
    verdict = assess_value(claim(26746, 2024), HUALQUI)
    assert verdict["class"] == "different_definition" and verdict["match"]["definition"] == "projection"
    assert verdict["proposal"]["value"] == 25795 and verdict["proposal"]["source_key"] == "census_2024"


def test_the_same_figure_without_projections_is_unexplained_and_left_to_the_model():
    census_only = table({2017: 24333, 2024: 25795})
    verdict = assess_value(claim(26746, 2024), census_only)
    assert verdict["unexplained"] and verdict["ambiguous"]
    assert "different_definition" in allowed_classes(claim(26746, 2024), census_only)
    assert "different_definition" not in allowed_classes(claim(26811, 2024), HUALQUI)  # projections read, no match


def test_a_census_2017_count_labelled_2020_is_a_mislabelled_vintage():
    verdict = assess_value(claim(926, 2020), JUAN_FERNANDEZ)  # eswiki Juan Fernández
    assert verdict["class"] == "mislabelled_vintage" and verdict["match"]["year"] == 2017
    assert verdict["proposal"]["action"] == "update" and verdict["proposal"]["value"] == 904


def test_a_slip_of_one_or_two_neighbouring_digits_is_a_typo():
    two = assess_value(claim(25413, 2017), CURACAUTIN)  # eswiki Curacautín: 25,413 for 17,413
    assert two["class"] == "genuine_error" and two["near"]["value"] == 17413 and two["ambiguous"]
    assert "possibly a typo" in two["explanation"] and two["confidence"] == 0.6
    one = assess_value(claim(17431, 2017), CURACAUTIN)
    assert one["class"] == "genuine_error" and not one["ambiguous"] and one["confidence"] == 0.85
    assert "most likely a typo" in one["explanation"]
    assert assess_value(claim(26746, 2024), table({2017: 24333, 2024: 25795}))["class"] != "genuine_error"


def test_a_projection_labelled_as_a_census_says_so_once():
    verdict = assess_value(claim(26746, 2024, "census", source="Wikipedia EN", label="2024 Census"), HUALQUI)
    assert verdict["class"] == "different_definition"
    assert verdict["explanation"] == ("26,746 is labelled as a census count, but it is INE's projection for 2024 (base "
                                      "Census 2017); Census 2024 counted 25,795.")


SANTO_DOMINGO = table({2017: 10900, 2024: 13171}, {2017: 11231, 2020: 11934, 2024: 12609})


def test_a_figure_far_from_the_comuna_size_is_probably_another_place():
    # Wikidata gives Santo Domingo (13,171 people) 1,029,110: the Dominican city's figure
    statement = claim(1029110, 2020, role="historical", source="Wikidata", location="statement",
                      label="point in time 2020-01-01", rank="NormalRank")
    verdict = assess_value(statement, SANTO_DOMINGO)
    assert verdict["class"] == "genuine_error" and verdict["ambiguous"] and verdict["confidence"] <= 0.7
    assert verdict["explanation"].startswith("1,029,110 is 78 times INE's Census 2024 count, 13,171: probably another "
                                             "place's figure")
    assert not verdict["unexplained"]  # no unread official source could explain it
    assert allowed_classes(statement, SANTO_DOMINGO) == {"genuine_error", "cross_source_mismatch"}
    currency = dict((v["class"], v) for _, v in assess_wikidata_item([statement], SANTO_DOMINGO))["outdated_vintage"]
    assert "newest population statement" not in currency["explanation"]
    assert currency["explanation"].startswith("Census 2024 counted 13,171, and Wikidata has no statement for it.")
    assert "see the finding on that value" in currency["explanation"]


def test_a_figure_in_the_text_far_from_the_comuna_size_is_a_locality_not_a_finding():
    canela = table({2017: 9093, 2024: 9639})
    for value, year in ((203, 2017), (2000, None)):  # Canela: a locality's count; 'no supera los 2000 habitantes'
        result = assess_value(claim(value, year, role="historical" if year else "current", location="body"), canela)
        assert result["check"] == "not the comuna's figure"
        assert "probably refers to a locality or an area, not the comuna" in result["explanation"]
    assert allowed_classes(claim(203, 2017, role="historical", location="body"), canela) == set()
    chaiten = assess_value(claim(189, 2006, role="historical", location="body"), table({2017: 5071, 2024: 4025}))
    assert chaiten["check"] and "5% of INE's Census 2024 count" in chaiten["explanation"]


def test_a_rounded_official_figure_gets_that_figures_verdict():
    taltal = assess_value(claim(12100, source="Wikidata", location="statement"), table({2017: 13317, 2024: 12097}))
    assert taltal["class"] == "consistent" and taltal["rounded"] and taltal["confidence"] == 0.85
    assert taltal["explanation"] == "12,100 (12,097 rounded) matches INE's Census 2024 count."
    chiguayante = table({2017: 85938, 2024: 85822}, {2017: 90068, 2020: 91180, 2024: 91963})
    verdict = assess_value(claim(86000, 2017), chiguayante)  # eswiki Chiguayante: 86,000 for 2017
    assert verdict["class"] == "outdated_vintage" and verdict["match"]["year"] == 2017 and verdict["confidence"] == 0.85
    assert verdict["explanation"].startswith("86,000 (85,938 rounded) is INE's Census 2017 count")
    assert assess_value(claim(2000, 2024), table({2017: 2063, 2024: 1750}))["class"] != "consistent"  # one digit left


TIERRA_AMARILLA = table({2017: 14019, 2024: 11846}, {2017: 13941, 2020: 14312, 2024: 14431})


def test_an_infobox_showing_wikidatas_figure_says_so():
    shown = claim(14019, 2017, label="2017", value_from="wikidata", field="población")
    verdict = assess_value(shown, TIERRA_AMARILLA)
    assert verdict["class"] == "outdated_vintage"
    assert verdict["explanation"] == (
        "The infobox has no figure of its own and shows Wikidata's: 14,019 is INE's Census 2017 count, shown as the "
        "current figure. The current official figure is the Census 2024 count, 11,846. Fixing Wikidata's statement "
        "updates this infobox too.")
    assert assess_sourcing({**shown, "reference_raw": ""}, None, verdict, TIERRA_AMARILLA) is None  # Wikidata's references, not its own
    several = claim(None, value_from="wikidata", statements=2)
    assert assess_value(several, TIERRA_AMARILLA) is None  # which statement the infobox shows can't be told


def test_an_infobox_with_an_empty_field_and_nothing_in_wikidata_shows_no_figure():
    # eswiki Cabrero: población empty, población_urb = 21492, no population in Wikidata
    cabrero = claim(None, 2017, value_from="wikidata", missing=True, field="población", urban_field="población_urb",
                    urban_value=21492, quote="población_urb = 21492")
    verdict = assess_value(cabrero, table({2017: 28573, 2024: 31256}))
    assert verdict["class"] == "missing_value" and verdict["proposal"]["value"] == 31256
    assert verdict["explanation"] == (
        "The infobox shows no population figure: its población field is empty, and Wikidata, which fills it then, has "
        "no population statement. Its población_urb field holds 21,492, an urban population, not the comuna total, "
        "which the infobox shows only beside a total. Census 2024 counted 31,256.")
    assert assess_sourcing({**cabrero, "reference_raw": ""}, None, verdict, HUALQUI) is None


def test_withdrawn_and_nonexistent_censuses():
    discredited = assess_value(claim(16508, 2012, "census", source="Wikipedia EN", label="2012 Census"), CURACAUTIN)
    assert discredited["class"] == "discredited_source"
    nonexistent = assess_value(claim(1000, 2022, "census", source="Wikipedia EN", label="2022 Census"), CURACAUTIN)
    assert nonexistent["class"] == "nonexistent_census"


def test_a_census_2024_count_labelled_2017_census_is_mislabelled_and_keeps_its_figure():
    verdict = assess_value(claim(11746, 2017, "census", source="Wikipedia EN", label="2017 Census"), QUIRIHUE)
    assert verdict["class"] == "mislabelled_vintage"
    assert verdict["proposal"] == {**verdict["proposal"], "value": 11746, "year": 2024}


def test_historical_statements_are_consistent_or_left_unchecked():
    assert assess_value(claim(926, 2017, role="historical", source="Wikidata", location="statement"),
                        JUAN_FERNANDEZ)["class"] == "consistent"
    assert assess_value(claim(16970, 2002, "census", role="historical", location="body"), CURACAUTIN) is None


def test_a_figure_another_source_labels_as_the_2012_census_is_a_lead_not_a_fact():
    wikidata = claim(16508, 2020, role="historical", source="Wikidata", location="statement")
    enwiki = claim(16508, 2012, "census", source="Wikipedia EN", label="2012 Census")
    verdict = assess_value(wikidata, CURACAUTIN, [wikidata, enwiki])
    assert verdict["class"] == "discredited_source" and verdict["ambiguous"] and verdict["related"] == enwiki["id"]


def test_infobox_against_article_text():
    infobox = claim(26746, 2024)
    body = claim(25795, 2024, "census", role="historical", location="body", label="2024 census")
    assert assess_consistency(infobox, [body])["class"] == "internal_inconsistency"
    history = claim(1598, 2024, "census", role="historical", source="Wikipedia EN", location="history_table")
    assert "already gives the 2024 census" in assess_consistency(claim(1473, 2012, "census"), [history])["explanation"]
    assert assess_consistency(claim(1843, 2017), [claim(1843, 2017, "census", location="body")]) is None


def test_references():
    assert assess_sourcing(claim(26746, 2024, reference_raw=""), None, None, HUALQUI)["class"] == "unsourced"
    assert "citation needed" in assess_sourcing(claim(1, reference_raw="{{cr}}"), None, None, HUALQUI)["explanation"]
    match = {"verdict": None, "match": {"definition": "census", "year": 2024, "value": 11746, "obs_id": "c", "source": "INE"}}
    cited_2017 = assess_sourcing(claim(11746, reference_raw="<ref>censo2017.cl</ref>"), {"years": [2017],
                                 "domains": ["censo2017.cl"]}, match, QUIRIHUE)
    assert cited_2017["class"] == "mislabelled_vintage"
    assert {"kind": "citation", "source": "censo2017.cl", "location": "infobox reference", "years": [2017]} \
        in cited_2017["evidence"]  # the explanation names 2017, so the evidence must hold it


def test_wikidata_items_without_the_2024_count_or_a_preferred_statement():
    statements = [claim(24333, 2020, role="historical", source="Wikidata", location="statement", rank="NormalRank",
                        label="point in time 2020-01-01"),
                  claim(20968, 2007, role="historical", source="Wikidata", location="statement", rank="NormalRank",
                        label="point in time 2007-01-01")]
    classes = [v["class"] for _, v in assess_wikidata_item(statements, HUALQUI)]
    assert classes == ["outdated_vintage", "wikidata_rank_qualifier"]
    missing = claim(None, source="Wikidata", location="item", missing=True)
    assert assess_value(missing, HUALQUI)["class"] == "missing_value"


def test_figures_from_years_or_censuses_factsync_holds_nothing_for_are_not_checked():
    tortel = table({2017: 523, 2024: 505})
    assert assess_value(claim(227, 1970, role="historical", location="body"), tortel) is None       # 'en 1970'
    assert assess_value(claim(6695, 2002, role="historical", location="body"), tortel) is None      # '(INE 2002)'
    assert assess_value(claim(370, None, location="body"), tortel) is None     # a municipal count, no year
    assert assess_value(claim(523, None, location="body"), tortel)["class"] == "outdated_vintage"
    assert assess_value(claim(16508, 2012, "census", role="historical", location="body", label="2012 census"),
                        CURACAUTIN)["class"] == "discredited_source"


def test_a_reference_written_after_the_figure_counts():
    # enwiki Isla de Pascua: the <ref> sits in population_total, population_footnotes is empty
    isla = claim(7750, 2017, "census", source="Wikipedia EN", label="2017 census", reference_raw=None,
                 value_raw="7750<ref>{{cite web |language= es |url= https://resultados.censo2017.cl/Home/Download "
                           "|title= Censo 2017}}</ref>")
    assert assess_sourcing(isla, None, None, HUALQUI) is None


def test_rounding_is_not_read_into_a_census_figure_factsync_cannot_check():
    taltal = table({2017: 13317, 2024: 12097}, {2002: 10711, 2017: 12831})
    # enwiki Taltal: about 11,000 at the 2002 census; INE's 2002 projection 10,711 rounds to it by chance
    assert assess_value(claim(11000, 2002, "census", role="historical", source="Wikipedia EN", location="body"),
                        taltal) is None


def test_wikidata_with_the_latest_count_under_the_wrong_date():
    mejillones = table({2017: 13467, 2024: 14084})
    statement = claim(14084, 2020, role="historical", source="Wikidata", location="statement",
                      label="point in time 2020-01-01", rank="NormalRank")
    currency = assess_wikidata_item([statement], mejillones)[0][1]
    assert currency["explanation"] == ("Wikidata gives the Census 2024 count, 14,084, but its statement has point in "
                                       "time 2020-01-01, so no statement is for Census 2024.")


def test_rounding_never_overrides_a_label():
    # enwiki Juan Fernández: 900 labelled '2012 Census' is not read as Census 2024's 904 rounded
    verdict = assess_value(claim(900, 2012, "census", source="Wikipedia EN", label="2012 Census"), JUAN_FERNANDEZ)
    assert verdict["class"] == "discredited_source" and not verdict.get("rounded")


def test_a_history_table_row_is_named_once():
    # enwiki Freire: the table's 2017 row against the infobox's 2017 figure
    row = claim(24606, 2017, "census", role="historical", source="Wikipedia EN", location="history_table",
                label="2017 (Historical populations table)")
    verdict = assess_consistency(claim(22390, 2017, source="Wikipedia EN"), [row])
    assert verdict["explanation"] == ("The infobox gives 22,390 for 2017, but the Historical populations table gives "
                                      "24,606.")


def test_a_label_naming_a_census_factsync_holds_is_no_lead():
    # Pudahuel: eswiki and enwiki both give 240,819, enwiki as '2017 Census'; Census 2017 counted 230,293
    pudahuel = table({2017: 230293, 2024: 227820}, {2017: 240958})
    eswiki = claim(240819, 2017, "census")
    enwiki = claim(240819, 2017, "census", source="Wikipedia EN", label="2017 Census")
    verdict = assess_value(eswiki, pudahuel, [eswiki, enwiki])
    assert verdict["class"] == "cross_source_mismatch" and verdict["unexplained"] and not verdict.get("related")


def test_a_one_digit_slip_under_another_year_is_only_possibly_a_typo():
    chaiten = table({2017: 5071, 2024: 4025}, {2008: 5289})
    verdict = assess_value(claim(5073, 2008), chaiten)  # eswiki Chaitén: 5,073 (2008), one digit from the 2017 count
    assert verdict["class"] == "genuine_error" and "possibly a typo" in verdict["explanation"]
    assert verdict["ambiguous"] and verdict["confidence"] == 0.6
