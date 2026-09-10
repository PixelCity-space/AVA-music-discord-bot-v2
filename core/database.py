import sqlite3
import os
import queue
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, Dict, Any, List, Generator
from core.models import Song
from utils.logger import log

class SQLiteConnectionPool:
    """
    Thread-safe connection pool for SQLite to eliminate per-query connect/disconnect overhead.
    Preconfigures WAL mode, synchronous=NORMAL, and in-memory temp stores.
    """
    def __init__(self, db_path: str, max_connections: int = 5, timeout: float = 10.0):
        self.db_path = db_path
        self.max_connections = max_connections
        self.timeout = timeout
        self._pool: queue.Queue[sqlite3.Connection] = queue.Queue(maxsize=max_connections)
        self._all_connections: List[sqlite3.Connection] = []
        self._is_closed = False

        for _ in range(max_connections):
            conn = self._create_connection()
            self._all_connections.append(conn)
            self._pool.put(conn)

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path, 
            timeout=self.timeout, 
            check_same_thread=False
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        return conn

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        if self._is_closed:
            raise RuntimeError("Cannot acquire connection from a closed SQLiteConnectionPool.")
        conn = self._pool.get(block=True, timeout=self.timeout)
        try:
            yield conn
        finally:
            if not self._is_closed:
                self._pool.put(conn)

    def close(self):
        self._is_closed = True
        while not self._pool.empty():
            self._pool.get_nowait()
        for conn in self._all_connections:
            conn.close()
        self._all_connections.clear()

