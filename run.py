"""FactSync Chile command-line entry point.

Usage:  .venv\\Scripts\\python run.py input_examples\\example_1.json [--sample]

Prints the run's progress and summary; writes output/<run_id>/result.json and the traces in logs/. A run that can't
complete prints a structured error ({"status": "error", "error": {code, message, stage, recoverable}}) and exits with
1, or with 2 when the input itself is the problem.
"""
import argparse
import json
import sys
import traceback
from pathlib import Path

from pydantic import ValidationError

from app.config import load_settings
from app.errors import RunError, error_body, invalid_input
from app.orchestration.loop import run
from app.schemas import RunInput


def fail(error, run_id=None, exit_code=1):
    print(json.dumps(error_body(error, run_id), ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", type=Path, help="a run input JSON file, e.g. input_examples/example_1.json")
    parser.add_argument("--sample", action="store_true", help="run on recorded sample data, without live services")
    args = parser.parse_args()

    settings = load_settings(sample_mode=True if args.sample else None)
    try:
        run_input = RunInput.model_validate_json(args.input.read_text(encoding="utf-8"))
    except OSError as exc:
        fail(RunError("invalid_input", f"can't read {args.input}: {exc.strerror or exc}", stage="input",
                      recoverable=False, status=400), exit_code=2)
    except ValidationError as exc:
        fail(invalid_input(exc), exit_code=2)
    try:
        result = run(run_input, settings)
    except RunError as error:
        if error.code == "internal_error":
            traceback.print_exc()
        fail(error, run_id=(error.result or {}).get("run_id"))
    summary = {k: result[k] for k in ("run_id", "status", "mode", "summary", "model_usage", "execution_time_seconds",
                                      "trace_file", "world_model_audit_file")}
    summary["comunas"] = [{
        "cut": c["cut"], "name": c["name"], "status": c["status"], "critic_rounds": c["critic"]["rounds"],
        "findings": [f"{f['target']} {f['claim'].get('location')} {f['claim'].get('value')}: {f['class']} "
                     f"({f['status']}, {f['critic']['score']}/9)" for f in c["findings"]],
        "drafts": {k: v.get("status") for k, v in c["drafts"].items() if isinstance(v, dict) and "target" in v},
    } for c in result["comunas"]]
    summary["output"] = f"output/{result['run_id']}/result.json"
    summary["report"] = result["report_file"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
