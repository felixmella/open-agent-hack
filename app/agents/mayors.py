"""The agents' work on the second fact, mayors: who Wikipedia and Wikidata name as each comuna's mayor, against
SERVEL's election results.

Same agents, same loop, same World Model: each class here is the mayor reading of an agent in app/agents/ (the
trace names it as that agent), and keeps its contract with the orchestrator. Code reads the structured fields and
recomputes every fact; the model decides what code can't settle (whether two differently written names are the same
person, what a name SERVEL never had might be, which election to read next) and words the drafts, and code checks
each answer:

  Extractor  reads each infobox's mayor field: the name, the text in brackets (a party, "alcalde suplente"), a linked
             article, the years it points to. The model only for a field code can't read; its name must be in the field
  Analyst    compares each name with every candidate of the elections read (app/knowledge/names.py, mayors.py); asks
             the model which candidate an uncertain name refers to, then derives the class from that person's record
  Critic     the same 9-point rubric; holds back a name no election read explains while an unread election could,
             and sends the Planner to read one (discovery, one election further back each round)
  Editor     drafts the infobox lines and Wikidata statement from SERVEL's winner, spelled as a page already spells
             them, else as the model writes them (checked letter by letter against SERVEL), else from SERVEL's capitals

SERVEL says who was elected, never who holds the office today: every draft asks the editor to check that, and a
page whose name the Analyst can't explain is never called wrong without a human.
"""
import re
from datetime import date

from app.agents.analyst import Analyst, digest
from app.agents.critic import AGENT_ORDER, APPROVE_AT, Critic, signature
from app.agents.editor import Editor, en_date, es_date
from app.agents.extractor import Extractor
from app.agents.llm import batched, model_note
from app.knowledge import mayors, names
from app.knowledge.catalog import coverage, of_fact
from app.knowledge.wikitext import infobox_parameters

FACT = mayors.FACT
PAGE_OF = {"eswiki": "es", "enwiki": "en", "wikidata": "wikidata"}
NAME_FIELDS = {"es": ("dirigentes_nombres", "alcalde", "dirigentes_nombres1", "dirigente1_nombre",
                      "nombres de dirigentes"),
               "en": ("leader_name", "leader_name1", "mayor")}
OFFICE_FIELDS = {"es": ("dirigentes_títulos", "dirigentes_títulos1", "dirigente1_cargo"),
                 "en": ("leader_title", "leader_title1")}
