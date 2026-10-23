"""Critic: scores every finding on a 9-point rubric and approves it at 7 or more. When a comuna has findings below
7, it sends ONE specific fix back to the agent responsible (Planner, Extractor or Analyst). It also reviews drafts.

The rubric, 3 points per criterion:
  evidence fidelity      the claim is what its source says; every official figure cited is the one in the World
                         Model; the explanation states no figure the evidence doesn't hold
  definition discipline  the class is one the facts allow; it holds up on review; the confidence fits what is known.
                         A figure that matches no official figure read so far scores 0 here while an official source
                         is still unread: only that source can confirm or rule out an official estimate
  correction sourcing    a correction is proposed when one is needed; its figure is an official one in the World
                         Model; its source is INE's publication of that figure

The facts are recomputed from the World Model, not taken from the Analyst. The model's judgment (does the class fit,
is the explanation faithful) can overturn a verdict the model made, but costs a verdict made by code only one point.
"""
import re
from itertools import combinations

from app.agents.analyst import build_claims, claims_first
from app.agents.llm import batched, model_note
from app.agents.planner import CATALOG
from app.knowledge import matcher
from app.knowledge.taxonomy import census_facts, describe_classes, official_source

APPROVE_AT = 7
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
"made_by" says whether code or a model produced the verdict. Judge both the same way.
JSON: {{"reviews": [{{"finding_id": "...", "class_fits": true, "explanation_faithful": true, "note": "one sentence; required when either is false"}}]}}"""


def figures_in(text):
    """The figures a text states, however it groups thousands: 25,795, 25.795, 25 795, or with a non-breaking
    space as Spanish Wikipedia writes them (25&nbsp;795)."""
    text = re.sub(r"&nbsp;|&#160;|&thinsp;|[   ]", " ", str(text or ""))
    return {int(re.sub(r"\D", "", token)) for token in FIGURES.findall(text)}


def allowed_figures(evidence, extra=()):
    """Figures an explanation may state: those in the evidence (and the years a cited reference names), and
    differences between them."""
    numbers = set(extra)
    for item in evidence:
        numbers |= {y for y in item.get("years") or [] if isinstance(y, int)}
        for key in ("value", "year", "value_raw", "label", "quote", "source"):
            value = item.get(key)
            numbers |= {value} if isinstance(value, int) else figures_in(value)
    values = [n for n in numbers if n >= 100]
    return numbers | {abs(a - b) for a, b in combinations(values, 2)}


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

    def review(self, comuna, findings, observed, round_no, open_sources):
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
        fix = self.choose_fix(comuna, rejected, results) if rejected else None
        for finding in fresh:
            result = results[finding["id"]]
            self.world.assess(finding["claim"]["id"], agent=self.name, run_id=self.run_id, round_no=round_no, data={
                "finding_id": finding["id"], "class": finding["class"], "status": "approved" if result["approved"] else "rejected",
                **result, "fix": fix if fix and fix["finding_id"] == finding["id"] else None})
        review = {"round": round_no, "approved": not rejected, "results": results,
                  "rejected": [f["id"] for f in rejected], "fix": fix}
        comuna.reviews.append(review)
        scores = ", ".join(f"{f['class']} {results[f['id']]['score']}/9" for f in findings)
        if fix:
            self.tracer.event(self.name, "reject", input_summary=f"{comuna.name}: {len(findings)} findings ({scores})",
                              output_summary=f"{len(rejected)} below {APPROVE_AT}/9; fix for {fix['target_agent']}: {fix['instruction']}",
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
                                      for e in f["evidence"] if e["kind"] == "official"]} for f in group]}

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
        value, label, source = finding["claim"].get("value"), finding["claim"].get("label"), finding["claim"]["source_name"]
        shown = f"{value:,}" if isinstance(value, int) else "no figure"

        # evidence fidelity
        fidelity = 0
        observation = store.get_observation(finding["claim"]["id"])
        if observation and observation["payload"].get("value") == value and finding["claim"].get("verified") is not False:
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
        calibrated = finding["confidence"] <= 0.7 if unexplained else (finding["method"] != "matcher" or finding["confidence"] >= 0.8)
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
        if unexplained and open_sources:
            discipline = 0
            held = ", ".join(f"Census {y} {r['value']:,}" for y, r in sorted(table["census"].items()))
            names = "; ".join(CATALOG[s].rstrip(".") for s in open_sources)
            failures.append(failure("unread_official_source", f"{shown} ({source}, '{label}') matches no official figure "
                                    f"read so far ({held}). Before calling it {finding['class']}, read the official "
                                    f"source not yet consulted ({names}): only its figures can confirm or rule out "
                                    f"an official estimate.", "Planner", critical=True, held=held, unread=names))

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

    def choose_fix(self, comuna, rejected, results):
        """ONE fix per comuna and round: discovery first (it can settle several findings at once), then
        re-extraction, then re-analysis; among those, the lowest-scoring finding."""
        options = [(AGENT_ORDER[f_["target_agent"]], results[f["id"]]["score"], i, f, f_)
                   for i, f in enumerate(rejected) for f_ in results[f["id"]]["failures"]]
        if not options:
            finding = rejected[0]
            return {"target_agent": "Analyst", "finding_id": finding["id"], "check": "score",
                    "instruction": f"Revisit the {finding['class']} finding: it scored {results[finding['id']]['score']}/9.",
                    "comuna": comuna.name}
        _, _, _, finding, chosen = min(options, key=lambda o: o[:3])
        fix = {"target_agent": chosen["target_agent"], "finding_id": finding["id"], "check": chosen["check"],
               "instruction": chosen["detail"], "suggested_class": chosen.get("suggested_class"),
               "comuna": comuna.name, "cut": comuna.cut, "figures": [figure(finding)]}
        if chosen["check"] == "unread_official_source":  # one source can settle every such figure: ask once for all
            waiting = [f for f in rejected if any(x["check"] == chosen["check"] for x in results[f["id"]]["failures"])]
            fix["figures"] = [figure(f) for f in waiting]
            fix["finding_ids"] = [f["id"] for f in waiting]
            if len(waiting) > 1:
                listed = "; ".join(f"{x['value']:,} ({x['source']}, '{x['label']}', called {x['class']})"
                                   for x in fix["figures"])
                fix["instruction"] = (f"{len(waiting)} figures match no official figure read so far ({chosen['held']}): "
                                      f"{listed}. Before classifying them, read the official source not yet consulted "
                                      f"({chosen['unread']}): only its figures can confirm or rule out official "
                                      f"estimates.")
        return fix

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
            "figure": correction.get("value") == latest["value"] and latest["value"] in figures_in(body),
            "year": str(latest["year"]) in body,
            "citation": bool(re.search(r"\{\{\s*(cita web|cite web)|S854", body, re.I)),
            "official_url": bool(source) and source["url"] in body,
            "access_date": bool(re.search(r"fechaacceso\s*=|access-date\s*=|S813", body)),
            "well_formed": well_formed(body, draft["target"]),
            "summary": draft["target"] == "wikidata" or (0 < len(summary) <= 500 and latest["value"] in figures_in(summary)),
            "figures_faithful": not {n for n in figures_in(summary) | figures_in(explanation) if n >= 100} - allowed,
            "explanation": bool(explanation) and latest["value"] in figures_in(explanation),
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
    """Balanced templates and references; for Wikidata, one QuickStatements command per line."""
    if body.count("{{") != body.count("}}") or body.count("<ref") != body.count("</ref>"):
        return False
    return target != "wikidata" or all(re.match(r"^Q\d+\|P\d+\|", line) for line in body.splitlines() if line)


def figure(finding):
    claim = finding["claim"]
    return {"finding_id": finding["id"], "value": claim.get("value"), "source": claim["source_name"],
            "location": claim.get("location"), "label": claim.get("label"), "class": finding["class"]}
