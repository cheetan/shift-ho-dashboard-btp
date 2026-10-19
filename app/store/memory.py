from datetime import datetime, timezone
from app.store.base import DataStore


class MemoryStore(DataStore):
    """In-process data store — no HANA required. Resets on every restart.
    Activate with USE_MEMORY_STORE=true for local testing."""

    def __init__(self):
        self._sources: dict[str, dict] = {}
        self._ho_status: dict[str, str] = {}

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
        self._ho_status = {k: v for k, v in notes.items() if not k.startswith("hide:")}
