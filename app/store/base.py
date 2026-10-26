from abc import ABC, abstractmethod


class DataStore(ABC):

    @abstractmethod
    def upsert_source(self, source: str, headers: list, rows: list,
                      uploaded_by: str, meta: dict | None = None) -> None:
        """Replace the stored data for a given source with a new upload."""

    @abstractmethod
    def get_source(self, source: str) -> tuple[list, list, dict]:
        """Return (headers, rows, meta) for source, or ([], [], {}) if not uploaded yet."""

    @abstractmethod
    def get_upload_meta(self, source: str) -> dict:
        """Return {uploaded_by, uploaded_at, row_count} for source, or {} if not uploaded."""

    @abstractmethod
    def get_ho_status(self) -> dict:
        """Return all HO status notes as a flat dict {key: value}."""

    @abstractmethod
    def save_ho_status(self, notes: dict, updated_by: str) -> None:
        """Replace all HO status notes with the provided dict."""

    @abstractmethod
    def get_ho_updated_at(self) -> str:
        """Return the UTC timestamp of the last save_ho_status call, or '' if never saved."""
