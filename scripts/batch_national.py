"""The national batch: every comuna, region by region, to measure how far the population figures (or, with
--fact mayor, the mayors) in Spanish and English Wikipedia and in Wikidata are from INE's Census 2024 count (or from
who SERVEL says was elected in 2024).

Usage:  .venv\\Scripts\\python scripts\\batch_national.py [--tag 20261025] [--fact mayor] [--pause 15] [--use-llm]
                                                    [--region Aysén ...]

Each region is one ordinary run (run_id national-<tag>-<nn>-<region>) with its own result.json, review queue and
trace; a region already finished under the same tag is skipped, so a rerun resumes. By default the agents take
their deterministic paths (no model calls): the whole country through Nightshift would take days. --use-llm turns
the model on, paced and capped by each run's call budget. --pause waits between regions, since every run reads the
Wikipedia views live (Zetaris fetches them from the MediaWiki API).

At the end it writes output/national-<tag>/summary.json and summary.md, computed from the runs' results: for each
source, how many comunas show a current population figure, how many of those are INE's Census 2024 count, and why
the others differ; which official sources the Planner added and for how many figures; what became of the figures
that could only be checked against an older census; and, per page, what changed since each comuna's last check.
For mayors: for each source, how many pages name the mayor elected in 2024, and why the others differ (a former
mayor, and which election they last won; a losing candidate; a name SERVEL doesn't have), with every unknown name
listed for a human to look at.
"""
import argparse
import json
import re
import sys
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.zetaris import ZetarisClient, as_str  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.engines.world_model import normalize_name  # noqa: E402
from app.errors import RunError  # noqa: E402
from app.orchestration.loop import run  # noqa: E402
from app.report.html import CLASS_LABELS, title_case  # noqa: E402
from app.schemas import RunInput  # noqa: E402

TARGETS = {"es": "Spanish Wikipedia", "en": "English Wikipedia", "wikidata": "Wikidata"}


def slug(region):
    """'Región de Aysén del General Carlos Ibáñez del Campo' -> 'aysen-del-general-carlos-ibanez-del-campo'."""
    ascii_text = unicodedata.normalize("NFKD", region).encode("ascii", "ignore").decode().lower()
    ascii_text = re.sub(r"^region (de |del )?", "", ascii_text)
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")[:40].rstrip("-")


def regions(settings):
    """Every comuna's CUT, grouped by region, from the Census 2024 list (one SQL statement)."""
    client = ZetarisClient(settings.zetaris_rest_url, settings.zetaris_org_id, settings.zetaris_api_key)
    grouped = {}
    for row in client.query("SELECT cut, region FROM factsync.ine_census2024").rows:
        grouped.setdefault(as_str(row["region"]) or "?", []).append(as_str(row["cut"]))
    return {region: sorted(cuts) for region, cuts in sorted(grouped.items(), key=lambda kv: min(kv[1]))}


def current_figure(comuna, target):
    """How a source shows the comuna's current population: 'up to date' (INE's Census 2024 count, correctly
    labelled), the class of the finding about it, or None when the source has no page or figure."""
    if target == "wikidata":
        about = [f for f in comuna["findings"] if f["target"] == "wikidata"]
        missing = next((f for f in about if f["class"] == "missing_value"), None)
        if missing:
            return "missing_value"
        statements = [c for c in comuna["checks"] if c["claim"].get("target") == "wikidata"] + about
        outdated = next((f for f in about if f["aspect"] == "currency"), None)
        if outdated:  # no Census 2024 statement
            newest = next((f for f in about if f["aspect"] == "value" and f["claim"]["id"] == outdated["claim"]["id"]),
                          None)
            if newest and newest["class"] == "genuine_error":  # its newest figure isn't this comuna's, or is a typo
                return "genuine_error"
            latest = comuna["official"]["census"][max(comuna["official"]["census"], key=int)]
            if any(s["claim"].get("value") == latest for s in statements):  # the 2024 count, dated wrongly
                return "mislabelled_vintage"
            return "outdated_vintage"
        return "up to date" if statements else None
    infobox = [f for f in comuna["findings"] if f["target"] == target and f["aspect"] == "value"
               and f["claim"].get("location") == "infobox"]
    if infobox:
        return infobox[0]["class"]
    consistent = [c for c in comuna["checks"] if c["claim"].get("target") == target
                  and c["claim"].get("location") == "infobox" and c["result"] == "consistent"]
    return "up to date" if consistent else None


