import asyncio
import discord
from ui.i18n import init_translate
from core.actions import RadioState
from core.models import Song
from ui.cleanup import ChannelCleaner
from ui.context import UIContext
from ui.presence import PresenceManager
from ui.utils import safe_delete_message, safe_fetch_message
from ui.views.player import NowPlayingView
from ui.views.station import FrequencyStationView, WelcomeLayout
from utils.logger import log


class UIManager:
    """Coordinates persistent station and player message rendering with burst coalescing."""

    def __init__(self, bot: discord.Client, config, radio):
        self.bot = bot
        self.config = config
        self.radio = radio
        self._ui_lock = asyncio.Lock()
        self._last_station_sig = None
        self._last_player_sig = None
        self._update_pending = False
        self._pending_args: tuple[Song | None, int | None, bool] | None = None

        self.presence = PresenceManager(bot, config, radio)
        self.cleaner = ChannelCleaner(bot, config, radio)

        # Initialize UI context object for dependency injection
        self.context = UIContext(
            bot=self.bot,
            config=self.config,
            update_callback=self.update_now_playing,
        )

        # Initialize sub-systems
        init_translate(radio)

    async def update_now_playing(
        self, song: Song | None, force_channel_id: int | None = None, force_cleanup: bool = False
    ):
        """Public entry point for UI updates with coalescing so rapid bursts merge into the latest state."""
        if self._ui_lock.locked():
            self._pending_args = (
                song,
                force_channel_id,
                force_cleanup or bool(self._pending_args and self._pending_args[2]),
            )
            self._update_pending = True
            log.debug("[UI] Coalescing concurrent UI update request.")
            return

        async with self._ui_lock:
            await self._update_ui_internal(song, force_channel_id=force_channel_id, force_cleanup=force_cleanup)
            while self._update_pending:
                self._update_pending = False
                pending = self._pending_args
                self._pending_args = None
                if pending:
                    p_song, p_chan_id, p_force = pending
                    await self._update_ui_internal(p_song, force_channel_id=p_chan_id, force_cleanup=p_force)

    async def _update_ui_internal(
        self, song: Song | None, force_channel_id: int | None = None, force_cleanup: bool = False
    ):
        """Internal UI rendering logic."""
        try:
            if isinstance(song, dict):
                song = None

            has_no_song = song is None or not song.path
            show_player = bool(not has_no_song or self.radio.voice_channel_id)

            if not self.bot or self.bot.is_closed():
                return

            # 1. Presence & Channel Status Updates (with deduplication)
            await self.presence.update(song, force_channel_id=force_channel_id)

            channel = self.bot.get_channel(self.config.radio_text_channel_id)
            if not channel:
                try:
                    channel = await self.bot.fetch_channel(self.config.radio_text_channel_id)
                except Exception as e:
                    log.error(f"UI Manager could not find radio channel {self.config.radio_text_channel_id}: {e}")
                    return

            # 2. Handle Station Message (Header, diff-checked to skip redundant edits)
            await self._render_station_message(channel)

            # 3. Handle Player Message (Centerpiece)
            await self._render_player_message(channel, song, show_player)

            # 4. Schedule non-blocking stray message cleanup outside _ui_lock
            self.cleaner.schedule(channel, force=force_cleanup or not show_player)

        except Exception as e:
            log.error(f"UIManager update failed: {e}", exc_info=True)

    def _compute_station_signature(self):
        guild = self.context.get_guild()
        if guild:
            afk_id = self.radio.config.afk_channel_id
            vc_sig = tuple(
                (c.id, c.name)
                for c in sorted(guild.voice_channels, key=lambda c: c.position)
                if c.id != afk_id
            )[:25]
        else:
            vc_sig = ()
        return (bool(self.radio.voice_channel_id), self.radio.language, self.radio.is_compact, vc_sig)

    async def _render_station_message(self, channel):
        if not self.radio.station_message:
            msg_id = self.radio.embed_manager.load_message_id("station")
            if msg_id:
                fetched = await safe_fetch_message(channel, msg_id)
                if fetched and fetched.author.id == self.bot.user.id:
                    self.radio.station_message = fetched
                else:
                    log.debug(f"[UI] Stored station message {msg_id} unavailable; will post new message.")
                    self.radio.station_message = None

        station_sig = self._compute_station_signature()
        if self.radio.station_message and station_sig == self._last_station_sig:
            return

        if not self.radio.voice_channel_id:
            view = WelcomeLayout(self.radio, context=self.context)
        else:
            view = FrequencyStationView(self.radio, context=self.context)

        if self.radio.station_message:
            try:
                await self.radio.station_message.edit(view=view)
            except Exception as e:
                log.warning(f"[UI] Station message edit failed, sending replacement: {e}")
                self.radio.station_message = await channel.send(view=view)
        else:
            self.radio.station_message = await channel.send(view=view)

        self._last_station_sig = station_sig
        em = self.radio.embed_manager
        if hasattr(em, "save_message_id_async"):
            await em.save_message_id_async("station", self.radio.station_message.id)
        else:
            em.save_message_id("station", self.radio.station_message.id)

    def _compute_player_signature(self, song: Song | None) -> tuple:
        active_song = song or self.radio.current_song
        elapsed = int(self.radio.elapsed_seconds)

        last_user_id = self.radio.last_user.id if self.radio.last_user else None
        target_fav_uid = (str(last_user_id) if last_user_id else None) or (active_song.user_id if active_song else None)
        is_fav = bool(active_song and target_fav_uid and self.radio.fav_manager.is_favorite(target_fav_uid, active_song))

        return (
            self.radio.status,
            active_song.path if active_song else None,
            active_song.title if active_song else None,
            active_song.is_resolving if active_song else None,
            active_song.duration if active_song else 0,
            elapsed if self.radio.status == RadioState.PLAYING else 0,
            self.radio.loop_mode,
            self.radio.loop_queue_mode,
            self.radio.is_compact,
            self.radio.language,
            self.radio.voice_channel_id,
            last_user_id,
            self.radio.has_history,
            is_fav,
        )

    async def _render_player_message(self, channel, song, show_player):
        if not channel:
            return

        if not show_player:
            self._last_player_sig = None
            msg_id = self.radio.embed_manager.load_message_id("player")
            if self.radio.now_playing_message:
                if self.radio.now_playing_message.author.id == self.bot.user.id:
                    await safe_delete_message(self.radio.now_playing_message)
                self.radio.now_playing_message = None
            elif msg_id:
                m = await safe_fetch_message(channel, msg_id)
                if m and m.author.id == self.bot.user.id:
                    await safe_delete_message(m)

            em = self.radio.embed_manager
            if hasattr(em, "save_message_id_async"):
                await em.save_message_id_async("player", None)
            else:
                em.save_message_id("player", None)
            return

        if not self.radio.now_playing_message:
            msg_id = self.radio.embed_manager.load_message_id("player")
            if msg_id:
                fetched = await safe_fetch_message(channel, msg_id)
                if fetched and fetched.author.id == self.bot.user.id:
                    self.radio.now_playing_message = fetched
                else:
                    log.debug(f"[UI] Stored player message {msg_id} unavailable; will post new message.")
                    self.radio.now_playing_message = None

        player_sig = self._compute_player_signature(song)
        if self.radio.now_playing_message and player_sig == self._last_player_sig:
            return

        player_view = NowPlayingView(self.radio, song=song, context=self.context)

        if self.radio.now_playing_message:
            try:
                await self.radio.now_playing_message.edit(embed=None, view=player_view)
            except Exception as e:
                log.warning(f"[UI] Player message edit failed, sending replacement: {e}")
                self.radio.now_playing_message = await channel.send(view=player_view)
        else:
            self.radio.now_playing_message = await channel.send(view=player_view)

        self._last_player_sig = player_sig
        em = self.radio.embed_manager
        if hasattr(em, "save_message_id_async"):
            await em.save_message_id_async("player", self.radio.now_playing_message.id)
        else:
            em.save_message_id("player", self.radio.now_playing_message.id)

    async def update_progress(self):
        """Lightweight progress-only tick that skips station, presence, and channel cleanup work."""
        if self._ui_lock.locked() or self.radio.status != RadioState.PLAYING or not self.radio.now_playing_message:
            return
        if not self.bot or self.bot.is_closed():
            return
        async with self._ui_lock:
            if self.radio.status != RadioState.PLAYING or not self.radio.now_playing_message:
                return
            channel = self.bot.get_channel(self.config.radio_text_channel_id)
            if not channel:
                try:
                    channel = await self.bot.fetch_channel(self.config.radio_text_channel_id)
                except Exception as e:
                    log.warning(f"[UI] Progress update could not fetch radio channel {self.config.radio_text_channel_id}: {e}")
                    return
            await self._render_player_message(channel, self.radio.current_song, show_player=True)

    async def force_new_embed(self):
        """Immediately clears message IDs and triggers a fresh UI build."""
        async with self._ui_lock:
            self.radio.now_playing_message = None
            self.radio.station_message = None
            self._last_station_sig = None
            self._last_player_sig = None
            self.presence.reset_voice_status_cache()

            em = self.radio.embed_manager
            if hasattr(em, "clear_message_ids_async"):
                await em.clear_message_ids_async("player", "station", "search")
            else:
                em.clear_message_ids("player", "station", "search")

            await self._update_ui_internal(self.radio.current_song, force_cleanup=True)

    async def refresh_all_uis(self):
        """Triggers a lock-safe update of the current UI state."""
        await self.update_now_playing(self.radio.current_song)

    async def clear_voice_status(self, channel_id: int):
        """Public method to clear the status of a specific voice channel."""
        async with self._ui_lock:
            await self.presence.update_channel_status(None, force_channel_id=channel_id)
