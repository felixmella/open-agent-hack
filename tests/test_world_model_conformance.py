"""The official Meterless World Model conformance suite, ported 1:1 to pytest.

Source: engines/world-model/conformance/runner.ts in github.com/Meterless/Meterless (Apache-2.0). Each test keeps
the check id and the literal inputs and expectations of the TypeScript runner.
"""
from datetime import datetime, timezone

import pytest

from app.engines.world_model import ProvenanceError, WorldModel, decide, entity_id_from_name, normalize_name


def clock():
    return datetime(2026, 5, 18, tzinfo=timezone.utc)


OBSERVATIONS = [
    {"id": "a1", "entity": {"type": "person", "name": "Jerome Powell"}, "source": {"kind": "rss"},
     "title": "Fed holds rates", "at": "2026-05-17T14:00:00.000Z"},
    {"id": "a2", "entity": {"type": "person", "name": "Jerome Powell"}, "source": {"kind": "rss"},
     "title": "Powell signals patience", "at": "2026-05-17T16:30:00.000Z"},
]


def manual(at):
    return {"kind": "manual", "at": at}


def test_sid_001_stable_ids_normalize_diacritics_and_nbsp():
    assert normalize_name("José  García") == normalize_name("Jose Garcia")
    assert entity_id_from_name("person", "José García") == entity_id_from_name("person", "jose garcia")


def test_sid_002_distinct_names_stay_distinct():
    assert entity_id_from_name("org", "Acme Corp") != entity_id_from_name("org", "Acme Corporation")
    assert entity_id_from_name("person", "x") != entity_id_from_name("org", "x")


def test_band_001_merge_bands_at_boundaries():
    assert decide(0.85) == "auto-merge"
    assert decide(0.84) == "review"
    assert decide(0.82) == "review"
    assert decide(0.81) == "new"


def test_prov_001_writes_without_provenance_are_rejected():
    world = WorldModel(storage="memory", namespace="conf")
    with pytest.raises(ProvenanceError):
        world.upsert_entity(type="person", name="No Provenance", source=None)


def test_idem_001_reingesting_the_same_batch_is_a_noop():
    world = WorldModel(storage="memory", namespace="conf", clock=clock)
    world.ingest(OBSERVATIONS)
    shape1 = world.state_shape_canonical()
    second = world.ingest(OBSERVATIONS)
    assert second.changed is False
    assert world.state_shape_canonical() == shape1


def test_idem_002_an_edited_batch_changes_state():
    world = WorldModel(storage="memory", namespace="conf", clock=clock)
    world.ingest(OBSERVATIONS)
    shape1 = world.state_shape_canonical()
    mutated = [{**OBSERVATIONS[0], "title": OBSERVATIONS[0]["title"] + " (edited)"}, OBSERVATIONS[1]]
    run = world.ingest(mutated)
    assert run.changed is True
    assert world.state_shape_canonical() != shape1


def test_bitemp_001_bitemporal_edges_and_point_in_time_queries():
    world = WorldModel(storage="memory", namespace="conf")
    world.upsert_entity(type="player", external_key={"system": "g", "id": "p1"}, attrs={}, source=manual("2087-01-01T00:00:00.000Z"))
    world.upsert_entity(type="team", external_key={"system": "g", "id": "a"}, attrs={}, source=manual("2087-01-01T00:00:00.000Z"))
    world.upsert_entity(type="team", external_key={"system": "g", "id": "b"}, attrs={}, source=manual("2088-03-01T00:00:00.000Z"))
    world.relate(from_id="player:g:p1", type="plays-for", to_id="team:g:a", valid_from="2087-01-01T00:00:00.000Z",
                 source=manual("2087-01-01T00:00:00.000Z"))
    world.relate(from_id="player:g:p1", type="plays-for", to_id="team:g:b", valid_from="2088-03-01T00:00:00.000Z",
                 source=manual("2088-03-01T00:00:00.000Z"))

    now = world.view("graph").neighbors_of("player:g:p1", via="plays-for")
    assert len(now) == 1 and now[0]["id"] == "team:g:b"
    then = world.view("graph").neighbors_of("player:g:p1", via="plays-for", at="2087-06-01T00:00:00.000Z")
    assert len(then) == 1 and then[0]["id"] == "team:g:a"


def test_audit_001_audit_log_is_ordered():
    world = WorldModel(storage="memory", namespace="conf")
    world.upsert_entity(type="x", name="Audit One", source=manual("2026-01-01T00:00:00.000Z"))
    world.upsert_entity(type="x", name="Audit Two", source=manual("2026-01-02T00:00:00.000Z"))
    log = world.audit()
    assert len(log) >= 2
    assert all(later["seq"] > earlier["seq"] for earlier, later in zip(log, log[1:]))
