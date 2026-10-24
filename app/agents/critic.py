"""Critic: scores every finding on a 9-point rubric and approves it at 7 or more. When a comuna has findings below
7, it sends ONE specific fix back to the agent responsible (Planner, Extractor or Analyst). It also reviews drafts.

The rubric, 3 points per criterion:
  evidence fidelity      the claim is what its source says; every official figure cited is the one in the World
                         Model; the explanation states no figure the evidence doesn't hold
  definition discipline  the class is one the facts allow; it holds up on review; the confidence fits what is known.
                         A figure that matches no official figure read so far scores 0 here while an official source
                         whose coverage could explain it is unread: only that source's figures can confirm or rule
                         out an official figure of another definition or year
  correction sourcing    a correction is proposed when one is needed; its figure is an official one in the World
                         Model; its source is INE's publication of that figure

The facts are recomputed from the World Model, not taken from the Analyst. The model's judgment (does the class fit,
is the explanation faithful) can overturn a verdict the model made, but costs a verdict made by code only one point.

The Critic also checks the Analyst's work for completeness: a claim left unchecked because it names a year no official
figure read covers (a figure from the 2002 census, before its counts are read) holds up approval while an unread
source in the catalog covers that year. Either way, the fix asks the Planner to read a source, and lists for each
figure the sources whose coverage could explain or check it.
"""
import re
from itertools import combinations

from app.agents.analyst import build_claims, claims_first
from app.agents.llm import batched, model_note
from app.knowledge import matcher
from app.knowledge.catalog import could_explain, coverage
from app.knowledge.taxonomy import census_facts, describe_classes, official_source

APPROVE_AT = 7
SPACES = re.compile(r"&nbsp;|&#160;|&thinsp;|[\u00a0\u202f\u2009]")  # non-breaking and thin spaces
FIGURES = re.compile(r"\d{1,3}(?:[., ]\d{3})+|\d{3,}")
AGENT_ORDER = {"Planner": 0, "Extractor": 1, "Analyst": 2}
ACTIONS = {"consistency": {"update"}, "sourcing": {"add_citation"}, "currency": {"add_statement"},
           "rank": {"set_rank_qualifiers"}}
HISTORICAL_ACTIONS = {"relabel", "fix_figure", "deprecate", "human_review"}
CRITICAL_DRAFT_CHECKS = ("figure", "official_url", "figures_faithful")
# Classes whose verdicts need judgment; the others (missing value, unsourced, outdated, Wikidata rank) are mechanical.
JUDGED = {"different_definition", "mislabelled_vintage", "discredited_source", "nonexistent_census", "genuine_error",
          "cross_source_mismatch", "internal_inconsistency"}

PROMPT = """FactSync Chile - Critic.
You review the Analyst's findings on population figures for a Chilean comuna. The classes used:
{classes}
For each finding decide:
- class_fits: is this class the best account of why the figure differs, given the evidence? Be strict about
  definitions: an INE projection or estimate is not a census count, and a difference of definition is not an error.
  A figure that matches no official figure shown is not a projection or estimate unless the evidence shows one equal to it.
- explanation_faithful: does the explanation state only what the evidence shows (figures, years, sources)?
"made_by" says whether code or a model produced the verdict. Judge both the same way. "digit_check", when given, is a
fact computed by code: how the figure differs digit by digit from an official count. It is evidence for a typo.
JSON: {{"reviews": [{{"finding_id": "...", "class_fits": true, "explanation_faithful": true, "note": "one sentence; required when either is false"}}]}}"""


def figures_in(text):
    """The figures a text states, however it groups thousands: 25,795, 25.795, 25 795, or with a non-breaking
    space as Spanish Wikipedia writes them (25&nbsp;795)."""
    text = SPACES.sub(" ", str(text or ""))
    return {int(re.sub(r"\D", "", token)) for token in FIGURES.findall(text)}


def states(text, value):
    """Whether a text gives this figure: in any grouping, and also when it is under 100 (Antártica counted 60)."""
    if value in figures_in(text):
        return True
    spaced = SPACES.sub(" ", str(text or ""))
    return value < 100 and re.search(rf"(?<![\d.,]){value}(?!\d|[.,]\d)", spaced) is not None


