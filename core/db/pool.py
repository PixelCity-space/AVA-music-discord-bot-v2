import os
import queue
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager, suppress


class SQLiteConnectionPool:
    """
    Thread-safe connection pool for SQLite to eliminate per-query connect/disconnect overhead.
    Preconfigures synchronous=NORMAL and in-memory temp stores per connection.
    """

    def __init__(self, db_path: str, max_connections: int = 5, timeout: float = 10.0):
        self.db_path = db_path
        self.max_connections = max_connections
        self.timeout = timeout
        self._pool: queue.Queue[sqlite3.Connection] = queue.Queue(maxsize=max_connections)
        self._all_connections: list[sqlite3.Connection] = []
        self._is_closed = False

        for _ in range(max_connections):
            conn = self._create_connection()
            self._all_connections.append(conn)
            self._pool.put(conn)

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
            timeout=self.timeout,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        return conn

    @property
    def is_closed(self) -> bool:
        return self._is_closed

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


def init_schema(pool: SQLiteConnectionPool):
    """Initializes SQLite WAL mode, tables, performance indices, and migrations."""
    os.makedirs(os.path.dirname(pool.db_path), exist_ok=True) if os.path.dirname(pool.db_path) else None
    with pool.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")

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
        with suppress(sqlite3.OperationalError):
            cursor.execute("ALTER TABLE song_cache ADD COLUMN local_path TEXT")

        # 2. Playback History
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

        # 6. Performance Indices
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_id_desc ON history (id DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_user ON history (user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_played ON history (played_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_song_cache_updated ON song_cache (last_updated DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fav_user ON favorites (user_id)")
        conn.commit()

        # Migrations for existing history schemas
        for col in ("requested_by TEXT", "user_id TEXT"):
            with suppress(sqlite3.OperationalError):
                cursor.execute(f"ALTER TABLE history ADD COLUMN {col}")
        conn.commit()

