"""The review queue: one self-contained HTML page per run, for the person who reviews FactSync's drafts.

It is rendered from the run's result alone (the dict `run` returns, or output/<run_id>/result.json read back): what
each figure is and why it differs, the evidence, the Critic's score, the draft edits with their citations, and what
the agents did on the way (rejections, discovery, escalations). No scripts or styles load from the network, so the
page works offline and in sample mode.
"""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.knowledge.taxonomy import CLASSES, census_facts

TEMPLATES = Path(__file__).resolve().parent / "templates"
CLASS_LABELS = {
    "outdated_vintage": "Outdated", "different_definition": "Different definition",
    "discredited_source": "Withdrawn census", "nonexistent_census": "Nonexistent census",
    "mislabelled_vintage": "Mislabelled vintage", "internal_inconsistency": "Internal inconsistency",
    "cross_source_mismatch": "Unexplained mismatch", "wikidata_rank_qualifier": "Rank or qualifiers",
    "unsourced": "Unsourced", "genuine_error": "Likely error", "missing_value": "Missing value",
    "consistent": "Consistent",
}
TONES = {"genuine_error": "red", "cross_source_mismatch": "red", "discredited_source": "red",
         "nonexistent_census": "red", "outdated_vintage": "amber", "mislabelled_vintage": "amber",
         "different_definition": "blue", "internal_inconsistency": "violet", "unsourced": "slate",
         "missing_value": "slate", "wikidata_rank_qualifier": "slate", "consistent": "green"}
TARGETS = {"es": "Wikipedia (ES)", "en": "Wikipedia (EN)", "wikidata": "Wikidata"}
LOCATIONS = {"infobox": "infobox", "lead": "lead", "body": "article text", "history_table": "population table",
             "statement": "statement", "item": "item"}
DRAFTS = {"eswiki": "Spanish Wikipedia", "enwiki": "English Wikipedia", "wikidata": "Wikidata"}
PAGES = {"eswiki": "es", "enwiki": "en", "wikidata": "wikidata"}  # draft key -> the target of its findings
ASPECT_ORDER = {"value": 0, "consistency": 1, "sourcing": 2, "currency": 3, "rank": 4}
LOCATION_ORDER = {"infobox": 0, "lead": 1, "body": 2, "history_table": 3, "statement": 4, "item": 5}
METHODS = {"matcher": "code", "rules (Critic's suggestion)": "code, following the Critic's suggestion",
           "matcher (model unavailable)": "code (no model available)",
           "matcher (model gave no usable verdict)": "code (the model gave no usable verdict)"}
FINDING_STATUS = {"approved": "Critic approved", "escalated": "escalated to you", "pending": "pending"}
COMUNA_STATUS = {"approved": "Critic approved", "partial": "partly escalated", "escalated": "escalated", "pending": "pending"}
SOURCES = {"official_census": "INE census 2017 and 2024", "official_projections": "INE projections 2002–2035",
           "wikidata": "Wikidata", "wikipedia_es": "Wikipedia (ES)", "wikipedia_en": "Wikipedia (EN)"}
STATUS_ORDER = {"escalated": 0, "partial": 1, "pending": 2, "approved": 3}


def figure(value):
    return f"{value:,}" if isinstance(value, int) else "—"


def title_case(name):
    """INE writes comuna names in capitals: 'SAN PEDRO DE LA PAZ' reads 'San Pedro de la Paz'."""
    words = str(name or "").title().split(" ")
    small = {"De", "Del", "La", "Las", "Los", "Y"}
    return " ".join(w.lower() if i and w in small else w for i, w in enumerate(words))


def qid(item):
    return str(item or "").rstrip("/").rsplit("/", 1)[-1]


def by_year(table):
    """Year-keyed figures (int keys from a run, str keys from result.json), oldest first."""
    return [(int(year), value) for year, value in sorted((table or {}).items(), key=lambda kv: int(kv[0]))]


def claim_links(claim, comuna_drafts):
    """Where a reviewer can see the claim: the article revision FactSync read, or the Wikidata item."""
    if claim.get("target") in ("es", "en"):
        title = claim.get("title") or (comuna_drafts.get(f"{claim['target']}wiki") or {}).get("page")
        base = f"https://{claim['target']}.wikipedia.org"
        links = []
        if claim.get("revid"):
            links.append(("revision read", f"{base}/w/index.php?oldid={claim['revid']}"))
        if title:
            links.append(("article", f"{base}/wiki/{quote(str(title).replace(' ', '_'))}"))
        return links
    if claim.get("item"):
        return [("item", f"https://www.wikidata.org/wiki/{qid(claim['item'])}#P1082")]
    return []


