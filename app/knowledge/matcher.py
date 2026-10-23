"""Deterministic matching of population claims against INE's official figures.

For each claim, code works out what it can know for certain: which official figure (census count or projection, for
which year) the value equals, whether it is one digit away from one (a typo), whether the census it is attributed to
was held or withdrawn, and whether the claim states the current population or a historical one. The result is a
candidate verdict. When the facts allow more than one reading it is marked ambiguous, and the Analyst asks the model.

The same facts tell the Critic which classes a verdict may have (`allowed_classes`), so the model's judgment is
always checked against arithmetic.
"""
from app.knowledge.taxonomy import census_facts, census_status
from app.knowledge.wikitext import has_citation


def fmt(value):
    return f"{value:,}"


def official_table(observations):
    """Official figures by definition and year, from the World Model's official observations."""
    table = {"census": {}, "projection": {}}
    for o in observations:
        p = o["payload"]
        if o["source"].get("kind") == "official" and p.get("property") == "population" and p.get("value") is not None:
            table.setdefault(p["definition"], {})[p["stated_year"]] = {
                "obs_id": o["id"], "source": o["source"].get("name"), "definition": p["definition"],
                "year": p["stated_year"], "value": p["value"]}
    return table


def latest_census(table):
    return table["census"][max(table["census"])]


def held_years():
    return set(census_facts()["held_by_factsync"])


def checkable_year(year, basis):
    """Whether a historical figure for `year` can be checked: it falls in the years INE's projections cover, and
    isn't (possibly) from an older census FactSync holds no figures for, such as 2002."""
    first, last = census_facts()["projection_years"]
    if not first <= year <= last:
        return False
    return basis == "projection" or census_status(year) != "valid" or year in held_years()


def unchecked_reason(claim):
    if not claim.get("stated_year"):
        return "no year stated and no official figure matches, so it can't be told what it refers to"
    return f"refers to {claim['stated_year']}, a year FactSync holds no official figures for"


def claim_evidence(claim):
    return {"kind": "claim", "obs_id": claim["id"], "source": claim["source_name"], "location": claim["location"],
            "value": claim["value"], "value_raw": claim.get("value_raw"), "label": claim.get("label"),
            "quote": claim.get("quote")}


def official_evidence(record):
    return {"kind": "official", "obs_id": record["obs_id"], "source": record["source"],
            "definition": record["definition"], "year": record["year"], "value": record["value"]}


def update_proposal(table):
    """The correction for a figure shown as the current population: INE's latest census count."""
    latest = latest_census(table)
    return {"action": "update", "value": latest["value"], "year": latest["year"], "definition": "census",
            "obs_id": latest["obs_id"], "source_key": f"census_{latest['year']}"}


def exact_matches(value, table):
    return [record for definition in ("census", "projection")
            for _, record in sorted(table.get(definition, {}).items()) if record["value"] == value]


def digit_slip(a, b):
    """How two figures of the same length differ when one looks like a typo of the other: 1 for one wrong digit or
    two neighbouring digits swapped, 2 for two neighbouring wrong digits (25,413 for 17,413); otherwise 0."""
    x, y = str(a), str(b)
    if len(x) != len(y) or x == y:
        return 0
    diffs = [i for i in range(len(x)) if x[i] != y[i]]
    if len(diffs) == 1:
        return 1
    if len(diffs) == 2 and diffs[1] == diffs[0] + 1:
        swapped = x[diffs[0]] == y[diffs[1]] and x[diffs[1]] == y[diffs[0]]
        return 1 if swapped else 2 if len(x) >= 4 else 0
    return 0


def near_miss(value, table, year):
    """The census count a figure is most likely a typo of (closest slip first, then the census year it states)."""
    candidates = [(digit_slip(value, r["value"]), r) for r in table["census"].values()]
    candidates = sorted(((slip, r) for slip, r in candidates if slip), key=lambda c: (c[0], c[1]["year"] != year,
                                                                                       -c[1]["year"]))
    return ({**candidates[0][1], "slip": candidates[0][0]}) if candidates else None


def stated_census(claim):
    """The census a claim is attributed to and how it stands ('valid', 'discredited', 'nonexistent'), or (None, None)
    when the claim isn't presented as a census figure."""
    if claim.get("basis") != "census" or not claim.get("stated_year"):
        return None, None
    return claim["stated_year"], census_status(claim["stated_year"])


def verdict(cls, explanation, confidence, claim, records=(), **extra):
    return {"class": cls, "explanation": explanation, "confidence": confidence,
            "evidence": [claim_evidence(claim)] + [official_evidence(r) for r in records],
            "ambiguous": False, "unexplained": False, "candidates": [], "match": None, "proposal": None, **extra}


