"""Test doubles for the second fact: a Zetaris that serves SERVEL's real rows (from the committed CSV) and the real
mayor fields of four comunas' infoboxes as recorded on Oct 26, 2026 (Rengo's articles carry no comuna code, as in the
live data, so the Retriever matches them by name), and model handlers for the mayor prompts."""
import csv
import re

from app.adapters.zetaris import QueryResult
from app.config import ROOT
from app.knowledge.catalog import BUILT_IN, COLUMNS
from app.knowledge.names import compare, person, tokens

COMUNAS = [("06115", "RENGO", "REGIÓN DEL LIBERTADOR GENERAL BERNARDO O'HIGGINS"),
           ("05703", "LLAILLAY", "REGIÓN DE VALPARAÍSO"), ("16106", "PINTO", "REGIÓN DE ÑUBLE"),
           ("07408", "YERBAS BUENAS", "REGIÓN DEL MAULE")]
ITEMS = {"06115": "Q56120", "05703": "Q14498", "16106": "Q51106", "07408": "Q2056254"}
# (cut as the article view gives it, title, revid, office, name field, party field)
ESWIKI = [(None, "Rengo", "175000001", "[[Alcalde]]", "Enrique Alfonso del Barrio Hernández", None),
          ("05703", "Llay-Llay", "175514873", "[[Alcalde]]",
           "Edgardo González Arancibia ([[Partido Demócrata Cristiano (Chile)|PDC]])", None),
          ("16106", "Pinto (Chile)", "175893369", "[[Alcalde]]",
           "[[Jairo del Pino Lema|Jairo del Pino]] ([[Partido Republicano de Chile (2019)|REP]])", None),
          ("07408", "Yerbas Buenas", "176001633", "[[Anexo:Alcaldes de Chile|Alcalde]]", "Rafael Viguera González", None)]
ENWIKI = [(None, "Rengo", "1300000001", "[[Alcalde]]", "Carlos Soto", ""),
          ("05703", "Llay-Llay", "1382101060", "[[Alcalde]]", "Mario Marillanca", ""),
          ("16106", "Pinto, Chile", "1378790942", "[[Alcalde]]", "Wyatt Mathis", "[[Independent Democratic Union|UDI]]"),
          ("07408", "Yerbas Buenas", "1381926554", "[[Mayor]]", "Rafael Viguera González", None)]
WIKIDATA = [("07408", "s-yerbas-p6", "Jonathan Eduardo Norambuena Barros", "2024-12-06", "2026-10-22",
             "https://www.sinim.gov.cl/ficha_comunal.php?municipio=07408")]
SERVEL_CSV = ROOT / "data" / "official" / "servel_alcaldes_2012_2024.csv"


def servel_rows():
    with SERVEL_CSV.open(encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["cut"] in ITEMS]


def article(language, office, name, party):
    if language == "es":
        return f"{{{{Ficha de entidad subnacional\n| dirigentes_títulos = {office}\n| dirigentes_nombres = {name}\n}}}}"
    return (f"{{{{Infobox settlement\n| leader_title = {office}\n| leader_name = {name}\n"
            f"| leader_party = {party or ''}\n}}}}")


def wikipedia_rows(rows, language, wanted):
    return [{"cut": cut, "wikidata_item": f"http://www.wikidata.org/entity/{ITEMS[c]}", "title": title, "revid": revid,
             "revision_timestamp": "2026-10-20T00:00:00Z", "wikitext": article(language, office, name, party),
             "office_raw": office, "name_raw": name, "party_raw": party if language == "en" else None}
            for (cut, title, revid, office, name, party), c in zip(rows, ITEMS) if cut is None or cut in wanted]


