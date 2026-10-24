"""The conflict taxonomy (why a population figure differs from the official one) and the census facts it rests on.

Census facts live in data/reference/chile_censuses.json: which censuses Chile held, which one INE withdrew (2012), and
the official INE sources a correction or a check may cite. Which censuses a run holds figures for depends on what it
read (the source catalog, app/knowledge/catalog.py).
"""
import json
from functools import cache

from app.config import ROOT

CLASSES = {
    "consistent": "Matches the official figure it says it is.",
    "outdated_vintage": "An older official figure (e.g. the Census 2017 count) shown as the current population.",
    "different_definition": "An official figure under another definition (an INE estimate or projection, or only the "
                            "urban or rural part of a census count) shown where the comuna's census count is "
                            "expected. Not an error in itself.",
    "discredited_source": "Attributed to the 2012 census, whose results INE withdrew.",
    "nonexistent_census": "Attributed to a census Chile never held (e.g. 1999, 2022).",
    "mislabelled_vintage": "A real official figure labelled with the wrong year or census, or cited to a source that "
                           "doesn't hold it (citation mismatch).",
    "internal_inconsistency": "The article contradicts itself (infobox vs body).",
    "cross_source_mismatch": "Matches no official figure, and nothing in the sources explains it.",
    "wikidata_rank_qualifier": "Wikidata statements lack the rank, point in time, method or reference needed to use "
                               "them correctly.",
    "unsourced": "No reference, or a reference that can't support the figure.",
    "genuine_error": "A typo, a wrong unit or a corrupted field.",
    "missing_value": "The source has no population figure at all.",
}
PROBLEMS = sorted(set(CLASSES) - {"consistent"})

# Classes that only make sense when the figure equals an official figure under the named definition.
NEEDS_OFFICIAL_MATCH = {"consistent", "outdated_vintage", "mislabelled_vintage", "different_definition"}
# Classes a figure can get from its label or its digits alone, before every official source has been read.
LABEL_DETERMINED = {"discredited_source", "nonexistent_census", "genuine_error", "missing_value"}


@cache
def census_facts():
    return json.loads((ROOT / "data" / "reference" / "chile_censuses.json").read_text(encoding="utf-8"))


def census_status(year):
    """How a figure attributed to a census in `year` stands: 'valid', 'discredited' or 'nonexistent'."""
    if year is None:
        return None
    facts = census_facts()
    if str(year) in facts["discredited"]:
        return "discredited"
    return "valid" if int(year) in facts["valid"] else "nonexistent"


def official_source(key):
    return census_facts()["official_sources"][key]


def is_official_domain(domain):
    return any(domain == d or domain.endswith("." + d) for d in census_facts()["official_domains"])


def describe_classes(classes=None):
    """The taxonomy as prompt text: one line per class."""
    return "\n".join(f"- {name}: {CLASSES[name]}" for name in (classes or CLASSES))
