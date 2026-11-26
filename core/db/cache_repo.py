import threading
from collections import OrderedDict
from datetime import datetime
from typing import Any

from core.db.pool import SQLiteConnectionPool
from utils.logger import log


class CacheRepository:
    """Thread-safe data-access and in-memory LRU cache for song_cache table."""

    def __init__(self, pool: SQLiteConnectionPool, max_mem_entries: int = 256):
        self._pool = pool
        self._max_mem_entries = max_mem_entries
        self._mem_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._cache_lock = threading.Lock()

    def _mem_put(self, url: str, data: dict[str, Any]):
        with self._cache_lock:
            if url in self._mem_cache:
                self._mem_cache.move_to_end(url)
            elif len(self._mem_cache) >= self._max_mem_entries:
                self._mem_cache.popitem(last=False)
            self._mem_cache[url] = dict(data)

    def get(self, url: str) -> dict[str, Any] | None:
        if self._pool.is_closed:
            return None
        with self._cache_lock:
            cached_mem = self._mem_cache.get(url)
            if cached_mem is not None:
                self._mem_cache.move_to_end(url)
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
        local_path: str | None = None,
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
                    "duration": duration,
                    "thumbnail_url": thumbnail_url,
                    "local_path": local_path,
                    "last_updated": now_iso,
                },
            )
        except Exception as e:
            log.error(f"Error setting cache for {url}: {e}", exc_info=True)

    def update_path(self, url: str, local_path: str):
        try:
            now_iso = datetime.now().isoformat()
            with self._pool.get_connection() as conn:
                conn.execute(
                    "UPDATE song_cache SET local_path = ?, last_updated = ? WHERE url = ?",
                    (local_path, now_iso, url),
                )
                conn.commit()
            with self._cache_lock:
                if url in self._mem_cache:
                    self._mem_cache[url]["local_path"] = local_path
                    self._mem_cache[url]["last_updated"] = now_iso
                    self._mem_cache.move_to_end(url)
        except Exception as e:
            log.error(f"Error updating cache path for {url}: {e}", exc_info=True)

    def clear_metadata(self):
        try:
            with self._pool.get_connection() as conn:
                conn.execute("DELETE FROM song_cache")
                conn.commit()
            with self._cache_lock:
                self._mem_cache.clear()
        except Exception as e:
            log.error(f"Error clearing cache DB: {e}", exc_info=True)

    def get_all_cached_urls(self) -> list[str]:
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT url FROM song_cache WHERE local_path IS NOT NULL")
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            log.error(f"Error fetching cached URLs: {e}", exc_info=True)
            return []

    def set_batch(self, songs_data: list[dict[str, Any]]):
        if not songs_data:
            return
        try:
            now_iso = datetime.now().isoformat()

            def _parse_duration(val):
                try:
                    return max(0, int(val or 0))
                except (ValueError, TypeError):
                    return 0

            rows: list[tuple[str, str, str, int, str, str | None, str]] = []
            for d in songs_data:
                url_val = d.get("url") or d.get("path")
                if not isinstance(url_val, str) or not url_val:
                    continue
                rows.append((
                    url_val,
                    str(d.get("title") or ""),
                    str(d.get("uploader") or "Unknown"),
                    _parse_duration(d.get("duration")),
                    str(d.get("thumbnail_url") or ""),
                    d.get("local_path"),
                    now_iso,
                ))
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
            log.error(f"Error in set_cache_batch: {e}", exc_info=True)

    def reset_local_paths(self):
        try:
            with self._pool.get_connection() as conn:
                conn.execute("UPDATE song_cache SET local_path = NULL")
                conn.commit()
            with self._cache_lock:
                for entry in self._mem_cache.values():
                    entry["local_path"] = None
        except Exception as e:
            log.error(f"Error resetting local_path in cache DB: {e}", exc_info=True)
