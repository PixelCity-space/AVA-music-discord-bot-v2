import asyncio
from typing import Optional, TYPE_CHECKING
from core.models import Song
from utils.logger import log

if TYPE_CHECKING:
    from core.state import RadioManager

class PrefetchService:
    """Handles background pre-resolving and cache downloading of upcoming tracks for gapless playback."""
    
    def __init__(self, radio: 'RadioManager'):
        self.radio = radio
        self.prefetched_song: Optional[Song] = None
        self.prefetch_task: Optional[asyncio.Task] = None

    def reset(self):
        """Resets the prefetch state between tracks and cancels any in-flight task."""
        if self.prefetch_task and not self.prefetch_task.done():
            self.prefetch_task.cancel()
        self.prefetched_song = None
        self.prefetch_task = None

    def trigger_prefetch(self, next_song: Song):
        """Starts a background prefetch task for the next song."""
        if not next_song or self.prefetched_song == next_song:
            return
            
        self.prefetched_song = next_song
        self.prefetch_task = asyncio.create_task(self._prefetch_next_track(next_song))

    async def _prefetch_next_track(self, song: Song):
        """Pre-resolves stream URL and downloads audio for upcoming track in background."""
        if not song or self.radio.is_cached(song):
            return
            
        try:
            log.info(f"[PREFETCH] Pre-buffering next track: {song.title or song.path}")
            if song.is_external and not song.stream_url and not song.is_resolving:
                from providers import resolve_any
                resolved = await resolve_any(song.path, self.radio.providers)
                if resolved:
                    song.update(resolved)
                    song.cache_to_db(self.radio.db)
                    log.info(f"[PREFETCH] Stream URL resolved ahead of time for: {song.title}")
            
            if song.is_external and not self.radio.is_cached(song):
                await self.radio.start_cache_download(song)
        except Exception as e:
            log.warning(f"[PREFETCH] Error pre-buffering {song.title or song.path}: {e}")
