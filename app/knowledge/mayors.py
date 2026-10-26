"""The second fact, mayors: what SERVEL's election results say, the taxonomy of why a page's mayor differs from
them, and the deterministic verdicts the agents start from (the counterpart of matcher.py and taxonomy.py).

SERVEL says who was ELECTED in each election, never who holds the office today: resignations, removals, deaths,
stand-ins and replacements chosen by the council don't appear in it. So no verdict calls a name wrong; a name SERVEL
can't explain is "unknown", and every draft asks the editor to check that the office hasn't changed hands since.

Election facts (dates, terms, sources) live in data/reference/chile_municipal_elections.json.
"""
import json
import re
from datetime import date
from functools import cache

from app.config import ROOT
from app.knowledge import names

FACT = "mayor"
CLASSES = {
    "consistent": "Names the mayor elected in the latest election read (SERVEL).",
    "outdated_mayor": "Names a mayor elected in an earlier election who wasn't elected in the latest one: a former "
                      "mayor shown as the current one.",
    "not_elected": "Names someone SERVEL lists as a candidate for this comuna who wasn't elected in any election "
                   "read: possibly a replacement chosen after the election, or a mayor from before 2012.",
    "unknown_name": "Names no one SERVEL lists as a candidate for this comuna in the elections read: possibly a "
                    "stand-in or a replacement, a misspelling, or vandalism. Never called wrong without a human.",
    "missing_value": "The source names no mayor at all.",
    "wikidata_qualifier": "A Wikidata mayor statement lacks the start time, end time or reference needed to read it "
                          "correctly, or gives a wrong one.",
}
PROBLEMS = sorted(set(CLASSES) - {"consistent"})
JUDGED = {"not_elected", "unknown_name"}  # verdicts that need judgment; the others follow from SERVEL's rows
PAGES = {"es": "eswiki", "en": "enwiki", "wikidata": "wikidata"}


@cache
def facts():
    return json.loads((ROOT / "data" / "reference" / "chile_municipal_elections.json").read_text(encoding="utf-8"))


def election(year):
    return facts()["elections"][str(year)]


def official_source(year):
    return facts()["official_sources"][f"servel_{year}"]


def describe_classes(classes=None):
    return "\n".join(f"- {name}: {CLASSES[name]}" for name in (classes or CLASSES))


def stand_in(notes):
    """Whether the text beside a name calls the person a stand-in ('alcalde suplente', '(S)')."""
    words = facts()["stand_in_words"]
    return any(n.strip().lower() in ("s", "(s)") or any(w in n.lower() for w in words) for n in notes or [])


# ----- SERVEL's rows -------------------------------------------------------------------------------------------

def election_table(observations):
    """SERVEL's candidates by election year, from the World Model's official mayor observations: {year: [row]},
    each row with the person's name parts, party, votes and whether elected, winners first."""
    table = {}
    for o in observations:
        p = o["payload"]
        if o["source"].get("kind") != "official" or p.get("property") != "mayor_candidate":
            continue
        row = {"obs_id": o["id"], "year": p["year"], "name": p["name"], "party": p.get("party"), "pact": p.get("pact"),
               "votes": p.get("votes"), "elected": bool(p.get("elected")), "source": o["source"].get("name"),
               "person": names.person(p.get("given_names"), p.get("first_surname"), p.get("second_surname"))}
        table.setdefault(p["year"], []).append(row)
    for rows in table.values():
        rows.sort(key=lambda r: (not r["elected"], -(r["votes"] or 0)))
    return dict(sorted(table.items()))


def latest_year(table):
    return max(table) if table else None


def winner(table, year=None):
    year = year or latest_year(table)
    return next((r for r in table.get(year, []) if r["elected"]), None)


