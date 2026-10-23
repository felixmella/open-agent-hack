"""Read surface: graph neighbours with point-in-time queries, observations per entity, and context payloads.

Consumers read through these views, never the store directly. A context payload is structured data with trace
metadata (why these items, how many were left out), not a pre-rendered prompt.
"""
from datetime import datetime, timezone

from .store import dumps


def parse_time(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class GraphView:
    """Edges carry validity intervals. Edges of one type from one entity form a timeline: each edge is valid until
    the next one starts (or until its own valid_to), unless it was written as multi-valued."""

    def __init__(self, store):
        self.store = store

    def intervals(self, from_id, edge_type=None):
        timelines = {}
        for edge in self.store.edges(from_id, edge_type):
            timelines.setdefault(edge["type"], []).append(edge)
        intervals = []
        for edges in timelines.values():
            single = sorted((e for e in edges if not e["multi"]), key=lambda e: parse_time(e["valid_from"]))
            for i, edge in enumerate(single):
                end = parse_time(edge["valid_to"])
                if i + 1 < len(single):
                    successor = parse_time(single[i + 1]["valid_from"])
                    end = min(end, successor) if end else successor
                intervals.append((edge, parse_time(edge["valid_from"]), end))
            intervals += [(e, parse_time(e["valid_from"]), parse_time(e["valid_to"])) for e in edges if e["multi"]]
        return intervals

    def neighbors_of(self, entity_id, via=None, at=None):
        """Current neighbours (open-ended edges), or the neighbours valid at a moment when `at` is given."""
        moment = parse_time(at)
        neighbours = []
        for edge, start, end in self.intervals(entity_id, via):
            active = end is None if moment is None else start <= moment and (end is None or moment < end)
            if active:
                neighbours.append({"id": edge["to_id"], "via": edge["type"], "valid_from": edge["valid_from"],
                                   "valid_to": end.isoformat() if end else None, "source": edge["source"]})
        return neighbours


class ObservationView:
    def __init__(self, store):
        self.store = store

    def for_entity(self, entity_id, *, kinds=None):
        observations = self.store.observations(entity_id)
        return [o for o in observations if kinds is None or o["source"].get("kind") in kinds]

    def latest_assessments(self, entity_id):
        """The latest assessment of each observation (assessments are append-only; later ones supersede)."""
        latest = {}
        for assessment in self.store.assessments(entity_id=entity_id):
            latest[assessment["observation_id"]] = assessment
        return latest


def build_context(store, entity_id, *, intent, budget_chars=8000, include=None, rank=None):
    entity = store.get_entity(entity_id)
    if entity is None:
        raise KeyError(f"unknown entity {entity_id}")
    candidates = [o for o in store.observations(entity_id) if include is None or include(o)]
    ordered = sorted(candidates, key=rank) if rank else candidates
    selected, used, truncated = [], 0, False
    for observation in ordered:
        size = len(dumps(observation))
        if selected and used + size > budget_chars:
            truncated = True
            break
        selected.append(observation)
        used += size
    latest = ObservationView(store).latest_assessments(entity_id)
    return {
        "entity": {k: entity[k] for k in ("id", "type", "name", "aliases", "attrs")},
        "intent": intent,
        "observations": selected,
        "assessments": [latest[o["id"]] for o in selected if o["id"] in latest],
        "derived": store.get_derived(entity_id),
        "trace": {
            "selection_reason": f"{intent}: {len(selected)} of {len(candidates)} matching observations, in priority order",
            "strategy": "budgeted" if truncated else "complete",
            "selected": len(selected),
            "available": len(candidates),
            "truncated": truncated,
            "budget_chars": budget_chars,
            "used_chars": used,
        },
    }
