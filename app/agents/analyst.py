"""Analyst: explains why each population figure for a comuna is what it is.

It reads the comuna's context payload from the World Model (official figures, Wikidata statements, Wikipedia claims
read this run, and the Critic's fixes), runs the deterministic matcher on every claim, and asks the model only about
the claims the matcher can't settle, all in one call per comuna. Every finding is written back to the World Model as
an append-only assessment attributed to the Analyst and the round.
"""
import hashlib

from app.agents.llm import batched, model_note
from app.knowledge import matcher
from app.knowledge.taxonomy import CLASSES, describe_classes
from app.knowledge.wikitext import basis_of, strip_markup

PROMPT = """FactSync Chile - Analyst.
For each claim below, code compared a population figure for a Chilean comuna with every official INE figure read so
far and found no single explanation. Choose the class that best explains it, from the claim's candidates:
{classes}
Facts: since 1950 Chile held censuses in 1952, 1960, 1970, 1982, 1992, 2002, 2017 and 2024; INE withdrew the 2012
census results. INE also publishes yearly estimates and projections, a different definition from a census count, and
each census's urban and rural population: parts of a comuna, not its total.
Use only the figures shown. If a source not read yet could explain a figure, say so rather than guess. Follow any
critic_instruction.
JSON: {{"verdicts": [{{"claim_id": "...", "class": "...", "explanation": "one or two sentences", "confidence": 0.5}}]}}"""

CLAIM_FIELDS = ("id", "target", "source_name", "title", "revid", "location", "role", "value", "value_raw", "stated_year",
                "basis", "label", "quote", "method", "verified", "rank", "item", "statement", "missing", "reference_raw",
                "field", "value_from", "wikidata_item", "wikidata_statement")
# What the Extractor's code reading of an infobox field carries beyond the SQL reading.
FIELD_EXTRAS = ("field", "value_from", "missing", "statements", "wikidata_item", "wikidata_statement", "urban_field",
                "urban_value", "quote")


def digest(*parts):
    return hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).hexdigest()[:16]


def claims_first(observation):
    """Context priority: official figures, then Wikidata, then Wikipedia claims."""
    order = {"official": 0, "wikidata": 1, "wikipedia": 2}
    return order.get(observation["source"].get("kind"), 3), observation["seq"]


def article_key(source):
    return source.get("language"), source.get("revid")


def build_claims(observations):
    """The claims to check, from the run's observations (infobox figures, figures in article text and history
    tables, Wikidata statements), and the reference found behind each infobox figure."""
    claims, citations = [], {}
    for o in observations:
        p, s = o["payload"], o["source"]
        if s.get("kind") == "wikipedia" and p.get("property") == "population_citation":
            citations[article_key(s)] = p
            continue
        if p.get("property") != "population":
            continue
        if s.get("kind") == "wikipedia":
            claim = {"id": o["id"], "target": s["language"], "source_name": s["name"], "title": s.get("title"),
                     "revid": s.get("revid"), "article": article_key(s), "location": p.get("location")}
            if p.get("extracted_by") == "zetaris" or p.get("field"):  # the infobox field, read by SQL or by code
                raw_year = p.get("stated_year_raw")
                claim.update(role="current", value=p.get("value"), value_raw=p.get("value_raw"),
                             stated_year=p.get("stated_year"), basis=basis_of(raw_year),
                             label=strip_markup(raw_year) or None, reference_raw=p.get("reference_raw"),
                             verified=True, method=p.get("method") or "zetaris",
                             **{k: p[k] for k in FIELD_EXTRAS if p.get(k) is not None})
            else:
                year, basis = p.get("stated_year"), {"census": "census", "projection": "projection",
                                                     "estimate": "projection"}.get(p.get("basis"))
                if p.get("location") == "history_table":
                    label = f"{year} (Historical populations table)"
                else:
                    label = f"{year} {basis}" if year and basis else str(year) if year else "no year"
                claim.update(role="historical" if year and p.get("location") != "infobox" else "current",
                             value=p.get("value"), value_raw=p.get("value_text"), stated_year=year, basis=basis,
                             label=label, quote=p.get("quote"), verified=p.get("verified"), method=p.get("method"))
            claims.append(claim)
        elif s.get("kind") == "wikidata":
            if p.get("missing"):
                claims.append({"id": o["id"], "target": "wikidata", "source_name": "Wikidata", "location": "item",
                               "role": "current", "value": None, "missing": True, "item": s.get("item"),
                               "label": "no population statement"})
                continue
            year, method = p.get("stated_year"), p.get("determination_method") or ""
            claims.append({"id": o["id"], "target": "wikidata", "source_name": "Wikidata", "location": "statement",
                           "role": "historical" if year else "current", "value": p.get("value"),
                           "value_raw": str(p.get("value")), "stated_year": year,
                           "basis": "census" if "Q39825" in method else None,
                           "label": f"point in time {p['point_in_time'][:10]}" if p.get("point_in_time") else "no point in time",
                           "rank": p.get("rank"), "determination_method": method or None,
                           "references": p.get("references") or [], "item": s.get("item"), "statement": s.get("statement")})
    # an infobox field SQL couldn't read, read by the Extractor (code or model), replaces the unread one
    read_again = {c["article"] for c in claims if c.get("location") == "infobox" and c.get("method") != "zetaris"}
    for claim in [c for c in claims if c.get("method") == "zetaris" and c["article"] in read_again]:
        claims.remove(claim)
        for read in claims:
            if read.get("article") == claim["article"] and read.get("location") == "infobox":
                read["reference_raw"] = claim.get("reference_raw") or read.get("reference_raw")
    return claims, citations


