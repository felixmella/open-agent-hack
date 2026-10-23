"""One FactSync run, as an explicit state machine:

  plan -> retrieve -> extract -> [analyse -> critique -> route the fix]* -> draft -> critique drafts -> output

Each round, the Analyst assesses every comuna still pending and the Critic scores its findings. A comuna whose
findings all pass is approved. Otherwise the Critic's one fix is routed to the agent responsible: the Planner adds a
source (discovery, and the Retriever reads it), the Extractor re-reads an article, or the Analyst picks the fix up
from the World Model next round. After `max_critic_rounds` fixes, findings that still fail are escalated to a human,
and the comuna's approved findings go on to the Editor.

Writes output/<run_id>/result.json, logs/trace-<run_id>.jsonl and logs/world-model-<run_id>.jsonl. A run that can't
complete (the scope matches no comuna, Zetaris can't be read, a bug) raises RunError with a code, the stage and whether
retrying can help, after tracing it and writing an error result.
"""
import json
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from app.adapters.meterless import LLMError, NightshiftClient
from app.adapters.zetaris import ZetarisClient, ZetarisError
from app.agents.analyst import Analyst, claims_first
from app.agents.critic import Critic, signature
from app.agents.editor import Editor
from app.agents.extractor import Extractor
from app.agents.llm import AgentLLM
from app.agents.planner import Planner, ScopeError
from app.agents.retriever import Retriever
from app.engines.world_model import WorldModel
from app.errors import RunError
from app.knowledge import matcher
from app.orchestration.state import Caps, ComunaState, RunState
from app.tracing import Tracer

TARGETS = ("eswiki", "enwiki", "wikidata")
ZETARIS_STATUS = {"zetaris_not_configured": 503, "zetaris_unreachable": 503, "not_in_sample": 422}  # others: 502


def new_run_id():
    return datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:6]


def mode_of(settings):
    return "sample" if settings.sample_mode else "live"


def relative(path, settings):
    return path.relative_to(settings.logs_dir.parent).as_posix()


