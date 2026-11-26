
from core.db.pool import SQLiteConnectionPool
from core.models import Song
from utils.logger import log


class HistoryRepository:
    """Data-access and O(1) presence cache for history and system_stats tables."""

    def __init__(self, pool: SQLiteConnectionPool, max_entries: int = 1000):
        self._pool = pool
        self.max_entries = max_entries
        self._has_history_cache: bool | None = None
        self._estimated_count: int | None = None

    def add(self, song: Song):
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                if self._estimated_count is None and self.max_entries > 0:
                    cursor.execute("SELECT COUNT(*) FROM history")
                    row = cursor.fetchone()
                    self._estimated_count = row[0] if row else 0

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
                        song.user_id or None,
                    ),
                )
                if self.max_entries > 0:
                    self._estimated_count = (self._estimated_count or 0) + 1
                    if self._estimated_count > self.max_entries:
                        cursor.execute(
                            """
                            DELETE FROM history WHERE id < (
                                SELECT id FROM history ORDER BY id DESC LIMIT 1 OFFSET ?
                            )
                            """,
                            (self.max_entries - 1,),
                        )
                        self._estimated_count = self.max_entries
                else:
                    cursor.execute("DELETE FROM history")
                    self._estimated_count = 0
                conn.commit()
                self._has_history_cache = self.max_entries > 0
        except Exception as e:
            log.error(f"Error adding to history DB: {e}", exc_info=True)

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
            log.error(f"Error checking has_history in DB: {e}", exc_info=True)
            return False

    def count(self) -> int:
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM history")
                row = cursor.fetchone()
                return row[0] if row else 0
        except Exception as e:
            log.error(f"Error checking get_history_count in DB: {e}", exc_info=True)
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

    def get_latest(self, offset: int = 0) -> Song | None:
        if offset < 0:
            return None
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM history ORDER BY id DESC LIMIT 1 OFFSET ?", (offset,))
                row = cursor.fetchone()
                return Song.from_dict(dict(row)) if row else None
        except Exception as e:
            log.error(f"Error getting history item from DB: {e}", exc_info=True)
            return None

    def pop_latest(self) -> Song | None:
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
                    if self._estimated_count is not None:
                        self._estimated_count = max(0, self._estimated_count - 1)
                    return song
                self._has_history_cache = False
                self._estimated_count = 0
                return None
        except Exception as e:
            log.error(f"Error popping history from DB: {e}", exc_info=True)
            return None

    def get_all(self, limit: int | None = None) -> list[Song]:
        try:
            with self._pool.get_connection() as conn:
                cursor = conn.cursor()
                if limit:
                    cursor.execute("SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,))
                else:
                    cursor.execute("SELECT * FROM history ORDER BY id DESC")
                return [Song.from_dict(dict(row)) for row in cursor.fetchall()]
        except Exception as e:
            log.error(f"Error getting history from DB: {e}", exc_info=True)
            return []

    def clear(self):
        try:
            with self._pool.get_connection() as conn:
                conn.execute("DELETE FROM history")
                conn.commit()
                self._has_history_cache = False
                self._estimated_count = 0
        except Exception as e:
            log.error(f"Error clearing history DB: {e}", exc_info=True)

