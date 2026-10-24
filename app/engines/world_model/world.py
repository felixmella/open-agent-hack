"""The World Model: shared, provenance-stamped world state that every agent reads and writes through.

Canonical entities, an append-only observation log, edges with validity intervals and append-only assessments,
behind one write path (upsert_entity, ingest, relate, assess) and one read surface (view, context, audit).
Derived aggregates are rebuilt from the log, never edited in place, and every mutation lands in an ordered audit log.

Consumers can register projections: functions of an entity's observations and assessments that the engine runs
whenever it rebuilds that entity's derived data (`reproject`), and over the log as it stood at an earlier point
(`project_as_of`): what consuming agents see, and what they saw then. The audit sequence is the log's clock.

Each instance counts the calls to each capability, so a consumer can report which ones it used (`capabilities`).
"""
import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import ingest as stages
from .ids import entity_id_from_key, entity_id_from_name
from .resolver import EntityResolver
from .store import Store, dumps
from .views import GraphView, ObservationView, build_context


@dataclass
class IngestResult:
    changed: bool = False
    appended: list = field(default_factory=list)
    unchanged: list = field(default_factory=list)
    entities_created: list = field(default_factory=list)
    entities_updated: list = field(default_factory=list)
    reviews: list = field(default_factory=list)


def _iso(moment):
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _digest(*parts):
    return hashlib.sha256(dumps(parts).encode("utf-8")).hexdigest()[:24]


# The engine's capabilities, as `capabilities()` reports them, with what each one is.
CAPABILITIES = {
    "upsert_entity": "canonical entities with stable ids (conformance sid-001, sid-002)",
    "ingest": "the append-only observation log: extract, normalize, resolve, validate, append, project (idem-001, "
              "idem-002, prov-001)",
    "resolve_by_name": "entity resolution by name similarity, in bands (band-001)",
    "assess": "append-only assessments, attributed to an agent, a run and a round",
    "context": "budgeted context payloads for agents, with trace metadata",
    "view:observations": "observations and assessments per entity",
    "reproject": "derived data rebuilt from the log by registered projections",
    "project_as_of": "point-in-time reconstruction: the projections over the log as it stood at an earlier point",
    "export_audit": "the ordered audit log, exported (audit-001)",
    "relate": "time-bounded relationships between entities (bitemp-001)",
    "view:graph": "point-in-time graph queries over those relationships (bitemp-001)",
}


def _require_source(source, what):
    if not isinstance(source, dict) or not source.get("kind"):
        raise stages.ProvenanceError(f"{what} without provenance: source.kind is required")


