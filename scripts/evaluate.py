"""Measure what the model adds to FactSync's agents.

The same comunas, from the same recorded Zetaris rows, run twice: once with every agent on its deterministic path
(the matcher, sentence patterns, the rule-based Critic, templates, discovery by cues), once with the model (Nemotron
through Nightshift) where the agents use it. Every difference between the two runs is listed with its evidence; each
one is adjudicated in eval/adjudication.json (which run was right, and why), and both runs are scored on those
answers.

Usage:  .venv\\Scripts\\python scripts\\evaluate.py record   needs Zetaris: records eval/snapshot for eval/scope.json
        .venv\\Scripts\\python scripts\\evaluate.py run      needs Nightshift: both runs, into eval/runs/rules and /model
        .venv\\Scripts\\python scripts\\evaluate.py diff     eval/differences.json and .md, and a blank adjudication file
        .venv\\Scripts\\python scripts\\evaluate.py score    eval/results.json and .md, from eval/adjudication.json
"""
import argparse
import dataclasses
import hashlib
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.sample_data import SampleData  # noqa: E402
from app.config import ROOT, load_settings  # noqa: E402
from app.engines.world_model import WorldModel  # noqa: E402
from app.orchestration.loop import run  # noqa: E402
from app.report.html import CLASS_LABELS, title_case  # noqa: E402
from app.schemas import RunInput  # noqa: E402

EVAL = ROOT / "eval"
MODES = ("rules", "model")
PROSE = ("lead", "body", "history_table")
VERDICTS = ("rules", "model", "both", "neither")


def record():
    from snapshot_sample_data import record as snapshot  # the sample-data recorder, pointed at eval/snapshot
    snapshot([EVAL / "scope.json"], EVAL / "snapshot")


def run_both():
    scope = json.loads((EVAL / "scope.json").read_text(encoding="utf-8"))
    for mode in MODES:
        out = EVAL / "runs" / mode
        shutil.rmtree(out, ignore_errors=True)
        settings = dataclasses.replace(load_settings(sample_mode=False), logs_dir=out / "logs", state_dir=out / "state",
                                       output_dir=out / "output")
        run_input = RunInput.model_validate({**scope, "run_id": f"eval-{mode}",
                                             "options": {"use_llm": mode == "model", "max_critic_rounds": 2}})
        world = WorldModel(strip_suffixes=[", Chile"])  # in memory: neither run sees the other's conclusions
        result = run(run_input, settings, zetaris=SampleData(EVAL / "snapshot"), world=world)
        # kept flat in eval/runs/<mode>/ (folders named output/ or logs/ are ignored by git)
        for source, name in ((f"output/eval-{mode}/result.json", "result.json"),
                             (f"output/eval-{mode}/report.html", "report.html"),
                             (f"logs/trace-eval-{mode}.jsonl", "trace.jsonl"),
                             (f"logs/world-model-eval-{mode}.jsonl", "world-model-audit.jsonl")):
            shutil.move(out / source, out / name)
        for folder in ("output", "logs", "state"):
            shutil.rmtree(out / folder, ignore_errors=True)
        print(f"{mode}: {result['status']}, {result['summary']['findings']} findings, "
              f"{result['model_usage']['calls']} model calls, {result['execution_time_seconds']} s")


def result_of(mode):
    return json.loads((EVAL / "runs" / mode / "result.json").read_text(encoding="utf-8"))


def judged(result):
    """Every claim a run judged, keyed by comuna, page, location, figure, year and aspect: its verdict."""
    items = {}
    for comuna in result["comunas"]:
        for item in comuna["findings"] + comuna["checks"]:
            claim, aspect = item["claim"], item.get("aspect", "value")
            key = (comuna["cut"], claim.get("target"), claim.get("location"), claim.get("value"),
                   claim.get("stated_year"), aspect)
            verdict = item.get("class") or f"check: {item['result']}"
            items.setdefault(key, []).append({
                "comuna": title_case(comuna["name"]), "verdict": verdict, "label": claim.get("label"),
                "quote": claim.get("quote"), "basis": claim.get("basis"), "method": claim.get("method"),
                "explanation": item.get("explanation") or item.get("note"), "status": item.get("status"),
                "decided_by": (item.get("model") or {}).get("model_served") if item.get("method") == "llm" else "code",
                "official": comuna["official"]})
    return items


def difference_id(kind, key):
    return "d" + hashlib.sha1(json.dumps([kind, key], default=str).encode("utf-8")).hexdigest()[:8]