def fed_by_wikidata(comuna, target):
    """Whether the source's infobox has no figure of its own and shows Wikidata's (eswiki's template does that)."""
    return any(x["claim"].get("target") == target and x["claim"].get("location") == "infobox"
               and x["claim"].get("value_from") == "wikidata" and x["claim"].get("value") is not None
               for x in comuna["findings"] + comuna["checks"])


def census_2002(comuna):
    """The figures attributed to the 2002 census, and what became of each: consistent with INE's count, a finding
    (and its class), or still not checkable."""
    outcomes = Counter()
    for item in comuna["findings"] + comuna["checks"]:
        claim = item["claim"]
        if claim.get("stated_year") == 2002 and claim.get("basis") == "census" and item.get("aspect", "value") == "value":
            outcomes[item.get("class") or item["result"]] += 1
    return outcomes


def summarize(results, tag, use_llm):
    by_target = {t: Counter() for t in TARGETS}
    from_wikidata = {t: Counter() for t in TARGETS}
    classes, checks, unchecked_years, cited_2002, since = Counter(), Counter(), Counter(), Counter(), Counter()
    discoveries, served = Counter(), Counter()
    comunas = checked_before = 0
    for result in results:
        for discovery in result.get("discoveries") or []:
            discoveries[discovery["source"]] += 1
            served[discovery["source"]] += len(discovery.get("requests") or [])
        for comuna in result["comunas"]:
            comunas += 1
            for target in TARGETS:
                outcome = current_figure(comuna, target)
                by_target[target][outcome or "no figure"] += 1
                if fed_by_wikidata(comuna, target):
                    from_wikidata[target][outcome or "no figure"] += 1
            for finding in comuna["findings"]:
                classes[finding["class"]] += 1
            for check in comuna["checks"]:
                checks[check["result"]] += 1
                if check["result"] == "not checkable":
                    unchecked_years[str(check["claim"].get("stated_year") or "no year")] += 1
            cited_2002.update(census_2002(comuna))
            if comuna.get("since_last_check"):
                checked_before += 1
                since.update(change["outcome"] for change in comuna["since_last_check"]["pages"].values())
    sources = {}
    for target, counts in by_target.items():
        shown = sum(n for k, n in counts.items() if k not in ("no figure", "missing_value"))
        current = counts["up to date"]
        sources[target] = {"comunas_with_a_figure": shown, "census_2024_count": current,
                           "differs": shown - current, "missing": counts["missing_value"],
                           "no_page_or_figure": counts["no figure"],
                           "share_differing": round((shown - current) / shown, 3) if shown else None,
                           "why": dict(sorted(((k, n) for k, n in counts.items()
                                               if k not in ("up to date", "no figure", "missing_value")),
                                              key=lambda kv: -kv[1])),
                           "infobox_shows_wikidata": sum(from_wikidata[target].values()),
                           "infobox_shows_wikidata_by_outcome": dict(from_wikidata[target].most_common())}
    figures = sum(s["comunas_with_a_figure"] for s in sources.values())
    differing = sum(s["differs"] for s in sources.values())
    return {"tag": tag, "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "method": "agents with the model (Nightshift)" if use_llm else
                      "agents on their deterministic paths (matcher, rule-based Critic, templates): no model calls",
            "comunas": comunas, "regions": len(results),
            "current_figures": figures, "differing_from_census_2024": differing,
            "share_differing": round(differing / figures, 3) if figures else None,
            "by_source": sources, "findings_by_class": dict(classes.most_common()),
            "checks": dict(checks.most_common()), "not_checkable_by_year": dict(unchecked_years.most_common()),
            "census_2002_figures": dict(cited_2002.most_common()),
            "discoveries": {s: {"runs": n, "figures": served[s]} for s, n in discoveries.most_common()},
            "since_last_check": {"comunas_checked_before": checked_before, **dict(since.most_common())},
            "runs": [{"run_id": r["run_id"], "status": r["status"], "comunas": r["summary"]["comunas"],
                      "findings": r["summary"]["findings"], "drafts": r["summary"]["drafts"],
                      "report": r.get("report_file")} for r in results]}


