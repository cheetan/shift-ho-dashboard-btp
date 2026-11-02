from datetime import datetime, timezone
from app.store.base import DataStore


class MemoryStore(DataStore):
    """In-process data store — no HANA required. Resets on every restart.
    Activate with USE_MEMORY_STORE=true for local testing."""

    def __init__(self):
        self._sources: dict[str, dict] = {}
        self._ho_status: dict[str, str] = {}
        self._ho_updated_at: str = ""
        self._ho_history: dict[str, list] = {}

    def upsert_source(self, source, headers, rows, uploaded_by, meta=None):
        self._sources[source] = {
            "headers":     headers,
            "rows":        rows,
            "meta":        meta or {},
            "uploaded_by": uploaded_by,
            "uploaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "row_count":   len(rows),
        }

    def get_source(self, source):
        entry = self._sources.get(source, {})
        return entry.get("headers", []), entry.get("rows", []), entry.get("meta", {})

    def get_upload_meta(self, source):
        entry = self._sources.get(source)
        if not entry:
            return {}
        return {
            "uploaded_by": entry["uploaded_by"],
            "uploaded_at": entry["uploaded_at"],
            "row_count":   entry["row_count"],
        }

    def get_ho_status(self):
        return dict(self._ho_status)

    def save_ho_status(self, notes, updated_by):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        old_by_ticket = {}
        for key, val in self._ho_status.items():
            if key.startswith("ho:") and key.count(":") >= 2:
                old_by_ticket[key.split(":", 2)[2]] = val.strip()
        new_by_ticket = {}
        for key, val in notes.items():
            if key.startswith("ho:") and key.count(":") >= 2:
                new_by_ticket[key.split(":", 2)[2]] = str(val).strip()
        recorded = set()
        for tid, new_val in new_by_ticket.items():
            if tid in recorded:
                continue
            old_val = old_by_ticket.get(tid, "")
            if new_val and new_val != old_val:
                self._ho_history.setdefault(tid, []).insert(
                    0, {"value": new_val, "by": updated_by, "at": now[:16]}
                )
                recorded.add(tid)
        self._ho_status = {k: v for k, v in notes.items() if not k.startswith("hide:")}
        self._ho_updated_at = now

    def get_ho_history(self, ticket_id):
        return list(self._ho_history.get(ticket_id, []))

    def get_ho_updated_at(self) -> str:
        return self._ho_updated_at