def people(table):
    """Every person in the elections read, with the years they ran and won: {key: {'rows', 'ran', 'won'}}. One
    person's rows share both surnames, and one row's given names include the other's: SERVEL writes the same mayor
    'ALBERTO PATRICIO' in 2016 and 'PATRICIO' in 2024 (2024 keeps one given name, not always the first), while
    'JUAN CARLOS' and 'JUAN PABLO' stay two people."""
    found = {}
    rows = sorted(((year, row) for year, rows_ in table.items() for row in rows_),
                  key=lambda yr: -len(yr[1]["person"]["given"]))
    for year, row in rows:
        surnames = (tuple(row["person"]["first"]), tuple(row["person"]["second"]))
        given = set(row["person"]["given"])
        key = next((k for k, e in found.items() if k[:2] == surnames and given <= e["given"]), None)
        if key is None:
            key = (*surnames, len(found))
            found[key] = {"rows": [], "ran": [], "won": [], "given": given}
        entry = found[key]
        entry["rows"].append(row)
        entry["ran"].append(year)
        if row["elected"]:
            entry["won"].append(year)
    for entry in found.values():
        entry["ran"], entry["won"] = sorted(set(entry["ran"])), sorted(set(entry["won"]))
    return found


def matches(name, table):
    """Each person in the elections read whose name fits `name`, best fit first: [(level, why, person entry)]."""
    found = []
    for entry in people(table).values():
        fit = max((names.compare(name, row["person"]) for row in entry["rows"]),
                  key=lambda f: names.LEVELS[f["level"]])
        if fit["level"] != "none":
            found.append((fit["level"], fit["why"], entry))
    return sorted(found, key=lambda m: (-names.LEVELS[m[0]], -len(m[2]["won"]), -max(m[2]["ran"])))


def title(row):
    return names.title_case(row["name"])


def terms(years):
    """'2012, 2016 and 2021' (the elections a person won)."""
    years = sorted(years)
    return ", ".join(map(str, years[:-1])) + (" and " if len(years) > 1 else "") + str(years[-1]) if years else ""


def classify(entry, table):
    """The class a person's record gives a page naming them: elected in the latest election read, in an earlier one,
    or never in the elections read."""
    if latest_year(table) in entry["won"]:
        return "consistent"
    return "outdated_mayor" if entry["won"] else "not_elected"


def evidence_rows(table, entry=None):
    """The SERVEL rows a verdict cites: the latest winner, and every row of the person the page names."""
    rows = [winner(table)] + (entry["rows"] if entry else [])
    seen, cited = set(), []
    for row in rows:
        if row and row["obs_id"] not in seen:
            seen.add(row["obs_id"])
            cited.append({"kind": "official", "obs_id": row["obs_id"], "source": row["source"], "year": row["year"],
                          "name": row["name"], "elected": row["elected"], "votes": row["votes"], "party": row["party"]})
    return cited


def proposal(table, claim, cls, check_first=False):
    """The correction a finding proposes: the latest winner, from SERVEL's results of that election. `check_first`
    when the page may be right after all (a stand-in, a replacement): the draft then asks the editor to check
    before applying it."""
    if cls == "consistent":
        return None
    top = winner(table)
    year = latest_year(table)
    if claim["target"] == "wikidata":
        action = "set_qualifiers" if cls == "wikidata_qualifier" else "add_statement"
    else:
        action = "update"
    return {"action": action, "person": top["name"], "year": year, "source_key": f"servel_{year}",
            "obs_id": top["obs_id"], "check_first": check_first}


PAGE_NAMES = {"es": "The Spanish Wikipedia infobox", "en": "The English Wikipedia infobox",
              "wikidata": "Wikidata (no head of government statement)"}


def explain(cls, name, entry, table, comuna, notes=(), target=None):
    top, year = winner(table), latest_year(table)
    comuna = names.title_case(comuna)
    elected = f"{title(top)} was elected in the {year} election (SERVEL; term from {election(year)['term_from']})"
    read = terms(list(table))
    if cls == "consistent":
        who = f"{name} is {title(top)}," if names.fold(name) != names.fold(top["name"]) else f"{name} was"
        return f"{who} elected mayor of {comuna} in {year} (SERVEL)."
    if cls == "missing_value":
        return f"{PAGE_NAMES.get(target, 'The page')} names no mayor. {elected}."
    who = title(max(entry["rows"], key=lambda r: len(r["name"]))) if entry else None
    named = f"{name} is {who}," if who and names.fold(name) != names.fold(who) else f"{name} was"
    if cls == "outdated_mayor":
        lost = [r for r in entry["rows"] if r["year"] == year]
        again = f" {who} ran again in {year} and wasn't elected ({lost[0]['votes']:,} votes to {top['votes']:,})." \
            if lost and isinstance(lost[0]["votes"], int) and isinstance(top["votes"], int) else ""
        return f"{named} elected mayor in {terms(entry['won'])} (SERVEL). {elected}.{again}"
    if cls == "not_elected":
        return (f"{named} a candidate in {terms(entry['ran'])}, not elected in any election read ({read}). "
                f"{elected}. {who} may hold the office as a replacement, or may have been mayor before 2012: check "
                f"before changing it.")
    note = f" The page itself calls them '{'; '.join(notes)}'." if stand_in(notes) else ""
    return (f"{name} matches no candidate SERVEL lists for {comuna} in {read}. {elected}. It may be a stand-in or a "
            f"replacement chosen by the council, a misspelling, or vandalism.{note}")


