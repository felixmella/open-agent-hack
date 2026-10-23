"""Meterless World Model engine, implemented in Python for FactSync Chile.

Spec: github.com/Meterless/Meterless/tree/main/engines/world-model. Conformance: the 8 checks of the official
suite (conformance/runner.ts) are ported 1:1 in tests/test_world_model_conformance.py.
"""
from .ids import decide, entity_id_from_key, entity_id_from_name, name_similarity, normalize_name
from .ingest import ProvenanceError
from .resolver import EntityResolver, Resolution
from .world import IngestResult, WorldModel

__all__ = [
    "EntityResolver", "IngestResult", "ProvenanceError", "Resolution", "WorldModel", "decide", "entity_id_from_key",
    "entity_id_from_name", "name_similarity", "normalize_name",
]