def mayor_outcome(comuna, target):
    """What a source says about the mayor: 'elected in 2024', the class of the finding about it (a former mayor gets
    the year of the last election they won), or None when the source has no page."""
    about = [f for f in comuna["findings"] if f["target"] == target and f["aspect"] == "value"]
    if not about and any(f["target"] == target and f["class"] == "wikidata_qualifier" for f in comuna["findings"]):
        return "elected in 2024"  # Wikidata names the winner, with a qualifier to fix (counted apart)
        finding = about[0]
        if finding["class"] == "outdated_mayor" and finding.get("match"):
            return f"outdated_mayor_{max(finding['match']['won'])}"
        return finding["class"]
    if any(c["claim"].get("target") == target and c["result"] == "consistent" for c in comuna["checks"]):
        return "elected in 2024"
    return None


def summarize_mayors(results, tag, use_llm):
    by_target = {t: Counter() for t in TARGETS}
    classes, discoveries, served, unknown, signals, qualifiers = Counter(), Counter(), Counter(), [], [], 0
    comunas = 0
    for result in results:
        for discovery in result.get("discoveries") or []:
            discoveries[discovery["source"]] += 1
            served[discovery["source"]] += len(discovery.get("requests") or [])
        for comuna in result["comunas"]:
            comunas += 1
            for target in TARGETS:
                by_target[target][mayor_outcome(comuna, target) or "not read"] += 1
            for finding in comuna["findings"]:
                classes[finding["class"]] += 1
                qualifiers += finding["class"] == "wikidata_qualifier"
                if finding["class"] == "unknown_name":
                    unknown.append({"comuna": title_case(comuna["name"]), "cut": comuna["cut"],
                                    "source": TARGETS[finding["target"]], "name": finding["claim"].get("name"),
                                    "notes": finding["claim"].get("notes") or [], "reading": finding.get("reading")})
                if finding.get("signals") and finding["target"] != "wikidata":
                    signals.append(f"{title_case(comuna['name'])} ({TARGETS[finding['target']]})")
    sources = {}
    for target, counts in by_target.items():
        naming = sum(n for k, n in counts.items() if k not in ("not read", "missing_value"))
        current = counts["elected in 2024"]
        sources[target] = {"pages_naming_a_mayor": naming, "name_the_2024_winner": current,
                           "name_someone_else": naming - current, "name_no_one": counts["missing_value"],
                           "not_read": counts["not read"],
                           "share_someone_else": round((naming - current) / naming, 3) if naming else None,
                           "why": dict(sorted(((k, n) for k, n in counts.items()
                                               if k not in ("elected in 2024", "not read", "missing_value")),
                                              key=lambda kv: -kv[1]))}
    naming = sum(s["pages_naming_a_mayor"] for s in sources.values())
    other = sum(s["name_someone_else"] for s in sources.values())
    return {"tag": tag, "fact": "mayor", "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "method": "agents with the model (Nightshift)" if use_llm else
                      "agents on their deterministic paths (name matcher, rule-based Critic, templates): no model calls",
            "comunas": comunas, "regions": len(results), "pages_naming_a_mayor": naming,
            "naming_someone_else": other, "share_someone_else": round(other / naming, 3) if naming else None,
            "by_source": sources, "findings_by_class": dict(classes.most_common()),
            "wikidata_qualifier_findings": qualifiers, "unknown_names": unknown,
            "office_may_have_changed": signals,
            "discoveries": {s: {"runs": n, "names": served[s]} for s, n in discoveries.most_common()},
            "runs": [{"run_id": r["run_id"], "status": r["status"], "comunas": r["summary"]["comunas"],
                      "findings": r["summary"]["findings"], "drafts": r["summary"]["drafts"],
                      "report": r.get("report_file")} for r in results]}


WHY = {"outdated_mayor_2021": "former mayor, last elected 2021", "outdated_mayor_2016": "former mayor, last elected 2016",
       "outdated_mayor_2012": "former mayor, last elected 2012", "not_elected": "a candidate never elected 2012-2024",
       "unknown_name": "no one SERVEL lists (stand-in, misspelling or vandalism?)",
       "outdated_mayor": "former mayor", "wikidata_qualifier": "qualifiers"}


