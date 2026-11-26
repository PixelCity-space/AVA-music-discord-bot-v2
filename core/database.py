import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from core.db import (
    CacheRepository,
    FavoritesRepository,
    HistoryRepository,
    SQLiteConnectionPool,
    init_schema,
)
from core.models import Song


class Database:
    """
    Backward-compatible facade composing the SQLite connection pool
    and domain repositories (cache, history, favorites).
    """

    DEFAULT_MAX_HISTORY_ENTRIES = 1000

    def __init__(self, db_path: str = "data/radio.db", timeout: float = 10.0, pool_size: int = 5):
        self.db_path = db_path
        self.timeout = timeout
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._pool = SQLiteConnectionPool(self.db_path, max_connections=pool_size, timeout=self.timeout)
        init_schema(self._pool)

        self.cache_repo = CacheRepository(self._pool)
        self.history_repo = HistoryRepository(self._pool, max_entries=self.DEFAULT_MAX_HISTORY_ENTRIES)
        self.favorites_repo = FavoritesRepository(self._pool)

    @property
    def MAX_HISTORY_ENTRIES(self) -> int:
        return self.history_repo.max_entries

    @MAX_HISTORY_ENTRIES.setter
    def MAX_HISTORY_ENTRIES(self, value: int):
        self.history_repo.max_entries = value

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager borrowing a preconfigured SQLite connection from the pool."""
        with self._pool.get_connection() as conn:
            yield conn

    def close(self):
        """Closes all connections in the pool."""
        self._pool.close()

    # --- Cache Methods ---
    def get_cache(self, url: str) -> dict[str, Any] | None:
        return self.cache_repo.get(url)

    def set_cache(
        self,
        url: str,
        title: str,
        uploader: str,
        duration: int,
        thumbnail_url: str,
        local_path: str | None = None,
    ):
        self.cache_repo.set(url, title, uploader, duration, thumbnail_url, local_path=local_path)

    def update_cache_path(self, url: str, local_path: str):
        self.cache_repo.update_path(url, local_path)

    def clear_cache_metadata(self):
        self.cache_repo.clear_metadata()

    def get_all_cached_urls(self) -> list[str]:
        return self.cache_repo.get_all_cached_urls()

    def cache_song(self, song: Song, local_path: str | None = None):
        if song and song.path:
            self.cache_repo.set(
                url=song.path,
                title=song.title or "",
                uploader=song.uploader or "Unknown",
                duration=song.duration,
                thumbnail_url=song.thumbnail_url or "",
                local_path=local_path,
            )

    def set_cache_batch(self, songs_data: list[dict[str, Any]]):
        self.cache_repo.set_batch(songs_data)

    def clear_cache(self):
        self.cache_repo.reset_local_paths()

    # --- History Methods ---
    def add_history(self, song: Song):
        self.history_repo.add(song)

    def has_history(self) -> bool:
        return self.history_repo.has_items()

    def get_history_count(self) -> int:
        return self.history_repo.count()

    def increment_stat(self, key: str):
        self.history_repo.increment_stat(key)

    def get_history_latest(self, offset: int = 0) -> Song | None:
        return self.history_repo.get_latest(offset=offset)

    def pop_history_latest(self) -> Song | None:
        return self.history_repo.pop_latest()

    def get_history(self, limit: int | None = None) -> list[Song]:
        return self.history_repo.get_all(limit=limit)

    def clear_history(self):
        self.history_repo.clear()

    # --- Favorites Methods ---
    def add_favorite(self, user_id: str, song: Song):
        self.favorites_repo.add(user_id, song)

    def remove_favorite(self, user_id: str, path: str):
        self.favorites_repo.remove(user_id, path)

    def is_favorite(self, user_id: str, path: str) -> bool:
        return self.favorites_repo.is_favorite(user_id, path)

    def get_favorites(self, user_id: str) -> list[Song]:
        return self.favorites_repo.get_all(user_id)

    def get_favorite_count(self, user_id: str) -> int:
        return self.favorites_repo.count(user_id)

    def clear_favorites(self, user_id: str):
        self.favorites_repo.clear(user_id)
