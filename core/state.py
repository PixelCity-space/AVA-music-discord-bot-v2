import asyncio
import inspect
import discord
from typing import List, Optional, Callable
from core.actions import RadioState, RadioAction, RadioActionData
from core.models import Song
from core.embed_state import EmbedStateManager
from core.database import Database
from core.queue_manager import QueueManager
from services.favorites import FavoriteManager
from services.history import HistoryManager
from services.cache_service import CacheService
from services.permissions import PermissionService
from services.command_service import CommandService
from services.track_resolver import TrackResolverService
from providers import get_providers
from utils.logger import log

class RadioManager:
    """
    Central state coordinator and action dispatcher for the Radio Bot.
    Decoupled from direct audio streaming and UI rendering.
    """
    def __init__(self, config, instance_name: str = ""):
        self.config = config
        self.instance_name = instance_name
        self.embed_manager = EmbedStateManager(instance_name=instance_name)
        self.providers = get_providers(config)
        
        # Persistence & Services
        self.db = Database(config.database_path)
        self.fav_manager = FavoriteManager(self.db)
        self.history_manager = HistoryManager(self.db, max_size=config.history_limit)
        self.cache_service = CacheService(config, self.db)
        self.permission_service = PermissionService(config)
        self.command_service = CommandService(self)
        self.resolver = TrackResolverService(self.db, self.providers)
        
        # Connection State
        self.voice: Optional[discord.VoiceClient] = None
        self.voice_channel_id: Optional[int] = None
        
        # Playback & Queue State
        self.status = RadioState.IDLE
        self.current_song: Optional[Song] = None
        self.queue_manager = QueueManager()
        self.volume: float = config.default_volume
        self.station_message: Optional[discord.Message] = None
        self.now_playing_message: Optional[discord.Message] = None

        # UI State
        self.language: str = config.default_language
        self.is_compact: bool = (config.default_ui_mode == "compact")
        self.show_queue: bool = False

        self.volume_muted: bool = False
        
        # Progress Tracking
        self.track_start_time: Optional[float] = None
        self.track_start_offset: float = 0.0
        self.seek_position: Optional[float] = None
        self.is_seeking: bool = False
        
        # Internal Queues & Locks
        self.action_queue = asyncio.Queue()
        self._action_event = asyncio.Event()
        self._background_tasks: set[asyncio.Task] = set()
        self.last_user: Optional[discord.Member | discord.User] = None
        self.task: Optional[asyncio.Task] = None

        # Callbacks (set by UIManager / Player)
        self.on_state_change: Optional[Callable] = None

    def create_task(self, coro, name: Optional[str] = None) -> asyncio.Task:
        """Creates, retains strong reference, and tracks a background task with unhandled exception logging."""
        task = asyncio.create_task(coro, name=name)
        self._background_tasks.add(task)

        def _on_done(t: asyncio.Task):
            self._background_tasks.discard(t)
            if not t.cancelled():
                exc = t.exception()
                if exc:
                    log.error(f"[TASK] Unhandled exception in background task '{t.get_name()}': {exc}", exc_info=exc)

        task.add_done_callback(_on_done)
        return task

    async def close(self):
        """Cancels and awaits all active background tasks and closes the database connection pool."""
        if self._background_tasks:
            log.info(f"[RADIO] Draining {len(self._background_tasks)} background tasks...")
            for task in list(self._background_tasks):
                if not task.done():
                    task.cancel()
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()
        
        # Close providers (thread pools) and database connection pool
        for provider in self.providers:
            if hasattr(provider, "close"):
                provider.close()
        self.db.close()

    # --- Queue & Navigation delegates (backward-compatible properties) ---
    @property
    def queue(self) -> List[Song]:
        return self.queue_manager.queue

    @queue.setter
    def queue(self, value: List[Song]):
        self.queue_manager.queue = value

    @property
    def future_queue(self) -> List[Song]:
        return self.queue_manager.future_queue

    @future_queue.setter
    def future_queue(self, value: List[Song]):
        self.queue_manager.future_queue = value

    @property
    def is_navigating(self) -> bool:
        return self.queue_manager.is_navigating

    @is_navigating.setter
    def is_navigating(self, value: bool):
        self.queue_manager.is_navigating = value

    @property
    def history_ptr(self) -> int:
        return self.queue_manager.history_ptr

    @history_ptr.setter
    def history_ptr(self, value: int):
        self.queue_manager.history_ptr = value

    @property
    def loop_mode(self) -> bool:
        return self.queue_manager.loop_mode

    @loop_mode.setter
    def loop_mode(self, value: bool):
        self.queue_manager.loop_mode = value

    @property
    def loop_queue_mode(self) -> bool:
        return self.queue_manager.loop_queue_mode

    @loop_queue_mode.setter
    def loop_queue_mode(self, value: bool):
        self.queue_manager.loop_queue_mode = value

    @property
    def elapsed_seconds(self) -> float:
        """Returns the current playback elapsed time in seconds."""
        elapsed = self.track_start_offset
        if self.track_start_time and self.status == RadioState.PLAYING:
            try:
                elapsed += (asyncio.get_running_loop().time() - self.track_start_time)
            except RuntimeError:
                pass
        return elapsed

    @property
    def has_history(self) -> bool:
        """Fast O(1) probe for history presence."""
        return self.history_manager.has_items()

    @property
    def history(self) -> List[Song]:
        return self.history_manager.history

    # --- Permission delegates ---
    def is_admin(self, user: discord.Member | discord.User) -> bool:
        return self.permission_service.is_admin(user)

    def can_interact(self, user: discord.Member | discord.User) -> bool:
        return self.permission_service.can_interact(user, self)

    # --- Cache delegates ---
    def is_cached(self, song: Song) -> bool:
        return self.cache_service.is_cached(song)

    def get_cache_path(self, song: Song) -> Optional[str]:
        return self.cache_service.get_cache_path(song)

    async def start_cache_download(self, song: Song):
        await self.cache_service.start_cache_download(song, task_creator=self.create_task)

    def cleanup_cache(self):
        self.cache_service.cleanup_cache()

    async def cleanup_cache_async(self):
        await self.cache_service.cleanup_cache_async()

    def clear_cache(self) -> int:
        return self.cache_service.clear_cache()

    async def clear_cache_async(self) -> int:
        return await self.cache_service.clear_cache_async()

    def delete_cache_file(self, song: Song):
        self.cache_service.delete_cache_file(song)

    def _notify_state_change(self):
        if self.on_state_change:
            if inspect.iscoroutinefunction(self.on_state_change):
                self.create_task(self.on_state_change(self.current_song), name="notify_state_change")
            else:
                self.on_state_change(self.current_song)

    # --- Action Dispatcher ---
    def dispatch(self, action: RadioAction, data: RadioActionData = None, user: Optional[discord.Member | discord.User] = None):
        user_str = f" by {user.name}" if user else " (System/Auto)"
        data_str = f" with [{data}]" if data is not None else ""
        log.info(f"[ACTION] {action.name}{data_str}{user_str}")
        if user:
            self.last_user = user
            
        # 1. Direct handling of state, queue, and database actions
        if self._handle_state_action(action, data, user):
            return

        # 2. Forward audio/voice actions to AudioPlayer
        self.action_queue.put_nowait((action, data))
        self._action_event.set()

    def _handle_state_action(self, action: RadioAction, data: RadioActionData, user: Optional[discord.Member | discord.User] = None) -> bool:
        """Handles non-audio state, queue, and database actions directly in RadioManager."""
        if action == RadioAction.ADD_EXT_LINK:
            self.create_task(self._add_external_link(data, user=user or self.last_user), name="add_ext_link")
            return True
        elif action == RadioAction.ADD_SONGS:
            self.create_task(self._add_songs(data, user=user or self.last_user), name="add_songs")
            return True
        elif action == RadioAction.REMOVE_FROM_QUEUE:
            self.queue_manager.remove(data)
            self._notify_state_change()
            return True
        elif action == RadioAction.CLEAR_QUEUE:
            self.queue_manager.clear()
            self._notify_state_change()
            return True
        elif action == RadioAction.MOVE_SONG:
            song, direction = data
            if self.queue_manager.move(song, direction):
                self._notify_state_change()
            return True
        elif action == RadioAction.TOGGLE_FAVORITE:
            user_id, song = data
            self.fav_manager.toggle_favorite(user_id, song)
            self._notify_state_change()
            return True
        elif action == RadioAction.CLEAR_FAVORITES:
            self.fav_manager.clear_favorites(data)
            self._notify_state_change()
            return True
        elif action == RadioAction.CLEAR_HISTORY:
            self.history_manager.clear()
            self.queue_manager.reset_navigation()
            self._notify_state_change()
            return True
        elif action == RadioAction.CLEAR_CACHE:
            self.clear_cache()
            self._notify_state_change()
            return True
        elif action == RadioAction.LOOP:
            self.queue_manager.toggle_loop()
            self._notify_state_change()
            return True
        elif action == RadioAction.LOOP_QUEUE:
            self.queue_manager.toggle_loop_queue()
            self._notify_state_change()
            return True
        elif action == RadioAction.SHUFFLE:
            self.queue_manager.shuffle()
            self._notify_state_change()
            return True
            
        return False

    def _wake_player_if_idle(self):
        if self.status == RadioState.IDLE and self.voice_channel_id:
            self.status = RadioState.PLAYING
            self._action_event.set()

    async def _add_external_link(self, query: str, user: Optional[discord.Member | discord.User] = None):
        """Adds an external link or search query to queue via TrackResolverService."""
        sanitized = self.resolver.sanitize_query(query)
        if not sanitized:
            log.warning(f"[SECURITY] Discarding invalid query: {query}")
            return

        provider = self.resolver.is_matching_provider(sanitized)

        if provider and provider.is_playlist(sanitized):
            log.info(f"[QUEUE] Playlist detected: {sanitized}")
            self.create_task(self._resolve_playlist_task(sanitized, user), name="resolve_playlist")
            return

        song = await self.resolver.prepare_external_song(sanitized, user=user)
        if not song:
            return

        self.queue.append(song)
        log.info(f"[QUEUE] Added: {song.title or song.path}")

        if song.is_resolving:
            self.create_task(self._resolve_link_task(song), name=f"resolve_song_{song.title or song.path}")

        self._wake_player_if_idle()
        self._notify_state_change()

    async def _add_songs(self, songs: List[Song], user: Optional[discord.Member | discord.User] = None):
        if not songs:
            return
        for song in songs:
            if user:
                song.requested_by = user.display_name
                song.user_id = str(user.id)
            self.queue.append(song)
        
        log.info(f"[QUEUE] Added {len(songs)} songs to queue.")
        self._wake_player_if_idle()
        self._notify_state_change()

    async def _resolve_playlist_task(self, url: str, user: Optional[discord.Member | discord.User] = None):
        songs = await self.resolver.resolve_playlist(url, user=user)
        if not songs:
            log.debug(f"[QUEUE] Playlist resolution yielded 0 tracks for: {url}")
            return
        for song in songs:
            self.queue.append(song)
        self._wake_player_if_idle()
        self._notify_state_change()

    async def _resolve_link_task(self, song: Song):
        ok = await self.resolver.resolve_song(song)
        if song == self.current_song:
            self._notify_state_change()
        elif not ok:
            log.debug(f"[QUEUE] Background link resolution failed for queued track: {song.path}")