def proposal_text(proposal):
    proposal = proposal or {}
    action, value, year = proposal.get("action"), proposal.get("value"), proposal.get("year")
    definition = "projection" if proposal.get("definition") == "projection" else "census"
    source = census_facts()["official_sources"].get(proposal.get("source_key") or "", {}).get("name")
    return {
        "update": f"Update to {figure(value)} (INE Census {year})",
        "add_statement": f"Add the Census {year} figure, {figure(value)}",
        "relabel": f"Relabel as the INE {definition} for {year}",
        "fix_figure": f"Correct to {figure(value)} (INE Census {year})",
        "deprecate": "Deprecate: not an official figure",
        "add_citation": f"Cite {source or 'INE'}",
        "set_rank_qualifiers": "Set ranks, points in time, methods and references",
        "human_review": "Needs a human: no official figure explains it",
    }.get(action, "")


def decided_by(note):
    """Who made a verdict or wrote a text: code, or the model Nightshift says answered (and whether it replayed it)."""
    if not note or note.get("method") != "llm":
        return "code"
    served = note.get("model_served") or note.get("routed_model") or "a model"
    return f"model: {served}" + (" (replayed from Nightshift's cache)" if note.get("nightshift_cache") == "exact" else "")


def where(claim):
    """Where a figure is shown; an infobox figure taken from Wikidata says so."""
    place = LOCATIONS.get(claim.get("location"), claim.get("location") or "")
    return f"{place} (from Wikidata)" if claim.get("value_from") == "wikidata" else place


def finding_view(finding):
    claim, critic = finding["claim"], finding.get("critic") or {}
    criteria = critic.get("criteria") or {}
    as_written = claim.get("value_raw") if finding["target"] in ("es", "en") else None  # Wikidata has no text form
    return {
        "id": finding["id"],
        "where": where(claim),
        "value": as_written or figure(claim.get("value")),
        "label": claim.get("label"),
        "quote": claim.get("quote"),
        "class": finding["class"], "class_label": CLASS_LABELS.get(finding["class"], finding["class"]),
        "class_help": CLASSES.get(finding["class"], ""), "tone": TONES.get(finding["class"], "slate"),
        "explanation": finding["explanation"],
        "confidence": finding.get("confidence"),
        "evidence": [e for e in finding.get("evidence") or [] if e.get("kind") == "official"],
        "proposal": proposal_text(finding.get("proposal")),
        "status": finding.get("status"), "status_label": FINDING_STATUS.get(finding.get("status"), finding.get("status")),
        "score": critic.get("score"),
        "criteria": [("evidence", criteria.get("evidence_fidelity")), ("definition", criteria.get("definition_discipline")),
                     ("sourcing", criteria.get("correction_sourcing"))] if criteria else [],
        "rounds": critic.get("rounds"),
        "critic_issues": [f["detail"] for f in critic.get("failures") or []] + list(critic.get("notes") or []),
        "classified_by": decided_by(finding.get("model")) if finding.get("method") == "llm" else
        METHODS.get(finding.get("method"), "code"),
        "reviewed_by": "code and " + decided_by(critic["judged_by_model"]) if critic.get("judged_by_model") else "code",
    }


def draft_view(key, draft, reviews):
    final = next((r[key] for r in reversed(reviews) if key in r), None)
    view = {"key": key, "status": draft.get("status"), "summary": draft.get("edit_summary"),
            "notes": draft.get("notes") or [], "text_changes": draft.get("text_changes") or [],
            "replaces": draft.get("replaces"), "score": final["score"] if final else None,
            "revisions": sum(1 for r in reviews if key in r),
            "body": draft.get("wikitext") or draft.get("quickstatements") or "", "links": []}
    if key == "wikidata":
        view["links"] = [("open in QuickStatements (review before running)",
                          "https://quickstatements.toolforge.org/#/v1=" + quote(view["body"], safe=""))]
    elif draft.get("page"):
        view["links"] = [("edit the article", f"https://{key[:2]}.wikipedia.org/w/index.php?title="
                                              f"{quote(str(draft['page']).replace(' ', '_'))}&action=edit")]
    return view


