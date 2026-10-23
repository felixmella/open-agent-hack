"""Ingest stages. Each observation runs the spec's event path: extract, normalize, resolve, validate, append,
project (resolve, append and project live in WorldModel.ingest). Only append is exactly-once, keyed by a
content-derived observation id, so re-ingesting the same batch is a no-op and an edited one appends.

An observation is a dict with an `entity` (type plus name and/or external_key), a `source` (provenance; at least
its `kind`), optional `provenance` details that don't change what was observed (fetch time, run, SQL), and any
payload fields (the observed content).
"""
import copy
import hashlib

from .store import dumps


class ProvenanceError(ValueError):
    """A write without provenance: a source naming at least its kind is required."""


def extract(raw):
    record = copy.deepcopy(raw)
    return {
        "entity": record.pop("entity", None) or {},
        "source": record.pop("source", None),
        "provenance": record.pop("provenance", None) or {},
        "payload": record,
    }


def normalize(record):
    entity = dict(record["entity"])
    if entity.get("name") is not None:
        entity["name"] = " ".join(str(entity["name"]).replace(" ", " ").split())
    record["entity"] = entity
    record["payload"] = {k: v.strip() if isinstance(v, str) else v for k, v in record["payload"].items()}
    return record


def validate(record):
    source = record["source"]
    if not isinstance(source, dict) or not source.get("kind"):
        raise ProvenanceError("observation without provenance: source.kind is required")
    entity = record["entity"]
    if not entity.get("type") or not (entity.get("name") or entity.get("external_key")):
        raise ValueError("an observation needs an entity type and a name or external key")


def observation_id(entity_id, record):
    content = dumps({"entity_id": entity_id, "source": record["source"], "payload": record["payload"]})
    return "obs_" + hashlib.sha256(content.encode("utf-8")).hexdigest()[:24]