def assess(claim, table, comuna, unread=()):
    """The deterministic verdict on what one page says about the mayor. `unread`: the elections not read yet. Returns
    a dict like matcher.assess_value's: class, explanation, confidence, evidence, proposal, ambiguous (the model
    should decide), unexplained (an unread election could explain it), candidates (classes the facts allow),
    person (the SERVEL person matched) and matches (every person whose name fits, for the model)."""
    name, notes = claim.get("name"), claim.get("notes") or []
    if not name:
        return {"class": "missing_value", "explanation": explain("missing_value", name, None, table, comuna,
                                                                 target=claim.get("target")),
                "confidence": 0.9, "evidence": evidence_rows(table), "ambiguous": False, "unexplained": False,
                "candidates": ["missing_value"], "person": None, "matches": [],
                "proposal": proposal(table, claim, "missing_value")}
    found = matches(name, table)
    best = [m for m in found if m[0] == found[0][0]] if found else []
    level = best[0][0] if best else "none"
    entry = best[0][2] if len(best) == 1 else None
    if entry and level in ("same", "likely"):
        cls = classify(entry, table)
        confidence = 0.9 if level == "same" and cls not in JUDGED else 0.6  # 'not elected' is a reading, not a match
        ambiguous = level == "likely"
    else:
        cls, confidence, ambiguous = "unknown_name", 0.5, bool(found)
    # a name that isn't the latest winner could be explained by an election not read yet
    unexplained = bool(unread) and cls in ("unknown_name", "not_elected")
    allowed = sorted({classify(m[2], table) for m in found} | {"unknown_name"}) if (ambiguous or not entry) else [cls]
    check_first = cls in JUDGED or stand_in(notes)
    return {"class": cls, "explanation": explain(cls, name, entry, table, comuna, notes), "confidence": confidence,
            "evidence": evidence_rows(table, entry), "ambiguous": ambiguous, "unexplained": unexplained,
            "candidates": allowed, "person": person_ref(entry), "level": level,
            "matches": [{"level": lvl, "why": why, **person_ref(e)} for lvl, why, e in found[:4]],
            "proposal": proposal(table, claim, cls, check_first)}


def person_ref(entry):
    if not entry:
        return None
    rows = entry["rows"]
    full = max((r["name"] for r in rows), key=len)  # the fullest spelling (2024 drops middle names)
    return {"id": "p_" + "_".join(names.fold(full).split()).lower(), "name": full, "ran": sorted(entry["ran"]),
            "won": sorted(entry["won"])}


def person_by_id(table, person_id):
    for entry in people(table).values():
        ref = person_ref(entry)
        if ref["id"] == person_id:
            return entry
    return None


# ----- Wikidata ------------------------------------------------------------------------------------------------

