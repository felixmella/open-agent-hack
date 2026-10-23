"""The national batch: every comuna, region by region, to measure how far the population figures in Spanish and
English Wikipedia and in Wikidata are from INE's Census 2024 count.

Usage:  .venv\\Scripts\\python scripts\\batch_national.py [--tag 20261025] [--pause 15] [--use-llm] [--region Aysén ...]

Each region is one ordinary run (run_id national-<tag>-<nn>-<region>) with its own result.json, review queue and
trace; a region already finished under the same tag is skipped, so a rerun resumes. By default the agents take
their deterministic paths (no model calls): the whole country through Nightshift would take days. --use-llm turns
the model on, paced and capped by each run's call budget. --pause waits between regions, since every run reads the
Wikipedia views live (Zetaris fetches them from the MediaWiki API).

At the end it writes output/national-<tag>/summary.json and summary.md, computed from the runs' results: for each
source, how many comunas show a current population figure, how many of those are INE's Census 2024 count, and why
the others differ.
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
        outdated = next((f for f in about if f["aspect"] == "currency"), None)
        if outdated:
            return "outdated_vintage"
        statements = [c for c in comuna["checks"] if c["claim"].get("target") == "wikidata"] + about
        return "up to date" if statements else None
    infobox = [f for f in comuna["findings"] if f["target"] == target and f["aspect"] == "value"
               and f["claim"].get("location") == "infobox"]
    if infobox:
        return infobox[0]["class"]
    consistent = [c for c in comuna["checks"] if c["claim"].get("target") == target
                  and c["claim"].get("location") == "infobox" and c["result"] == "consistent"]
    return "up to date" if consistent else None


def summarize(results, tag, use_llm):
    by_target = {t: Counter() for t in TARGETS}
    classes = Counter()
    comunas = 0
    for result in results:
        for comuna in result["comunas"]:
            comunas += 1
            for target in TARGETS:
                outcome = current_figure(comuna, target)
                by_target[target][outcome or "no figure"] += 1
            for finding in comuna["findings"]:
                classes[finding["class"]] += 1
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
                                              key=lambda kv: -kv[1]))}
    figures = sum(s["comunas_with_a_figure"] for s in sources.values())
    differing = sum(s["differs"] for s in sources.values())
    return {"tag": tag, "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "method": "agents with the model (Nightshift)" if use_llm else
                      "agents on their deterministic paths (matcher, rule-based Critic, templates): no model calls",
            "comunas": comunas, "regions": len(results),
            "current_figures": figures, "differing_from_census_2024": differing,
            "share_differing": round(differing / figures, 3) if figures else None,
            "by_source": sources, "findings_by_class": dict(classes.most_common()),
            "runs": [{"run_id": r["run_id"], "status": r["status"], "comunas": r["summary"]["comunas"],
                      "findings": r["summary"]["findings"], "drafts": r["summary"]["drafts"],
                      "report": r.get("report_file")} for r in results]}


def markdown(summary):
    lines = [f"# National batch {summary['tag']}", "",
             f"{summary['comunas']} comunas in {summary['regions']} regions; {summary['method']}.", "",
             f"Of {summary['current_figures']} current population figures shown across the three sources, "
             f"**{summary['differing_from_census_2024']} ({summary['share_differing']:.0%})** are not INE's Census 2024 "
             f"count (correctly labelled).", "",
             "| Source | Comunas with a figure | Census 2024 count | Differs | No figure (Wikidata) | Not read | Why it differs |",
             "|---|---|---|---|---|---|---|"]
    for target, s in summary["by_source"].items():
        why = ", ".join(f"{CLASS_LABELS.get(k, k)} {n}" for k, n in s["why"].items())
        share = f" ({s['share_differing']:.0%})" if s["share_differing"] is not None else ""
        lines.append(f"| {TARGETS[target]} | {s['comunas_with_a_figure']} | {s['census_2024_count']} | "
                     f"{s['differs']}{share} | {s['missing']} | {s['no_page_or_figure']} | {why} |")
    lines += ["", "*Not read:* FactSync reads the Wikipedia article linked from each comuna's Wikidata item (the "
              "`factsync.eswiki_articles` and `enwiki_articles` views). A comuna whose item links no article, often "
              "because the article is attached to the town's item instead, isn't counted; nor is an infobox without a "
              "population figure.", "", "Runs:", ""] + [
        f"- `{r['run_id']}`: {r['status']}, {r['comunas']} comunas, {r['findings']} findings, {r['drafts']} drafts "
        f"({r['report']})" for r in summary["runs"]]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", default=datetime.now(timezone.utc).strftime("%Y%m%d"))
    parser.add_argument("--pause", type=float, default=15.0, help="seconds between regions")
    parser.add_argument("--use-llm", action="store_true", help="let the agents call the model (slow)")
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
        run_id = f"national-{args.tag}-{number:02d}-{slug(region)}"
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
        run_input = RunInput.model_validate({"run_id": run_id, "scope": {"cuts": cuts},
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
    summary = summarize(results, args.tag, args.use_llm)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "summary.md").write_text(markdown(summary), encoding="utf-8")
    print(markdown(summary))


if __name__ == "__main__":
    main()
