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
    one = assess_value(claim(17431, 2017), CURACAUTIN)
    assert one["class"] == "genuine_error" and not one["ambiguous"] and one["confidence"] == 0.85
    assert assess_value(claim(26746, 2024), table({2017: 24333, 2024: 25795}))["class"] != "genuine_error"


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
    assert assess_sourcing(claim(26746, 2024, reference_raw=""), None, None)["class"] == "unsourced"
    assert "citation needed" in assess_sourcing(claim(1, reference_raw="{{cr}}"), None, None)["explanation"]
    match = {"verdict": None, "match": {"definition": "census", "year": 2024, "value": 11746, "obs_id": "c", "source": "INE"}}
    cited_2017 = assess_sourcing(claim(11746, reference_raw="<ref>censo2017.cl</ref>"), {"years": [2017],
                                 "domains": ["censo2017.cl"]}, match)
    assert cited_2017["class"] == "mislabelled_vintage"


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
