"""Stable identities and merge decisions.

World Model spec: external-keyed entities are `type:system:externalId`; name-keyed entities are `ent_` plus the
first 16 hex characters of SHA-256 over `type:normalizeName(name)`, so independent writers agree on an entity's
identity without coordinating. Same-type names merge by normalized Levenshtein similarity, in bands.
"""
import hashlib
import re
import unicodedata

AUTO_MERGE = 0.85
REVIEW = 0.82


def normalize_name(name):
    """Lowercase, strip diacritics, turn non-breaking spaces into spaces and collapse whitespace."""
    text = unicodedata.normalize("NFKD", str(name).replace(" ", " "))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().lower()


def entity_id_from_name(entity_type, name):
    digest = hashlib.sha256(f"{entity_type}:{normalize_name(name)}".encode("utf-8")).hexdigest()
    return f"ent_{digest[:16]}"


def entity_id_from_key(entity_type, system, external_id):
    return f"{entity_type}:{system}:{external_id}"


def levenshtein(a, b):
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def name_similarity(a, b):
    a, b = normalize_name(a), normalize_name(b)
    if not a and not b:
        return 1.0
    return 1 - levenshtein(a, b) / max(len(a), len(b))


def decide(similarity):
    """Merge band for a name similarity: inclusive lower bounds at 0.85 (auto-merge) and 0.82 (review)."""
    if similarity >= AUTO_MERGE:
        return "auto-merge"
    if similarity >= REVIEW:
        return "review"
    return "new"