def page_views(comuna):
    """One section per page with findings or a draft (Spanish and English Wikipedia, Wikidata): what is wrong on it,
    in reading order, then the draft that fixes it."""
    drafts, reviews = comuna.get("drafts") or {}, (comuna.get("critic") or {}).get("draft_reviews") or []
    pages = []
    for key, label in DRAFTS.items():
        mine = sorted((f for f in comuna.get("findings") or [] if f["target"] == PAGES[key]),
                      key=lambda f: (ASPECT_ORDER.get(f["aspect"], 9), LOCATION_ORDER.get(f["claim"].get("location"), 9)))
        draft = drafts.get(key)
        if not (mine or draft):
            continue
        claim = mine[0]["claim"] if mine else {}
        name = (draft or {}).get("page") or claim.get("title") or (qid(claim.get("item")) if claim.get("item") else None)
        pages.append({"key": key, "label": label, "name": name, "links": claim_links(claim, drafts) if claim else [],
                      "findings": [finding_view(f) for f in mine],
                      "draft": draft_view(key, draft, reviews) if draft else None})
    return pages


def comuna_view(comuna):
    drafts = comuna.get("drafts") or {}
    official = comuna.get("official") or {}
    return {
        "cut": comuna["cut"], "name": title_case(comuna["name"]), "status": comuna["status"],
        "status_label": COMUNA_STATUS.get(comuna["status"], comuna["status"]),
        "census": by_year(official.get("census")), "projection": by_year(official.get("projection")),
        "claims_checked": comuna.get("claims_checked", 0),
        "findings": comuna.get("findings") or [],
        "pages": page_views(comuna),
        "has_drafts": any(k in drafts for k in DRAFTS),
        "checks": [{"where": f"{TARGETS.get(c['claim'].get('target'), c['claim'].get('target'))} · {where(c['claim'])}",
                    "value": c["claim"].get("value_raw") or figure(c["claim"].get("value")),
                    "label": c["claim"].get("label"), "result": c["result"], "note": c.get("note")}
                   for c in comuna.get("checks") or []],
        "explanation": drafts.get("explanation"),
        "explanation_by": decided_by(drafts.get("explanation_by")),
        "escalations": [escalation_text(e) for e in comuna.get("escalations") or []],
        "rounds": (comuna.get("critic") or {}).get("rounds", 0),
    }


def escalation_text(entry):
    who = title_case(entry.get("comuna") or "")
    kind = entry.get("kind")
    if kind == "finding":
        return (f"{who}: {TARGETS.get(entry.get('target'), entry.get('target'))} "
                f"{CLASS_LABELS.get(entry.get('class'), entry.get('class'))} finding scored {entry.get('score')}/9 after "
                f"every Critic round. {entry.get('reason', '')}")
    if kind == "draft":
        return f"{who}: the {DRAFTS.get(entry.get('draft'), entry.get('draft'))} draft still fails review " \
               f"({entry.get('score')}/9). {entry.get('reason') or ''}"
    if kind == "entity_resolution":
        return (f"'{entry.get('name')}' matched {title_case(entry.get('candidate'))} only in the review band "
                f"(similarity {entry.get('similarity')}): confirm the comuna.")
    if kind == "data_fallback":
        return entry.get("reason", "")
    return f"{who}: {entry.get('reason', '')}"


def timeline(result):
    """What the agents did, from the result: Critic rejections and the fix sent back, discovery, re-reviews,
    escalations, draft revisions and data fallbacks, in round order."""
    events = []
    for discovery in result.get("discoveries") or []:
        events.append((discovery["round"], 1, f"round {discovery['round']}", "discovery", "Planner",
                       f"added {SOURCES.get(discovery['source'], discovery['source'])}: {discovery.get('reason', '')}",
                       decided_by(discovery)))
    for comuna in result.get("comunas") or []:
        name = title_case(comuna["name"])
        history = (comuna.get("critic") or {}).get("history") or []
        for i, review in enumerate(history):
            if not review["approved"] and review.get("fix"):
                events.append((review["round"], 0, f"round {review['round']}", "reject", "Critic",
                               rejection_text(name, review), None))
            elif review["approved"] and i:
                events.append((review["round"], 2, f"round {review['round']}", "approve", "Critic",
                               f"approved {name} after the fix", None))
        for revision in (comuna.get("critic") or {}).get("draft_reviews") or []:
            for key, review in revision.items():
                if not review["approved"]:
                    events.append((100 + review["round"], 3, f"draft review {review['round']}", "reject", "Critic",
                                   f"rejected the {DRAFTS.get(key, key)} draft for {name} ({review['score']}/9): "
                                   f"{review.get('instruction') or ''}", None))
    for escalation in result.get("escalations") or []:
        kind = escalation.get("kind")
        if kind == "data_fallback":
            events.append((0, 0, "reading", "fallback", "Orchestrator", escalation["reason"], None))
        elif kind == "entity_resolution":
            events.append((0, 1, "planning", "escalate", "Planner", f"asks a human: {escalation_text(escalation)}", None))
        else:
            when = f"round {escalation['round']}" if escalation.get("round") else "drafts"
            events.append((escalation.get("round") or 200, 4, when, "escalate", "Orchestrator",
                           f"escalated to a human: {escalation_text(escalation)}", None))
    events.sort(key=lambda e: (e[0], e[1]))
    return [{"when": when, "kind": kind, "agent": agent, "text": text, "by": by}
            for _, _, when, kind, agent, text, by in events]