class WorldModel:
    def __init__(self, storage="memory", namespace="world", clock=None, path=None, strip_suffixes=()):
        if storage == "memory":
            connection = sqlite3.connect(":memory:")
        elif storage == "sqlite":
            path = Path(path or Path("state") / f"world-{namespace}.sqlite")
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(path, timeout=60)  # runs from the CLI and the API may share the store
        else:
            raise ValueError(f"unknown storage {storage!r}; use 'memory' or 'sqlite'")
        self.namespace = namespace
        self.store = Store(connection)
        self.resolver = EntityResolver(self.store, strip_suffixes=strip_suffixes)
        self._clock = clock
        self._listeners = []
        self._projections = {}
        self.calls = Counter()

    def now(self):
        return _iso(self._clock() if self._clock else datetime.now(timezone.utc))

    def on_audit(self, callback):
        """Subscribe to audit entries as they are written (used to mirror engine activity into run traces)."""
        self._listeners.append(callback)

    def _audit(self, actor, action, target, details):
        ts = self.now()
        seq = self.store.append_audit(ts, actor, action, target, details)
        entry = {"seq": seq, "ts": ts, "actor": actor, "action": action, "target": target, "details": details}
        for callback in self._listeners:
            callback(entry)
        return entry

    # ----- write path -----------------------------------------------------------------------------------------

    def upsert_entity(self, *, type, name=None, external_key=None, attrs=None, aliases=None, source=None, actor=None):
        self.calls["upsert_entity"] += 1
        _require_source(source, "entity write")
        if external_key:
            entity_id = entity_id_from_key(type, external_key["system"], external_key["id"])
        elif name:
            entity_id = entity_id_from_name(type, name)
        else:
            raise ValueError("an entity needs a name or an external key")
        entity, _ = self._write_entity(entity_id, type, name, external_key, attrs or {}, aliases or [], source,
                                       actor or source["kind"])
        return entity

    def _write_entity(self, entity_id, entity_type, name, external_key, attrs, aliases, source, actor):
        """Create the entity, or merge into it: aliases are a union, atomic attributes are latest-wins."""
        now = self.now()
        existing = self.store.get_entity(entity_id)
        if existing is None:
            entity = {"id": entity_id, "type": entity_type, "name": name, "external_key": external_key,
                      "aliases": sorted({a for a in aliases if a and a != name}), "attrs": dict(attrs),
                      "created_at": now, "updated_at": now}
            self.store.put_entity(entity)
            self._audit(actor, "entity.create", entity_id, {"type": entity_type, "name": name, "source": source})
            return entity, "created"
        canonical_name = existing["name"] or name
        aliases_now = set(existing["aliases"]) | {a for a in [name, *aliases] if a and a != canonical_name}
        attrs_now = {**existing["attrs"], **attrs}
        if canonical_name == existing["name"] and aliases_now == set(existing["aliases"]) and attrs_now == existing["attrs"]:
            return existing, "unchanged"
        entity = {**existing, "name": canonical_name, "aliases": sorted(aliases_now), "attrs": attrs_now,
                  "updated_at": now}
        self.store.put_entity(entity)
        self._audit(actor, "entity.update", entity_id, {"name": canonical_name, "aliases": entity["aliases"],
                                                        "attrs": attrs_now, "source": source})
        return entity, "updated"

    def ingest(self, observations, *, actor="ingest"):
        self.calls["ingest"] += 1
        result = IngestResult()
        touched = set()
        for raw in observations:
            record = stages.normalize(stages.extract(raw))                         # extract, normalize
            spec = record["entity"]
            resolution = self.resolver.resolve(spec.get("type"), name=spec.get("name"),
                                               external_key=spec.get("external_key"))  # resolve
            stages.validate(record)                                                # validate
            if resolution.decision == "review":
                proposal = {"name": spec.get("name"), "candidate": resolution.entity_id,
                            "candidate_name": resolution.matched_name, "similarity": resolution.similarity}
                result.reviews.append(proposal)
                self._audit(actor, "entity.merge_proposal", resolution.entity_id, proposal)
            entity_id = resolution.entity_id if resolution.decision in ("exact", "auto-merge") else \
                entity_id_from_name(spec["type"], spec["name"])
            _, outcome = self._write_entity(entity_id, spec["type"], spec.get("name"), spec.get("external_key"),
                                            {}, [], record["source"], actor)        # merge is idempotent
            if outcome == "created":
                result.entities_created.append(entity_id)
            elif outcome == "updated":
                result.entities_updated.append(entity_id)
            obs_id = stages.observation_id(entity_id, record)
            if self.store.has_observation(obs_id):
                result.unchanged.append(obs_id)
                continue
            self.store.put_observation({                                           # append (exactly once)
                "id": obs_id, "seq": self.store.next_seq("observations"), "entity_id": entity_id,
                "source": record["source"], "payload": record["payload"], "provenance": record["provenance"],
                "observed_at": record["payload"].get("at") or record["provenance"].get("observed_at"),
                "ingested_at": self.now()})
            self._audit(actor, "observation.append", obs_id, {"entity_id": entity_id, "source": record["source"],
                                                              "resolution": resolution.decision})
            result.appended.append(obs_id)
            touched.add(entity_id)
        for entity_id in sorted(touched):                                          # project
            self._project(entity_id)
        self.store.commit()
        result.changed = bool(result.appended or result.entities_created or result.entities_updated)
        return result

    def _project(self, entity_id):
        """Rebuild an entity's derived data from its log: the counts, then every registered projection."""
        observations = self.store.observations(entity_id)
        times = sorted(t for t in (o["observed_at"] for o in observations) if t)
        derived = {
            "observation_count": len(observations),
            "by_source_kind": dict(Counter(o["source"]["kind"] for o in observations)),
            "first_observed_at": times[0] if times else None,
            "last_observed_at": times[-1] if times else None,
        }
        if self._projections:
            assessments = self.store.assessments(entity_id=entity_id)
            derived["projections"] = {name: fn(observations, assessments) for name, fn in self._projections.items()}
        self.store.put_derived(entity_id, derived)

    def register_projection(self, name, fn):
        """Add a projection, `fn(observations, assessments) -> dict` over one entity's log (oldest first). The
        engine runs it whenever it rebuilds that entity's derived data; its result is never edited in place."""
        self._projections[name] = fn

    def reproject(self, entity_id, *, actor="world_model"):
        """Rebuild an entity's derived data now (after assessments, which don't trigger a rebuild by themselves);
        returns it."""
        self.calls["reproject"] += 1
        self._project(entity_id)
        self._audit(actor, "derived.rebuild", entity_id, {"projections": sorted(self._projections)})
        self.store.commit()
        return self.store.get_derived(entity_id)

    def project_as_of(self, entity_id, seq):
        """The registered projections over the entity's log as it stood at audit sequence `seq`: the observations
        and assessments appended by then. Nothing is stored."""
        self.calls["project_as_of"] += 1
        observations = self.store.observations(entity_id)
        assessments = self.store.assessments(entity_id=entity_id)
        written = self.store.written_at([o["id"] for o in observations] + [a["id"] for a in assessments])
        observations = [o for o in observations if written.get(o["id"], 0) <= seq]
        assessments = [a for a in assessments if written.get(a["id"], 0) <= seq]
        return {name: fn(observations, assessments) for name, fn in self._projections.items()}

    def runs(self, entity_id):
        """The runs that assessed an entity, as (run_id, the audit sequence of the run's last assessment of it),
        oldest first."""
        assessments = [a for a in self.store.assessments(entity_id=entity_id) if a["run_id"]]
        written = self.store.written_at([a["id"] for a in assessments])
        last = {}
        for assessment in assessments:
            last[assessment["run_id"]] = max(last.get(assessment["run_id"], 0), written.get(assessment["id"], 0))
        return sorted(last.items(), key=lambda run: run[1])

    def relate(self, *, from_id, type, to_id, valid_from, valid_to=None, source=None, multi=False, actor=None):
        self.calls["relate"] += 1
        _require_source(source, "edge write")
        for entity_id in (from_id, to_id):
            if self.store.get_entity(entity_id) is None:
                raise KeyError(f"unknown entity {entity_id}")
        edge_id = "edge_" + _digest(from_id, type, to_id, valid_from, valid_to, multi)
        if any(e["id"] == edge_id for e in self.store.edges(from_id, type)):
            return next(e for e in self.store.edges(from_id, type) if e["id"] == edge_id)
        edge = {"id": edge_id, "seq": self.store.next_seq("edges"), "from_id": from_id, "type": type, "to_id": to_id,
                "valid_from": valid_from, "valid_to": valid_to, "multi": multi, "source": source,
                "created_at": self.now()}
        self.store.put_edge(edge)
        self._audit(actor or source["kind"], "edge.relate", edge_id,
                    {"from": from_id, "type": type, "to": to_id, "valid_from": valid_from, "valid_to": valid_to})
        self.store.commit()
        return edge

    def assess(self, observation_id, *, agent, data, run_id=None, round_no=None):
        """Append an agent's assessment of an observation; later assessments supersede earlier ones."""
        self.calls["assess"] += 1
        observation = self.store.get_observation(observation_id)
        if observation is None:
            raise KeyError(f"unknown observation {observation_id}")
        seq = self.store.next_seq("assessments")
        assessment = {"id": "asm_" + _digest(observation_id, agent, run_id, round_no, data, seq), "seq": seq,
                      "observation_id": observation_id, "entity_id": observation["entity_id"], "agent": agent,
                      "run_id": run_id, "round": round_no, "data": data, "created_at": self.now()}
        self.store.put_assessment(assessment)
        self._audit(agent, "assessment.add", assessment["id"],
                    {"observation_id": observation_id, "class": data.get("class"), "status": data.get("status")})
        self.store.commit()
        return assessment

    # ----- read surface ---------------------------------------------------------------------------------------

    def view(self, name):
        views = {"graph": GraphView, "observations": ObservationView}
        if name not in views:
            raise KeyError(f"unknown view {name!r}; available: {sorted(views)}")
        self.calls[f"view:{name}"] += 1
        return views[name](self.store)

    def entity(self, entity_id):
        return self.store.get_entity(entity_id)

    def entities(self, entity_type=None):
        return self.store.entities(entity_type)

    def context(self, entity_id, *, intent, budget_chars=8000, include=None, rank=None):
        self.calls["context"] += 1
        return build_context(self.store, entity_id, intent=intent, budget_chars=budget_chars, include=include,
                             rank=rank)

    def audit(self, since_seq=0):
        return self.store.audit(since_seq)

    def export_audit(self, path, since_seq=0):
        """Write the audit entries after `since_seq` to a JSONL file (replacing it); returns how many."""
        self.calls["export_audit"] += 1
        entries = self.audit(since_seq)
        with Path(path).open("w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        return len(entries)

    def capabilities(self):
        """Which capabilities this instance has used, with how often, and which it hasn't (dormant), counted from
        its calls. Name resolutions are counted by the resolver."""
        calls = {**self.calls, "resolve_by_name": self.resolver.calls}
        return {"live": {name: calls[name] for name in CAPABILITIES if calls.get(name)},
                "dormant": {name: what for name, what in CAPABILITIES.items() if not calls.get(name)}}

    def state_shape_canonical(self):
        """A canonical serialisation of the world's content (no timestamps), for idempotency checks."""
        return dumps({
            "entities": [{k: e[k] for k in ("id", "type", "name", "external_key", "aliases", "attrs")}
                         for e in self.store.entities()],
            "observations": sorted(({k: o[k] for k in ("id", "entity_id", "source", "payload")}
                                    for o in self.store.observations()), key=lambda o: o["id"]),
            "edges": sorted(({k: e[k] for k in ("id", "from_id", "type", "to_id", "valid_from", "valid_to", "multi")}
                             for e in self.store.edges()), key=lambda e: e["id"]),
            "assessments": [{k: a[k] for k in ("observation_id", "agent", "data")} for a in self.store.assessments()],
        })