def assess_value(claim, table, others=()):
    """Why this figure is what it is. Returns a candidate verdict, or None for a historical figure from a census
    FactSync holds no figures for (e.g. 'the 2002 census counted 16,970'), which can't be checked."""
    value, current = claim["value"], claim["role"] == "current"
    latest = latest_census(table)
    stated = claim.get("stated_year")
    census_year, status = stated_census(claim)
    label = claim.get("label") or (str(stated) if stated else "no year")
    now = f" The current official figure is the Census {latest['year']} count, {fmt(latest['value'])}." if current else ""

    if value is None:
        if claim.get("missing"):
            return verdict("missing_value", f"{claim['source_name']} has no population figure for this comuna; "
                           f"Census {latest['year']} counted {fmt(latest['value'])}.", 0.95, claim, [latest],
                           proposal=update_proposal(table))
        return verdict("genuine_error", f"The field holds no clean figure ('{claim.get('value_raw')}').{now}", 0.6,
                       claim, [latest] if current else [], ambiguous=True, candidates=["genuine_error", "unsourced"],
                       proposal=update_proposal(table) if current else {"action": "human_review"})

    matches = exact_matches(value, table)
    census_hits = [m for m in matches if m["definition"] == "census"]
    projection_hits = sorted((m for m in matches if m["definition"] == "projection"),
                             key=lambda m: (m["year"] != stated, -m["year"]))
    if census_hits:
        result = census_verdict(claim, census_hits[0], table, label, status, now)
        if projection_hits:  # the same number is also a projection: the label decides, so let the model weigh it
            result["evidence"] += [official_evidence(m) for m in projection_hits]
            result.update(ambiguous=True, candidates=[result["class"], "different_definition"],
                          confidence=min(result["confidence"], 0.7))
        return result
    if projection_hits:
        hit = projection_hits[0]
        if claim.get("basis") == "projection" and stated == hit["year"] and not current:
            return verdict("consistent", f"{fmt(value)} matches INE's projection for {hit['year']}.", 0.95, claim,
                           [hit], match=hit)
        presented = " presented as a census count" if claim.get("basis") == "census" else ""
        return verdict("different_definition",
                       f"{fmt(value)} is INE's projection for {hit['year']} (estimates and projections, base Census "
                       f"2017){presented}, not a census count; Census {latest['year']} counted {fmt(latest['value'])}.",
                       0.95 if stated in (None, hit["year"]) else 0.85, claim, [hit, latest], match=hit,
                       proposal=update_proposal(table) if current else {"action": "relabel", "value": value,
                                                                         "year": hit["year"], "definition": "projection",
                                                                         "obs_id": hit["obs_id"],
                                                                         "source_key": "projections_base2017"})
    if status == "discredited":
        return verdict("discredited_source", f"{fmt(value)} is attributed to the {census_year} census, whose results "
                       f"INE withdrew; it is not an official figure.{now}", 0.9, claim, [latest] if current else [],
                       proposal=update_proposal(table) if current else {"action": "deprecate"})
    if status == "nonexistent":
        return verdict("nonexistent_census", f"{fmt(value)} is attributed to a {census_year} census, but Chile held no "
                       f"census in {census_year}.{now}", 0.9, claim, [latest] if current else [],
                       proposal=update_proposal(table) if current else {"action": "human_review"})
    if not current and stated and not checkable_year(stated, claim.get("basis")):
        return None
    if status == "valid" and census_year not in held_years():
        return verdict("outdated_vintage", f"{fmt(value)} is attributed to the {census_year} census, an older count "
                       f"than Census {latest['year']} ({fmt(latest['value'])}); FactSync holds no {census_year} figures "
                       f"to verify it.", 0.85, claim, [latest], proposal=update_proposal(table))
    near = near_miss(value, table, stated)
    if not near and claim.get("location") in ("lead", "body") and not stated:
        return None  # prose with no year and no official match: can't tell what it refers to
    if near:
        is_latest = near["year"] == latest["year"]
        records = [table["census"][near["year"]]] + ([latest] if current and not is_latest else [])
        how = "one digit" if near["slip"] == 1 else "two neighbouring digits"
        return verdict("genuine_error", f"{fmt(value)} differs in {how} from INE's Census {near['year']} count, "
                       f"{fmt(near['value'])}: most likely a typo." + ("" if is_latest else now),
                       0.85 if near["slip"] == 1 else 0.75, claim, records, near=near,
                       ambiguous=near["slip"] == 2, candidates=["genuine_error", "cross_source_mismatch"],
                       proposal=update_proposal(table) if current else {"action": "fix_figure", "value": near["value"],
                                                                         "year": near["year"], "definition": "census",
                                                                         "obs_id": near["obs_id"],
                                                                         "source_key": f"census_{near['year']}"})
    return unexplained_verdict(claim, table, others, current, now)