def write_result(settings, result):
    out_dir = settings.output_dir / result["run_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


@contextmanager
def stage(name):
    """Run one stage of the run; anything that stops it becomes a RunError naming the stage."""
    try:
        yield
    except RunError:
        raise
    except ScopeError as exc:
        raise RunError("scope_unresolved", str(exc), stage=name, recoverable=False, status=422) from exc
    except ZetarisError as exc:
        raise RunError(exc.code, str(exc), stage=name, recoverable=exc.recoverable,
                       status=ZETARIS_STATUS.get(exc.code, 502)) from exc
    except Exception as exc:
        raise RunError("internal_error", f"{type(exc).__name__}: {exc}", stage=name, recoverable=False) from exc


def open_world(settings):
    return WorldModel(storage="sqlite", namespace="factsync", path=settings.state_dir / "world-factsync.sqlite",
                      strip_suffixes=[", Chile"])


def nightshift(settings, tracer):
    try:
        return NightshiftClient(settings.meterless_base_url, settings.meterless_runtime_token, settings.meterless_model)
    except LLMError as exc:
        tracer.event("Orchestrator", "connect_model", status="fallback",
                     output_summary=f"{exc}; every agent takes its deterministic path")
        return None


def run(run_input, settings, *, echo=True, zetaris=None, llm_client=None, world=None, today=None, llm_interval=1.0):
    """Run FactSync on a scope. Returns the result, also written to output/<run_id>/result.json; raises RunError
    when the run can't complete."""
    started = time.monotonic()
    run_id = run_input.run_id or new_run_id()
    tracer = Tracer(run_id, settings.logs_dir, echo=echo)
    tracer.event("Orchestrator", "start_run", input_summary=run_input.model_dump_json(exclude_none=True),
                 output_summary=f"mode={mode_of(settings)}", target_agent="Planner")
    try:
        return execute(run_id, run_input, settings, tracer, started, zetaris=zetaris, llm_client=llm_client,
                       world=world, today=today, llm_interval=llm_interval)
    except Exception as exc:
        error = exc if isinstance(exc, RunError) else RunError(
            "internal_error", f"{type(exc).__name__}: {exc}", stage="run", recoverable=False)
        error.result = {"run_id": run_id, "status": "error", "mode": mode_of(settings), "error": error.to_dict(),
                        "trace_file": relative(tracer.path, settings),
                        "execution_time_seconds": round(time.monotonic() - started, 1)}
        write_result(settings, error.result)
        tracer.event("Orchestrator", "finish_run", status="error",
                     output_summary=f"{error.code} in {error.stage}: {error.message}"[:300])
        if error is exc:
            raise
        raise error from exc


def execute(run_id, run_input, settings, tracer, started, *, zetaris, llm_client, world, today, llm_interval):
    with stage("setup"):
        world = world or open_world(settings)
        audit_start = (world.audit() or [{"seq": 0}])[-1]["seq"]
        zetaris = zetaris or ZetarisClient(settings.zetaris_rest_url, settings.zetaris_org_id, settings.zetaris_api_key)
        if llm_client is None and run_input.options.use_llm and not settings.sample_mode:
            llm_client = nightshift(settings, tracer)
    with stage("plan"):
        planner = Planner(zetaris, world, tracer)
        plan = planner.plan(run_input)
    state = RunState(run_id, Caps.for_run(run_input.options, len(plan.cuts)),
                     {cut: ComunaState(cut, name) for cut, name in plan.comunas.items()})
    llm = AgentLLM(llm_client if run_input.options.use_llm else None, tracer, max_calls=state.caps.max_llm_calls,
                   min_interval=llm_interval)
    planner.llm = llm
    retriever = Retriever(zetaris, world, tracer, run_id, observed=state.observed)
    extractor = Extractor(world, tracer, llm, run_id)
    analyst = Analyst(world, tracer, llm, run_id)
    critic = Critic(world, tracer, llm, run_id)
    editor = Editor(world, tracer, llm, run_id, today=today)
    for review in plan.reviews:
        state.escalations.append({"kind": "entity_resolution", "reason": "name matched a comuna only in the review band",
                                  **review})

    with stage("retrieve"):
        retrieval = retriever.fetch(plan)
    with stage("extract"):
        for comuna in state.comunas.values():
            extractor.extract(comuna, state.observed)

    with stage("analyze"):
        for round_no in range(1, state.caps.max_critic_rounds + 2):
            pending = state.pending()
            if not pending:
                break
            tracer.event("Orchestrator", "start_round", round_no=round_no, target_agent="Analyst",
                         output_summary=f"round {round_no}: {len(pending)} comuna(s) pending: {', '.join(c.name for c in pending)}")
            fixes = {}
            for comuna in pending:
                try:
                    comuna.findings, comuna.checks = analyst.analyze(comuna, state.observed, round_no, plan.sources)
                except LookupError as exc:
                    fail_comuna(state, comuna, tracer, str(exc), round_no)
                    continue
                review = critic.review(comuna, comuna.findings, state.observed, round_no, planner.open_sources(plan, state))
                if review["approved"]:
                    comuna.status = "approved"
                elif round_no > state.caps.max_critic_rounds:
                    escalate(state, comuna, world, tracer, review, round_no, run_id)
                else:
                    fixes[comuna.cut] = review["fix"]
            route(fixes, state, plan, planner, retriever, extractor, tracer, round_no, retrieval)

    with stage("draft"):
        for comuna in state.comunas.values():
            approved = [f for f in comuna.findings if (comuna.approved.get(f["id"]) or {}).get("signature") == signature(f)]
            if approved:
                write_drafts(comuna, approved, state, world, editor, critic, tracer, run_id)

    with stage("output"):
        return finish(run_id, settings, tracer, started, world, audit_start, state, plan, retrieval, llm)


def finish(run_id, settings, tracer, started, world, audit_start, state, plan, retrieval, llm):
    audit_path = settings.logs_dir / f"world-model-{run_id}.jsonl"
    exported = world.export_audit(audit_path, since_seq=audit_start)
    comunas = [comuna_result(c, world, state) for c in state.comunas.values()]
    findings = [f for c in comunas for f in c["findings"]]
    by_class = {}
    for finding in findings:
        by_class[finding["class"]] = by_class.get(finding["class"], 0) + 1
    result = {
        "run_id": run_id,
        "status": "success" if not (state.errors or state.escalations) else "partial",
        "mode": mode_of(settings),
        "summary": {
            "comunas": len(comunas), "claims": sum(c["claims_checked"] for c in comunas), "findings": len(findings),
            "findings_by_class": dict(sorted(by_class.items())),
            "drafts": sum(len([k for k in c["drafts"] if k in TARGETS]) for c in comunas),
            "escalations": len(state.escalations),
            "critic_rejections": sum(1 for c in state.comunas.values() for r in c.reviews if not r["approved"]),
            "discoveries": [d["source"] for d in state.discoveries],
        },
        "plan": {"cuts": plan.cuts, "sources": plan.sources, "reason": plan.reason, "unresolved": plan.unresolved,
                 "reviews": plan.reviews},
        "retrieval": {k: {kk: vv for kk, vv in v.items() if kk != "reviews"} | {"reviews": len(v["reviews"])}
                      for k, v in retrieval.items()},
        "discoveries": state.discoveries,
        "comunas": comunas,
        "escalations": state.escalations,
        "errors": state.errors,
        "model_usage": llm.usage(),
        "trace_file": relative(tracer.path, settings),
        "world_model_audit_file": relative(audit_path, settings),
        "world_model_audit_entries": exported,
        "execution_time_seconds": round(time.monotonic() - started, 1),
    }
    write_result(settings, result)
    tracer.event("Orchestrator", "finish_run", status=result["status"],
                 output_summary=f"{len(comunas)} comunas, {len(findings)} findings, {result['summary']['drafts']} drafts, "
                                f"{len(state.escalations)} escalations in {result['execution_time_seconds']} s")
    return result


def route(fixes, state, plan, planner, retriever, extractor, tracer, round_no, retrieval):
    """Send each comuna's fix to the agent responsible. Discovery requests are pooled: one new source serves them all."""
    for fix in fixes.values():
        tracer.event("Orchestrator", "route_fix", input_summary=f"{fix['comuna']}: {fix['check']}",
                     output_summary=fix["instruction"][:200], target_agent=fix["target_agent"], round_no=round_no)
    requests = [{"comuna": f["comuna"], "value": x["value"], "source": x["source"], "label": x["label"],
                 "classified_as": x["class"]} for f in fixes.values() if f["target_agent"] == "Planner"
                for x in f["figures"]]
    if requests:
        source = planner.discover(plan, requests, state, round_no)
        if source:
            try:
                retrieval.update(retriever.fetch(plan, [source]))
            except ZetarisError as exc:
                state.declined[source] = f"could not be read: {exc}"
                state.errors.append({"code": exc.code, "message": str(exc)[:300], "stage": "retrieve",
                                     "recoverable": exc.recoverable, "source": source})
                tracer.event("Retriever", "query_zetaris", status="failure", round_no=round_no,
                             output_summary=f"{source}: {str(exc)[:200]}")
    for cut, fix in fixes.items():
        if fix["target_agent"] == "Extractor":
            extractor.extract(state.comunas[cut], state.observed, round_no=round_no, instruction=fix["instruction"])


def escalate(state, comuna, world, tracer, review, round_no, run_id):
    """After the last round: what still fails goes to a human, with the Critic's last word on it."""
    approved_any = False
    for finding in comuna.findings:
        result = review["results"][finding["id"]]
        if result["approved"]:
            approved_any = True
            continue
        reason = "; ".join(f["detail"] for f in result["failures"]) or f"scored {result['score']}/9"
        entry = {"kind": "finding", "cut": comuna.cut, "comuna": comuna.name, "finding_id": finding["id"],
                 "class": finding["class"], "target": finding["target"], "score": result["score"],
                 "reason": reason, "round": round_no}
        comuna.escalations.append(entry)
        state.escalations.append(entry)
        world.assess(finding["claim"]["id"], agent="Orchestrator", run_id=run_id, round_no=round_no,
                     data={"finding_id": finding["id"], "status": "escalated", "reason": reason})
    comuna.status = "partial" if approved_any else "escalated"
    tracer.event("Orchestrator", "escalate", round_no=round_no, status="escalated", target_agent="human",
                 input_summary=f"{comuna.name}: Critic rounds used up ({state.caps.max_critic_rounds})",
                 output_summary=f"{len(comuna.escalations)} finding(s) escalated to a human reviewer")


def fail_comuna(state, comuna, tracer, message, round_no):
    comuna.status = "escalated"
    entry = {"kind": "comuna", "cut": comuna.cut, "comuna": comuna.name, "reason": message, "round": round_no}
    comuna.escalations.append(entry)
    state.escalations.append(entry)
    state.errors.append({"code": "no_official_figures", "message": message, "stage": "analyze", "recoverable": True,
                         "cut": comuna.cut})
    tracer.event("Orchestrator", "escalate", round_no=round_no, status="failure", target_agent="human",
                 output_summary=f"{comuna.name}: {message}")


def write_drafts(comuna, approved, state, world, editor, critic, tracer, run_id):
    """Draft, have the Critic review each draft, allow one revision, escalate what still fails."""
    observations = [o for o in world.view("observations").for_entity(comuna.entity_id) if o["id"] in state.observed]
    table = matcher.official_table(observations)
    evidence = [e for f in approved for e in f["evidence"]]
    drafts = editor.draft(comuna, approved, table, round_no=1)
    for revision in range(state.caps.max_draft_revisions + 1):
        reviews = {key: critic.review_draft(comuna, key, drafts[key], drafts.get("explanation", ""), evidence, table,
                                            revision + 1) for key in TARGETS if key in drafts}
        comuna.draft_reviews.append(reviews)
        failed = {key: r for key, r in reviews.items() if not r["approved"]}
        if not failed:
            break
        if revision == state.caps.max_draft_revisions:
            for key, review in failed.items():
                drafts[key]["status"] = "escalated"
                entry = {"kind": "draft", "cut": comuna.cut, "comuna": comuna.name, "draft": key,
                         "score": review["score"], "reason": review["instruction"]}
                comuna.escalations.append(entry)
                state.escalations.append(entry)
            tracer.event("Orchestrator", "escalate", status="escalated", target_agent="human",
                         output_summary=f"{comuna.name}: draft(s) {', '.join(failed)} still fail after a revision")
            break
        instruction = " ".join(f"{key}: {r['instruction']}" for key, r in failed.items())
        tracer.event("Orchestrator", "route_fix", target_agent="Editor", round_no=revision + 1,
                     input_summary=f"{comuna.name}: draft review", output_summary=instruction[:200])
        drafts = editor.draft(comuna, approved, table, round_no=revision + 2, instruction=instruction)
    for key in TARGETS:
        if key in drafts:
            drafts[key].setdefault("status", "approved")
    comuna.drafts = drafts


def comuna_result(comuna, world, state):
    observations = [o for o in world.view("observations").for_entity(comuna.entity_id) if o["id"] in state.observed]
    table = matcher.official_table(sorted(observations, key=claims_first))
    last = comuna.reviews[-1]["results"] if comuna.reviews else {}
    findings = []
    for finding in comuna.findings:
        result = last.get(finding["id"], {})
        rounds = [r["round"] for r in comuna.reviews if finding["id"] in r["results"]]
        status = "approved" if result.get("approved") else \
            "escalated" if any(e.get("finding_id") == finding["id"] for e in comuna.escalations) else "pending"
        findings.append({**{k: finding[k] for k in ("id", "target", "aspect", "class", "explanation", "confidence",
                                                     "method", "claim", "evidence", "proposal")},
                         "status": status,
                         "critic": {"score": result.get("score"), "criteria": result.get("criteria"),
                                    "rounds": len(rounds), "failures": result.get("failures", []),
                                    "notes": result.get("notes", [])}})
    return {
        "cut": comuna.cut, "name": comuna.name, "status": comuna.status,
        "official": {d: {y: r["value"] for y, r in sorted(t.items()) if d == "census" or y in (2017, 2020, 2024)}
                     for d, t in table.items() if t},
        "claims_checked": len({f["claim"]["id"] for f in comuna.findings} | {c["claim"]["id"] for c in comuna.checks}),
        "findings": findings,
        "checks": comuna.checks,
        "critic": {"rounds": len(comuna.reviews),
                   "history": [{"round": r["round"], "approved": r["approved"], "rejected": r["rejected"],
                                "fix": r["fix"]} for r in comuna.reviews],
                   "draft_reviews": comuna.draft_reviews},
        "drafts": comuna.drafts,
        "escalations": comuna.escalations,
    }