def assess_wikidata(statements, table, comuna, today=None):
    """Wikidata's head of government statements (P6) of one comuna item. Returns [(statement claim, verdict)] for
    the findings, and the signals other pages' verdicts should know (the latest winner's term recorded as ended)."""
    today = (today or date.today()).isoformat()
    top, year = winner(table), latest_year(table)
    found, signals = [], []
    current = [s for s in statements if not s.get("end_time") or s["end_time"] > today]
    for statement in statements:
        verdict = assess(statement, table, comuna)
        is_winner = verdict["class"] == "consistent"
        if is_winner and statement.get("end_time") and statement["end_time"] <= today:
            signals.append({"kind": "term_ended", "source": "Wikidata", "date": statement["end_time"],
                            "person": top["name"], "statement": statement.get("statement")})
        problems = []
        if is_winner:
            term_from = election(year)["term_from"]
            starts = {election(won)["term_from"] for won in (verdict["person"] or {}).get("won") or [year]}
            start = statement.get("start_time") or ""
            year_only = start.endswith("-01-01") and start[:4] in {s[:4] for s in starts}  # a date to the year: "2024"
            if start not in starts and not year_only:
                problems.append(f"its start time is {start or 'missing'}, but the term began on {term_from}")
            if not statement.get("references"):
                problems.append("it has no reference")
        elif statement in current and verdict["class"] != "consistent":
            found.append((statement, verdict))
            continue
        if problems:
            found.append((statement, {**verdict, "class": "wikidata_qualifier", "candidates": ["wikidata_qualifier"],
                                      "explanation": f"Wikidata's statement for {title(top)}: " + "; ".join(problems)
                                                     + ".", "proposal": proposal(table, statement, "wikidata_qualifier"),
                                      "ambiguous": False, "unexplained": False}))
    return found, signals


def office_changed(signals, comuna_name):
    """A sentence for verdicts when another source records the latest winner's term as ended."""
    ended = next((s for s in signals if s["kind"] == "term_ended"), None)
    if not ended:
        return None
    return (f"{ended['source']} records the end of {names.title_case(ended['person'])}'s term on {ended['date']}: "
            f"the office of mayor of {comuna_name} may have changed hands since the election.")


# ----- the picture ---------------------------------------------------------------------------------------------

def mayor_picture(observations, assessments):
    """The World Model projection for mayors: per page, the name it shows and the verdict on it, from the latest
    run that checked the comuna's mayor (assessments marked fact=mayor). Same shape as comuna_picture's pages, so
    picture.since_last_check compares two of them."""
    mine = [a for a in assessments if (a["data"] or {}).get("fact") == FACT and a["run_id"]]
    analysed = [a for a in mine if a["agent"] == "Analyst"]
    elected = {}
    for o in observations:
        p = o["payload"]
        if o["source"].get("kind") == "official" and p.get("property") == "mayor_candidate" and p.get("elected"):
            elected[str(p["year"])] = p["name"]
    if not analysed:
        return {"run_id": None, "elected": elected, "pages": {}}
    run_id = analysed[-1]["run_id"]
    mine = [a for a in mine if a["run_id"] == run_id]
    final = max(a["round"] or 0 for a in mine if a["agent"] == "Analyst")
    verdicts = [a["data"] for a in mine if a["agent"] == "Analyst" and (a["round"] or 0) == final]
    status = {}
    for a in mine:
        if a["agent"] in ("Critic", "Orchestrator") and a["data"].get("finding_id"):
            status[a["data"]["finding_id"]] = a["data"]["status"]
    pages = {}
    for data in verdicts:
        claim = data.get("claim") or {}
        page = PAGES.get(claim.get("target"))
        if not page or page in pages or claim.get("location") not in ("infobox", "statement", "item"):
            continue
        verdict = data.get("class") or data.get("check")
        pages[page] = {"value": claim.get("name"), "label": claim.get("office"), "reference": claim.get("reference_raw"),
                       "observation": claim.get("id"), "verdict": verdict,
                       "status": status.get(data.get("id"), "checked" if data.get("check") else "proposed")}
    return {"run_id": run_id, "checked_at": max(a["created_at"] for a in mine), "elected": elected, "pages": pages}


def shown(value):
    """A figure or a name, for messages: 25,795 or 'Carlos Soto'."""
    return f"{value:,}" if isinstance(value, int) else f"'{value}'" if value else "no name"


def cue_years(text):
    """Years a page's text points to (a reference's date, a term like 2016-2021), for choosing which election to read."""
    return sorted({int(y) for y in re.findall(r"\b(20[01][0-9]|202[0-6])\b", str(text or ""))})


def fit(source, figure):
    """How well an election fits a name's cues, lower first: an election held in or just before a year the page
    points to, else the most recent one not read (a former mayor is most likely the previous one)."""
    year = source["years_from"]
    cues = figure.get("cues") or []
    if any(0 <= cue - year < 5 for cue in cues):
        return (0, -year)
    return (1, -year)