def differences():
    """What differs between the two runs: claims only one run kept (extraction), claims judged differently
    (verdict), and what follows from them (other aspects). Plus the discovery choices and the Critic's model flags."""
    rules, model = (judged(result_of(mode)) for mode in MODES)
    found = []
    for key in sorted(set(rules) | set(model), key=lambda k: tuple(str(x) for x in k)):
        cut, target, location, value, year, aspect = key
        a, b = rules.get(key), model.get(key)
        if a and b and sorted(x["verdict"] for x in a) == sorted(x["verdict"] for x in b):
            continue
        if aspect == "value" and location in PROSE and (not a or not b):
            kind = "extraction"
        elif aspect == "value":
            kind = "verdict"
        else:
            kind = "follow-on"
        found.append({"id": difference_id(kind, key), "kind": kind, "cut": cut, "page": target, "location": location,
                      "value": value, "year": year, "aspect": aspect, "rules": a, "model": b})
    flags = []
    for comuna in result_of("model")["comunas"]:
        for finding in comuna["findings"]:
            judged_by = (finding.get("critic") or {}).get("judged_by_model")
            notes = (finding.get("critic") or {}).get("notes") or []
            failures = [f for f in (finding.get("critic") or {}).get("failures") or []
                        if f["check"] in ("class_fit", "explanation")]
            if judged_by and (notes or failures):
                flags.append({"id": difference_id("critic", finding["id"]), "kind": "critic flag",
                              "comuna": title_case(comuna["name"]), "page": finding["target"],
                              "value": finding["claim"].get("value"), "class": finding["class"],
                              "explanation": finding["explanation"],
                              "flag": " ".join(notes + [f["detail"] for f in failures]), "final_status": finding["status"]})
    return found, flags


def summary_of(result):
    usage = result["model_usage"]
    return {"findings": result["summary"]["findings"], "drafts": result["summary"]["drafts"],
            "escalations": result["summary"]["escalations"], "critic_rejections": result["summary"]["critic_rejections"],
            "discoveries": result["summary"]["discoveries"], "model_calls": usage["calls"],
            "fallbacks": usage["fallbacks"], "served_model": usage["served_model"],
            "seconds": result["execution_time_seconds"],
            "draft_reviews_failed": sum(1 for c in result["comunas"] for revision in c["critic"]["draft_reviews"]
                                        for review in revision.values() if not review["approved"])}


def show(entries):
    if not entries:
        return "not kept"
    return "; ".join(f"{CLASS_LABELS.get(e['verdict'], e['verdict'])}" + (f" ({e['decided_by']})" if e["decided_by"]
                                                                            not in (None, "code") else "")
                     for e in entries)