def rejection_text(name, review):
    """A Critic rejection in one line: discovery requests by their figures, other fixes by their instruction."""
    fix, rejected = review["fix"], len(review["rejected"])
    if fix.get("check") == "unread_official_source" and fix.get("figures"):
        figures = "; ".join(f"{figure(x['value'])} ({x['source']}, '{x['label']}')" for x in fix["figures"])
        verb = "match" if len(fix["figures"]) > 1 else "matches"
        return (f"rejected {name}: {figures} {verb} no official figure read so far, so it sent the Planner to read "
                f"an official source before anything is classified")
    instruction = fix["instruction"] if len(fix["instruction"]) <= 240 else \
        fix["instruction"][:237].rsplit(" ", 1)[0] + "…"
    return (f"rejected {name} ({rejected} finding{'s' if rejected != 1 else ''} below 7/9) and sent one fix to the "
            f"{fix['target_agent']}: {instruction}")


def model_line(usage):
    if not usage or not usage.get("calls"):
        return "No model calls: every step took its deterministic path."
    served = ", ".join(f"{model} ({n})" for model, n in sorted((usage.get("served_model") or {}).items()))
    line = f"{usage['calls']} model calls through Meterless Nightshift, answered by {served}."
    if usage.get("fallbacks"):
        line += " Fell back to code: " + ", ".join(f"{a} {n}×" for a, n in sorted(usage["fallbacks"].items())) + "."
    if usage.get("nightshift_cache"):
        line += " Replayed from Nightshift's cache: " + ", ".join(f"{n}" for n in usage["nightshift_cache"].values()) + "."
    return line


def build_view(result):
    if result.get("status") == "error":
        return {"error": result.get("error") or {}, "result": result}
    summary = result.get("summary") or {}
    comunas = sorted((comuna_view(c) for c in result.get("comunas") or []),
                     key=lambda c: (STATUS_ORDER.get(c["status"], 9), -len(c["findings"]), c["name"]))
    plan = result.get("plan") or {}
    discovered = {d["source"] for d in result.get("discoveries") or []}
    data = result.get("data") or {}
    return {
        "result": result, "summary": summary, "comunas": comunas, "timeline": timeline(result),
        "sources": [(SOURCES.get(s, s), s in discovered) for s in plan.get("sources") or []],
        "model_line": model_line(result.get("model_usage")),
        "classes": [(name, CLASS_LABELS[name], TONES[name], CLASSES[name]) for name in CLASSES if name != "consistent"],
        "by_class": [(CLASS_LABELS.get(k, k), TONES.get(k, "slate"), v)
                     for k, v in sorted((summary.get("findings_by_class") or {}).items(), key=lambda kv: -kv[1])],
        "needs_review": [{"kind": e.get("kind"), "text": escalation_text(e)} for e in result.get("escalations") or []],
        "data": data,
        "unresolved": plan.get("unresolved") or [],
    }


def render_report(result, generated_at=None):
    environment = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]),
                              trim_blocks=True, lstrip_blocks=True)
    environment.filters["figure"] = figure
    environment.filters["title_case"] = title_case
    template = environment.get_template("review_queue.html.j2")
    generated = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return template.render(**build_view(result), generated_at=generated)


def write_report(result, output_dir):
    """Write output/<run_id>/report.html; returns its path."""
    path = Path(output_dir) / result["run_id"] / "report.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(result), encoding="utf-8")
    return path