def compact(claim):
    return {k: claim[k] for k in CLAIM_FIELDS if claim.get(k) is not None}


class Analyst:
    name = "Analyst"

    def __init__(self, world, tracer, llm, run_id):
        self.world = world
        self.tracer = tracer
        self.llm = llm
        self.run_id = run_id

    def context(self, comuna, observed):
        context = self.world.context(comuna.entity_id, intent="analyze", budget_chars=80_000, rank=claims_first,
                                     include=lambda o: o["id"] in observed and o["payload"].get("document") != "article")
        return context

    def analyze(self, comuna, observed, round_no, sources_read):
        context = self.context(comuna, observed)
        self.tracer.event("WorldModel", "build_context", input_summary=f"{comuna.entity_id} ({comuna.name}), round {round_no}",
                          output_summary=context["trace"]["selection_reason"]
                                         + (" (truncated)" if context["trace"]["truncated"] else ""),
                          target_agent=self.name, round_no=round_no, engine="world_model")
        table = matcher.official_table(context["observations"])
        if not table["census"]:
            raise LookupError(f"no official census figures for {comuna.name} in the World Model")
        claims, citations = build_claims(context["observations"])
        findings, checks, elsewhere = [], [], set()
        for claim in claims:
            verdict = matcher.assess_value(claim, table, claims)
            if verdict is None:
                checks.append({"claim": compact(claim), "result": "not checkable", "note": matcher.unchecked_reason(claim)})
            elif verdict.get("check"):  # checked, and not a figure for the comuna as a whole
                checks.append({"claim": compact(claim), "result": verdict["check"], "note": verdict["explanation"]})
                elsewhere.add(claim["id"])
            elif verdict["class"] == "consistent":
                checks.append({"claim": compact(claim), "result": "consistent", "note": verdict["explanation"]})
            else:
                findings.append(self.finding(comuna, claim, "value", verdict, round_no))
        sourced = set()  # one reference per infobox field, however many figures it holds
        for infobox in [c for c in claims if c["location"] == "infobox"]:
            body = [c for c in claims if c.get("article") == infobox["article"] and c["id"] not in elsewhere
                    and c["location"] in ("lead", "body", "history_table")]
            consistency = matcher.assess_consistency(infobox, body)
            if consistency:
                consistency["proposal"] = matcher.update_proposal(table)
                findings.append(self.finding(comuna, infobox, "consistency", consistency, round_no))
            if infobox["article"] in sourced:
                continue
            sourced.add(infobox["article"])
            sourcing = matcher.assess_sourcing(infobox, citations.get(infobox["article"]),
                                               matcher.assess_value(infobox, table, claims), table)
            if sourcing:
                findings.append(self.finding(comuna, infobox, "sourcing", sourcing, round_no))
        statements = [c for c in claims if c["target"] == "wikidata" and not c.get("missing")]
        for anchor, verdict in matcher.assess_wikidata_item(statements, table):
            aspect = "currency" if verdict["class"] == "outdated_vintage" else "rank"
            findings.append(self.finding(comuna, anchor, aspect, verdict, round_no))

        fixes = self.open_fixes(comuna, round_no)
        asked = self.classify(comuna, findings, table, round_no, fixes, sources_read)
        for finding in findings:
            self.world.assess(finding["claim"]["id"], agent=self.name, run_id=self.run_id, round_no=round_no,
                              data={**finding, "status": "proposed"})
        by_class = {}
        for finding in findings:
            by_class[finding["class"]] = by_class.get(finding["class"], 0) + 1
        self.tracer.event(self.name, "assess_claims", input_summary=f"{comuna.name}: {len(claims)} claims, official "
                          f"figures {', '.join(f'{d} {sorted(t)}' for d, t in table.items() if t)}",
                          output_summary=f"{len(findings)} findings {by_class}; {len(checks)} consistent or not checkable; "
                                         f"{asked} sent to the model" + (f"; applied {len(fixes)} Critic fix(es)" if fixes else ""),
                          target_agent="Critic", round_no=round_no, status="success")
        return findings, checks

    def finding(self, comuna, claim, aspect, verdict, round_no):
        near = verdict.get("near")  # a census count the figure is one or two neighbouring digits away from
        return {"id": "fnd_" + digest(claim["id"], aspect), "cut": comuna.cut, "target": claim["target"],
                "aspect": aspect, "claim": compact(claim), "class": verdict["class"],
                "explanation": verdict["explanation"], "confidence": verdict["confidence"],
                "evidence": verdict["evidence"], "proposal": verdict.get("proposal"), "match": verdict.get("match"),
                "related": verdict.get("related"), "ambiguous": verdict["ambiguous"],
                "unexplained": verdict["unexplained"], "candidates": verdict["candidates"], "method": "matcher",
                "digits": {"official": near["value"], "year": near["year"], "slip": near["slip"]} if near else None,
                "round": round_no}

    def open_fixes(self, comuna, round_no):
        """The Critic's fixes addressed to the Analyst in the previous round, read from the World Model."""
        fixes = {}
        for review in self.world.view("observations").assessments(comuna.entity_id, run_id=self.run_id, agent="Critic"):
            fix = review["data"].get("fix")
            if review["round"] == round_no - 1 and fix and fix.get("target_agent") == self.name:
                fixes[fix["finding_id"]] = fix
        return fixes

    def classify(self, comuna, findings, table, round_no, fixes, sources_read):
        """Ask the model about the ambiguous findings (one call per comuna); reuse earlier verdicts while the facts
        and the Critic's instructions are unchanged. Returns how many findings were sent to the model."""
        loaded = ",".join(sorted(d for d, t in table.items() if t))
        todo = []
        for finding in findings:
            fix = fixes.get(finding["id"])
            if not finding["ambiguous"] and not fix:
                continue
            key = f"{finding['id']}|{loaded}"
            cached = comuna.llm_verdicts.get(key)
            if cached and not fix:
                finding.update(cached)
                continue
            todo.append((finding, fix, key))
        if not todo:
            return 0

        def payload(group):
            years = {f["claim"].get("stated_year") for f, _, _ in group} | {2017, 2024}
            official = {d: {y: r["value"] for y, r in sorted(t.items()) if d == "census" or y in years}
                        for d, t in table.items() if t}
            return {"comuna": comuna.name, "official_figures": official, "sources_read": sources_read,
                    "claims": [{"claim_id": f["id"], "source": f["claim"]["source_name"], "location": f["claim"]["location"],
                                "value": f["claim"].get("value"), "value_as_written": f["claim"].get("value_raw"),
                                "label": f["claim"].get("label"), "quote": f["claim"].get("quote"),
                                "matcher_note": f["explanation"], "candidates": f["candidates"] or [f["class"]],
                                **({"critic_instruction": fix["instruction"][:300]} if fix else {})} for f, fix, _ in group]}

        answers = {}  # finding id -> (the model's verdict or None, the reply's LLMResult); None when the request failed
        for group in batched(todo, payload):
            classes = sorted({c for f, _, _ in group for c in f["candidates"] or [f["class"]]})
            reply = self.llm.ask_json(self.name, "classify", PROMPT.format(classes=describe_classes(classes)),
                                      payload(group), target_agent="Critic", round_no=round_no,
                                      validate=lambda d: None if isinstance(d.get("verdicts"), list) else "no 'verdicts' list") \
                if self.llm else None
            verdicts = {str(v.get("claim_id")): v for v in reply[0]["verdicts"] if isinstance(v, dict)} if reply else {}
            for finding, _, _ in group:
                answers[finding["id"]] = (verdicts.get(finding["id"]), reply[1]) if reply else None
        for finding, fix, key in todo:
            answer, result = answers[finding["id"]] or (None, None)
            if answer and answer.get("class") in CLASSES and answer.get("class") != "consistent":
                try:
                    confidence = float(answer.get("confidence"))
                except (TypeError, ValueError):
                    confidence = 0.5
                update = {"class": answer["class"], "explanation": str(answer.get("explanation") or finding["explanation"])[:600],
                          "confidence": round(min(max(confidence, 0.0), 0.8), 2), "method": "llm", "model": model_note(result)}
            elif fix and fix.get("suggested_class"):
                update = {"class": fix["suggested_class"], "explanation": finding["explanation"],
                          "confidence": min(finding["confidence"], 0.6), "method": "rules (Critic's suggestion)"}
            else:
                update = {"method": "matcher (model unavailable)" if result is None else "matcher (model gave no usable verdict)"}
            finding.update(update)
            comuna.llm_verdicts[key] = update
        return len(todo)
