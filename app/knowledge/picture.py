"""The comuna picture: what FactSync last concluded about a comuna, rebuilt by the World Model from its log (a projection
the orchestrator registers with the engine; it is never edited in place).

It holds the official figures read, and from the latest run that assessed the comuna: for each page (Spanish and
English Wikipedia, Wikidata), the figure it shows as the current population and the verdict on it; every finding's
class, status and Critic score; escalations; and drafts. Because it is built from the log alone, the engine can
rebuild it as of any earlier point (`WorldModel.project_as_of`): comparing the picture a previous run left with the
current one is "since your last check".
"""
PAGES = {"es": "eswiki", "en": "enwiki", "wikidata": "wikidata"}
FIGURE = ("value", "label", "reference")


def comuna_picture(observations, assessments):
    assessments = [a for a in assessments if not (a["data"] or {}).get("fact")]  # population only: mayor runs mark theirs
    official = {}
    for o in observations:
        p = o["payload"]
        if o["source"].get("kind") == "official" and p.get("property") == "population" and p.get("value") is not None:
            key = p["scope"] if p.get("scope") in ("urban", "rural") else p["definition"]
            official.setdefault(key, {})[str(p["stated_year"])] = p["value"]
    analysed = [a for a in assessments if a["run_id"] and a["agent"] == "Analyst"]
    if not analysed:
        return {"run_id": None, "official": official, "pages": {}}
    run_id = analysed[-1]["run_id"]
    mine = [a for a in assessments if a["run_id"] == run_id]
    final = max(a["round"] or 0 for a in mine if a["agent"] == "Analyst")
    verdicts = [a["data"] for a in mine if a["agent"] == "Analyst" and (a["round"] or 0) == final]
    findings = {d["id"]: {"target": d["target"], "aspect": d["aspect"], "class": d["class"], "status": "proposed",
                          "claim": d["claim"]} for d in verdicts if d.get("id")}
    for a in mine:
        data = a["data"]
        if a["agent"] == "Critic" and data.get("finding_id") in findings:
            findings[data["finding_id"]].update(status=data["status"], score=data.get("score"))
        elif a["agent"] == "Orchestrator" and data.get("finding_id") in findings:
            findings[data["finding_id"]]["status"] = data["status"]
    checks = [d for d in verdicts if d.get("check")]
    latest_census = max((int(y) for y in official.get("census", {})), default=None)
    drafts = {}
    for a in mine:
        if a["agent"] in ("Editor", "Critic") and a["data"].get("draft"):
            drafts[a["data"]["draft"]] = a["data"].get("status")
    return {"run_id": run_id, "checked_at": max(a["created_at"] for a in mine), "official": official,
            "pages": pages(findings, checks, latest_census),
            "findings": {fid: {k: v for k, v in f.items() if k != "claim"} for fid, f in findings.items()},
            "open_escalations": sum(1 for f in findings.values() if f["status"] == "escalated"),
            "drafts": drafts}


def figure(claim):
    reference = claim.get("reference_raw")
    return {"value": claim.get("value"), "label": claim.get("label"), "reference": reference or None,
            "observation": claim.get("id")}


def pages(findings, checks, latest_census):
    """Per page, the figure it shows as the comuna's current population and the verdict on it: the infobox of each
    Wikipedia, and Wikidata's statement for the latest census (or the finding that says there is none)."""
    shown = {}
    for target in ("es", "en"):
        verdict = next((f for f in findings.values() if f["target"] == target and f["aspect"] == "value"
                        and f["claim"].get("location") == "infobox"), None)
        if verdict:
            shown[PAGES[target]] = {**figure(verdict["claim"]), "verdict": verdict["class"], "status": verdict["status"]}
            continue
        check = next((c for c in checks if c["claim"].get("target") == target
                      and c["claim"].get("location") == "infobox"), None)
        if check:
            shown[PAGES[target]] = {**figure(check["claim"]), "verdict": check["check"], "status": "checked"}
    about = [f for f in findings.values() if f["target"] == "wikidata"]
    gap = next((f for f in about if f["class"] == "missing_value" or f["aspect"] == "currency"), None)
    current = next((c for c in checks if c["claim"].get("target") == "wikidata" and c["check"] == "consistent"
                    and c["claim"].get("stated_year") == latest_census), None)
    if gap:
        shown["wikidata"] = {**figure(gap["claim"]), "verdict": gap["class"], "status": gap["status"]}
    elif current:
        shown["wikidata"] = {**figure(current["claim"]), "verdict": "consistent", "status": "checked"}
    return shown


def since_last_check(before, now):
    """Page by page, how what a source shows changed between two pictures: fixed (it now shows the right figure),
    changed, unchanged, new (not read before) or gone (not read now)."""
    changes = {}
    for page in [p for p in PAGES.values() if p in before["pages"] or p in now["pages"]]:
        old, new = before["pages"].get(page), now["pages"].get(page)
        if old is None:
            outcome = "new"
        elif new is None:
            outcome = "gone"
        elif all(old.get(k) == new.get(k) for k in FIGURE):
            outcome = "unchanged"
        elif new["verdict"] == "consistent" and old["verdict"] != "consistent":
            outcome = "fixed"
        else:
            outcome = "changed"
        changes[page] = {"outcome": outcome, "before": old, "now": new}
    return changes
