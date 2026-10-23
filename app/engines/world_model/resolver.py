"""Entity resolution. External keys map straight to IDs. Names are compared with every known entity of the same
type (name and aliases) by normalized Levenshtein similarity, then banded: auto-merge, review or new. Merges are
never destructive: a review-band match is reported for a human or a supervising agent to settle."""
import re
from dataclasses import dataclass

from .ids import decide, entity_id_from_key, entity_id_from_name, name_similarity, normalize_name


@dataclass
class Resolution:
    entity_id: str | None
    decision: str  # "exact", "auto-merge", "review" or "new"
    similarity: float
    matched_name: str | None = None


class EntityResolver:
    def __init__(self, store, *, strip_suffixes=()):
        self.store = store
        self.strip_suffixes = [normalize_name(s) for s in strip_suffixes]

    def clean(self, name):
        """Normalize a name and drop disambiguators such as a trailing "(Chile)" or configured suffixes."""
        text = normalize_name(re.sub(r"\s*\([^)]*\)\s*$", "", str(name)))
        for suffix in self.strip_suffixes:
            if text.endswith(suffix):
                text = text[: -len(suffix)].rstrip(" ,")
        return text

    def resolve(self, entity_type, *, name=None, external_key=None):
        if external_key:
            entity_id = entity_id_from_key(entity_type, external_key["system"], external_key["id"])
            return Resolution(entity_id, "exact", 1.0, name)
        exact = entity_id_from_name(entity_type, name)
        if self.store.get_entity(exact):
            return Resolution(exact, "exact", 1.0, name)
        cleaned = self.clean(name)
        target, best, best_name = None, 0.0, None
        for entity in self.store.entities(entity_type):
            for candidate in [entity["name"], *entity["aliases"]]:
                if candidate:
                    score = name_similarity(cleaned, self.clean(candidate))
                    if score > best:
                        target, best, best_name = entity["id"], score, candidate
        decision = decide(best)
        return Resolution(None if decision == "new" else target, decision, round(best, 4), best_name)
