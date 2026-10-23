"""FactSync Chile command-line entry point.

Usage:  .venv\\Scripts\\python run.py input_examples\\example_1.json [--sample]

Prints the run's progress and summary; writes output/<run_id>/result.json and the traces in logs/.
"""
import argparse
import json
import sys
from pathlib import Path

from app.config import load_settings
from app.orchestration.loop import run
from app.schemas import RunInput


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", type=Path, help="a run input JSON file, e.g. input_examples/example_1.json")
    parser.add_argument("--sample", action="store_true", help="run on recorded sample data, without live services")
    args = parser.parse_args()

    settings = load_settings(sample_mode=True if args.sample else None)
    run_input = RunInput.model_validate_json(args.input.read_text(encoding="utf-8"))
    result = run(run_input, settings)
    summary = {k: result[k] for k in ("run_id", "status", "mode", "plan", "execution_time_seconds", "trace_file",
                                      "world_model_audit_file")}
    summary["comunas"] = [{"cut": c["cut"], "name": c["name"], "context_trace": c["context"]["trace"]}
                          for c in result["comunas"]]
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
