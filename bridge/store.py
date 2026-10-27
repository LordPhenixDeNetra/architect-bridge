"""Stockage SQLite : journal brut, resultats, curseur d'acquittement."""
import json
import sqlite3
import threading
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from bridge.drivers.architect import Result

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT
);
CREATE TABLE IF NOT EXISTS results (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL UNIQUE,
    raw_message_id INTEGER NOT NULL REFERENCES raw_messages(id),
    kind TEXT NOT NULL,
    specimen_id TEXT, instrument_specimen_id TEXT, carrier_id TEXT, position INTEGER,
    patient_id_practice TEXT, patient_id_lab TEXT, patient_id_3 TEXT,
    assay_number TEXT, assay_name TEXT, dilution TEXT, assay_status TEXT,
    reagent_lot TEXT, reagent_serial TEXT, control_lot TEXT,
    result_type TEXT, value TEXT, units TEXT, reference_range TEXT,
    flags TEXT NOT NULL, result_status TEXT,
    operator_order TEXT, operator_release TEXT,
    completed_at TEXT, instrument_serial TEXT, priority TEXT,
    comments TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_cursor (id INTEGER PRIMARY KEY CHECK (id = 1), acked_seq INTEGER NOT NULL);
INSERT OR IGNORE INTO api_cursor (id, acked_seq) VALUES (1, 0);
"""

RESULT_COLUMNS = [f for f in Result.__dataclass_fields__]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _to_json(row: sqlite3.Row) -> dict:
    return {
        "seq": row["seq"],
        "uid": row["uid"],
        "kind": row["kind"],
        "specimenId": row["specimen_id"],
        "instrumentSpecimenId": row["instrument_specimen_id"],
        "carrierId": row["carrier_id"],
        "position": row["position"],
        "patientIds": {"practice": row["patient_id_practice"], "lab": row["patient_id_lab"],
                       "id3": row["patient_id_3"]},
        "assay": {"number": row["assay_number"], "name": row["assay_name"],
                  "dilution": row["dilution"], "status": row["assay_status"]},
        "reagent": {"lot": row["reagent_lot"], "serial": row["reagent_serial"]},
        "controlLot": row["control_lot"],
        "resultType": row["result_type"],
        "value": row["value"],
        "units": row["units"],
        "referenceRange": row["reference_range"],
        "flags": json.loads(row["flags"]),
        "resultStatus": row["result_status"],
        "operators": {"order": row["operator_order"], "release": row["operator_release"]},
        "completedAt": row["completed_at"],
        "instrumentSerial": row["instrument_serial"],
        "priority": row["priority"],
        "comments": json.loads(row["comments"]),
        "rawMessageId": row["raw_message_id"],
    }


class Store:
    def __init__(self, path: str):
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(SCHEMA)

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._db.execute(sql, params)

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        # fetchall sous verrou : sinon une lecture peut voir une insertion annulee ensuite.
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    def save_raw(self, text: str) -> int:
        cur = self._exec("INSERT INTO raw_messages (received_at, text, status) VALUES (?, ?, 'received')",
                         (_now(), text))
        return cur.lastrowid

    def mark_raw(self, raw_id: int, status: str, error: str | None = None) -> None:
        self._exec("UPDATE raw_messages SET status = ?, error = ? WHERE id = ?", (status, error, raw_id))

    def insert_results(self, raw_id: int, results: list[Result]) -> int:
        cols = ["raw_message_id"] + RESULT_COLUMNS
        sql = (f"INSERT INTO results ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
               "ON CONFLICT(uid) DO NOTHING")
        inserted = 0
        with self._lock:
            self._db.execute("BEGIN")
            try:
                for r in results:
                    d = asdict(r)
                    d["flags"], d["comments"] = json.dumps(d["flags"]), json.dumps(d["comments"])
                    inserted += self._db.execute(sql, [raw_id] + [d[c] for c in RESULT_COLUMNS]).rowcount
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        return inserted

    def fetch_results(self, after: int, limit: int) -> list[dict]:
        rows = self._query("SELECT * FROM results WHERE seq > ? ORDER BY seq LIMIT ?", (after, limit))
        return [_to_json(r) for r in rows]

    def ack(self, up_to: int) -> None:
        self._exec("UPDATE api_cursor SET acked_seq = MAX(acked_seq, ?) WHERE id = 1", (up_to,))

    def stats(self) -> dict:
        today = datetime.now(timezone.utc).date().isoformat()
        row = self._query("""SELECT
            (SELECT COUNT(*) FROM raw_messages WHERE received_at >= ?) AS today,
            (SELECT COUNT(*) FROM raw_messages WHERE status = 'parse_error') AS errors,
            (SELECT COUNT(*) FROM results WHERE seq > (SELECT acked_seq FROM api_cursor)) AS unacked""",
                         (today,))[0]
        return {"messagesToday": row["today"], "parseErrors": row["errors"], "unackedResults": row["unacked"]}

    def raw_messages(self, status: str | None, limit: int) -> list[dict]:
        sql, params = "SELECT * FROM raw_messages", ()
        if status:
            sql, params = sql + " WHERE status = ?", (status,)
        rows = self._query(sql + " ORDER BY id DESC LIMIT ?", params + (limit,))
        return [dict(r) for r in rows]

    def get_raw(self, raw_id: int) -> str | None:
        rows = self._query("SELECT text FROM raw_messages WHERE id = ?", (raw_id,))
        return rows[0]["text"] if rows else None

    def purge(self, retention_days: int, now: datetime) -> None:
        cutoff = (now - timedelta(days=retention_days)).isoformat(timespec="seconds")
        with self._lock:
            self._db.execute("""DELETE FROM results
                WHERE seq <= (SELECT acked_seq FROM api_cursor)
                AND raw_message_id IN (SELECT id FROM raw_messages WHERE received_at < ?)""", (cutoff,))
            self._db.execute("""DELETE FROM raw_messages WHERE received_at < ?
                AND id NOT IN (SELECT raw_message_id FROM results)""", (cutoff,))
