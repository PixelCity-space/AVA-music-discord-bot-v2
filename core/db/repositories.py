from datetime import datetime
from typing import Any, Dict, List, Optional

from core.db.pool import SQLiteConnectionPool
from core.models import Song
from utils.logger import log


class CacheRepository:
    """Data-access and in-memory LRU cache for song_cache table."""

    def __init__(self, pool: SQLiteConnectionPool, max_mem_entries: int = 256):
        self._pool = pool
        self._max_mem_entries = max_mem_entries
        self._mem_cache: Dict[str, Dict[str, Any]] = {}

    def _mem_put(self, url: str, data: Dict[str, Any]):
        if len(self._mem_cache) >= self._max_mem_entries:
            self._mem_cache.clear()
        self._mem_cache[url] = dict(data)

    def get(self, url: str) -> Optional[Dict[str, Any]]:
        if self._pool.is_closed:
            return None
        cached_mem = self._mem_cache.get(url)
        if cached_mem is not None:
            return dict(cached_mem)
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM song_cache WHERE url = ?", (url,))
                row = cursor.fetchone()
                if row:
                    data = dict(row)
                    data["duration"] = int(data["duration"])
                    self._mem_put(url, data)
                    return dict(data)
        except Exception as e:
            log.debug(f"Cache get error: {url}: {e}")
        return None

    def set(
        self,
        url: str,
        title: str,
        uploader: str,
        duration: int,
        thumbnail_url: str,
        local_path: Optional[str] = None,
    ):
        try:
            now_iso = datetime.now().isoformat()
            with self._pool.get_connection() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO song_cache
                    (url, title, uploader, duration, thumbnail_url, local_path, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (url, title, uploader, duration, thumbnail_url, local_path, now_iso),
                )
                conn.commit()
            self._mem_put(
                url,
                {
                    "url": url,
                    "title": title,
                    "uploader": uploader,
                    "duration": int(duration),
                    "thumbnail_url": thumbnail_url,
                    "local_path": local_path,
                    "last_updated": now_iso,
                },
            )
        except Exception as e:
            log.error(f"Error setting cache for {url}: {e}")

    def update_path(self, url: str, local_path: str):
        try:
            now_iso = datetime.now().isoformat()
            with self._pool.get_connection() as conn:
                conn.execute(
                    "UPDATE song_cache SET local_path = ?, last_updated = ? WHERE url = ?",
                    (local_path, now_iso, url),
                )
                conn.commit()
            if url in self._mem_cache:
                self._mem_cache[url]["local_path"] = local_path
                self._mem_cache[url]["last_updated"] = now_iso
        except Exception as e:
            log.error(f"Error updating cache path for {url}: {e}")

    def clear_metadata(self):
        try:
            with self._pool.get_connection() as conn:
                conn.execute("DELETE FROM song_cache")
                conn.commit()
            self._mem_cache.clear()
        except Exception as e:
            log.error(f"Error clearing cache DB: {e}")

    def get_all_cached_urls(self) -> List[str]:
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT url FROM song_cache WHERE local_path IS NOT NULL")
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            log.error(f"Error fetching cached URLs: {e}")
            return []

    def set_batch(self, songs_data: List[Dict[str, Any]]):
        if not songs_data:
            return
        try:
            now_iso = datetime.now().isoformat()

            def _parse_duration(val):
                try:
                    return max(0, int(val or 0))
                except (ValueError, TypeError):
                    return 0

            rows = [
                (
                    d.get("url") or d.get("path"),
                    d.get("title", ""),
                    d.get("uploader", "Unknown"),
                    _parse_duration(d.get("duration")),
                    d.get("thumbnail_url", ""),
                    d.get("local_path"),
                    now_iso,
                )
                for d in songs_data
                if (d.get("url") or d.get("path"))
            ]
            with self._pool.get_connection() as conn:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO song_cache
                    (url, title, uploader, duration, thumbnail_url, local_path, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                conn.commit()
            for r in rows:
                self._mem_put(
                    r[0],
                    {
                        "url": r[0],
                        "title": r[1],
                        "uploader": r[2],
                        "duration": r[3],
                        "thumbnail_url": r[4],
                        "local_path": r[5],
                        "last_updated": r[6],
                    },
                )
        except Exception as e:
            log.error(f"Error in set_cache_batch: {e}")

    def reset_local_paths(self):
        try:
            with self._pool.get_connection() as conn:
                conn.execute("UPDATE song_cache SET local_path = NULL")
                conn.commit()
            for entry in self._mem_cache.values():
                entry["local_path"] = None
        except Exception as e:
            log.error(f"Error resetting local_path in cache DB: {e}")


class HistoryRepository:
    """Data-access and O(1) presence cache for history and system_stats tables."""

    def __init__(self, pool: SQLiteConnectionPool, max_entries: int = 1000):
        self._pool = pool
        self.max_entries = max_entries
        self._has_history_cache: Optional[bool] = None

    def add(self, song: Song):
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO history
                    (title, path, uploader, duration, thumbnail_url, is_external, requested_by, user_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        song.title,
                        song.path,
                        song.uploader,
                        song.duration,
                        song.thumbnail_url,
                        song.is_external,
                        song.requested_by,
                        str(song.user_id) if song.user_id else None,
                    ),
                )
                if self.max_entries > 0:
                    cursor.execute(
                        """
                        DELETE FROM history WHERE id < (
                            SELECT id FROM history ORDER BY id DESC LIMIT 1 OFFSET ?
                        )
                        """,
                        (self.max_entries - 1,),
                    )
                else:
                    cursor.execute("DELETE FROM history")
                conn.commit()
                self._has_history_cache = True
        except Exception as e:
            log.error(f"Error adding to history DB: {e}")

    def has_items(self) -> bool:
        if self._pool.is_closed:
            return False
        if self._has_history_cache is not None:
            return self._has_history_cache
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM history LIMIT 1")
                exists = cursor.fetchone() is not None
                self._has_history_cache = exists
                return exists
        except Exception as e:
            log.error(f"Error checking has_history in DB: {e}")
            return False

    def count(self) -> int:
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM history")
                row = cursor.fetchone()
                return row[0] if row else 0
        except Exception as e:
            log.error(f"Error checking get_history_count in DB: {e}")
            return 0

    def increment_stat(self, key: str):
        try:
            with self._pool.get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO system_stats (key, value) VALUES (?, 1)
                    ON CONFLICT(key) DO UPDATE SET value = value + 1
                    """,
                    (key,),
                )
                conn.commit()
        except Exception as e:
            log.warning(f"Failed to increment system stat '{key}': {e}")

    def get_latest(self, offset: int = 0) -> Optional[Song]:
        if offset < 0:
            return None
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM history ORDER BY id DESC LIMIT 1 OFFSET ?", (offset,))
                row = cursor.fetchone()
                return Song.from_dict(dict(row)) if row else None
        except Exception as e:
            log.error(f"Error getting history item from DB: {e}")
            return None

    def pop_latest(self) -> Optional[Song]:
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM history ORDER BY id DESC LIMIT 1")
                row = cursor.fetchone()
                if row:
                    song = Song.from_dict(dict(row))
                    cursor.execute("DELETE FROM history WHERE id = ?", (row["id"],))
                    conn.commit()
                    self._has_history_cache = None
                    return song
                self._has_history_cache = False
                return None
        except Exception as e:
            log.error(f"Error popping history from DB: {e}")
            return None

    def get_all(self, limit: Optional[int] = None) -> List[Song]:
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                if limit:
                    cursor.execute("SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,))
                else:
                    cursor.execute("SELECT * FROM history ORDER BY id DESC")
                return [Song.from_dict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            log.error(f"Error getting history from DB: {e}")
            return []

    def clear(self):
        try:
            with self._pool.get_connection() as conn:
                conn.execute("DELETE FROM history")
                conn.commit()
                self._has_history_cache = False
        except Exception as e:
            log.error(f"Error clearing history DB: {e}")


class FavoritesRepository:
    """Data-access and per-user path cache for favorites table."""

    def __init__(self, pool: SQLiteConnectionPool, max_cached_users: int = 50):
        self._pool = pool
        self._max_cached_users = max_cached_users
        self._fav_cache: Dict[str, set[str]] = {}

    def _ensure_user_cache(self, user_id: str) -> Optional[set[str]]:
        if self._pool.is_closed or not user_id:
            return None
        uid = str(user_id)
        if uid not in self._fav_cache:
            try:
                with self._pool.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT path FROM favorites WHERE user_id = ?", (uid,))
                    if len(self._fav_cache) >= self._max_cached_users:
                        self._fav_cache.clear()
                    self._fav_cache[uid] = {row[0] for row in cursor.fetchall()}
            except Exception:
                return None
        return self._fav_cache[uid]

    def add(self, user_id: str, song: Song):
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
            if uid in self._fav_cache:
                self._fav_cache[uid].add(song.path)
        except Exception as e:
            log.error(f"Error adding favorite to DB: {e}")

    def remove(self, user_id: str, path: str):
        try:
            uid = str(user_id)
            with self._pool.get_connection() as conn:
                conn.execute("DELETE FROM favorites WHERE user_id = ? AND path = ?", (uid, path))
                conn.commit()
            if uid in self._fav_cache:
                self._fav_cache[uid].discard(path)
        except Exception as e:
            log.error(f"Error removing favorite from DB: {e}")

    def is_favorite(self, user_id: str, path: str) -> bool:
        if not user_id or not path or self._pool.is_closed:
            return False
        cached = self._ensure_user_cache(str(user_id))
        return path in cached if cached is not None else False

    def get_all(self, user_id: str) -> List[Song]:
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM favorites WHERE user_id = ?", (str(user_id),))
                return [Song.from_dict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            log.error(f"Error getting favorites from DB: {e}")
            return []

    def count(self, user_id: str) -> int:
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM favorites WHERE user_id = ?", (str(user_id),))
                row = cursor.fetchone()
                return row[0] if row else 0
        except Exception as e:
            log.error(f"Error getting favorite count from DB: {e}")
            return 0

    def clear(self, user_id: str):
        try:
            uid = str(user_id)
            with self._pool.get_connection() as conn:
                conn.execute("DELETE FROM favorites WHERE user_id = ?", (uid,))
                conn.commit()
            self._fav_cache[uid] = set()
        except Exception as e:
            log.error(f"Error clearing favorites DB: {e}")

