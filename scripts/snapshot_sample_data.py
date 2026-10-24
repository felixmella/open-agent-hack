"""Record the sample data: the rows the Planner and the Retriever read from the Zetaris views for the example inputs,
so FactSync can run without Zetaris (SAMPLE_MODE=true, or run.py --sample).

Usage:  .venv\\Scripts\\python scripts\\snapshot_sample_data.py [input_examples\\example_1.json ...]   (default: all)

The Planner reads the source catalog and resolves each example's scope; then the Retriever reads every source in the
catalog (the ones read on demand too, so discovery works offline) for all those comunas at once, through a wrapper
that keeps each query's rows exactly as Zetaris returned them. They go to data/sample/<view>.json
with the SQL and the time; data/sample/manifest.json lists the comunas covered. Needs Zetaris (read-only key is
enough); never prints secret values.
"""
import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.zetaris import ZetarisClient  # noqa: E402
from app.agents.planner import Plan, Planner  # noqa: E402
from app.agents.retriever import Retriever  # noqa: E402
from app.config import ROOT, load_settings  # noqa: E402
from app.engines.world_model import WorldModel  # noqa: E402
from app.schemas import RunInput  # noqa: E402
from app.tracing import Tracer, utc_now  # noqa: E402

VIEW = re.compile(r"\bFROM\s+(factsync\.\w+)", re.I)


class Recorder:
    """A Zetaris client that keeps every query's result."""

    def __init__(self, client):
        self.client = client
        self.results = []

    def query(self, sql, *, limit=100_000):
        result = self.client.query(sql, limit=limit)
        self.results.append(result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("inputs", nargs="*", type=Path)
    args = parser.parse_args()
    inputs = args.inputs or sorted((ROOT / "input_examples").glob("example_*.json"))

    settings = load_settings(sample_mode=False)
    recorder = Recorder(ZetarisClient(settings.zetaris_rest_url, settings.zetaris_org_id, settings.zetaris_api_key))
    world = WorldModel(strip_suffixes=[", Chile"])
    with tempfile.TemporaryDirectory() as logs:
        tracer = Tracer("snapshot", logs, echo=False)
        planner = Planner(recorder, world, tracer)
        examples, comunas, catalog = {}, {}, None
        for path in inputs:
            plan = planner.plan(RunInput.model_validate_json(path.read_text(encoding="utf-8")))
            examples[path.name] = plan.cuts
            comunas.update(plan.comunas)
            catalog = plan.catalog
            print(f"{path.name}: {len(plan.cuts)} comunas ({plan.reason})")
        cuts = sorted(comunas)
        everything = Plan(cuts=cuts, comunas={c: comunas[c] for c in cuts}, sources=list(catalog), reason="snapshot",
                          catalog=catalog)
        Retriever(recorder, world, tracer, "snapshot").fetch(everything)

    views = {}
    for result in recorder.results:
        view = VIEW.search(result.sql).group(1).lower()
        recorded = views.setdefault(view, {"view": view, "queries": [], "columns": result.columns, "rows": []})
        if result.sql in recorded["queries"]:
            continue  # the Planner reads the catalog and the comuna list once per example
        recorded["queries"].append(result.sql)
        seen = {json.dumps(r, ensure_ascii=False) for r in recorded["rows"]}
        for row in result.rows:
            values = [row.get(c) for c in recorded["columns"]]
            if json.dumps(values, ensure_ascii=False) not in seen:
                recorded["rows"].append(values)

    out = settings.sample_dir
    out.mkdir(parents=True, exist_ok=True)
    recorded_at = utc_now()
    for view, recorded in sorted(views.items()):
        path = out / f"{view.split('.', 1)[1]}.json"
        path.write_text(json.dumps({**recorded, "recorded_at": recorded_at}, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
        print(f"{path.relative_to(ROOT).as_posix()}: {len(recorded['rows'])} rows, {path.stat().st_size / 1024:,.0f} KB")
    manifest = {"recorded_at": recorded_at, "recorded_by": "scripts/snapshot_sample_data.py",
                "examples": examples, "comunas": {c: comunas[c] for c in cuts},
                "views": {v: f"{v.split('.', 1)[1]}.json" for v in sorted(views)}}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(cuts)} comunas covered; manifest in {(out / 'manifest.json').relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
