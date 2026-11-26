import threading
from collections import OrderedDict

from core.db.pool import SQLiteConnectionPool
from core.models import Song
from utils.logger import log


class FavoritesRepository:
    """Thread-safe data-access and per-user LRU path cache for favorites table."""

    def __init__(self, pool: SQLiteConnectionPool, max_cached_users: int = 50):
        self._pool = pool
        self._max_cached_users = max_cached_users
        self._fav_cache: OrderedDict[str, set[str]] = OrderedDict()
        self._cache_lock = threading.Lock()

    def _ensure_user_cache(self, user_id: str | int) -> set[str] | None:
        if self._pool.is_closed or not user_id:
            return None
        uid = str(user_id)
        with self._cache_lock:
            if uid in self._fav_cache:
                self._fav_cache.move_to_end(uid)
                return set(self._fav_cache[uid])
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT path FROM favorites WHERE user_id = ?", (uid,))
                paths = {row[0] for row in cursor.fetchall()}
            with self._cache_lock:
                if uid in self._fav_cache:
                    self._fav_cache.move_to_end(uid)
                elif len(self._fav_cache) >= self._max_cached_users:
                    self._fav_cache.popitem(last=False)
                self._fav_cache[uid] = paths
                return set(paths)
        except Exception as e:
            log.error(f"Error loading favorites cache for user {uid}: {e}", exc_info=True)
            return None

    def add(self, user_id: str | int, song: Song):
        if not song or not song.path:
            return
        try:
            uid = str(user_id)
            with self._pool.get_connection() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO favorites
                    (user_id, path, title, uploader, duration, thumbnail_url, is_external)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (uid, song.path, song.title, song.uploader, song.duration, song.thumbnail_url, song.is_external),
                )
                conn.commit()
            with self._cache_lock:
                if uid in self._fav_cache:
                    self._fav_cache[uid].add(song.path)
                    self._fav_cache.move_to_end(uid)
        except Exception as e:
            log.error(f"Error adding favorite to DB: {e}", exc_info=True)

    def remove(self, user_id: str | int, path: str):
        try:
            uid = str(user_id)
            with self._pool.get_connection() as conn:
                conn.execute("DELETE FROM favorites WHERE user_id = ? AND path = ?", (uid, path))
                conn.commit()
            with self._cache_lock:
                if uid in self._fav_cache:
                    self._fav_cache[uid].discard(path)
                    self._fav_cache.move_to_end(uid)
        except Exception as e:
            log.error(f"Error removing favorite from DB: {e}", exc_info=True)

    def is_favorite(self, user_id: str | int, path: str) -> bool:
        if not user_id or not path or self._pool.is_closed:
            return False
        cached = self._ensure_user_cache(str(user_id))
        return path in cached if cached is not None else False

    def get_all(self, user_id: str | int) -> list[Song]:
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM favorites WHERE user_id = ?", (str(user_id),))
                return [Song.from_dict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            log.error(f"Error getting favorites from DB: {e}", exc_info=True)
            return []

    def count(self, user_id: str | int) -> int:
        if self._pool.is_closed:
            return 0
        uid = str(user_id)
        with self._cache_lock:
            cached = self._fav_cache.get(uid)
            if cached is not None:
                self._fav_cache.move_to_end(uid)
                return len(cached)
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM favorites WHERE user_id = ?", (uid,))
                row = cursor.fetchone()
                return row[0] if row else 0
        except Exception as e:
            log.error(f"Error getting favorite count from DB: {e}", exc_info=True)
            return 0

    def clear(self, user_id: str | int):
        try:
            uid = str(user_id)
            with self._pool.get_connection() as conn:
                conn.execute("DELETE FROM favorites WHERE user_id = ?", (uid,))
                conn.commit()
            with self._cache_lock:
                self._fav_cache[uid] = set()
                self._fav_cache.move_to_end(uid)
        except Exception as e:
            log.error(f"Error clearing favorites DB: {e}", exc_info=True)