def allowed_figures(evidence, extra=()):
    """Figures an explanation may state: those in the evidence (and the years a cited reference names), differences
    between them, and the years of Chile's censuses, which explanations name ('the 2017 Census' is no figure)."""
    facts = census_facts()
    numbers = set(extra) | set(facts["valid"]) | {int(year) for year in facts["discredited"]}
    for item in evidence:
        numbers |= {y for y in item.get("years") or [] if isinstance(y, int)}
        for key in ("value", "year", "value_raw", "label", "quote", "source"):
            value = item.get(key)
            numbers |= {value} if isinstance(value, int) else figures_in(value)
    values = [n for n in numbers if n >= 100]
    return numbers | {abs(a - b) for a, b in combinations(values, 2)}


def needs_source(facts):
    """Whether a verdict rests on figures not read yet: a figure matching nothing, one only possibly a typo, or one
    attributed to a census whose counts weren't read."""
    return bool(facts) and (facts["unexplained"] or bool(facts.get("near") and facts["ambiguous"])
                            or (facts["class"] == "outdated_vintage" and not facts.get("match")))


def signature(finding):
    proposal = finding.get("proposal") or {}
    return f"{finding['class']}|{finding['explanation']}|{finding['confidence']}|{proposal.get('action')}|{proposal.get('value')}"


def failure(check, detail, target_agent, **extra):
    return {"check": check, "detail": detail, "target_agent": target_agent, **extra}