def markdown_mayors(summary):
    lines = [f"# National batch {summary['tag']}: mayors", "",
             f"{summary['comunas']} comunas in {summary['regions']} regions; {summary['method']}.", "",
             f"Of {summary['pages_naming_a_mayor']} pages that name a mayor across the three sources, "
             f"**{summary['naming_someone_else']} ({summary['share_someone_else']:.0%})** don't name the mayor SERVEL "
             f"says was elected in October 2024. SERVEL records who was elected, not who holds the office today, so "
             f"some of these may be right (a stand-in, a replacement): every draft asks the editor to check.", "",
             "| Source | Pages naming a mayor | The 2024 winner | Someone else | Names no one | Not read | Who else |",
             "|---|---|---|---|---|---|---|"]
    for target, s in summary["by_source"].items():
        why = ", ".join(f"{WHY.get(k, k)} {n}" for k, n in s["why"].items())
        share = f" ({s['share_someone_else']:.0%})" if s["share_someone_else"] is not None else ""
        lines.append(f"| {TARGETS[target]} | {s['pages_naming_a_mayor']} | {s['name_the_2024_winner']} | "
                     f"{s['name_someone_else']}{share} | {s['name_no_one']} | {s['not_read']} | {why} |")
    discovered = "; ".join(f"{s} in {d['runs']} of {summary['regions']} regions, for {d['names']} names"
                           for s, d in summary.get("discoveries", {}).items())
    if discovered:
        lines += ["", f"**Discovery.** Elections the Planner added from the Zetaris catalog when the Critic sent names "
                      f"back: {discovered}."]
    if summary["office_may_have_changed"]:
        lines += ["", "**The office may have changed hands** (Wikidata records the end of the 2024 winner's term): "
                      + ", ".join(summary["office_may_have_changed"]) + "."]
    if summary["unknown_names"]:
        lines += ["", f"**Names SERVEL doesn't have** ({len(summary['unknown_names'])}), for a human to look at:", ""]
        lines += [f"- {u['comuna']} ({u['cut']}), {u['source']}: '{u['name']}'"
                  + (f" ({'; '.join(u['notes'])})" if u["notes"] else "")
                  + (f", read by the model as {u['reading'].replace('_', ' ')}" if u.get("reading") else "")
                  for u in summary["unknown_names"]]
    lines += ["", "*Names no one:* an infobox whose mayor field is empty, or a Wikidata item without a head of "
              "government (P6) statement.", "",
              "*Not read:* FactSync reads the Wikipedia article linked from each comuna's Wikidata item; a comuna "
              "whose item links no article isn't counted.", "", "Runs:", ""] + [
        f"- `{r['run_id']}`: {r['status']}, {r['comunas']} comunas, {r['findings']} findings, {r['drafts']} drafts "
        f"({r['report']})" for r in summary["runs"]]
    return "\n".join(lines) + "\n"


