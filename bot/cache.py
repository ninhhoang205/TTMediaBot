from __future__ import annotations

import os
import pickle
from collections import deque
from typing import Any, Dict, List, TYPE_CHECKING

from bot import app_vars
from bot.migrators import cache_migrator

import portalocker

if TYPE_CHECKING:
    from bot.player.track import Track


cache_data_type = Dict[str, Any]


class Cache:
    def __init__(self, cache_data: cache_data_type):
        self.cache_version = cache_data["cache_version"] if "cache_version" in cache_data else CacheManager.version
        self.recents: deque[Track] = (
            cache_data["recents"]
            if "recents" in cache_data
            else deque(maxlen=app_vars.recents_max_lenth)
        )
        self.favorites: Dict[str, List[Track]] = (
            cache_data["favorites"] if "favorites" in cache_data else {}
        )
        self.radio_favorites: Dict[str, List[Track]] = (
            cache_data["radio_favorites"] if "radio_favorites" in cache_data else {}
        )

    @property
    def data(self):
        return {"cache_version": self.cache_version, "recents": self.recents, "favorites": self.favorites, "radio_favorites": self.radio_favorites}


class CacheManager:
    version = 1

    def __init__(self, file_name: str) -> None:
        if not os.path.isabs(file_name):
            self.file_name = os.path.join(app_vars.cache_dir, file_name)
        else:
            self.file_name = file_name
        os.makedirs(os.path.dirname(self.file_name), exist_ok=True)
        try:
            self.data = cache_migrator.migrate(self, self._load())
            self.cache = Cache(self.data)
        except FileNotFoundError:
            self.cache = Cache({})
            self._dump(self.cache.data)
        self._lock()

    def _dump(self, data: cache_data_type):
        with open(self.file_name, "wb") as f:
            pickle.dump(data, f)

    def _load(self) -> cache_data_type:
        with open(self.file_name, "rb") as f:
            return pickle.load(f)

    def _lock(self):
        self.file_locker = portalocker.Lock(
            self.file_name,
            timeout=0,
            flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
        )
        try:
            self.file_locker.acquire()
        except portalocker.exceptions.LockException:
            raise PermissionError()

    def close(self):
        if hasattr(self, "file_locker") and self.file_locker:
            try:
                self.file_locker.release()
            except Exception:
                pass

    def save(self):
        self.file_locker.release()
        self._dump(self.cache.data)
        self.file_locker.acquire()