class Database:
    MAX_HISTORY_ENTRIES = 1000

    def __init__(self, db_path: str = "data/radio.db", timeout: float = 10.0, pool_size: int = 5):
        self.db_path = db_path
        self.timeout = timeout
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._pool = SQLiteConnectionPool(self.db_path, max_connections=pool_size, timeout=self.timeout)
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager borrowing a preconfigured SQLite connection from the pool."""
        with self._pool.get_connection() as conn:
            yield conn

    def close(self):
        """Closes all connections in the pool."""
        self._pool.close()

    def _init_db(self):
        """Initializes the database, creates tables and performance indices."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Song Metadata Cache
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS song_cache (
                    url TEXT PRIMARY KEY,
                    title TEXT,
                    uploader TEXT,
                    duration INTEGER,
                    thumbnail_url TEXT,
                    local_path TEXT,
                    last_updated TIMESTAMP
                )
            """)
            
            # Migration for local_path if it doesn't exist
            try:
                cursor.execute("ALTER TABLE song_cache ADD COLUMN local_path TEXT")
            except sqlite3.OperationalError:
                pass
            
            # 2. Playback History (with user stats)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    path TEXT,
                    uploader TEXT,
                    duration INTEGER,
                    thumbnail_url TEXT,
                    is_external BOOLEAN,
                    requested_by TEXT,
                    user_id TEXT,
                    played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 3. User Settings
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id TEXT PRIMARY KEY,
                    language TEXT,
                    volume FLOAT,
                    ui_mode TEXT
                )
            """)

            # 4. Global Stats
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_stats (
                    key TEXT PRIMARY KEY,
                    value INTEGER DEFAULT 0
                )
            """)
            
            # 5. User Favorites
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    user_id TEXT,
                    path TEXT,
                    title TEXT,
                    uploader TEXT,
                    duration INTEGER,
                    thumbnail_url TEXT,
                    is_external BOOLEAN,
                    PRIMARY KEY (user_id, path)
                )
            """)

            # 6. Performance Indices (to prevent Full Table Scans)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_id_desc ON history (id DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_user ON history (user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_played ON history (played_at DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_song_cache_updated ON song_cache (last_updated DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_fav_user ON favorites (user_id)")
            
            conn.commit()

            # Migrations for existing history schemas
            try:
                cursor.execute("ALTER TABLE history ADD COLUMN requested_by TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE history ADD COLUMN user_id TEXT")
            except sqlite3.OperationalError:
                pass
            conn.commit()

    # --- Cache Methods ---
    def get_cache(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM song_cache WHERE url = ?", (url,))
                row = cursor.fetchone()
                if row:
                    data = dict(row)
                    data["duration"] = int(data["duration"])
                    return data
        except Exception as e:
            log.debug(f"Cache get error: {url}: {e}")
        return None

    def set_cache(self, url: str, title: str, uploader: str, duration: int, thumbnail_url: str, local_path: Optional[str] = None):
        """Caches song metadata."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO song_cache 
                    (url, title, uploader, duration, thumbnail_url, local_path, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (url, title, uploader, duration, thumbnail_url, local_path, datetime.now().isoformat()))
                conn.commit()
        except Exception as e:
            log.error(f"Error setting cache for {url}: {e}")

    def update_cache_path(self, url: str, local_path: str):
        """Updates just the local path of a cached song."""
        try:
            with self._get_connection() as conn:
                conn.execute("UPDATE song_cache SET local_path = ?, last_updated = ? WHERE url = ?", (local_path, datetime.now().isoformat(), url))
                conn.commit()
        except Exception as e:
            log.error(f"Error updating cache path for {url}: {e}")

    def clear_cache_metadata(self):
        """Purges old song metadata from cache."""
        try:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM song_cache")
                conn.commit()
        except Exception as e:
            log.error(f"Error clearing cache DB: {e}")

    def get_all_cached_urls(self) -> List[str]:
        """Returns all URLs that have cached files."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT url FROM song_cache WHERE local_path IS NOT NULL")
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            log.error(f"Error fetching cached URLs: {e}")
            return []

    def cache_song(self, song: Song, local_path: Optional[str] = None):
        """Convenience wrapper to cache a Song object."""
        if song and song.path:
            self.set_cache(
                url=song.path,
                title=song.title or "",
                uploader=song.uploader or "Unknown",
                duration=song.duration,
                thumbnail_url=song.thumbnail_url or "",
                local_path=local_path
            )

    def set_cache_batch(self, songs_data: List[Dict[str, Any]]):
        """Atomically inserts or replaces a batch of song metadata in a single transaction."""
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
                    now_iso
                )
                for d in songs_data
                if (d.get("url") or d.get("path"))
            ]
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.executemany("""
                    INSERT OR REPLACE INTO song_cache 
                    (url, title, uploader, duration, thumbnail_url, local_path, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, rows)
                conn.commit()
        except Exception as e:
            log.error(f"Error in set_cache_batch: {e}")

    def clear_cache(self):
        """Resets the local_path for all cached songs, effectively clearing the physical cache reference."""
        try:
            with self._get_connection() as conn:
                conn.execute("UPDATE song_cache SET local_path = NULL")
                conn.commit()
        except Exception as e:
            log.error(f"Error resetting local_path in cache DB: {e}")

    # --- History Methods ---
    def add_history(self, song: Song):
        """Saves a song to the history table and prunes old entries beyond MAX_HISTORY_ENTRIES."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO history 
                    (title, path, uploader, duration, thumbnail_url, is_external, requested_by, user_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    song.title, song.path, song.uploader, song.duration, 
                    song.thumbnail_url, song.is_external, song.requested_by, str(song.user_id) if song.user_id else None
                ))
                # Prune old history entries if over limit
                cursor.execute("""
                    DELETE FROM history WHERE id NOT IN (
                        SELECT id FROM history ORDER BY id DESC LIMIT ?
                    )
                """, (self.MAX_HISTORY_ENTRIES,))
                conn.commit()
        except Exception as e:
            log.error(f"Error adding to history DB: {e}")

    def has_history(self) -> bool:
        """Fast O(1) check whether any history records exist."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM history LIMIT 1")
                return cursor.fetchone() is not None
        except Exception as e:
            log.error(f"Error checking has_history in DB: {e}")
            return False

    def get_history_count(self) -> int:
        """Returns total count of history records."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM history")
                row = cursor.fetchone()
                return row[0] if row else 0
        except Exception as e:
            log.error(f"Error checking get_history_count in DB: {e}")
            return 0

    def increment_stat(self, key: str):
        """Increments a global counter for analytics."""
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO system_stats (key, value) VALUES (?, 1)
                    ON CONFLICT(key) DO UPDATE SET value = value + 1
                """, (key,))
                conn.commit()
        except Exception as e:
            log.warning(f"Failed to increment system stat '{key}': {e}")

    def get_history_latest(self, offset: int = 0) -> Optional[Song]:
        """Returns the history entry at the given offset (0 = latest) without deleting."""
        if offset < 0:
            return None
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM history ORDER BY id DESC LIMIT 1 OFFSET ?", (offset,))
                row = cursor.fetchone()
                if row:
                    return Song.from_dict(dict(row))
                return None
        except Exception as e:
            log.error(f"Error getting history item from DB: {e}")
            return None

    def pop_history_latest(self) -> Optional[Song]:
        """Fetches and deletes the most recent history entry."""
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM history ORDER BY id DESC LIMIT 1")
                row = cursor.fetchone()
                if row:
                    song = Song.from_dict(dict(row))
                    cursor.execute("DELETE FROM history WHERE id = ?", (row["id"],))
                    conn.commit()
                    return song
                return None
        except Exception as e:
            log.error(f"Error popping history from DB: {e}")
            return None

    def get_history(self, limit: Optional[int] = None) -> List[Song]:
        """Retrieves history entries, using index for fast retrieval."""
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                if limit:
                    cursor.execute("SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,))
                else:
                    cursor.execute("SELECT * FROM history ORDER BY id DESC")
                rows = cursor.fetchall()
                return [Song.from_dict(dict(row)) for row in rows]
        except Exception as e:
            log.error(f"Error getting history from DB: {e}")
            return []

    def clear_history(self):
        try:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM history")
                conn.commit()
        except Exception as e:
            log.error(f"Error clearing history DB: {e}")

    # --- Favorites Methods ---
    def add_favorite(self, user_id: str, song: Song):
        if not song or not song.path:
            return
            
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO favorites 
                    (user_id, path, title, uploader, duration, thumbnail_url, is_external)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    str(user_id), song.path, song.title, song.uploader, 
                    song.duration, song.thumbnail_url, song.is_external
                ))
                conn.commit()
        except Exception as e:
            log.error(f"Error adding favorite to DB: {e}")

    def remove_favorite(self, user_id: str, path: str):
        try:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM favorites WHERE user_id = ? AND path = ?", (str(user_id), path))
                conn.commit()
        except Exception as e:
            log.error(f"Error removing favorite from DB: {e}")

    def is_favorite(self, user_id: str, path: str) -> bool:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM favorites WHERE user_id = ? AND path = ?", (str(user_id), path))
                return cursor.fetchone() is not None
        except Exception:
            return False

    def get_favorites(self, user_id: str) -> List[Song]:
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM favorites WHERE user_id = ?", (str(user_id),))
                rows = cursor.fetchall()
                return [Song.from_dict(dict(row)) for row in rows]
        except Exception as e:
            log.error(f"Error getting favorites from DB: {e}")
            return []

    def get_favorite_count(self, user_id: str) -> int:
        """Returns the number of favorites saved by a user."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM favorites WHERE user_id = ?", (str(user_id),))
                row = cursor.fetchone()
                return row[0] if row else 0
        except Exception as e:
            log.error(f"Error getting favorite count from DB: {e}")
            return 0

    def clear_favorites(self, user_id: str):
        try:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM favorites WHERE user_id = ?", (str(user_id),))
                conn.commit()
        except Exception as e:
            log.error(f"Error clearing favorites DB: {e}")
