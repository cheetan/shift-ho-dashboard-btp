import json
from datetime import datetime, timezone
from app.store.base import DataStore
from app.config import get_hana_config


class HanaStore(DataStore):
    """Persists data in SAP HANA Cloud via hdbcli."""

    def __init__(self):
        self._conn = None
        self._history_table_ensured = False

    def _get_conn(self):
        from hdbcli import dbapi
        cfg = get_hana_config()
        if self._conn is None or not self._conn.isconnected():
            self._conn = dbapi.connect(
                address=cfg["host"],
                port=cfg["port"],
                user=cfg["user"],
                password=cfg["password"],
                encrypt=True,
                sslValidateCertificate=False,
            )
        return self._conn

    def _cursor(self):
        return self._get_conn().cursor()

    def _ensure_history_table(self):
        if self._history_table_ensured:
            return
        try:
            cur = self._cursor()
            cur.execute("SELECT COUNT(*) FROM HO_STATUS_HISTORY WHERE 1=0")
            cur.close()
        except Exception:
            try:
                cur = self._cursor()
                cur.execute(
                    "CREATE TABLE HO_STATUS_HISTORY ("
                    "TICKET_ID   NVARCHAR(200)  NOT NULL, "
                    "NOTE_VALUE  NVARCHAR(5000) NOT NULL, "
                    "CHANGED_BY  NVARCHAR(200)  NOT NULL, "
                    "CHANGED_AT  NVARCHAR(30)   NOT NULL"
                    ")"
                )
                self._get_conn().commit()
                cur.close()
            except Exception as e:
                import sys
                print(f"ERROR creating HO_STATUS_HISTORY: {e}", file=sys.stderr)
        self._history_table_ensured = True

    def upsert_source(self, source, headers, rows, uploaded_by, meta=None):
        cur = self._cursor()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("DELETE FROM SOURCE_CACHE WHERE SOURCE = ?", (source,))
        cur.execute(
            "INSERT INTO SOURCE_CACHE "
            "(SOURCE, HEADERS_JSON, ROWS_JSON, META_JSON, UPLOADED_BY, UPLOADED_AT, ROW_COUNT) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                source,
                json.dumps(headers, ensure_ascii=False),
                json.dumps(rows, ensure_ascii=False),
                json.dumps(meta or {}, ensure_ascii=False),
                uploaded_by,
                now,
                len(rows),
            ),
        )
        self._get_conn().commit()
        cur.close()

    def get_source(self, source):
        cur = self._cursor()
        cur.execute(
            "SELECT HEADERS_JSON, ROWS_JSON, META_JSON FROM SOURCE_CACHE WHERE SOURCE = ?",
            (source,),
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            return [], [], {}
        return json.loads(row[0]), json.loads(row[1]), json.loads(row[2])

    def get_upload_meta(self, source):
        cur = self._cursor()
        cur.execute(
            "SELECT UPLOADED_BY, UPLOADED_AT, ROW_COUNT FROM SOURCE_CACHE WHERE SOURCE = ?",
            (source,),
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            return {}
        return {
            "uploaded_by": row[0],
            "uploaded_at": str(row[1])[:16] if row[1] else "—",
            "row_count":   row[2],
        }

    def get_ho_status(self):
        cur = self._cursor()
        cur.execute("SELECT NOTE_KEY, NOTE_VALUE FROM HO_STATUS")
        rows = cur.fetchall()
        cur.close()
        return {r[0]: r[1] for r in rows}

    def save_ho_status(self, notes, updated_by):
        self._ensure_history_table()
        cur = self._cursor()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # History recording — isolated so failures never abort the main save
        try:
            cur.execute("SELECT NOTE_KEY, NOTE_VALUE FROM HO_STATUS")
            old_rows = cur.fetchall()
            old_notes = {r[0]: r[1] for r in old_rows}
            old_by_ticket = {}
            for key, val in old_notes.items():
                if key.startswith("ho:") and key.count(":") >= 2:
                    old_by_ticket[key.split(":", 2)[2]] = val.strip()
            new_by_ticket = {}
            for key, val in notes.items():
                if key.startswith("ho:") and key.count(":") >= 2:
                    tid = key.split(":", 2)[2]
                    v = str(val).strip()
                    old_val = old_by_ticket.get(tid, "")
                    if v != old_val:
                        new_by_ticket[tid] = v
                    elif tid not in new_by_ticket:
                        new_by_ticket[tid] = v
            recorded = set()
            for tid, new_val in new_by_ticket.items():
                if tid in recorded:
                    continue
                old_val = old_by_ticket.get(tid, "")
                if new_val and new_val != old_val:
                    cur.execute(
                        "INSERT INTO HO_STATUS_HISTORY (TICKET_ID, NOTE_VALUE, CHANGED_BY, CHANGED_AT) "
                        "VALUES (?, ?, ?, ?)",
                        (tid, new_val[:5000], updated_by, now),
                    )
                    recorded.add(tid)
        except Exception as e:
            import sys
            print(f"HO_STATUS_HISTORY insert error: {e}", file=sys.stderr)

        # Main save — critical path, always runs
        cur.execute("DELETE FROM HO_STATUS")
        for key, value in notes.items():
            if key.startswith("hide:"):
                continue
            cur.execute(
                "INSERT INTO HO_STATUS (NOTE_KEY, NOTE_VALUE, UPDATED_BY, UPDATED_AT) "
                "VALUES (?, ?, ?, ?)",
                (key, str(value)[:5000], updated_by, now),
            )
        self._get_conn().commit()
        cur.close()

    def get_ho_history(self, ticket_id):
        self._ensure_history_table()
        cur = self._cursor()
        cur.execute(
            "SELECT NOTE_VALUE, CHANGED_BY, CHANGED_AT FROM HO_STATUS_HISTORY "
            "WHERE TICKET_ID = ? ORDER BY CHANGED_AT DESC",
            (ticket_id,),
        )
        rows = cur.fetchall()
        cur.close()
        return [{"value": r[0], "by": r[1], "at": str(r[2])[:16]} for r in rows]

    def get_ho_updated_at(self) -> str:
        cur = self._cursor()
        cur.execute("SELECT MAX(UPDATED_AT) FROM HO_STATUS")
        row = cur.fetchone()
        cur.close()
        return str(row[0]) if row and row[0] else ""
