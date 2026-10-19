from app.config import USE_MEMORY_STORE
from app.store.base import DataStore

_store: DataStore | None = None


def get_store() -> DataStore:
    global _store
    if _store is None:
        if USE_MEMORY_STORE:
            from app.store.memory import MemoryStore
            _store = MemoryStore()
        else:
            from app.store.hana import HanaStore
            _store = HanaStore()
    return _store
