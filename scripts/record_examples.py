"""Run example inputs live (Zetaris and Nightshift) and keep each run's evidence in output_examples/<example>/: the
result, the review queue, the agents' trace and the World Model's audit log, as the run wrote them, plus about.json
(the input, the commit the code was at, and when). FactSync never reads output_examples/: it is for readers.

Usage:  .venv\\Scripts\\python scripts\\record_examples.py [input_examples\\example_1.json ...]   (default: all four)
        .venv\\Scripts\\python scripts\\record_examples.py --national 20261024c   (keep a national batch's runs instead)
"""
import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import ROOT, load_settings  # noqa: E402
from app.errors import RunError  # noqa: E402
from app.orchestration.loop import run  # noqa: E402
from app.schemas import RunInput  # noqa: E402

OUT = ROOT / "output_examples"


def commit():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def record(path, settings, compare_with=None):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    run_input = RunInput.model_validate_json(path.read_text(encoding="utf-8"))
    options = run_input.options.model_copy(update={"compare_with": compare_with}) if compare_with else run_input.options
    run_input = run_input.model_copy(update={"run_id": f"{path.stem}-live-{stamp}", "options": options})
    started_at, code = datetime.now(timezone.utc).isoformat(timespec="seconds"), commit()
    try:
        result = run(run_input, settings)
    except RunError as error:
        print(f"{path.name}: failed ({error.code} in {error.stage}): {error.message}", flush=True)
        return None
    target = OUT / path.stem
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    run_id = result["run_id"]
    shutil.copy(settings.output_dir / run_id / "result.json", target / "result.json")
    if result.get("report_file"):
        shutil.copy(ROOT / result["report_file"], target / "report.html")
    shutil.copy(settings.logs_dir / f"trace-{run_id}.jsonl", target / "trace.jsonl")
    shutil.copy(settings.logs_dir / f"world-model-{run_id}.jsonl", target / "world-model-audit.jsonl")
    about = {"input": json.loads(path.read_text(encoding="utf-8")), "input_file": path.relative_to(ROOT).as_posix(),
             "compare_with": compare_with,
             "run_id": run_id, "started_at": started_at, "commit": code, "status": result["status"],
             "summary": result["summary"], "model_usage": result["model_usage"],
             "seconds": result["execution_time_seconds"]}
    (target / "about.json").write_text(json.dumps(about, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{path.name}: {result['status']}, {result['summary']['findings']} findings, "
          f"{result['model_usage']['calls']} model calls, {result['execution_time_seconds']} s -> {target}", flush=True)
    return result


def national(tag, settings):
    """Keep a national batch (scripts/batch_national.py) as it ran: its summary, and each region's result, review queue,
    trace and World Model audit log, in output_examples/national/."""
    target = OUT / "national"
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    batch = settings.output_dir / f"national-{tag}"
    summary = json.loads((batch / "summary.json").read_text(encoding="utf-8"))
    for name in ("summary.json", "summary.md"):
        shutil.copy(batch / name, target / name)
    for region in summary["runs"]:
        folder, run_id = target / region["run_id"], region["run_id"]
        folder.mkdir()
        shutil.copy(settings.output_dir / run_id / "result.json", folder / "result.json")
        shutil.copy(settings.output_dir / run_id / "report.html", folder / "report.html")
        shutil.copy(settings.logs_dir / f"trace-{run_id}.jsonl", folder / "trace.jsonl")
        shutil.copy(settings.logs_dir / f"world-model-{run_id}.jsonl", folder / "world-model-audit.jsonl")
    print(f"national-{tag}: {len(summary['runs'])} regions -> {target}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("inputs", nargs="*", type=Path)
    parser.add_argument("--national", metavar="TAG", help="keep the national batch with this tag instead")
    parser.add_argument("--compare-with", metavar="RUN", help="the runs to compare with for 'since the last check' "
                                                             "(a run-id prefix, e.g. national-20261024c)")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    settings = load_settings(sample_mode=False)
    if args.national:
        national(args.national, settings)
        return
    for path in args.inputs or sorted((ROOT / "input_examples").glob("example_*.json")):
        record(path, settings, args.compare_with)


if __name__ == "__main__":
    main()
