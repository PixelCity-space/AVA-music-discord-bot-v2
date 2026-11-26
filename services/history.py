from datetime import datetime

from core.database import Database
from core.models import Song


class HistoryManager:
    def __init__(self, db: Database, max_size: int = 50):
        self.db = db
        self.max_size = max_size

    def add(self, song: Song):
        if not song or not song.path:
            return
            
        if not song.played_at:
            song.played_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        self.db.add_history(song)

    def get_all(self, limit: int | None = None) -> list[Song]:
        """Returns items from the DB. Defaults to no limit if None."""
        return self.db.get_history(limit=limit)

    def clear(self):
        """Removes all items from history."""
        self.db.clear_history()

    def get_latest(self, offset: int = 0) -> Song | None:
        """Returns the history entry at the given offset (0 = latest) without deleting."""
        return self.db.get_history_latest(offset=offset)

    def pop_latest(self) -> Song | None:
        """Fetches and deletes the most recent history entry. (Legacy/Manual use)"""
        return self.db.pop_history_latest()

    def has_items(self) -> bool:
        """O(1) check if history contains any items."""
        return self.db.has_history()

    @property
    def history(self) -> list[Song]:
        """Bounded history access for UI and commands (defaults to max_size limit)."""
        return self.get_all(limit=self.max_size)