class FakeMayorZetaris:
    """Serves the catalog, INE's comuna list and the mayor views, honouring the CUT list and election year."""

    def __init__(self):
        self.sql = []
        self.servel = servel_rows()

    def query(self, sql, limit=100_000):
        self.sql.append(sql)
        wanted = set(re.findall(r"'(\d{5})'", sql)) or set(ITEMS)
        if "factsync.source_catalog" in sql:
            rows = [{c: None if row[c] is None else str(row[c]).lower() if isinstance(row[c], bool) else str(row[c])
                     for c in COLUMNS} for row in BUILT_IN]
        elif "factsync.ine_census2024" in sql:
            rows = [{"cut": c, "comuna": n, "region": r} for c, n, r in COMUNAS]
        elif "factsync.servel_mayors" in sql:
            year = re.search(r"year = (\d{4})", sql).group(1)
            rows = [{**r, "elected": r["elected"]} for r in self.servel if r["year"] == year and r["cut"] in wanted]
        elif "factsync.wikidata_mayor" in sql:
            stated = {cut: (st, name, start, end, ref) for cut, st, name, start, end, ref in WIKIDATA}
            rows = []
            for cut, item in ITEMS.items():
                if cut not in wanted:
                    continue
                st, name, start, end, ref = stated.get(cut, (None,) * 5)
                rows.append({"wikidata_item": f"http://www.wikidata.org/entity/{item}", "cut": cut,
                             "label_es": next(n for c, n, _ in COMUNAS if c == cut).title(), "statement_id": st,
                             "person_item": "http://www.wikidata.org/entity/Q130000001" if st else None,
                             "person_label_es": name, "person_label_en": name, "start_time": start, "end_time": end,
                             "rank": "NormalRank" if st else None, "reference_url": ref, "stated_in": None})
        elif "factsync.eswiki_mayor" in sql:
            rows = wikipedia_rows(ESWIKI, "es", wanted)
        elif "factsync.enwiki_mayor" in sql:
            rows = wikipedia_rows(ENWIKI, "en", wanted)
        else:
            raise AssertionError(f"unexpected SQL: {sql}")
        return QueryResult(sql, list(rows[0]) if rows else [], rows, len(rows), 3, 1)


# ----- model handlers for the mayor prompts --------------------------------------------------------------------

def analyst_matches_by_surname(payload):
    """The candidate whose first surname and a given name (or its start) appear in the name; else a reading."""
    verdicts = []
    for claim in payload["claims"]:
        written = tokens(claim["name_as_written"])
        chosen = next((c["person_id"] for c in claim["candidates"]
                       if compare(claim["name_as_written"], person(*split(c["name"])))["level"] in ("same", "likely")
                       or (written and any(w in tokens(c["name"]) for w in written[-2:])
                           and any(t.startswith(written[0]) for t in tokens(c["name"])))), None)
        verdicts.append({"claim_id": claim["claim_id"], "same_person_as": chosen,
                         "reading": None if chosen else "vandalism",
                         "explanation": f"{claim['name_as_written']} is "
                                        + ("a candidate listed." if chosen else "not a name SERVEL lists for this comuna; "
                                           "it looks like vandalism."),
                         "confidence": 0.7})
    return {"verdicts": verdicts}


def split(full):
    """A SERVEL full name as (given, first surname, second surname), for the handlers: the last two words are the
    surnames, a particle staying with the word after it."""
    words = full.split()
    second = words[-1]
    first_at = len(words) - 2
    while first_at > 1 and words[first_at - 1] in ("DEL", "DE", "LA", "LOS", "LAS"):
        first_at -= 1
    return " ".join(words[:first_at]), " ".join(words[first_at:-1]), second


def planner_reads_the_previous_election(payload):
    def latest(candidates):
        return max(candidates, key=lambda s: int(s.rsplit("_", 1)[1]))
    return {"choices": [{"figure": n, "source": latest(f["candidates"]),
                         "reason": "A former mayor was most likely elected in the previous election."}
                        for n, f in payload["figures"].items()]}


def editor_names(payload):
    elected, year = payload["elected"]["name"], payload["elected"]["year"]
    name = " ".join(w.title() if w not in ("DEL", "DE", "LA") else w.lower() for w in elected.split())
    return {"name": name, "es_summary": f"Alcalde según SERVEL (elección {year}): {name}.",
            "en_summary": f"Mayor per SERVEL's {year} election results: {name}.",
            "explanation": f"The pages name someone else; SERVEL's results show {name} elected in {year}."}


def critic_agrees(payload):
    return {"reviews": [{"finding_id": f["finding_id"], "class_fits": True, "explanation_faithful": True, "note": ""}
                        for f in payload["findings"]]}


MAYOR_HANDLERS = {"Analyst": analyst_matches_by_surname, "Planner": planner_reads_the_previous_election,
                  "Editor": editor_names, "Critic": critic_agrees}