def census_verdict(claim, hit, table, label, status, now):
    value, year, current = claim["value"], hit["year"], claim["role"] == "current"
    latest = latest_census(table)
    stated = claim.get("stated_year")
    if stated in (None, year) and status in (None, "valid"):
        if year == latest["year"] or not current:
            return verdict("consistent", f"{fmt(value)} matches INE's Census {year} count.", 0.95, claim, [hit],
                           match=hit)
        return verdict("outdated_vintage", f"{fmt(value)} is INE's Census {year} count, shown as the current figure.{now}",
                       0.95, claim, [hit, latest], match=hit, proposal=update_proposal(table))
    withdrawn = " (a census whose results INE withdrew)" if status == "discredited" else \
        " (a census that never took place)" if status == "nonexistent" else ""
    return verdict("mislabelled_vintage", f"{fmt(value)} is INE's Census {year} count, but it is labelled "
                   f"'{label}'{withdrawn}." + (now if year != latest["year"] else ""), 0.9, claim,
                   [hit] + ([latest] if current and hit is not latest else []), match=hit,
                   proposal=update_proposal(table) if current else {"action": "relabel", "value": value, "year": year,
                                                                     "definition": "census", "obs_id": hit["obs_id"],
                                                                     "source_key": f"census_{year}"})


def unexplained_verdict(claim, table, others, current, now):
    """A figure that equals no official figure held. Another source giving the same figure with a label is a lead;
    otherwise the figure is unexplained, and only the model (and the Critic) can take it further."""
    value = claim["value"]
    held = ", ".join(f"Census {y} {fmt(r['value'])}" for y, r in sorted(table["census"].items()))
    projections = table.get("projection") or {}
    if claim.get("stated_year") in projections:
        held += f", projection {claim['stated_year']} {fmt(projections[claim['stated_year']]['value'])}"
    records = [r for _, r in sorted(table["census"].items())]
    if claim.get("stated_year") in projections:
        records.append(projections[claim["stated_year"]])
    proposal = update_proposal(table) if current else {"action": "human_review"}
    for other in others:
        if other["id"] == claim["id"] or other["value"] != value or other["source_name"] == claim["source_name"]:
            continue
        year, status = stated_census(other)
        if not year:
            continue
        cls = {"discredited": "discredited_source", "nonexistent": "nonexistent_census"}.get(status, "mislabelled_vintage")
        why = "; INE withdrew that census's results" if status == "discredited" else ""
        result = verdict(cls, f"{fmt(value)} matches no official figure held ({held}), but {other['source_name']} "
                         f"gives the same figure labelled '{other.get('label')}'{why}.{now}", 0.7, claim, records,
                         ambiguous=True, unexplained=True, candidates=[cls, "cross_source_mismatch", "unsourced"],
                         related=other["id"], proposal=proposal)
        result["evidence"].append(claim_evidence(other))
        return result
    candidates = ["cross_source_mismatch", "genuine_error", "unsourced"]
    if not projections:
        candidates.append("different_definition")
    return verdict("cross_source_mismatch", f"{fmt(value)} matches no official figure held ({held}).{now}", 0.4, claim,
                   records, ambiguous=True, unexplained=True, candidates=candidates, proposal=proposal)


def allowed_classes(claim, table, others=()):
    """The classes the facts allow for a claim's value: what the Critic checks a verdict against."""
    candidate = assess_value(claim, table, others)
    if candidate is None:
        return set()
    if not candidate["unexplained"]:
        return {candidate["class"], *candidate["candidates"]}
    allowed = {"cross_source_mismatch", "genuine_error", "unsourced"}
    if candidate.get("related"):
        allowed.add(candidate["class"])
    if not table.get("projection"):
        allowed.add("different_definition")  # a guess the Critic sends back for checking, not a verified class
    return allowed


