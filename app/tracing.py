"""Run traces: one JSON object per event in logs/trace-<run_id>.jsonl, plus a readable line on stdout.

Traces record what actually happened: which agent acted, on whom, with which SQL or which model (as served by
Nightshift), and how it ended. They are evidence, so nothing here is ever synthesised after the fact.
"""
import json
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Tracer:
    def __init__(self, run_id, logs_dir, *, echo=True):
        self.run_id = run_id
        self.path = Path(logs_dir) / f"trace-{run_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")  # a run that reuses a run_id replaces that run's trace
        self.echo = echo
        self.events = []

    def event(self, agent, action, *, input_summary="", output_summary="", target_agent=None, status="success",
              confidence=None, retry_count=0, round_no=None, llm=None, sql=None, rows=None, latency_ms=None, **extra):
        record = {
            "timestamp": utc_now(),
            "run_id": self.run_id,
            "trace_id": self.run_id,
            "agent_name": agent,
            "action": action,
            "input_summary": input_summary,
            "output_summary": output_summary,
            "target_agent": target_agent,
            "model": llm.model_served if llm else None,
            "model_requested": llm.model_requested if llm else None,
            "routed_model": llm.routed_model if llm else None,
            "receipt_id": llm.receipt_id if llm else None,
            "receipt_requested_model": getattr(llm, "receipt_requested_model", None),
            "provider_model": getattr(llm, "provider_model", None),
            "winning_route": getattr(llm, "winning_route", None),
            "confidence": confidence,
            "retry_count": retry_count,
            "round": round_no,
            "status": status,
            "latency_ms": latency_ms if latency_ms is not None else (llm.latency_ms if llm else None),
        }
        if sql is not None:
            record["sql"] = sql
            record["rows"] = rows
        record.update(extra)
        self.events.append(record)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        if self.echo:
            model = f"  [model: {llm.model_served}]" if llm else ""
            target = f" -> {target_agent}" if target_agent else ""
            print(f"[{record['timestamp'][11:19]}] {agent}: {action}{target} ({status}) {output_summary[:120]}{model}",
                  flush=True)
        return record