class Critic:
    name = "Critic"

    def __init__(self, world, tracer, llm, run_id):
        self.world = world
        self.tracer = tracer
        self.llm = llm
        self.run_id = run_id

    # ----- findings -------------------------------------------------------------------------------------------

    def review(self, comuna, findings, observed, round_no, open_sources, checks=()):
        """Score the comuna's findings and check its unchecked claims. `open_sources` are the catalog rows of the
        official sources the run could still read, by source id."""
        context = self.world.context(comuna.entity_id, intent="review", budget_chars=80_000, rank=claims_first,
                                     include=lambda o: o["id"] in observed and o["payload"].get("document") != "article")
        table = matcher.official_table(context["observations"])
        claims, _ = build_claims(context["observations"])
        by_id = {c["id"]: c for c in claims}
        fresh = [f for f in findings if (comuna.approved.get(f["id"]) or {}).get("signature") != signature(f)]
        judgments = self.judge(comuna, fresh, table, round_no)
        results = {}
        for finding in findings:
            memo = comuna.approved.get(finding["id"])
            if memo and memo["signature"] == signature(finding):
                results[finding["id"]] = memo["result"]
                continue
            result = self.score(finding, by_id.get(finding["claim"]["id"]), table, claims, open_sources,
                                judgments.get(finding["id"]))
            results[finding["id"]] = result
            if result["approved"]:
                comuna.approved[finding["id"]] = {"signature": signature(finding), "result": result}
            else:
                comuna.approved.pop(finding["id"], None)
        rejected = [f for f in findings if not results[f["id"]]["approved"]]
        uncovered = self.uncovered(checks, table, open_sources)
        fix = self.choose_fix(comuna, rejected, results, table, uncovered) if rejected or uncovered else None
        for finding in fresh:
            result = results[finding["id"]]
            self.world.assess(finding["claim"]["id"], agent=self.name, run_id=self.run_id, round_no=round_no, data={
                "finding_id": finding["id"], "class": finding["class"], "status": "approved" if result["approved"] else "rejected",
                **result, "fix": fix if fix and fix["finding_id"] == finding["id"] else None})
        review = {"round": round_no, "approved": not (rejected or uncovered), "results": results,
                  "rejected": [f["id"] for f in rejected], "unchecked": [x["claim_id"] for x in uncovered], "fix": fix}
        comuna.reviews.append(review)
        scores = ", ".join(f"{f['class']} {results[f['id']]['score']}/9" for f in findings)
        if fix:
            held = f"{len(rejected)} below {APPROVE_AT}/9" + (f", {len(uncovered)} claim(s) unchecked" if uncovered else "")
            self.tracer.event(self.name, "reject", input_summary=f"{comuna.name}: {len(findings)} findings ({scores})",
                              output_summary=f"{held}; fix for {fix['target_agent']}: {fix['instruction']}",
                              target_agent=fix["target_agent"], round_no=round_no, status="rejected",
                              confidence=None, fix=fix)
        else:
            self.tracer.event(self.name, "approve", input_summary=f"{comuna.name}: {len(findings)} findings ({scores})",
                              output_summary=f"all {len(findings)} findings scored {APPROVE_AT}/9 or more",
                              target_agent="Editor", round_no=round_no, status="approved")
        return review

    def judge(self, comuna, findings, table, round_no):
        """The model's reading of each new or changed finding that is a judgment call (made by the model, or of a
        class that needs judgment): does the class fit, is the explanation faithful. Findings go in batches small
        enough for one streamed request each."""
        findings = [f for f in findings if f["method"] == "llm" or f["class"] in JUDGED]
        if not findings or not self.llm:
            return {}
        official = {d: {y: r["value"] for y, r in sorted(t.items()) if d == "census" or y in (2017, 2020, 2024)}
                    for d, t in table.items() if t}

        def payload(group):
            return {"comuna": comuna.name, "official_figures_read": official, "findings": [{
                "finding_id": f["id"], "class": f["class"], "explanation": f["explanation"],
                "made_by": "model" if f["method"] == "llm" else "code",
                "claim": {k: f["claim"].get(k) for k in ("source_name", "location", "value", "value_raw", "label", "quote")
                          if f["claim"].get(k) is not None},
                "official_evidence": [{k: e[k] for k in ("source", "definition", "year", "value")}
                                      for e in f["evidence"] if e["kind"] == "official"],
                **({"digit_check": digit_check(f)} if f.get("digits") else {})} for f in group]}

        judgments = {}
        for group in batched(findings, payload):
            classes = describe_classes(sorted({f["class"] for f in group}))
            reply = self.llm.ask_json(self.name, "review", PROMPT.format(classes=classes), payload(group),
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

    def score(self, finding, claim, table, claims, open_sources, judgment):
        failures, notes = [], []
        store = self.world.store
        value, source = finding["claim"].get("value"), finding["claim"]["source_name"]
        label = finding["claim"].get("label") or "no year"
        shown = f"{value:,}" if isinstance(value, int) else "no figure"

        # evidence fidelity
        fidelity = 0
        observation = store.get_observation(finding["claim"]["id"])
        # an infobox showing Wikidata's figure: the statement it shows must hold that figure too
        statement = store.get_observation((observation or {}).get("provenance", {}).get("wikidata_observation"))
        if observation and observation["payload"].get("value") == value and finding["claim"].get("verified") is not False \
                and (statement is None or statement["payload"].get("value") == value):
            fidelity += 1
        else:
            extracted = finding["claim"].get("method") in ("llm", "rules")
            failures.append(failure("claim_fidelity", f"The claim {shown} ({source}) doesn't match its observation in the "
                                    f"World Model; re-read it from the article.", "Extractor" if extracted else "Analyst"))
        wrong = [e for e in finding["evidence"] if e["kind"] == "official" and not self.official_holds(e)]
        if not wrong:
            fidelity += 1
        else:
            failures.append(failure("official_evidence", "Cite only official figures held in the World Model: "
                                    + ", ".join(f"{e.get('source')} {e.get('year')} {e.get('value')}" for e in wrong)
                                    + " doesn't match.", "Analyst"))
        proposal = finding.get("proposal") or {}
        stray = sorted(n for n in figures_in(finding["explanation"])
                       - allowed_figures(finding["evidence"], [proposal.get("value") or 0]) if n >= 100)
        faithful = (judgment or {}).get("explanation_faithful", True)
        if not stray and faithful:
            fidelity += 1
        else:
            detail = (f"The explanation states {', '.join(f'{n:,}' for n in stray)}, which the evidence doesn't hold."
                      if stray else f"The explanation goes beyond the evidence: {judgment.get('note')}")
            failures.append(failure("explanation", detail + " Explain using only the evidence.", "Analyst"))

        # definition discipline
        discipline = 0
        facts = matcher.assess_value(claim, table, claims) if finding["aspect"] == "value" and claim else None
        allowed = matcher.allowed_classes(claim, table, claims) if facts else {finding["class"]}
        if finding["class"] in allowed:
            discipline += 1
        else:
            suggestion = facts["class"] if not facts["unexplained"] else "cross_source_mismatch"
            failures.append(failure("class_allowed", f"{shown} ({source}, '{label}') can't be {finding['class']}: "
                                    f"{facts['explanation']} Classes the facts allow: {', '.join(sorted(allowed))}.",
                                    "Analyst", suggested_class=suggestion))
        fits = (judgment or {}).get("class_fits", True)
        if fits:
            discipline += 1
        else:
            notes.append(f"class doubted on review: {judgment.get('note')}")
        unexplained = bool(facts and facts["unexplained"])
        candidates = [s for s, row in (open_sources or {}).items() if could_explain(row, claim, table)] \
            if needs_source(facts) else []
        expected = min(0.8, facts["confidence"]) if facts else 0.8  # a rounded figure's match is held less firmly
        calibrated = finding["confidence"] <= 0.7 if unexplained else (finding["method"] != "matcher"
                                                                      or finding["confidence"] >= expected)
        if calibrated:
            discipline += 1
        else:
            failures.append(failure("confidence", f"Confidence {finding['confidence']} doesn't fit a figure "
                                    + ("no official figure explains." if unexplained else "an official figure explains."),
                                    "Analyst"))
        if finding["class"] not in allowed:  # a class the facts rule out is a definition failure, not a detail
            discipline = 0
        if not fits and finding["method"] == "llm":
            discipline = 0
            failures.append(failure("class_fit", f"The class {finding['class']} doesn't hold up for {shown} ({source}): "
                                    f"{judgment.get('note')}", "Analyst"))
        if candidates:
            discipline = 0
            held = matcher.held_figures(table)
            names = ", ".join(f"{s} ({coverage(open_sources[s])})" for s in candidates)
            failures.append(failure("unread_official_source", f"{shown} ({source}, '{label}') matches no official figure "
                                    f"read so far ({held}). Before calling it {finding['class']}, read an official source "
                                    f"whose coverage could explain it ({names}): only its figures can confirm or rule "
                                    f"out an official figure of another definition or year.", "Planner", critical=True,
                                    held=held, candidates=candidates))

        # correction sourcing
        sourcing = 0
        role = finding["claim"].get("role")
        needed = ACTIONS.get(finding["aspect"]) or ({"update"} if role == "current" else HISTORICAL_ACTIONS)
        if proposal.get("action") in needed:
            sourcing += 1
        else:
            failures.append(failure("correction_needed", f"A {finding['class']} finding on a {role or 'item'} figure "
                                    f"needs a correction of kind {' or '.join(sorted(needed))}.", "Analyst"))
        if self.proposal_value_holds(proposal, table):
            sourcing += 1
        else:
            latest = matcher.latest_census(table)
            failures.append(failure("correction_figure", f"The correction must be an official figure from the World "
                                    f"Model (for the current population, Census {latest['year']}: {latest['value']:,}).",
                                    "Analyst"))
        if self.proposal_source_holds(proposal):
            sourcing += 1
        else:
            failures.append(failure("correction_source", "The correction must cite INE's publication of that figure.",
                                    "Analyst"))
        total = fidelity + discipline + sourcing
        return {"score": total, "approved": total >= APPROVE_AT,
                "criteria": {"evidence_fidelity": fidelity, "definition_discipline": discipline,
                             "correction_sourcing": sourcing},
                "failures": failures, "notes": notes, "judged_by_model": judgment.get("model") if judgment else None}

    def official_holds(self, evidence):
        observation = self.world.store.get_observation(evidence.get("obs_id"))
        if not observation or observation["source"].get("kind") != "official":
            return False
        payload = observation["payload"]
        return payload.get("value") == evidence.get("value") and payload.get("stated_year") == evidence.get("year")

    def proposal_value_holds(self, proposal, table):
        if "value" not in proposal:
            return True
        observation = self.world.store.get_observation(proposal.get("obs_id"))
        if not observation or observation["source"].get("kind") != "official" \
                or observation["payload"].get("value") != proposal["value"]:
            return False
        if proposal.get("action") in ("update", "add_statement"):
            return proposal.get("year") == matcher.latest_census(table)["year"]
        return True

    @staticmethod
    def proposal_source_holds(proposal):
        key = proposal.get("source_key")
        if proposal.get("action") in ("human_review", "deprecate", None) and key is None:
            return proposal.get("action") is not None
        sources = census_facts()["official_sources"]
        if key not in sources:
            return False
        if "value" in proposal:
            expected = "projections_base2017" if proposal.get("definition") == "projection" else f"census_{proposal.get('year')}"
            return key == expected
        return True

    def uncovered(self, checks, table, open_sources):
        """Claims left unchecked because they name a year no official figure read covers, each with the unread
        sources whose coverage could check it."""
        found = []
        for check in checks or ():
            claim = check["claim"]
            if check["result"] != "not checkable" or not claim.get("stated_year") or claim.get("value") is None:
                continue
            candidates = [s for s, row in (open_sources or {}).items() if could_explain(row, claim, table)]
            if candidates:
                found.append({**figure(claim, table), "candidates": candidates})
        return found

    def choose_fix(self, comuna, rejected, results, table, uncovered=()):
        """ONE fix per comuna and round: discovery first (one source can settle several figures at once), then
        re-extraction, then re-analysis; among those, the lowest-scoring finding. A discovery request carries every
        figure waiting for a source and every claim left unchecked, each with its candidate sources."""
        waiting = [(f, x) for f in rejected for x in results[f["id"]]["failures"] if x["check"] == "unread_official_source"]
        if waiting or uncovered:
            figures = [{**figure(f["claim"], table, f), "candidates": x["candidates"]} for f, x in waiting] + list(uncovered)
            fix = {"target_agent": "Planner", "check": "unread_official_source" if waiting else "unchecked_claims",
                   "finding_id": waiting[0][0]["id"] if waiting else None, "finding_ids": [f["id"] for f, _ in waiting],
                   "comuna": comuna.name, "cut": comuna.cut, "figures": figures, "suggested_class": None}
            if len(waiting) == 1 and not uncovered:
                fix["instruction"] = waiting[0][1]["detail"]
                return fix
            parts = []
            if waiting:
                parts.append(f"{len(waiting)} figures match no official figure read so far ({waiting[0][1]['held']}): "
                             + "; ".join(f"{x['value']:,} ({x['source']}, '{x['label']}', called {x['class']})"
                                         for x in figures[:len(waiting)]))
            if uncovered:
                parts.append(f"{len(uncovered)} claim(s) can't be checked with the official figures read: "
                             + "; ".join(f"{x['value']:,} ({x['source']} {x['location']}, '{x['label']}')"
                                         for x in uncovered))
            candidates = sorted({s for x in figures for s in x["candidates"]})
            fix["instruction"] = (". ".join(parts) + f". Before they are judged, read the official sources whose "
                                  f"coverage could explain or check them ({', '.join(candidates)}).")
            return fix
        options = [(AGENT_ORDER[f_["target_agent"]], results[f["id"]]["score"], i, f, f_)
                   for i, f in enumerate(rejected) for f_ in results[f["id"]]["failures"]]
        if not options:
            finding = rejected[0]
            return {"target_agent": "Analyst", "finding_id": finding["id"], "check": "score",
                    "instruction": f"Revisit the {finding['class']} finding: it scored {results[finding['id']]['score']}/9.",
                    "comuna": comuna.name}
        _, _, _, finding, chosen = min(options, key=lambda o: o[:3])
        return {"target_agent": chosen["target_agent"], "finding_id": finding["id"], "check": chosen["check"],
                "instruction": chosen["detail"], "suggested_class": chosen.get("suggested_class"),
                "comuna": comuna.name, "cut": comuna.cut, "figures": [figure(finding["claim"], table, finding)]}

    # ----- drafts ---------------------------------------------------------------------------------------------

    def review_draft(self, comuna, key, draft, explanation, evidence, table, round_no):
        """Nine checks on a draft; it passes with 7 or more, provided the figure and the source are right and the
        wording states no figure the approved findings don't hold."""
        latest = matcher.latest_census(table)
        correction = draft.get("correction") or {}
        source = official_source(correction.get("source_key")) if correction.get("source_key") in \
            census_facts()["official_sources"] else {}
        body = draft.get("wikitext") or draft.get("quickstatements") or ""
        summary = draft.get("edit_summary") or ""
        allowed = allowed_figures(evidence, [latest["value"], latest["year"]]) | figures_in(body)
        checks = {
            "figure": correction.get("value") == latest["value"] and states(body, latest["value"]),
            "year": str(latest["year"]) in body,
            "citation": bool(re.search(r"\{\{\s*(cita web|cite web)|S854", body, re.I)),
            "official_url": bool(source) and source["url"] in body,
            "access_date": bool(re.search(r"fechaacceso\s*=|access-date\s*=|S813", body)),
            "well_formed": well_formed(body, draft["target"]),
            "summary": draft["target"] == "wikidata" or (0 < len(summary) <= 500 and states(summary, latest["value"])),
            "figures_faithful": not {n for n in figures_in(summary) | figures_in(explanation) if n >= 100} - allowed,
            "explanation": bool(explanation) and states(explanation, latest["value"]),
        }
        score = sum(checks.values())
        approved = score >= APPROVE_AT and all(checks[name] for name in CRITICAL_DRAFT_CHECKS)
        issues = [name for name, ok in checks.items() if not ok]
        stray = sorted({n for n in figures_in(summary) | figures_in(explanation) if n >= 100} - allowed)
        instruction = None
        if not approved:
            instruction = "Fix: " + ", ".join(issues) + "." + (
                f" The edit summary or explanation states {', '.join(f'{n:,}' for n in stray)}, which no approved "
                f"finding holds." if stray else "") + (
                f" The edit summary must give the new figure, {latest['value']:,}, and cite INE." if not checks["summary"] else "")
        self.tracer.event(self.name, "review_draft", input_summary=f"{comuna.name} {key} draft",
                          output_summary=f"{comuna.name} {key} draft: {score}/9"
                                         + (f"; failed: {', '.join(issues)}" if issues else ""),
                          target_agent="Editor" if not approved else None, round_no=round_no,
                          status="approved" if approved else "rejected")
        return {"draft": key, "round": round_no, "score": score, "approved": approved, "checks": checks,
                "instruction": instruction}


def well_formed(body, target):
    """Balanced templates and references; for Wikidata, one QuickStatements command per line (a leading '-' removes
    a statement)."""
    if body.count("{{") != body.count("}}") or body.count("<ref") != body.count("</ref>"):
        return False
    return target != "wikidata" or all(re.match(r"^-?Q\d+\|P\d+\|", line) for line in body.splitlines() if line)


def digit_check(finding):
    """The code's digit-by-digit comparison of a figure with the census count it nearly equals."""
    digits, value = finding["digits"], finding["claim"].get("value")
    how = "one digit" if digits["slip"] == 1 else "two neighbouring digits"
    return f"{value:,} and INE's Census {digits['year']} count {digits['official']:,} differ in {how} only"


def figure(claim, table, finding=None):
    """A figure for a fix: what it is, where it is shown, its label, year and basis, and its size against the latest
    census count (the cues the Planner chooses a source by)."""
    value, latest = claim.get("value"), matcher.latest_census(table)
    return {("finding_id" if finding else "claim_id"): finding["id"] if finding else claim.get("id"), "value": value,
            "source": claim["source_name"], "location": claim.get("location"), "label": claim.get("label") or "no year",
            "year": claim.get("stated_year"), "basis": claim.get("basis"),
            "size": f"{matcher.scale(value, latest['value'])} the Census {latest['year']} count"
            if isinstance(value, int) and latest["value"] else None,
            "class": finding["class"] if finding else None}