def assess_consistency(infobox, body_claims):
    """Infobox vs article text: a different figure for the same year, or a newer census figure in the text."""
    if infobox is None or infobox["value"] is None:
        return None
    same_year, newer = [], []
    for claim in body_claims:
        if claim["value"] is None or not claim.get("stated_year"):
            continue
        if claim["stated_year"] == infobox.get("stated_year") and claim["value"] != infobox["value"]:
            same_year.append(claim)
        elif infobox.get("stated_year") and claim["stated_year"] > infobox["stated_year"] \
                and claim.get("basis") == "census" and census_status(claim["stated_year"]) == "valid":
            newer.append(claim)
    if not (same_year or newer):
        return None
    where = {"history_table": "Historical populations table", "lead": "lead", "body": "article text"}
    if same_year:
        other = same_year[0]
        explanation = (f"The infobox gives {fmt(infobox['value'])} for {infobox['stated_year']}, but the "
                       f"{where.get(other['location'], 'article')} gives {fmt(other['value'])} ('{other['label']}').")
    else:
        other = max(newer, key=lambda c: c["stated_year"])
        explanation = (f"The infobox gives {fmt(infobox['value'])} ('{infobox.get('label')}'), while the "
                       f"{where.get(other['location'], 'article')} already gives the {other['stated_year']} census "
                       f"figure, {fmt(other['value'])}.")
    return {"class": "internal_inconsistency", "explanation": explanation, "confidence": 0.9,
            "evidence": [claim_evidence(infobox)] + [claim_evidence(c) for c in same_year + newer],
            "ambiguous": False, "unexplained": False, "candidates": [], "match": None, "related": other["id"]}


def assess_sourcing(claim, citation, value_verdict):
    """An infobox figure's reference: none, or 'citation needed', makes it unsourced; a reference that names other
    census years than the figure's own is a citation mismatch."""
    raw = (claim.get("reference_raw") or "").strip()
    if not has_citation(raw):
        explanation = "The infobox figure is tagged 'citation needed'." if raw else "The infobox figure has no reference."
        return {"class": "unsourced", "explanation": explanation, "confidence": 0.95,
                "evidence": [claim_evidence(claim)], "ambiguous": False, "unexplained": False, "candidates": [],
                "match": None, "proposal": {"action": "add_citation", "source_key": f"census_{max(held_years())}"}}
    match = (value_verdict or {}).get("match")
    years = (citation or {}).get("years") or []
    if match and match["definition"] == "census" and years and match["year"] not in years:
        domains = ", ".join(citation.get("domains") or []) or "its source"
        return {"class": "mislabelled_vintage",
                "explanation": f"The reference ({domains}) names {', '.join(map(str, years))}, but the figure is "
                               f"INE's Census {match['year']} count.",
                "confidence": 0.8, "evidence": [claim_evidence(claim), official_evidence(match)], "ambiguous": False,
                "unexplained": False, "candidates": [], "match": match,
                "proposal": {"action": "add_citation", "source_key": f"census_{max(held_years())}"}}
    return None


def assess_wikidata_item(statements, table):
    """Item-level checks: no population at all, no statement for the latest census, and missing ranks, points in
    time, methods or references. Returns (anchor claim, verdict) pairs."""
    latest = latest_census(table)
    values = [s for s in statements if s["value"] is not None]
    if not values:
        return []  # the missing-value observation gets its own value verdict
    results = []
    has_latest = any(s["value"] == latest["value"] and s.get("stated_year") == latest["year"] for s in values)
    newest = max(values, key=lambda s: s.get("stated_year") or 0)
    if not has_latest:
        results.append((newest, {
            "class": "outdated_vintage",
            "explanation": f"Wikidata's newest population statement is {fmt(newest['value'])} ({newest['label']}); "
                           f"Census {latest['year']} counted {fmt(latest['value'])}, and Wikidata has no statement "
                           f"for it.",
            "confidence": 0.95, "evidence": [claim_evidence(s) for s in values] + [official_evidence(latest)],
            "ambiguous": False, "unexplained": False, "candidates": [], "match": None,
            "proposal": {**update_proposal(table), "action": "add_statement"}}))
    issues = []
    for test, text in ((lambda s: not s.get("stated_year"), "no point in time"),
                       (lambda s: not s.get("determination_method"), "no determination method"),
                       (lambda s: not s.get("references"), "no reference")):
        hit = [fmt(s["value"]) for s in values if test(s)]
        if hit:
            issues.append(f"{text} on {', '.join(hit)}")
    if len(values) > 1 and not any((s.get("rank") or "").startswith("Preferred") for s in values):
        issues.append("no statement is ranked preferred, so all of them count as current")
    if issues:
        results.append((newest, {
            "class": "wikidata_rank_qualifier",
            "explanation": "Wikidata's population statements have " + "; ".join(issues) + ".",
            "confidence": 0.95, "evidence": [claim_evidence(s) for s in values], "ambiguous": False,
            "unexplained": False, "candidates": [], "match": None,
            "proposal": {"action": "set_rank_qualifiers", "source_key": f"census_{latest['year']}"}}))
    return results
