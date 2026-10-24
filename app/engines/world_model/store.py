"""SQLite persistence for the World Model: canonical entities, an append-only observation log, edges with
validity intervals, append-only assessments, derived aggregates and an ordered audit log."""
import json
import sqlite3

SCHEMA_VERSION = "1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY, type TEXT NOT NULL, name TEXT, external_key TEXT,
    aliases TEXT NOT NULL, attrs TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS observations (
    id TEXT PRIMARY KEY, seq INTEGER NOT NULL, entity_id TEXT NOT NULL, source TEXT NOT NULL,
    payload TEXT NOT NULL, provenance TEXT NOT NULL, observed_at TEXT, ingested_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS observations_entity ON observations (entity_id, seq);
CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY, seq INTEGER NOT NULL, from_id TEXT NOT NULL, type TEXT NOT NULL, to_id TEXT NOT NULL,
    valid_from TEXT NOT NULL, valid_to TEXT, multi INTEGER NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS edges_from ON edges (from_id, type);
CREATE TABLE IF NOT EXISTS assessments (
    id TEXT PRIMARY KEY, seq INTEGER NOT NULL, observation_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    agent TEXT NOT NULL, run_id TEXT, round INTEGER, data TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS assessments_observation ON assessments (observation_id, seq);
CREATE INDEX IF NOT EXISTS assessments_entity ON assessments (entity_id, seq);
CREATE TABLE IF NOT EXISTS derived (entity_id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, actor TEXT, action TEXT NOT NULL,
    target TEXT, details TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS audit_target ON audit (target);
"""


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class Store:
    def __init__(self, connection):
        self.db = connection
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        found = self.db.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        if found is None:
            self.db.execute("INSERT INTO meta VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
        elif found["value"] != SCHEMA_VERSION:
            raise RuntimeError(f"world model store is schema {found['value']}, this code expects {SCHEMA_VERSION}")
        self.db.commit()

    def next_seq(self, table):
        return self.db.execute(f"SELECT COALESCE(MAX(seq), 0) + 1 FROM {table}").fetchone()[0]

    # entities
    def get_entity(self, entity_id):
        row = self.db.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
        return entity_from_row(row) if row else None

    def entities(self, entity_type=None):
        if entity_type:
            rows = self.db.execute("SELECT * FROM entities WHERE type = ? ORDER BY id", (entity_type,))
        else:
            rows = self.db.execute("SELECT * FROM entities ORDER BY id")
        return [entity_from_row(r) for r in rows]

    def put_entity(self, entity):
        self.db.execute(
            "INSERT INTO entities VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET name = excluded.name, "
            "aliases = excluded.aliases, attrs = excluded.attrs, updated_at = excluded.updated_at",
            (entity["id"], entity["type"], entity.get("name"), dumps(entity.get("external_key")),
             dumps(entity["aliases"]), dumps(entity["attrs"]), entity["created_at"], entity["updated_at"]))

    # observations
    def has_observation(self, observation_id):
        return self.db.execute("SELECT 1 FROM observations WHERE id = ?", (observation_id,)).fetchone() is not None

    def put_observation(self, obs):
        self.db.execute("INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (obs["id"], obs["seq"], obs["entity_id"], dumps(obs["source"]), dumps(obs["payload"]),
                         dumps(obs["provenance"]), obs.get("observed_at"), obs["ingested_at"]))

    def observations(self, entity_id=None):
        if entity_id:
            rows = self.db.execute("SELECT * FROM observations WHERE entity_id = ? ORDER BY seq", (entity_id,))
        else:
            rows = self.db.execute("SELECT * FROM observations ORDER BY seq")
        return [observation_from_row(r) for r in rows]

    def get_observation(self, observation_id):
        row = self.db.execute("SELECT * FROM observations WHERE id = ?", (observation_id,)).fetchone()
        return observation_from_row(row) if row else None

    # edges
    def put_edge(self, edge):
        self.db.execute("INSERT OR IGNORE INTO edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (edge["id"], edge["seq"], edge["from_id"], edge["type"], edge["to_id"], edge["valid_from"],
                         edge.get("valid_to"), int(edge["multi"]), dumps(edge["source"]), edge["created_at"]))

    def edges(self, from_id=None, edge_type=None):
        sql, args = "SELECT * FROM edges WHERE 1 = 1", []
        if from_id:
            sql, args = sql + " AND from_id = ?", args + [from_id]
        if edge_type:
            sql, args = sql + " AND type = ?", args + [edge_type]
        return [dict(r, multi=bool(r["multi"]), source=json.loads(r["source"])) for r in self.db.execute(sql + " ORDER BY seq", args)]

    # assessments
    def put_assessment(self, assessment):
        self.db.execute("INSERT INTO assessments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (assessment["id"], assessment["seq"], assessment["observation_id"], assessment["entity_id"],
                         assessment["agent"], assessment.get("run_id"), assessment.get("round"),
                         dumps(assessment["data"]), assessment["created_at"]))

    def assessments(self, entity_id=None, observation_id=None):
        sql, args = "SELECT * FROM assessments WHERE 1 = 1", []
        if entity_id:
            sql, args = sql + " AND entity_id = ?", args + [entity_id]
        if observation_id:
            sql, args = sql + " AND observation_id = ?", args + [observation_id]
        return [dict(r, data=json.loads(r["data"])) for r in self.db.execute(sql + " ORDER BY seq", args)]

    # derived aggregates (rebuilt, never edited)
    def put_derived(self, entity_id, data):
        self.db.execute("INSERT INTO derived VALUES (?, ?) ON CONFLICT(entity_id) DO UPDATE SET data = excluded.data",
                        (entity_id, dumps(data)))

    def get_derived(self, entity_id):
        row = self.db.execute("SELECT data FROM derived WHERE entity_id = ?", (entity_id,)).fetchone()
        return json.loads(row["data"]) if row else {}

    # audit
    def append_audit(self, ts, actor, action, target, details):
        cursor = self.db.execute("INSERT INTO audit (ts, actor, action, target, details) VALUES (?, ?, ?, ?, ?)",
                                 (ts, actor, action, target, dumps(details)))
        return cursor.lastrowid

    def audit(self, since_seq=0):
        rows = self.db.execute("SELECT * FROM audit WHERE seq > ? ORDER BY seq", (since_seq,))
        return [dict(r, details=json.loads(r["details"])) for r in rows]

    def written_at(self, ids):
        """The audit sequence at which each observation or assessment was appended: the log's common clock."""
        found, ids = {}, list(ids)
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            rows = self.db.execute(f"SELECT target, MIN(seq) FROM audit WHERE target IN ({', '.join('?' * len(chunk))}) "
                                   "AND action IN ('observation.append', 'assessment.add') GROUP BY target", chunk)
            found.update((target, seq) for target, seq in rows)
        return found

    def commit(self):
        self.db.commit()


def entity_from_row(row):
    return {"id": row["id"], "type": row["type"], "name": row["name"], "external_key": json.loads(row["external_key"]),
            "aliases": json.loads(row["aliases"]), "attrs": json.loads(row["attrs"]),
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


def observation_from_row(row):
    return {"id": row["id"], "seq": row["seq"], "entity_id": row["entity_id"], "source": json.loads(row["source"]),
            "payload": json.loads(row["payload"]), "provenance": json.loads(row["provenance"]),
            "observed_at": row["observed_at"], "ingested_at": row["ingested_at"]}
