import time

from core.database import Database
from core.models import Song
from utils.logger import log


class FavoriteManager:
    MAX_USER_FAVORITES = 250
    RATE_LIMIT_SECONDS = 0.8

    def __init__(self, db: Database):
        self.db = db
        self._user_last_toggle: dict[str, float] = {}

    def is_favorite(self, user_id: str | int, song: Song) -> bool:
        if not song or not song.path:
            return False
        return self.db.is_favorite(str(user_id), song.path)

    def toggle_favorite(self, user_id: str | int, song: Song) -> bool:
        """Returns True if added, False if removed (or rate-limited / capped)."""
        if not song or not song.path:
            return False
            
        u_id = str(user_id)
        now = time.time()
        last_time = self._user_last_toggle.get(u_id, 0.0)
        if now - last_time < self.RATE_LIMIT_SECONDS:
            log.warning(f"[RATE_LIMIT] User {u_id} toggled favorite too quickly.")
            return self.is_favorite(u_id, song)
        self._user_last_toggle[u_id] = now

        if self.db.is_favorite(u_id, song.path):
            self.db.remove_favorite(u_id, song.path)
            return False
        # Check user favorites quota
        current_count = self.db.get_favorite_count(u_id)
        if current_count >= self.MAX_USER_FAVORITES:
            log.warning(f"[QUOTA] User {u_id} reached max favorites limit ({self.MAX_USER_FAVORITES}).")
            return False

        self.db.add_favorite(u_id, song)
        song.cache_to_db(self.db)
        return True

    def get_favorites(self, user_id: str | int) -> list[Song]:
        return self.db.get_favorites(str(user_id))

    def clear_favorites(self, user_id: str | int):
        """Removes all favorites for a specific user."""
        self.db.clear_favorites(str(user_id))