REFS = re.compile(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", re.S | re.I)
CLAIM_FIELDS = ("id", "target", "source_name", "title", "revid", "location", "role", "name", "name_raw", "notes",
                "linked", "office", "party", "reference_raw", "cues", "method", "verified", "missing", "field", "item",
                "statement", "person_item", "start_time", "end_time", "rank", "references")
CAVEAT = ("SERVEL's results say who was elected on {days}, for the term from {term_from}; they don't say who holds "
          "the office today. Before applying this, check that it hasn't changed hands since (a resignation, a "
          "removal, a death, a stand-in).")


def compact(claim):
    return {k: claim[k] for k in CLAIM_FIELDS if claim.get(k) not in (None, [], "")}


def build_claims(observations):
    """The mayor claims to check, from the run's observations: each infobox's mayor field (the Extractor's reading
    replaces Zetaris's raw one) and each Wikidata head of government statement (or the item's lack of one)."""
    read = {(o["source"].get("language"), o["source"].get("revid")) for o in observations
            if o["payload"].get("property") == "mayor" and o["payload"].get("extracted_by") == "Extractor"}
    claims = []
    for o in observations:
        p, s = o["payload"], o["source"]
        if p.get("property") != "mayor":
            continue
        if s.get("kind") == "wikipedia":
            if p.get("extracted_by") != "Extractor" and (s.get("language"), s.get("revid")) in read:
                continue
            claims.append({"id": o["id"], "target": s["language"], "source_name": s["name"], "title": s.get("title"),
                           "revid": s.get("revid"), "article": (s["language"], s.get("revid")), "location": "infobox",
                           "role": "current", "name": p.get("name"), "name_raw": p.get("name_raw"),
                           "notes": p.get("notes") or [], "linked": p.get("linked"), "office": p.get("office"),
                           "party": p.get("party"), "reference_raw": p.get("reference_raw"),
                           "cues": p.get("cues") or [], "method": p.get("method") or "zetaris",
                           "verified": p.get("verified", True), "missing": not p.get("name"), "field": p.get("field")})
        elif s.get("kind") == "wikidata":
            if p.get("missing"):
                claims.append({"id": o["id"], "target": "wikidata", "source_name": "Wikidata", "location": "item",
                               "role": "current", "name": None, "missing": True, "item": s.get("item")})
            else:
                claims.append({"id": o["id"], "target": "wikidata", "source_name": "Wikidata", "location": "statement",
                               "role": "current", "name": p.get("name"), "person_item": p.get("person_item"),
                               "start_time": p.get("start_time"), "end_time": p.get("end_time"),
                               "rank": p.get("rank"), "references": p.get("references") or [], "item": s.get("item"),
                               "statement": s.get("statement")})
    return claims


def years_read(table):
    return sorted(table)


def unread_elections(sources_read, catalog):
    """The SERVEL elections in the catalog not read yet, as years."""
    return sorted(row["years_from"] for s, row in of_fact(catalog, FACT).items()
                  if row["kind"] == "official" and s not in sources_read)


# ----- Extractor -----------------------------------------------------------------------------------------------

READ_PROMPT = """FactSync Chile - Extractor.
Below is the mayor field of a Wikipedia infobox about a Chilean comuna, as wikitext. Give the name of the person it
names as mayor, exactly as written (null if it names no one), and any text it adds about them (a party, "suplente").
Never correct or complete a name. If a critic_instruction is given, follow it.
JSON: {"name": "...", "notes": ["..."]}"""


class MayorExtractor(Extractor):
    """Reads the mayor field of each article read this run into a claim."""

    def extract(self, comuna, observed, *, round_no=0, instruction=None):
        mine = [o for o in self.world.view("observations").for_entity(comuna.entity_id, kinds={"wikipedia"})
                if o["id"] in observed]
        kept = 0
        for article in [o for o in mine if o["payload"].get("document") == "article"]:
            field = next((o for o in mine if o["source"] == article["source"] and o["payload"].get("property") == "mayor"
                          and o["payload"].get("extracted_by") == "zetaris"), None)
            if field is None:
                continue
            observation, summary = self._read_mayor(comuna, article, field, round_no, instruction)
            result = self.world.ingest([observation], actor=self.name)
            observed.update(result.appended + result.unchanged)
            kept += 1
            self.tracer.event(self.name, "extract_claims", input_summary=f"{article['source']['name']} "
                              f"'{article['source']['title']}' rev {article['source'].get('revid')}: mayor field",
                              output_summary=summary, target_agent="WorldModel", round_no=round_no,
                              engine="world_model")
        return kept

    def _read_mayor(self, comuna, article, field, round_no, instruction):
        source, wikitext = article["source"], article["payload"].get("wikitext") or ""
        language = source["language"]
        params = infobox_parameters(wikitext)
        raw, name_field = field["payload"].get("name_raw"), NAME_FIELDS[language][0]
        if not raw:  # the usual field is empty or missing: another one some articles use
            name_field, raw = next(((f, params[f]) for f in NAME_FIELDS[language] if params.get(f)), (name_field, None))
        office = field["payload"].get("office_raw") or next((params[f] for f in OFFICE_FIELDS[language]
                                                             if params.get(f)), None)
        parsed = names.parse_field(raw)
        note = {"method": "rules"}
        if raw and not parsed["name"] and names.visible(raw).strip() and self.llm:
            reply = self.llm.ask_json(self.name, "read_mayor_field", READ_PROMPT,
                                      {"comuna": comuna.name, "article": source["title"], "field": raw[:600],
                                       **({"critic_instruction": instruction[:300]} if instruction else {})},
                                      target_agent="WorldModel", round_no=round_no,
                                      validate=lambda d: None if "name" in d else "no 'name'")
            written = str(reply[0].get("name") or "").strip() if reply else ""
            if written and set(names.tokens(written)) <= set(names.tokens(raw)):  # the name must be in the field
                parsed = {**parsed, "name": written, "notes": [str(n) for n in reply[0].get("notes") or []][:3]}
                note = model_note(reply[1])
        party = names.visible(field["payload"].get("party_raw") or "").strip() or None
        references = " ".join(REFS.findall(raw or ""))
        entity = {"type": "comuna", "name": comuna.name, "external_key": {"system": "cut", "id": comuna.cut}}
        observation = {"entity": entity, "source": source,
                       "provenance": {"agent": self.name, "run_id": self.run_id, "article_observation": article["id"],
                                      "observed_at": article["provenance"].get("observed_at"), **note},
                       "property": "mayor", "location": "infobox", "extracted_by": self.name, "method": note["method"],
                       "field": name_field, "name_raw": raw, "name": parsed["name"], "notes": parsed["notes"],
                       "linked": parsed["linked"], "others": parsed["others"],
                       "office": " ".join(names.visible(office or "").split()) or None, "party": party,
                       "reference_raw": references or None, "cues": mayors.cue_years(f"{raw or ''} {office or ''}"),
                       "missing": not parsed["name"], "verified": True}
        shown = f"names {parsed['name']!r}" if parsed["name"] else "names no mayor"
        extras = (f"; notes {parsed['notes']}" if parsed["notes"] else "") + \
            (f"; links to '{parsed['linked']}'" if parsed["linked"] else "")
        return observation, f"{name_field}: {shown}{extras} ({note['method']})"


# ----- Analyst -------------------------------------------------------------------------------------------------

ANALYST_PROMPT = """FactSync Chile - Analyst.
Each claim below is a name that Wikipedia or Wikidata gives as the mayor of a Chilean comuna, which code couldn't
match with certainty to a person in SERVEL's election results. SERVEL writes names in capitals without accents, and
in 2024 gives only the first given name. For each claim decide:
- same_person_as: the person_id of the candidate the name refers to, allowing nicknames (Max for Maximiliano), given
  names or a second surname left out or added, and misspellings; null if it refers to none of them
- reading: when null, what the name most likely is: "stand_in" (an acting or substitute mayor, or a replacement
  chosen after the election), "misspelling", "vandalism", "former_mayor" (mayor before the elections read) or
  "unclear"
- explanation: one or two sentences, using only the names, years, notes and signals given
- confidence: 0 to 1
SERVEL records who was elected, not who holds the office today: never claim who is mayor now. Follow any
critic_instruction.
JSON: {"verdicts": [{"claim_id": "...", "same_person_as": null, "reading": "...", "explanation": "...", "confidence": 0.6}]}"""
READINGS = {"stand_in", "misspelling", "vandalism", "former_mayor", "unclear"}


class MayorAnalyst(Analyst):
    """Explains why each page names the mayor it names."""

    def __init__(self, world, tracer, llm, run_id, catalog=None, today=None):
        super().__init__(world, tracer, llm, run_id)
        self.catalog = catalog or {}
        self.today = today or date.today()

    def analyze(self, comuna, observed, round_no, sources_read):
        context = self.context(comuna, observed)
        self.tracer.event("WorldModel", "build_context", input_summary=f"{comuna.entity_id} ({comuna.name}), round "
                          f"{round_no}", output_summary=context["trace"]["selection_reason"]
                          + (" (truncated)" if context["trace"]["truncated"] else ""), target_agent=self.name,
                          round_no=round_no, engine="world_model")
        table = mayors.election_table(context["observations"])
        if not table or not mayors.winner(table):
            raise LookupError(f"no SERVEL election results for {comuna.name} in the World Model")
        claims = build_claims(context["observations"])
        unread = unread_elections(sources_read, self.catalog)
        statements = [c for c in claims if c["target"] == "wikidata" and not c.get("missing")]
        flagged, signals = mayors.assess_wikidata(statements, table, comuna.name, self.today)
        changed = mayors.office_changed(signals, names.title_case(comuna.name))
        findings, checks = [], []
        for claim in claims:
            if claim["target"] == "wikidata" and not claim.get("missing"):
                continue  # statements: below
            verdict = mayors.assess(claim, table, comuna.name, unread)
            if changed and verdict["class"] != "consistent" and claim["target"] != "wikidata":
                verdict = {**verdict, "explanation": f"{verdict['explanation']} {changed}", "signals": signals,
                           "proposal": {**verdict["proposal"], "check_first": True}}
            if verdict["class"] == "consistent" and not verdict["ambiguous"]:
                checks.append({"claim": compact(claim), "result": "consistent", "note": verdict["explanation"]})
            else:  # an uncertain match with the winner too: the model confirms it below
                findings.append(self.mayor_finding(comuna, claim, verdict, round_no))
        flagged_ids = {s["id"] for s, _ in flagged}
        for statement, verdict in flagged:
            findings.append(self.mayor_finding(comuna, statement, verdict, round_no,
                                               aspect="qualifier" if verdict["class"] == "wikidata_qualifier" else "value"))
        for statement in statements:
            if statement["id"] not in flagged_ids:
                verdict = mayors.assess(statement, table, comuna.name, unread)
                checks.append({"claim": compact(statement), "result": verdict["class"] if verdict["class"] == "consistent"
                               else "former term", "note": verdict["explanation"]})
        fixes = self.open_fixes(comuna, round_no)
        asked = self.decide(comuna, findings, table, round_no, fixes, unread, signals)
        for finding in [f for f in findings if f["class"] == "consistent"]:  # confirmed: the page names the winner
            findings.remove(finding)
            checks.append({"claim": finding["claim"], "result": "consistent", "note": finding["explanation"],
                           "method": finding["method"], **({"model": finding["model"]} if finding.get("model") else {})})
        for finding in findings:
            self.world.assess(finding["claim"]["id"], agent=self.name, run_id=self.run_id, round_no=round_no,
                              data={**finding, "status": "proposed"})
        for check in checks:
            self.world.assess(check["claim"]["id"], agent=self.name, run_id=self.run_id, round_no=round_no,
                              data={"fact": FACT, "check": check["result"], "note": check["note"],
                                    "claim": check["claim"], "status": "checked"})
        by_class = {}
        for finding in findings:
            by_class[finding["class"]] = by_class.get(finding["class"], 0) + 1
        top = mayors.winner(table)
        self.tracer.event(self.name, "assess_claims", input_summary=f"{comuna.name}: {len(claims)} mayor claims; "
                          f"SERVEL elections read {years_read(table)}, latest winner {top['name']}",
                          output_summary=f"{len(findings)} findings {by_class}; {len(checks)} consistent or former "
                                         f"terms; {asked} sent to the model"
                                         + (f"; applied {len(fixes)} Critic fix(es)" if fixes else "")
                                         + (f"; signal: {changed}" if changed else ""),
                          target_agent="Critic", round_no=round_no, status="success")
        return findings, checks

    def mayor_finding(self, comuna, claim, verdict, round_no, aspect="value"):
        return {"id": "fnd_" + digest(claim["id"], aspect), "fact": FACT, "cut": comuna.cut, "target": claim["target"],
                "aspect": aspect, "claim": compact(claim), "class": verdict["class"],
                "explanation": verdict["explanation"], "confidence": verdict["confidence"],
                "evidence": verdict["evidence"], "proposal": verdict.get("proposal"), "match": verdict.get("person"),
                "matches": verdict.get("matches") or [], "level": verdict.get("level"), "related": None,
                "ambiguous": verdict["ambiguous"], "unexplained": verdict["unexplained"],
                "candidates": verdict["candidates"], "signals": verdict.get("signals") or [], "method": "matcher",
                "digits": None, "round": round_no}

    def decide(self, comuna, findings, table, round_no, fixes, unread, signals):
        """Ask the model which candidate each uncertain name refers to (or what it is, if none), once nothing unread
        could explain it; code derives the class from the chosen person's record. Reuses earlier answers while the
        elections read and the Critic's instructions are unchanged. Returns how many findings went to the model."""
        loaded = ",".join(map(str, years_read(table)))
        todo = []
        for finding in findings:
            fix = fixes.get(finding["id"])
            final = finding["class"] in mayors.JUDGED and not finding["unexplained"]
            if not (finding["ambiguous"] or final or fix) or finding["aspect"] != "value":
                continue
            key = f"{finding['id']}|{loaded}"
            cached = comuna.llm_verdicts.get(key)
            if cached and not fix:
                finding.update(cached)
                continue
            todo.append((finding, fix, key))
        if not todo:
            return 0
        top = mayors.winner(table)
        roster = mayors.people(table)

        def candidates_for(finding):
            listed = {m["id"]: m for m in finding["matches"]}
            for entry in roster.values():  # the winners of every election read, and the latest election's candidates
                ref = mayors.person_ref(entry)
                if ref["id"] not in listed and (entry["won"] or mayors.latest_year(table) in entry["ran"]):
                    listed[ref["id"]] = {**ref, "level": "none"}
            return [{"person_id": c["id"], "name": c["name"], "ran": c["ran"], "won": c["won"],
                     **({"code_fit": c["why"]} if c.get("why") else {})} for c in list(listed.values())[:10]]

        def payload(group):
            return {"comuna": comuna.name, "elections_read": years_read(table), "latest_winner": top["name"],
                    "signals": [f"{s['source']}: the term of {s['person']} ended on {s['date']}" for s in signals],
                    "claims": [{"claim_id": f["id"], "page": f"{f['claim']['source_name']} {f['claim']['location']}",
                                "name_as_written": f["claim"].get("name"), "notes": f["claim"].get("notes") or [],
                                "linked_article": f["claim"].get("linked"), "matcher_note": f["explanation"][:300],
                                "candidates": candidates_for(f),
                                **({"critic_instruction": fix["instruction"][:300]} if fix else {})}
                               for f, fix, _ in group]}

        answers = {}
        for group in batched(todo, payload):
            reply = self.llm.ask_json(self.name, "match_names", ANALYST_PROMPT, payload(group), target_agent="Critic",
                                      round_no=round_no, validate=lambda d: None if isinstance(d.get("verdicts"), list)
                                      else "no 'verdicts' list") if self.llm else None
            verdicts = {str(v.get("claim_id")): v for v in reply[0]["verdicts"] if isinstance(v, dict)} if reply else {}
            for finding, _, _ in group:
                answers[finding["id"]] = (verdicts.get(finding["id"]), reply[1]) if reply else None
        for finding, fix, key in todo:
            answer, result = answers[finding["id"]] or (None, None)
            update = self.apply(finding, answer, result, table, comuna, fix, unread)
            finding.update(update)
            comuna.llm_verdicts[key] = update
        return len(todo)

    def apply(self, finding, answer, result, table, comuna, fix, unread):
        """A model answer, checked: the person must be a listed candidate; the class follows from their record."""
        if not answer:
            return {"method": "matcher (model unavailable)" if result is None else "matcher (model gave no usable verdict)"}
        try:
            confidence = round(min(max(float(answer.get("confidence")), 0.0), 0.8), 2)
        except (TypeError, ValueError):
            confidence = 0.5
        explanation = str(answer.get("explanation") or "").strip()[:600] or finding["explanation"]
        chosen = answer.get("same_person_as")
        claim = finding["claim"]
        if chosen:
            entry = mayors.person_by_id(table, str(chosen))
            if entry is None:
                return {"method": "matcher (model gave no usable verdict)"}
            cls = mayors.classify(entry, table)
            check_first = cls in mayors.JUDGED or mayors.stand_in(claim.get("notes")) or bool(finding["signals"])
            return {"class": cls, "explanation": explanation, "confidence": confidence, "method": "llm",
                    "model": model_note(result), "match": mayors.person_ref(entry),
                    "evidence": mayors.evidence_rows(table, entry), "reading": None,
                    "unexplained": bool(unread) and cls == "not_elected",
                    "proposal": mayors.proposal(table, claim, cls, check_first)}
        reading = answer.get("reading") if answer.get("reading") in READINGS else "unclear"
        return {"class": "unknown_name", "explanation": explanation, "confidence": min(confidence, 0.7),
                "method": "llm", "model": model_note(result), "match": None, "reading": reading,
                "evidence": mayors.evidence_rows(table), "unexplained": bool(unread),
                "proposal": mayors.proposal(table, claim, "unknown_name", True)}


# ----- Critic --------------------------------------------------------------------------------------------------

CRITIC_PROMPT = """FactSync Chile - Critic.
You review the Analyst's findings on who Wikipedia and Wikidata name as the mayor of a Chilean comuna, against
SERVEL's election results. The classes used:
{classes}
For each finding decide:
- class_fits: is this class the best account of the name, given the evidence? SERVEL records who was elected, not who
  holds the office today: a name SERVEL can't explain is unknown, not wrong.
- explanation_faithful: does the explanation state only what the evidence shows (names, years, votes, signals)?
"made_by" says whether code or a model produced the verdict. Judge both the same way.
JSON: {{"reviews": [{{"finding_id": "...", "class_fits": true, "explanation_faithful": true, "note": "one sentence; required when either is false"}}]}}"""
YEARS = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
DRAFT_CHECKS = ("person", "citation", "official_url", "access_date", "well_formed", "summary", "names_faithful",
                "caveat", "explanation")
CRITICAL = ("person", "official_url", "names_faithful")


class MayorCritic(Critic):
    """Scores the mayor findings on the same 9-point rubric, and reviews the drafts."""

    def __init__(self, world, tracer, llm, run_id, today=None):
        super().__init__(world, tracer, llm, run_id)
        self.today = today or date.today()

    def review(self, comuna, findings, observed, round_no, open_sources, checks=()):
        context = self.world.context(comuna.entity_id, intent="review", budget_chars=80_000,
                                     include=lambda o: o["id"] in observed and o["payload"].get("document") != "article")
        table = mayors.election_table(context["observations"])
        by_id = {c["id"]: c for c in build_claims(context["observations"])}
        fresh = [f for f in findings if (comuna.approved.get(f["id"]) or {}).get("signature") != signature(f)]
        judgments = self.judge_mayors(comuna, fresh, table, round_no)
        results = {}
        for finding in findings:
            memo = comuna.approved.get(finding["id"])
            if memo and memo["signature"] == signature(finding):
                results[finding["id"]] = memo["result"]
                continue
            result = self.score_mayor(finding, by_id.get(finding["claim"]["id"]), table, comuna, open_sources,
                                      judgments.get(finding["id"]))
            results[finding["id"]] = result
            if result["approved"]:
                comuna.approved[finding["id"]] = {"signature": signature(finding), "result": result}
            else:
                comuna.approved.pop(finding["id"], None)
        rejected = [f for f in findings if not results[f["id"]]["approved"]]
        fix = self.choose_mayor_fix(comuna, rejected, results, table) if rejected else None
        for finding in fresh:
            result = results[finding["id"]]
            self.world.assess(finding["claim"]["id"], agent=self.name, run_id=self.run_id, round_no=round_no, data={
                "fact": FACT, "finding_id": finding["id"], "class": finding["class"],
                "status": "approved" if result["approved"] else "rejected", **result,
                "fix": fix if fix and fix["finding_id"] == finding["id"] else None})
        review = {"round": round_no, "approved": not rejected, "results": results,
                  "rejected": [f["id"] for f in rejected], "unchecked": [], "fix": fix}
        comuna.reviews.append(review)
        scores = ", ".join(f"{f['class']} {results[f['id']]['score']}/9" for f in findings)
        if fix:
            self.tracer.event(self.name, "reject", input_summary=f"{comuna.name}: {len(findings)} findings ({scores})",
                              output_summary=f"{len(rejected)} below {APPROVE_AT}/9; fix for {fix['target_agent']}: "
                                             f"{fix['instruction']}", target_agent=fix["target_agent"],
                              round_no=round_no, status="rejected", confidence=None, fix=fix)
        else:
            self.tracer.event(self.name, "approve", input_summary=f"{comuna.name}: {len(findings)} findings ({scores})",
                              output_summary=f"all {len(findings)} findings scored {APPROVE_AT}/9 or more",
                              target_agent="Editor", round_no=round_no, status="approved")
        return review

    def judge_mayors(self, comuna, findings, table, round_no):
        findings = [f for f in findings if f["method"] == "llm" or f["class"] in mayors.JUDGED]
        if not findings or not self.llm:
            return {}
        elected = {year: mayors.winner(table, year)["name"] for year in table}

        def payload(group):
            return {"comuna": comuna.name, "elected_by_year": elected, "findings": [{
                "finding_id": f["id"], "class": f["class"], "explanation": f["explanation"],
                "made_by": "model" if f["method"] == "llm" else "code",
                "claim": {k: f["claim"].get(k) for k in ("source_name", "location", "name", "notes")
                          if f["claim"].get(k)},
                "servel_evidence": [{k: e.get(k) for k in ("year", "name", "elected", "votes")} for e in f["evidence"]],
                **({"signals": [f"{s['source']}: term of {s['person']} ended {s['date']}" for s in f["signals"]]}
                   if f.get("signals") else {})} for f in group]}

        judgments = {}
        for group in batched(findings, payload):
            classes = mayors.describe_classes(sorted({f["class"] for f in group}))
            reply = self.llm.ask_json(self.name, "review", CRITIC_PROMPT.format(classes=classes), payload(group),
                                      target_agent="Analyst", round_no=round_no,
                                      validate=lambda d: None if isinstance(d.get("reviews"), list) else "no 'reviews' list")
            if not reply:
                continue
            note = model_note(reply[1])
            judgments.update({str(r.get("finding_id")): {"class_fits": r.get("class_fits") is not False,
                                                         "explanation_faithful": r.get("explanation_faithful") is not False,
                                                         "note": str(r.get("note") or "")[:300], "model": note}
                              for r in reply[0]["reviews"] if isinstance(r, dict)})
        return judgments

    def score_mayor(self, finding, claim, table, comuna, open_sources, judgment):
        failures, notes = [], []
        store = self.world.store
        shown = mayors.shown(finding["claim"].get("name"))
        source = finding["claim"]["source_name"]

        # evidence fidelity
        fidelity = 0
        observation = store.get_observation(finding["claim"]["id"])
        if observation and observation["payload"].get("name") == finding["claim"].get("name"):
            fidelity += 1
        else:
            failures.append(self._failure("claim_fidelity", f"The claim {shown} ({source}) doesn't match its observation "
                                          f"in the World Model; re-read the field.", "Extractor"))
        wrong = [e for e in finding["evidence"] if not self.servel_holds(e)]
        if not wrong:
            fidelity += 1
        else:
            failures.append(self._failure("official_evidence", "Cite only SERVEL rows held in the World Model: "
                                          + ", ".join(f"{e.get('year')} {e.get('name')}" for e in wrong)
                                          + " doesn't match.", "Analyst"))
        allowed_years = {int(y) for y in mayors.facts()["elections"]} | {e["year"] for e in finding["evidence"]} | \
            {int(s["date"][:4]) for s in finding.get("signals") or []} | set(finding["claim"].get("cues") or [])
        allowed_years |= {int(t[:4]) for e in mayors.facts()["elections"].values() for t in (e["term_from"], e["term_to"])}
        stray = sorted({int(y) for y in YEARS.findall(finding["explanation"])} - allowed_years)
        faithful = (judgment or {}).get("explanation_faithful", True)
        if not stray and faithful:
            fidelity += 1
        else:
            detail = (f"The explanation states {', '.join(map(str, stray))}, which the evidence doesn't hold." if stray
                      else f"The explanation goes beyond the evidence: {judgment.get('note')}")
            failures.append(self._failure("explanation", detail + " Explain using only the evidence.", "Analyst"))

        # definition discipline
        discipline = 0
        unread = sorted(row["years_from"] for row in (open_sources or {}).values())
        facts = mayors.assess(claim, table, comuna.name, unread) if claim and finding["aspect"] == "value" else None
        allowed = set(facts["candidates"]) if facts else {finding["class"]}
        if finding["method"] == "llm" and finding.get("match"):
            allowed.add(finding["class"])  # the model chose a listed person; the class is that person's record
        if finding["class"] in allowed:
            discipline += 1
        else:
            failures.append(self._failure("class_allowed", f"{shown} ({source}) can't be {finding['class']}: "
                                          f"{facts['explanation']} Classes the facts allow: {', '.join(sorted(allowed))}.",
                                          "Analyst", suggested_class=facts["class"]))
        fits = (judgment or {}).get("class_fits", True)
        if fits:
            discipline += 1
        else:
            notes.append(f"class doubted on review: {judgment.get('note')}")
        uncertain = finding["ambiguous"] or finding["class"] in mayors.JUDGED
        calibrated = finding["confidence"] <= 0.8 if uncertain else (finding["method"] != "matcher"
                                                                   or finding["confidence"] >= 0.8)
        if calibrated:
            discipline += 1
        else:
            failures.append(self._failure("confidence", f"Confidence {finding['confidence']} doesn't fit "
                                          + ("an uncertain match." if uncertain else "an exact match."), "Analyst"))
        if finding["class"] not in allowed:
            discipline = 0
        if not fits and finding["method"] == "llm":
            discipline = 0
            failures.append(self._failure("class_fit", f"The class {finding['class']} doesn't hold up for {shown} "
                                          f"({source}): {judgment.get('note')}", "Analyst"))
        if facts and facts["unexplained"] and open_sources:
            discipline = 0
            held = "SERVEL " + mayors.terms(years_read(table))
            candidates = list(open_sources)
            names_ = ", ".join(f"{s} ({coverage(open_sources[s])})" for s in candidates)
            failures.append(self._failure("unread_official_source", f"{shown} ({source}) matches no one elected in the "
                                          f"elections read so far ({held}). Before calling it {finding['class']}, read "
                                          f"an election that could explain it ({names_}): only its results can show "
                                          f"whether this person was elected then.", "Planner", critical=True,
                                          held=held, candidates=candidates))

        # correction sourcing
        sourcing = 0
        proposal = finding.get("proposal") or {}
        needed = {"set_qualifiers"} if finding["class"] == "wikidata_qualifier" else \
            {"add_statement"} if finding["target"] == "wikidata" else {"update"}
        if proposal.get("action") in needed:
            sourcing += 1
        else:
            failures.append(self._failure("correction_needed", f"A {finding['class']} finding needs a correction of "
                                          f"kind {' or '.join(sorted(needed))}.", "Analyst"))
        top, year = mayors.winner(table), mayors.latest_year(table)
        held = store.get_observation(proposal.get("obs_id"))
        if held and held["payload"].get("elected") and held["payload"].get("year") == year \
                and held["payload"].get("name") == proposal.get("person") == top["name"]:
            sourcing += 1
        else:
            failures.append(self._failure("correction_person", f"The correction must name the mayor SERVEL lists as "
                                          f"elected in {year}: {top['name']}.", "Analyst"))
        if proposal.get("source_key") == f"servel_{year}":
            sourcing += 1
        else:
            failures.append(self._failure("correction_source", f"The correction must cite SERVEL's results of the "
                                          f"{year} election.", "Analyst"))
        total = fidelity + discipline + sourcing
        return {"score": total, "approved": total >= APPROVE_AT,
                "criteria": {"evidence_fidelity": fidelity, "definition_discipline": discipline,
                             "correction_sourcing": sourcing},
                "failures": failures, "notes": notes, "judged_by_model": judgment.get("model") if judgment else None}

    @staticmethod
    def _failure(check, detail, target_agent, **extra):
        return {"check": check, "detail": detail, "target_agent": target_agent, **extra}

    def servel_holds(self, evidence):
        observation = self.world.store.get_observation(evidence.get("obs_id"))
        if not observation or observation["source"].get("kind") != "official":
            return False
        p = observation["payload"]
        return p.get("name") == evidence.get("name") and p.get("year") == evidence.get("year") \
            and bool(p.get("elected")) == bool(evidence.get("elected"))

    def choose_mayor_fix(self, comuna, rejected, results, table):
        """ONE fix per comuna and round: discovery first (one election can explain names in several comunas), then
        re-extraction, then re-analysis; among those, the lowest-scoring finding."""
        waiting = [(f, x) for f in rejected for x in results[f["id"]]["failures"] if x["check"] == "unread_official_source"]
        if waiting:
            figures = [{**mayor_figure(f), "candidates": x["candidates"]} for f, x in waiting]
            fix = {"target_agent": "Planner", "check": "unread_official_source", "finding_id": waiting[0][0]["id"],
                   "finding_ids": [f["id"] for f, _ in waiting], "comuna": comuna.name, "cut": comuna.cut,
                   "figures": figures, "suggested_class": None}
            if len(waiting) == 1:
                fix["instruction"] = waiting[0][1]["detail"]
            else:
                candidates = sorted({s for x in figures for s in x["candidates"]})
                fix["instruction"] = (f"{len(waiting)} names match no one elected in the elections read so far "
                                      f"({waiting[0][1]['held']}): " + "; ".join(
                                          f"{mayors.shown(x['value'])} ({x['source']} {x['location']}, called "
                                          f"{x['class']})" for x in figures)
                                      + f". Before they are judged, read the elections that could explain them "
                                        f"({', '.join(candidates)}).")
            return fix
        options = [(AGENT_ORDER[x["target_agent"]], results[f["id"]]["score"], i, f, x)
                   for i, f in enumerate(rejected) for x in results[f["id"]]["failures"]]
        if not options:
            finding = rejected[0]
            return {"target_agent": "Analyst", "finding_id": finding["id"], "check": "score",
                    "instruction": f"Revisit the {finding['class']} finding: it scored {results[finding['id']]['score']}/9.",
                    "comuna": comuna.name, "cut": comuna.cut, "figures": [mayor_figure(finding)]}
        _, _, _, finding, chosen = min(options, key=lambda o: o[:3])
        return {"target_agent": chosen["target_agent"], "finding_id": finding["id"], "check": chosen["check"],
                "instruction": chosen["detail"], "suggested_class": chosen.get("suggested_class"),
                "comuna": comuna.name, "cut": comuna.cut, "figures": [mayor_figure(finding)]}

    # ----- drafts ---------------------------------------------------------------------------------------------

    def review_draft(self, comuna, key, draft, explanation, evidence, table, round_no):
        """Nine checks on a mayor draft; it passes with 7 or more, provided it names SERVEL's winner, cites SERVEL,
        and its wording names no one the evidence doesn't."""
        top, year = mayors.winner(table), mayors.latest_year(table)
        source = mayors.official_source(year)
        correction = draft.get("correction") or {}
        body = draft.get("wikitext") or draft.get("statement") or ""
        summary = draft.get("edit_summary") or ""
        notes = " ".join(draft.get("notes") or [])
        written = correction.get("name_as_written") or ""
        surname = top["person"]["first"]
        allowed = set(names.tokens(" ".join(e.get("name") or "" for e in evidence))) | set(names.tokens(written)) \
            | set(names.tokens(comuna.name)) | set(names.tokens(" ".join(f.get("name") or "" for f in draft.get("named") or [])))
        checks = {
            "person": correction.get("person") == top["name"] and names.compare(written, top["person"])["level"] == "same"
            and written in body,
            "citation": draft["target"] == "wikidata" or bool(re.search(r"\{\{\s*(cita web|cite web)", body, re.I)),
            "official_url": source["url"] in body,
            "access_date": bool(re.search(r"fechaacceso\s*=|access-date\s*=|retrieved", body, re.I)),
            "well_formed": body.count("{{") == body.count("}}") and body.count("<ref") == body.count("</ref>"),
            "summary": 0 < len(summary) <= 500 and all(w in names.tokens(summary) for w in surname),
            "names_faithful": not (capitalized(summary) | capitalized(explanation)) - allowed - KNOWN_WORDS,
            "caveat": "SERVEL" in notes and str(year) in notes,
            "explanation": bool(explanation) and all(w in names.tokens(explanation) for w in surname),
        }
        score = sum(checks.values())
        approved = score >= APPROVE_AT and all(checks[name] for name in CRITICAL)
        issues = [name for name, ok in checks.items() if not ok]
        stray = sorted((capitalized(summary) | capitalized(explanation)) - allowed - KNOWN_WORDS)
        instruction = None
        if not approved:
            instruction = "Fix: " + ", ".join(issues) + "." + (
                f" The edit summary or explanation names {', '.join(w.title() for w in stray)}, whom no evidence "
                f"names." if stray else "") + (
                f" The edit summary must name the mayor elected in {year}, {names.title_case(top['name'])}, and cite "
                f"SERVEL." if not checks["summary"] else "")
        self.tracer.event(self.name, "review_draft", input_summary=f"{comuna.name} {key} mayor draft",
                          output_summary=f"{comuna.name} {key} draft: {score}/9"
                                         + (f"; failed: {', '.join(issues)}" if issues else ""),
                          target_agent="Editor" if not approved else None, round_no=round_no,
                          status="approved" if approved else "rejected")
        return {"draft": key, "round": round_no, "score": score, "approved": approved, "checks": checks,
                "instruction": instruction}


# Capitalized words a mayor draft's wording may use without naming a person.
KNOWN_WORDS = set(names.tokens(
    "Partido Party Vamos Nacional Renovación Renewal Demócrata Democrata Cristiano Christian Socialista Socialist "
    "Democratic Democracy Union Unión Republicano Comunista Communist Frente Amplio Radical Evolución Política Contigo "
    "Mejor Apruebo Dignidad Unidad Independientes Independents Coalition Pact Pacto Lista List " +
    "SERVEL Servicio Electoral Chile Chilean Wikipedia Wikidata English Spanish Inglés Español Alcalde Alcaldesa Mayor "
    "Infobox Ficha January February March April May June July August September October November December Enero Febrero "
    "Marzo Abril Mayo Junio Julio Agosto Septiembre Octubre Noviembre Diciembre The This These That Their They It Its "
    "In On At As An If When Both Each Neither Nor Before After Since Check SERVEL's Elección Elecciones Municipales "
    "Municipal Election Elections Results Resultados Según Per Was Antes Independent Independiente Ind RN UDI PS PPD "
    "PDC PC PR FA REP PSC FRVS PL PDG Evópoli Republican Demócratas QuickStatements P6 P580 P582 Head Government "
    "No None Name Names Note Draft Drafts Comuna Commune Region Región"))


def capitalized(text):
    """Capitalized words in a text that don't start a sentence: candidates for people's names."""
    found = set()
    for sentence in re.split(r"(?<=[.!?:;])\s+|\n", str(text or "")):
        words = re.findall(r"[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+(?:'s)?", sentence)
        for word in words[1:] if sentence[:1].isupper() else words:
            found |= set(names.tokens(word.removesuffix("'s")))
    return found


def mayor_figure(finding):
    """A name for a fix: what it is, where it is shown, and the year its page points to (the Planner's cue)."""
    claim = finding["claim"]
    cues = claim.get("cues") or []
    return {"finding_id": finding["id"], "value": claim.get("name"), "source": claim["source_name"],
            "location": claim.get("location"), "label": f"named as mayor ({claim.get('office') or 'infobox'})",
            "year": max(cues) if cues else None, "basis": None, "size": None, "class": finding["class"]}


# ----- Editor --------------------------------------------------------------------------------------------------

EDITOR_PROMPT = """FactSync Chile - Editor.
You write the wording for draft corrections of the mayor named on a Chilean comuna's Wikipedia pages and Wikidata
item. A human editor will review the drafts; nothing is published automatically. Write:
- name: the elected mayor's name exactly as SERVEL gives it (capitals, no accents), with Spanish capitalization and
  accents restored (e.g. "ENRIQUE DEL BARRIO HERNANDEZ" -> "Enrique del Barrio Hernández"); change no letter, add or
  drop no name
- es_summary: a Spanish Wikipedia edit summary (at most 250 characters), if there is an eswiki draft
- en_summary: an English Wikipedia edit summary (at most 250 characters), if there is an enwiki draft
- explanation: 2 to 4 plain English sentences for the reviewer: what each page says, what SERVEL's results show, and
  what the drafts change
Each summary must name the elected mayor and say it comes from SERVEL. SERVEL records who was elected, not who holds
the office today: never claim who is mayor now. Use only the names and years given. Follow any critic_instruction.
JSON: {"name": "...", "es_summary": "...", "en_summary": "...", "explanation": "..."}"""


class MayorEditor(Editor):
    """Drafts the mayor corrections: infobox lines with a SERVEL citation, and a Wikidata statement to add by hand."""

    def draft(self, comuna, findings, table, round_no, instruction=None):
        top, year = mayors.winner(table), mayors.latest_year(table)
        source = mayors.official_source(year)
        spelled, spelled_from = self.spelling(comuna, findings, top)
        drafts = {}
        for language, target in (("es", "eswiki"), ("en", "enwiki")):
            mine = [f for f in findings if f["target"] == language]
            if mine:
                drafts[target] = {"target": target, "page": mine[0]["claim"].get("title"),
                                  "revid": mine[0]["claim"].get("revid"), "findings": [f["id"] for f in mine],
                                  "anchor": mine[0]["claim"]["id"], "named": [f["claim"] for f in findings],
                                  "replaces": {"name": mine[0]["claim"].get("name_raw"),
                                               "office": mine[0]["claim"].get("office")}}
                drafts[target]["url"] = f"https://{language}.wikipedia.org/wiki/" + \
                    str(drafts[target]["page"] or "").replace(" ", "_")
        mine = [f for f in findings if f["target"] == "wikidata"]
        if mine:
            item = next((f["claim"].get("item") for f in mine if f["claim"].get("item")), None)
            qid = str(item or "").rstrip("/").rsplit("/", 1)[-1]
            drafts["wikidata"] = {"target": "wikidata", "page": qid, "url": f"https://www.wikidata.org/wiki/{qid}",
                                  "findings": [f["id"] for f in mine], "anchor": mine[0]["claim"]["id"],
                                  "named": [f["claim"] for f in findings]}  # the explanation covers every page
        if not drafts:
            return {}
        reply = self.word_mayor(comuna, drafts, findings, top, year, spelled_from, round_no, instruction)
        if spelled_from == "servel" and reply and names.same_letters(str(reply[0].get("name") or ""), top["name"]):
            spelled, spelled_from = str(reply[0]["name"]).strip(), "model"
        party = (mayors.facts()["parties"].get(names.fold(top["party"])) or {}) if top.get("party") else {}
        correction = {"person": top["name"], "name_as_written": spelled, "spelled_from": spelled_from, "year": year,
                      "party": top.get("party"), "source_key": f"servel_{year}", "url": source["url"],
                      "obs_id": top["obs_id"]}
        term = mayors.election(year)
        caveat = CAVEAT.format(days=term["days"], term_from=term["term_from"])
        for target, draft in drafts.items():
            draft["correction"] = correction
            lead = min((f for f in findings if f["id"] in draft["findings"]), key=lambda f: f["aspect"] != "value")
            notes = []
            if (lead.get("proposal") or {}).get("check_first"):
                notes.append(f"Check first: {lead['explanation']}")
            notes.append(caveat)
            if spelled_from == "servel":
                notes.append("SERVEL writes names in capitals without accents: check the spelling of the name.")
            if target == "wikidata":
                draft["statement"] = self.wikidata_statement(draft, findings, spelled, year, term, source)
                notes.append("QuickStatements needs the person's own Wikidata item, so no command is drafted: find "
                             "the item (or create one), then add the statement by hand.")
            else:
                draft["wikitext"] = self.infobox_lines(target, lead, spelled, party, source, year)
            draft["notes"] = notes
        self.summaries(drafts, reply, findings, spelled, year)
        if reply:
            drafts["explanation"] = str(reply[0]["explanation"])[:1500]
        else:
            leads = [min((f for f in findings if f["id"] in d["findings"]), key=lambda f: f["aspect"] != "value")
                     for k, d in drafts.items() if k in ("eswiki", "enwiki", "wikidata")]
            sentences = [s for f in leads for s in re.split(r"(?<=\.)\s+", f["explanation"].strip()) if s]
            drafts["explanation"] = " ".join(dict.fromkeys(sentences)) + \
                f" The drafts name {spelled}, elected in {year} (SERVEL)."
        drafts["explanation_by"] = model_note(reply[1]) if reply else {"method": "rules"}
        for name in [k for k in drafts if k in ("eswiki", "enwiki", "wikidata")]:
            self.world.assess(drafts[name]["anchor"], agent=self.name, run_id=self.run_id, round_no=round_no,
                              data={"fact": FACT, "status": "drafted", "draft": name,
                                    **{k: v for k, v in drafts[name].items() if k != "named"}})
        self.tracer.event(self.name, "draft_corrections", input_summary=f"{comuna.name}: {len(findings)} approved "
                          f"mayor findings", output_summary=", ".join(f"{k} ({len(drafts[k]['findings'])} findings)"
                                                                      for k in drafts if k in ("eswiki", "enwiki", "wikidata"))
                          + f"; name spelled from {spelled_from}; wording: {drafts['explanation_by']['method']}",
                          target_agent="Critic", round_no=round_no)
        return drafts

    def spelling(self, comuna, findings, top):
        """How to write the winner's name: as a page of this comuna already writes the same person (its linked
        article's title first, which is usually the fullest form), else from SERVEL's capitals (the model may then
        restore the accents)."""
        written, second = [], top["person"]["second"]
        for check in [c for c in comuna.checks if c["result"] == "consistent"]:
            claim = check["claim"]
            for name in (claim.get("linked"), claim.get("name")):
                if name and names.compare(name, top["person"])["level"] == "same" and \
                        (not second or names.tokens(name)[-len(second):] == second):
                    written.append(name)
        if written:
            return max(written, key=len), "page"
        return names.title_case(top["name"]), "servel"

    def word_mayor(self, comuna, drafts, findings, top, year, spelled_from, round_no, instruction):
        if not self.llm:
            return None
        body = {"comuna": comuna.name, "elected": {"name": top["name"], "year": year, "party": top.get("party"),
                                                   "votes": top.get("votes"), "source": "SERVEL"},
                "name_needs_accents": spelled_from == "servel",
                "drafts": {k: {"page_names": next((c.get("name") for c in d["named"] if c["target"] == PAGE_OF[k]), None),
                               "findings": [{"class": f["class"], "explanation": f["explanation"][:300]}
                                            for f in findings if f["id"] in d["findings"]]}
                           for k, d in drafts.items()}}
        if instruction:
            body["critic_instruction"] = instruction[:300]
        return self.llm.ask_json(self.name, "word_drafts", EDITOR_PROMPT, body, target_agent="Critic",
                                 round_no=round_no, validate=lambda d: None if d.get("explanation") else "no explanation")

    def infobox_lines(self, target, lead, spelled, party, source, year):
        office = (lead["claim"].get("office") or "").strip()
        if target == "eswiki":
            title = f"[[{office}]]" if office in ("Alcalde", "Alcaldesa") else "[[Alcalde]]"
            label = f" ({party['es']})" if party.get("es") else ""
            return "\n".join([
                f"| dirigentes_títulos = {title}",
                f"| dirigentes_nombres = {spelled}{label}<ref name=\"servel{year}\">{{{{cita web |url={source['url']} "
                f"|título={source['title']} |editorial={source['publisher']} |fechaacceso={es_date(self.today)}}}}}</ref>"])
        lines = [f"| leader_title = [[Alcalde]]",
                 f"| leader_name = {spelled}<ref name=\"SERVEL{year}\">{{{{cite web |url={source['url']} "
                 f"|title={source['title']} |publisher={source['publisher']} |language=es "
                 f"|access-date={en_date(self.today)}}}}}</ref>"]
        if party.get("en"):
            lines.append(f"| leader_party = {party['en']}")
        return "\n".join(lines)

    def wikidata_statement(self, draft, findings, spelled, year, term, source):
        ids = mayors.facts()["wikidata"]
        lines = [f"{draft['page']}: add {ids['head_of_government']} (head of government) = {spelled} (the person's "
                 f"item), with {ids['start_time']} (start time) = {term['term_from']}, and a reference: "
                 f"{ids['reference_url']} (reference URL) = {source['url']}, {ids['retrieved']} (retrieved) = "
                 f"{self.today.isoformat()}."]
        for finding in [f for f in findings if f["id"] in draft["findings"]]:
            claim = finding["claim"]
            if finding["class"] == "wikidata_qualifier":
                lines.append(f"Fix the existing statement for {claim.get('name')}: {finding['explanation']}")
            elif claim.get("location") == "statement":
                lines.append(f"The statement for {claim.get('name')} has no end time: add {ids['end_time']} (end time) "
                             f"= the end of their term, and keep it at normal rank.")
        return "\n".join(lines)

    def summaries(self, drafts, reply, findings, spelled, year):
        for target in ("eswiki", "enwiki"):
            if target not in drafts:
                continue
            old = next((c.get("name") for c in drafts[target]["named"] if c["target"] == target[:2]), None)
            if reply and reply[0].get(f"{target[:2]}_summary"):
                drafts[target]["edit_summary"] = str(reply[0][f"{target[:2]}_summary"])[:500]
            elif target == "eswiki":
                drafts[target]["edit_summary"] = f"Alcalde según SERVEL (elección de alcaldes {year}): {spelled}" + \
                    (f" (antes: {old})." if old else ".")
            else:
                drafts[target]["edit_summary"] = f"Mayor per SERVEL's {year} mayoral election results: {spelled}" + \
                    (f" (was {old})." if old else ".")
        if "wikidata" in drafts:
            drafts["wikidata"]["edit_summary"] = f"Head of government per SERVEL's {year} election results: {spelled}"