def diff():
    found, flags = differences()
    runs = {mode: summary_of(result_of(mode)) for mode in MODES}
    (EVAL / "differences.json").write_text(json.dumps({"runs": runs, "differences": found, "critic_flags": flags},
                                                      ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    lines = ["# Differences between the rules-only run and the model run", "",
             "Same comunas, same recorded rows (eval/snapshot). Each difference is adjudicated in eval/adjudication.json.",
             "", "| Id | Kind | Comuna | Page · location | Figure | Rules | Model | Evidence |", "|---|---|---|---|---|---|---|---|"]
    for d in found:
        entry = (d["rules"] or d["model"])[0]
        evidence = (entry.get("quote") or entry.get("explanation") or "").replace("|", "/").replace("\n", " ")[:220]
        figure = f"{d['value']:,}" if isinstance(d["value"], int) else "—"
        lines.append(f"| {d['id']} | {d['kind']} | {entry['comuna']} | {d['page']} · {d['location']} | {figure} "
                     f"({entry.get('label')}) | {show(d['rules'])} | {show(d['model'])} | {evidence} |")
    if flags:
        lines += ["", "## The Critic's model flags", "", "| Id | Comuna | Page | Figure | Class | Flag | Final |",
                  "|---|---|---|---|---|---|---|"]
        for f in flags:
            figure = f"{f['value']:,}" if isinstance(f["value"], int) else "—"
            lines.append(f"| {f['id']} | {f['comuna']} | {f['page']} | {figure} | {CLASS_LABELS.get(f['class'], f['class'])} "
                         f"| {f['flag'][:220]} | {f['final_status']} |")
    (EVAL / "differences.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    blank = EVAL / "adjudication.json"
    if not blank.exists():
        blank.write_text(json.dumps({item["id"]: {"correct": None, "note": ""} for item in found + flags},
                                    ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(found)} differences ({dict(Counter(d['kind'] for d in found))}), {len(flags)} Critic flags")


def fields_shown(wikitext, language):
    """The infobox's population fields as the article writes them, parsed from its wikitext (a template-aware parse,
    independent of the SQL that read them)."""
    from app.agents.extractor import INFOBOX_FIELDS
    from app.knowledge.wikitext import infobox_parameters
    params = infobox_parameters(wikitext)
    names = [n for key in ("value", "year", "reference") for n in INFOBOX_FIELDS[language][key]]
    return [f"{name} = {params[name]}" for name in names if params.get(name)] or ["no population field"]


def headline(tag, n=25, seed=2024):
    """A random sample of the national batch's current-figure verdicts (the ones its headline counts), each with its
    raw evidence from the World Model: the infobox's population fields parsed again from the article's wikitext, or
    the item's Wikidata statements. For checking the headline's precision by hand."""
    import random

    sys.path.insert(0, str(ROOT / "scripts"))
    from batch_national import TARGETS, current_figure
    settings = load_settings(sample_mode=False)
    world = WorldModel(storage="sqlite", path=settings.state_dir / "world-factsync.sqlite")
    verdicts = []
    for path in sorted(settings.output_dir.glob(f"national-{tag}-*/result.json")):
        for comuna in json.loads(path.read_text(encoding="utf-8"))["comunas"]:
            for target in TARGETS:
                outcome = current_figure(comuna, target)
                if outcome and outcome != "missing_value":
                    verdicts.append((comuna, target, outcome))
    sample = []
    for comuna, target, outcome in random.Random(seed).sample(verdicts, n):
        page = (comuna.get("picture") or {}).get("pages", {}).get({"es": "eswiki", "en": "enwiki"}.get(target, target), {})
        observations = world.view("observations").for_entity(f"comuna:cut:{comuna['cut']}")
        if target == "wikidata":
            evidence = sorted({(o["payload"].get("value"), o["payload"].get("point_in_time"), o["payload"].get("rank"))
                               for o in observations if o["source"].get("kind") == "wikidata"
                               and o["payload"].get("value") is not None}, key=str)
            evidence = [f"{v} (point in time {t}, {r})" for v, t, r in evidence]
        else:
            article = next((o for o in observations if o["payload"].get("document") == "article"
                            and o["source"].get("revid") == str((page.get("revid") or "")) or
                            (o["payload"].get("document") == "article" and o["source"].get("language") == target)), None)
            evidence = fields_shown(article["payload"]["wikitext"], target) if article else ["article not in the store"]
        sample.append({"id": "h" + hashlib.sha1(f"{comuna['cut']}{target}".encode()).hexdigest()[:8],
                       "comuna": title_case(comuna["name"]), "cut": comuna["cut"], "page": target, "verdict": outcome,
                       "figure": page.get("value"), "label": page.get("label"),
                       "census_2024": comuna["official"]["census"].get("2024"), "evidence": evidence})
    (EVAL / "headline_sample.json").write_text(json.dumps(sample, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# Headline spot check: {n} current-figure verdicts from national batch {tag}", "",
             f"Drawn at random (seed {seed}) from the verdicts the headline counts. Each verdict is checked against the "
             "page's own fields (parsed again from the article's wikitext) or Wikidata's statements, and INE's Census "
             "2024 count; the judgment is in adjudication.json.", "",
             "| Id | Comuna | Page | Verdict | Figure | Census 2024 | Evidence |", "|---|---|---|---|---|---|---|"]
    for s in sample:
        figure = f"{s['figure']:,}" if isinstance(s["figure"], int) else "—"
        lines.append(f"| {s['id']} | {s['comuna']} | {s['page']} | {CLASS_LABELS.get(s['verdict'], s['verdict'])} | "
                     f"{figure} ({s['label']}) | {s['census_2024']:,} | {'; '.join(s['evidence'])[:300].replace('|', '/')} |")
    (EVAL / "headline_sample.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(sample)} verdicts sampled into eval/headline_sample.md")


def score():
    data = json.loads((EVAL / "differences.json").read_text(encoding="utf-8"))
    answers = json.loads((EVAL / "adjudication.json").read_text(encoding="utf-8"))
    tally, findings = {}, Counter()
    for item in data["differences"] + data["critic_flags"]:
        answer = answers.get(item["id"]) or {}
        if answer.get("correct") not in VERDICTS + ("flag right", "flag wrong"):
            raise SystemExit(f"{item['id']} isn't adjudicated yet (eval/adjudication.json)")
        tally.setdefault(item["kind"], Counter())[answer["correct"]] += 1
        sides = [e["verdict"] for mode in MODES for e in item.get(mode) or []]
        if item["kind"] != "critic flag" and any(not v.startswith("check:") for v in sides):
            findings[answer["correct"]] += 1  # a difference in what the reviewer sees, not only in internal checks
    results = {"runs": data["runs"], "adjudicated": {kind: dict(counts) for kind, counts in tally.items()},
               "differences_in_findings": dict(findings)}
    sample = EVAL / "headline_sample.json"
    if sample.exists():
        verdicts = [answers.get(s["id"], {}).get("correct") for s in json.loads(sample.read_text(encoding="utf-8"))]
        results["headline_sample"] = dict(Counter(verdicts))
    (EVAL / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=1))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["record", "run", "diff", "score", "headline"])
    parser.add_argument("--tag", help="headline: the national batch to sample")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.step == "headline":
        headline(args.tag)
        return
    {"record": record, "run": run_both, "diff": diff, "score": score}[args.step]()


if __name__ == "__main__":
    main()
