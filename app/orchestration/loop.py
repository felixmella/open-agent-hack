"""One FactSync run: plan the scope, read every source into the World Model, and hand each comuna's context to the
analysis agents. Writes output/<run_id>/result.json, logs/trace-<run_id>.jsonl and logs/world-model-<run_id>.jsonl.
"""
import json
import time
import uuid
from datetime import datetime, timezone

from app.adapters.zetaris import ZetarisClient
from app.agents.planner import Planner
from app.agents.retriever import Retriever
from app.engines.world_model import WorldModel
from app.tracing import Tracer

ARTICLE = "article"


def new_run_id():
    return datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:6]


def open_world(settings):
    return WorldModel(storage="sqlite", namespace="factsync", path=settings.state_dir / "world-factsync.sqlite",
                      strip_suffixes=[", Chile"])


def claims_first(observation):
    """Context priority: official figures, then Wikidata, then Wikipedia claims; article texts are excluded."""
    order = {"official": 0, "wikidata": 1, "wikipedia": 2}
    return order.get(observation["source"].get("kind"), 3), observation["seq"]


def run(run_input, settings, *, echo=True):
    started = time.monotonic()
    run_id = run_input.run_id or new_run_id()
    tracer = Tracer(run_id, settings.logs_dir, echo=echo)
    world = open_world(settings)
    audit_start = (world.audit() or [{"seq": 0}])[-1]["seq"]
    tracer.event("Orchestrator", "start_run", input_summary=run_input.model_dump_json(exclude_none=True),
                 output_summary=f"mode={'sample' if settings.sample_mode else 'live'}", target_agent="Planner")

    zetaris = ZetarisClient(settings.zetaris_rest_url, settings.zetaris_org_id, settings.zetaris_api_key)
    plan = Planner(zetaris, world, tracer).plan(run_input)
    retrieval = Retriever(zetaris, world, tracer, run_id).fetch(plan)

    comunas = []
    for cut, name in plan.comunas.items():
        context = world.context(f"comuna:cut:{cut}", intent="analyze", budget_chars=12_000, rank=claims_first,
                                include=lambda o: o["payload"].get("document") != ARTICLE)
        comunas.append({"cut": cut, "name": name, "context": context})
        tracer.event("WorldModel", "build_context", input_summary=f"comuna:cut:{cut} ({name})",
                     output_summary=context["trace"]["selection_reason"], target_agent="Extractor", engine="world_model")

    audit_path = settings.logs_dir / f"world-model-{run_id}.jsonl"
    exported = world.export_audit(audit_path, since_seq=audit_start)
    result = {
        "run_id": run_id,
        "status": "success",
        "mode": "sample" if settings.sample_mode else "live",
        "plan": {"cuts": plan.cuts, "sources": plan.sources, "reason": plan.reason, "unresolved": plan.unresolved,
                 "reviews": plan.reviews},
        "retrieval": retrieval,
        "comunas": comunas,
        "trace_file": str(tracer.path.relative_to(settings.logs_dir.parent)),
        "world_model_audit_file": str(audit_path.relative_to(settings.logs_dir.parent)),
        "world_model_audit_entries": exported,
        "execution_time_seconds": round(time.monotonic() - started, 1),
    }
    out_dir = settings.output_dir / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tracer.event("Orchestrator", "finish_run", output_summary=f"{len(comunas)} comunas in {result['execution_time_seconds']} s",
                 status="success")
    return result
