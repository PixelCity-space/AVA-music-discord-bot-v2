import asyncio
import random
import discord
from ui.i18n import t, init_translate
from core.actions import RadioState
from core.models import Song
from ui.views.player import WelcomeLayout, FrequencyStationView, NowPlayingView
from ui.context import UIContext
from ui.utils import safe_delete_message, safe_fetch_message
from utils.logger import log


class UIManager:
    def __init__(self, bot: discord.Client, config, radio):
        self.bot = bot
        self.config = config
        self.radio = radio
        self._ui_lock = asyncio.Lock()
        self._last_cleanup = 0.0
        self._last_presence_sig = None
        self._last_station_sig = None
        self._last_player_sig = None
        self._last_voice_status = None
        self._cleanup_task: asyncio.Task | None = None
        self._update_pending = False
        self._pending_args: tuple[Song | None, int | None, bool] | None = None

        # Initialize UI context object for dependency injection
        self.context = UIContext(
            bot=self.bot,
            config=self.config,
            update_callback=self.update_now_playing
        )

        # Initialize sub-systems
        init_translate(radio)

    async def update_now_playing(self, song: Song | None, force_channel_id: int | None = None, force_cleanup: bool = False):
        """Public entry point for UI updates with coalescing so rapid bursts merge into the latest state."""
        if self._ui_lock.locked():
            self._pending_args = (song, force_channel_id, force_cleanup or bool(self._pending_args and self._pending_args[2]))
            self._update_pending = True
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

    async def _update_ui_internal(self, song: Song | None, force_channel_id: int | None = None, force_cleanup: bool = False):
        """Internal UI rendering logic."""
        try:
            if isinstance(song, dict):
                song = None

            has_no_song = song is None or not song.path
            show_player = bool(not has_no_song or self.radio.voice_channel_id)

            if not self.bot or self.bot.is_closed():
                return

            # 1. Presence & Channel Status Updates (with deduplication)
            await self._update_presence(song)
            await self._update_channel_status(song, force_channel_id=force_channel_id)

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
            self._schedule_cleanup(channel, force=force_cleanup or not show_player)

        except Exception as e:
            log.error(f"UIManager update failed: {e}")

    def _schedule_cleanup(self, channel, force: bool = False):
        now = asyncio.get_running_loop().time()
        if not force and (now - self._last_cleanup < self.config.ui_cleanup_frequency):
            return
        if self._cleanup_task and not self._cleanup_task.done():
            if not force:
                return
            self._cleanup_task.cancel()

        async def _delayed_cleanup():
            try:
                await asyncio.sleep(0.5)
                await self._cleanup_stray_messages(channel, force=force)
            except asyncio.CancelledError:
                pass

        self._cleanup_task = self.radio.create_task(_delayed_cleanup(), name="ui_stray_cleanup")

    async def _update_presence(self, song: Song | None):
        try:
            if self.radio.status == RadioState.PLAYING and song:
                current_sig = f"PLAYING:{song.title}"
                if current_sig != self._last_presence_sig:
                    activity = discord.Activity(
                        type=discord.ActivityType.listening,
                        name=song.title or t('unknown')
                    )
                    await self.bot.change_presence(activity=activity)
                    self._last_presence_sig = current_sig
            else:
                if self.radio.status == RadioState.PAUSED:
                    msg_src = t('holding_rhythm')
                elif self.radio.status == RadioState.IDLE:
                    msg_src = t('waiting_melody')
                else:
                    msg_src = t('at_command')

                final_msg = random.choice(msg_src) if isinstance(msg_src, list) else msg_src
                current_sig = f"{self.radio.status.name}:{final_msg}"
                if current_sig != self._last_presence_sig:
                    await self.bot.change_presence(activity=discord.Game(name=final_msg))
                    self._last_presence_sig = current_sig
        except Exception as e:
            log.debug(f"Presence update failed: {e}")

    async def _update_channel_status(self, song: Song | None, force_channel_id: int | None = None):
        """Updates the Voice Channel's status text (if enabled)."""
        if not self.config.update_voice_status:
            return

        try:
            target_id = force_channel_id or self.radio.voice_channel_id
            if not target_id:
                return

            channel = self.bot.get_channel(target_id)
            if not channel:
                channel = await self.bot.fetch_channel(target_id)

            if not channel or not isinstance(channel, discord.VoiceChannel):
                return

            if self.radio.status == RadioState.PLAYING and song:
                status_text = t('channel_status_playing', TITLE=song.title)
            else:
                status_text = None

            status_sig = (target_id, status_text)
            if status_sig == self._last_voice_status:
                return

            current_status = getattr(channel, 'status', 'UNKNOWN_ATTR')
            if current_status == 'UNKNOWN_ATTR' or current_status != status_text:
                await channel.edit(status=status_text)
            self._last_voice_status = status_sig

        except Exception as e:
            log.debug(f"Voice channel status update failed: {e}")

    async def _cleanup_stray_messages(self, channel, force=False):
        now = asyncio.get_running_loop().time()
        if not force and (now - self._last_cleanup < self.config.ui_cleanup_frequency):
            return
        self._last_cleanup = now

        try:
            current_station_id = self.radio.station_message.id if self.radio.station_message else None
            current_player_id = self.radio.now_playing_message.id if self.radio.now_playing_message else None
            current_search_id = self.radio.embed_manager.load_message_id("search")

            known_ids = {current_station_id, current_player_id, current_search_id}
            known_ids = {id for id in known_ids if id is not None}

            log.debug(f"[UI] Cleaning up. Known IDs: {known_ids}")

            to_delete = []
            async for msg in channel.history(limit=self.config.message_cleanup_limit):
                if msg.author.id == self.bot.user.id and msg.id not in known_ids:
                    to_delete.append(msg)

            if to_delete:
                if len(to_delete) > 1:
                    try:
                        await channel.delete_messages(to_delete)
                    except Exception:
                        for msg in to_delete:
                            await safe_delete_message(msg)
                else:
                    await safe_delete_message(to_delete[0])
        except Exception as ex:
            log.warning(f"UI Cleanup sweep failed: {ex}")

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
            except Exception:
                self.radio.station_message = await channel.send(view=view)
        else:
            self.radio.station_message = await channel.send(view=view)

        self._last_station_sig = station_sig
        self.radio.embed_manager.save_message_id("station", self.radio.station_message.id)

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

            self.radio.embed_manager.save_message_id("player", None)
            return

        if not self.radio.now_playing_message:
            msg_id = self.radio.embed_manager.load_message_id("player")
            if msg_id:
                fetched = await safe_fetch_message(channel, msg_id)
                if fetched and fetched.author.id == self.bot.user.id:
                    self.radio.now_playing_message = fetched
                else:
                    self.radio.now_playing_message = None

        player_sig = self._compute_player_signature(song)
        if self.radio.now_playing_message and player_sig == self._last_player_sig:
            return

        player_view = NowPlayingView(self.radio, song=song, context=self.context)

        if self.radio.now_playing_message:
            try:
                await self.radio.now_playing_message.edit(embed=None, view=player_view)
            except Exception:
                self.radio.now_playing_message = await channel.send(view=player_view)
        else:
            self.radio.now_playing_message = await channel.send(view=player_view)

        self._last_player_sig = player_sig
        self.radio.embed_manager.save_message_id("player", self.radio.now_playing_message.id)

    async def force_new_embed(self):
        """Immediately clears message IDs and triggers a fresh UI build."""
        async with self._ui_lock:
            self.radio.now_playing_message = None
            self.radio.station_message = None
            self._last_station_sig = None
            self._last_player_sig = None
            self._last_voice_status = None

            self.radio.embed_manager.clear_message_ids("player", "station", "search")

            await self._update_ui_internal(self.radio.current_song, force_cleanup=True)

    async def refresh_all_uis(self):
        """Triggers a lock-safe update of the current UI state."""
        await self.update_now_playing(self.radio.current_song)

    async def clear_voice_status(self, channel_id: int):
        """Public method to clear the status of a specific voice channel."""
        async with self._ui_lock:
            await self._update_channel_status(None, force_channel_id=channel_id)
