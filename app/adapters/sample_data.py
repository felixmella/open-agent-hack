"""Sample data: rows of the Zetaris views, recorded by scripts/snapshot_sample_data.py for the example scopes, and
served through the Zetaris client's query interface. FactSync reads them in sample mode (no Zetaris, no network),
and when a live Zetaris query fails in a way a retry could fix (a fallback the run escalates).

It answers the agents' own queries only: SELECT <columns> FROM factsync.<view> [WHERE series = '...' AND]
[cut IN (...)] [OR cut IS NULL], for comunas the snapshot covers, and the source catalog. Anything else is an error,
never a guess.
"""
import json
import re
import time
from pathlib import Path

from app.adapters.zetaris import QueryResult, ZetarisError

QUERY = re.compile(r"^SELECT\s+(?P<columns>.+?)\s+FROM\s+(?P<view>factsync\.\w+)(?:\s+WHERE\s+(?P<where>.+))?$",
                   re.I | re.S)
CONDITIONS = re.compile(r"series\s*=\s*'\w+'|cut\s+IN\s*\([^)]*\)|cut\s+IS\s+NULL|\b(?:AND|OR)\b|\s+", re.I)


class SampleData:
    def __init__(self, directory):
        self.directory = Path(directory)
        manifest = self.directory / "manifest.json"
        if not manifest.exists():
            raise ZetarisError(f"no sample data in {self.directory}: record it with scripts/snapshot_sample_data.py",
                               recoverable=False, code="sample_data_missing")
        self.manifest = json.loads(manifest.read_text(encoding="utf-8"))
        self.recorded_at = self.manifest["recorded_at"]
        self.comunas = self.manifest["comunas"]  # cut -> INE name, for every comuna the snapshot covers
        self.origin = f"sample snapshot recorded {self.recorded_at[:10]}"
        self._views = {}

    def view(self, name):
        if name not in self._views:
            path = self.directory / f"{name.split('.', 1)[1]}.json"
            if not path.exists():
                raise ZetarisError(f"the sample data has no rows for {name}", recoverable=False, code="not_in_sample")
            self._views[name] = json.loads(path.read_text(encoding="utf-8"))
        return self._views[name]

    def query(self, sql, *, limit=100_000):
        started = time.monotonic()
        statement = " ".join(sql.split()).rstrip(";").strip()
        match = QUERY.match(statement)
        where = (match.group("where") or "") if match else ""
        if not match or CONDITIONS.sub("", where):
            raise ZetarisError(f"the sample data can't answer this query: {statement[:160]}", recoverable=False,
                               code="not_in_sample")
        recorded = self.view(match.group("view").lower())
        columns = [c.strip() for c in match.group("columns").split(",")]
        missing = [c for c in columns if c not in recorded["columns"]]
        if missing:
            raise ZetarisError(f"the sample data has no column {', '.join(missing)} in {match.group('view')}",
                               recoverable=False, code="not_in_sample")
        series = re.search(r"series\s*=\s*'(\w+)'", where, re.I)
        listed = re.search(r"cut\s+IN\s*\(([^)]*)\)", where, re.I)
        cuts = set(re.findall(r"'([^']*)'", listed.group(1))) if listed else None
        if cuts is not None and cuts - set(self.comunas):
            outside = ", ".join(sorted(cuts - set(self.comunas))[:10])
            raise ZetarisError(f"the sample data covers the example comunas only ({len(self.comunas)}: "
                               f"{', '.join(sorted(self.comunas.values()))}); not covered: {outside}",
                               recoverable=False, code="not_in_sample")
        with_null = bool(re.search(r"cut\s+IS\s+NULL", where, re.I))
        rows = []
        for values in recorded["rows"]:
            row = dict(zip(recorded["columns"], values))
            if series and row.get("series") != series.group(1):
                continue
            if cuts is not None and not (row.get("cut") in cuts or (with_null and row.get("cut") is None)):
                continue
            rows.append({c: row[c] for c in columns})
        rows = rows[:limit]
        return QueryResult(statement, columns, rows, len(rows), int((time.monotonic() - started) * 1000), 1,
                           origin=self.origin)


class FallbackZetaris:
    """Zetaris first. When a query fails in a way a retry could fix (unreachable, a server error), the sample
    snapshot answers it if it covers it, and `on_fallback(result, error)` is told, so the run can trace and
    escalate it. Other failures, and queries the snapshot can't answer, raise the original error."""

    def __init__(self, live, sample, on_fallback):
        self.live = live
        self.sample = sample
        self.on_fallback = on_fallback

    def query(self, sql, *, limit=100_000):
        try:
            return self.live.query(sql, limit=limit)
        except ZetarisError as error:
            if not error.recoverable or self.sample is None:
                raise
            try:
                result = self.sample.query(sql, limit=limit)
            except ZetarisError:
                raise error from None
            self.on_fallback(result, error)
            return result