def markdown(summary):
    lines = [f"# National batch {summary['tag']}", "",
             f"{summary['comunas']} comunas in {summary['regions']} regions; {summary['method']}.", "",
             f"Of {summary['current_figures']} current population figures shown across the three sources, "
             f"**{summary['differing_from_census_2024']} ({summary['share_differing']:.0%})** are not INE's Census 2024 "
             f"count (correctly labelled).", "",
             "| Source | Comunas with a figure | Census 2024 count | Differs | No figure | Not read | Why it differs |",
             "|---|---|---|---|---|---|---|"]
    for target, s in summary["by_source"].items():
        why = ", ".join(f"{CLASS_LABELS.get(k, k)} {n}" for k, n in s["why"].items())
        share = f" ({s['share_differing']:.0%})" if s["share_differing"] is not None else ""
        lines.append(f"| {TARGETS[target]} | {s['comunas_with_a_figure']} | {s['census_2024_count']} | "
                     f"{s['differs']}{share} | {s['missing']} | {s['no_page_or_figure']} | {why} |")
    for target, s in summary["by_source"].items():
        if s.get("infobox_shows_wikidata"):
            outcomes = ", ".join(f"{'Census 2024 count' if k == 'up to date' else CLASS_LABELS.get(k, k)} {n}"
                                 for k, n in s["infobox_shows_wikidata_by_outcome"].items())
            lines += ["", f"**{s['infobox_shows_wikidata']} {TARGETS[target]} infoboxes have no population figure of "
                          f"their own and show Wikidata's** ({outcomes}); they are counted above under the figure they "
                          f"show. Their template fills an empty population field from Wikidata, so Wikidata's "
                          f"staleness reaches the article, and correcting Wikidata's statement corrects the infobox too."]
    discovered = "; ".join(f"{s} in {d['runs']} of {summary['regions']} regions, for {d['figures']} figures"
                           for s, d in summary.get("discoveries", {}).items())
    if discovered:
        lines += ["", f"**Discovery.** Sources the Planner added from the Zetaris catalog when the Critic sent figures "
                      f"back: {discovered}."]
    cited = summary.get("census_2002_figures") or {}
    if cited:
        lines += ["", "**Figures attributed to the 2002 census**, checked against INE's Census 2002 count once the "
                      "Planner added it: " + ", ".join(f"{CLASS_LABELS.get(k, k)} {n}" for k, n in cited.items()) + "."]
    unchecked = summary.get("not_checkable_by_year") or {}
    if unchecked:
        lines += ["", f"**{sum(unchecked.values())} figures could not be checked**, for want of an official figure for "
                      f"their year: " + ", ".join(f"{y}: {n}" for y, n in unchecked.items()) + "."]
    since = {k: n for k, n in (summary.get("since_last_check") or {}).items() if k != "comunas_checked_before"}
    if since:
        lines += ["", f"**Since the last check** of {summary['since_last_check']['comunas_checked_before']} comunas, "
                      f"per page: " + ", ".join(f"{k} {n}" for k, n in since.items()) + "."]
    lines += ["", "*No figure:* the source shows no population figure: a Wikidata item without a population "
              "statement, or an infobox whose population field is empty (with nothing in Wikidata to fill it on "
              "Spanish Wikipedia).", "",
              "*Not read:* FactSync reads the Wikipedia article linked from each comuna's Wikidata item (the "
              "`factsync.eswiki_articles` and `enwiki_articles` views). A comuna whose item links no article, often "
              "because the article is attached to the town's item instead, isn't counted. An infobox whose population "
              "field SQL can't read is read again from the article's wikitext, so it is counted under the figure the "
              "infobox shows (its own, Wikidata's, or none).", "", "Runs:", ""] + [
        f"- `{r['run_id']}`: {r['status']}, {r['comunas']} comunas, {r['findings']} findings, {r['drafts']} drafts "
        f"({r['report']})" for r in summary["runs"]]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", default=datetime.now(timezone.utc).strftime("%Y%m%d"))
    parser.add_argument("--pause", type=float, default=15.0, help="seconds between regions")
    parser.add_argument("--use-llm", action="store_true", help="let the agents call the model (slow)")
    parser.add_argument("--fact", choices=("population", "mayor"), default="population")
    parser.add_argument("--region", action="append", default=[], help="only these regions (name, any part)")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    settings = load_settings(sample_mode=False)
    plan = regions(settings)
    wanted = [normalize_name(r) for r in args.region]
    results = []
    for number, (region, cuts) in enumerate(plan.items(), 1):
        if wanted and not any(w in normalize_name(region) for w in wanted):
            continue
        run_id = f"national-{args.tag}-{number:02d}-{slug(region)}"[:64].rstrip("-")  # run ids stop at 64 characters
        done = settings.output_dir / run_id / "result.json"
        if done.exists():
            previous = json.loads(done.read_text(encoding="utf-8"))
            if previous.get("status") != "error":
                print(f"[{number:02d}] {title_case(region)}: done earlier ({previous['status']})", flush=True)
                results.append(previous)
                continue
        if results and args.pause:
            time.sleep(args.pause)
        started = time.monotonic()
        run_input = RunInput.model_validate({"run_id": run_id, "fact": args.fact, "scope": {"cuts": cuts},
                                             "options": {"use_llm": args.use_llm}})
        try:
            result = run(run_input, settings, echo=False)
        except RunError as error:
            print(f"[{number:02d}] {title_case(region)}: {error.code} in {error.stage}: {error.message}", flush=True)
            continue
        results.append(result)
        print(f"[{number:02d}] {title_case(region)}: {len(cuts)} comunas, {result['summary']['findings']} findings, "
              f"{result['summary']['drafts']} drafts, {result['status']} in {time.monotonic() - started:.0f} s", flush=True)

    out = settings.output_dir / f"national-{args.tag}"
    out.mkdir(parents=True, exist_ok=True)
    mayor = args.fact == "mayor"
    summary = (summarize_mayors if mayor else summarize)(results, args.tag, args.use_llm)
    text = (markdown_mayors if mayor else markdown)(summary)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "summary.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
