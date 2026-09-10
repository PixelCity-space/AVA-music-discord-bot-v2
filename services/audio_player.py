import time
import asyncio
import traceback
import discord
from typing import Optional, Callable, TYPE_CHECKING
from core.actions import RadioState
from core.models import Song
from utils.logger import log
from services.player import (
    VoiceManager,
    AudioSourceFactory,
    PrefetchService,
    PlaybackActionHandler
)

if TYPE_CHECKING:
    from core.state import RadioManager

class RadioPlayer:
    """
    Main audio playback orchestrator for RadioBot.
    Coordinates voice connection, audio source extraction, gapless prebuffering, and action dispatching.
    """
    def __init__(self, bot: discord.Client, config, radio: 'RadioManager', 
                 update_ui_callback: Callable, refresh_ui_callback: Callable, 
                 cleanup_ui_callback: Optional[Callable] = None):
        self.bot = bot
        self.config = config
        self.radio = radio
        self.update_ui = update_ui_callback
        self.refresh_ui = refresh_ui_callback
        self.cleanup_ui = cleanup_ui_callback
        
        # Modular sub-services
        self.voice_manager = VoiceManager(bot, config, radio, cleanup_ui_callback=cleanup_ui_callback)
        self.source_factory = AudioSourceFactory(config, radio)
        self.prefetcher = PrefetchService(radio)
        self.action_handler = PlaybackActionHandler(bot, radio, self.voice_manager, update_ui_callback)
        
        self.last_cache_cleanup = 0.0
        self.radio.on_state_change = self.update_ui

    async def ensure_voice(self) -> Optional[discord.VoiceClient]:
        """Delegates voice connection verification to VoiceManager."""
        return await self.voice_manager.ensure_voice()

    async def run_loop(self):
        """Main player lifecycle loop."""
        await self.bot.wait_until_ready()
        
        while not self.bot.is_closed():
            try:
                voice = await self.ensure_voice()
                
                # 1. State: DISCONNECTED
                if not voice:
                    await self._handle_disconnected_state()
                    continue

                # 2. Monitor Solitary Status (alone in voice channel)
                if await self.voice_manager.check_solitary_timeout(voice):
                    continue

                # 3. State: IDLE, STOPPED, or PAUSED
                if self.radio.status in [RadioState.IDLE, RadioState.STOPPED, RadioState.PAUSED]:
                    if await self._handle_idle_state(voice):
                        continue

                # 4. State: PLAYING (Song Selection & Start)
                if self.radio.status == RadioState.PLAYING:
                    await self._start_playback(voice)
                
                # 5. Periodic cache cleanup
                if time.time() - self.last_cache_cleanup > 3600:
                    self.radio.cleanup_cache()
                    self.last_cache_cleanup = time.time()

                # 6. Safety sleep to prevent busy-waiting
                await asyncio.sleep(self.config.player_loop_sleep)

            except Exception as e:
                log.error(f"Player crash: {e}")
                log.error(traceback.format_exc())
                await asyncio.sleep(self.config.error_retry_seconds)

    async def _handle_disconnected_state(self):
        """Logic when voice is not connected."""
        self.voice_manager.solitary_start = None
        try:
            action, data = await asyncio.wait_for(self.radio.action_queue.get(), timeout=self.config.action_timeout)
            await self.action_handler.handle_disconnected_action(action, data)
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            log.error(f"[PLAYER] Error in disconnected state handler: {e}")

    async def _handle_idle_state(self, voice: discord.VoiceClient) -> bool:
        """Logic when voice is connected but nothing is playing."""
        try:
            action, data = await asyncio.wait_for(self.radio.action_queue.get(), timeout=self.config.action_timeout)
            self.voice_manager.solitary_start = None
            return await self.action_handler.handle_idle_action(action, data, voice)
        except asyncio.TimeoutError:
            return True

    async def _start_playback(self, voice: discord.VoiceClient):
        """Prepares, buffers and starts audio streaming for the upcoming song."""
        self.prefetcher.reset()
        
        # 1. Queue popping & Song Selection
        if not self.radio.current_song or not self.radio.is_seeking:
            if self.radio.loop_mode and self.radio.current_song and not self.radio.is_navigating:
                log.info(f"[PLAYER] Loop Mode active. Replaying: {self.radio.current_song.title}")
                self.radio.is_seeking = True
                self.radio.seek_position = 0
            elif self.radio.future_queue:
                self.radio.current_song = self.radio.future_queue.pop(0)
                self.radio.is_navigating = True
                self.radio.history_ptr -= 1
            elif self.radio.queue:
                if self.radio.loop_queue_mode and self.radio.current_song and not self.radio.is_navigating:
                    self.radio.queue.append(self.radio.current_song)
                
                self.radio.current_song = self.radio.queue.pop(0)
                self.radio.is_navigating = False
                self.radio.history_ptr = 0
            else:
                if self.radio.loop_queue_mode and self.radio.current_song and not self.radio.is_navigating:
                    # Single song in queue loop rotation; replay it safely
                    log.info(f"[PLAYER] Loop Queue active with single track. Replaying: {self.radio.current_song.title}")
                    self.radio.is_seeking = True
                    self.radio.seek_position = 0
                else:
                    if voice and voice.is_playing():
                        log.warning("[PLAYER] Queue empty but voice still playing. Delaying IDLE state.")
                        await asyncio.sleep(1.0)
                        return

                    self.radio.status = RadioState.IDLE
                    self.radio.current_song = None
                    self.radio.is_navigating = False
                    self.radio.history_ptr = 0
                    await self.update_ui(None)
                    return
        
        song = self.radio.current_song
        self.radio.status = RadioState.BUFFERING
        await self.update_ui(song)
        
        if self.radio.is_seeking and song and song.is_external:
            log.info(f"[PLAYER] Re-resolving stream for: {song.title}")
            song.stream_url = None
            
        self.radio.is_seeking = False
        
        # 2. Source resolution (Local Cache vs Stream URL)
        source_path = await self.source_factory.resolve_source(song, update_ui_callback=self.update_ui)
        if song.is_external and not self.radio.is_cached(song):
            await self.radio.start_cache_download(song)
                
        if not source_path:
            log.error(f"[PLAYER] Could not resolve playable audio source for: {song.title if song else 'Unknown'}")
            self.radio.current_song = None
            self.radio.status = RadioState.IDLE
            await self.update_ui(None)
            return

        self.history_recorded = False
        self.playback_start_time = asyncio.get_event_loop().time()

        self.radio.track_start_offset = self.radio.seek_position or 0.0
        self.radio.seek_position = None
        
        done = asyncio.Event()
        def after_playing(error):
            if error:
                err_msg = str(error)
                if "read of closed file" not in err_msg.lower():
                    log.error(f"[PLAYER] Playback error: {error}")
                else:
                    log.debug(f"[PLAYER] Suppressed noise: {err_msg}")
            self.bot.loop.call_soon_threadsafe(done.set)

        if voice.is_playing() or voice.is_paused():
            voice.stop()
            await asyncio.sleep(0.05)
        
        self.radio.track_start_time = asyncio.get_event_loop().time()
        self.radio.status = RadioState.PLAYING
        
        # 3. Create FFmpeg audio source
        audio_source = self.source_factory.create_ffmpeg_source(
            source_path=source_path,
            song=song,
            track_start_offset=self.radio.track_start_offset,
            volume=self.radio.volume
        )
        
        voice.play(audio_source, after=after_playing)
        log.info(f"[PLAYER] Started playing: {song.uploader} - {song.title} ({song.duration}s)")
        await self.update_ui(song)

        # 4. Monitor playback and action queue
        await self._playback_monitor_loop(voice, song, done)
        
        try:
            await asyncio.wait_for(done.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            log.warning(f"[PLAYER] Playback thread for \"{song.title}\" did not exit within 3s. Forcing cleanup.")

        if not done.is_set(): 
            log.info(f"[PLAYER] Monitor loop broke or timed out: {song.title}")
        else:
            log.info(f"[PLAYER] Track finished normally: {song.title}")

        if not self.radio.is_seeking:
            self.radio.track_start_offset = 0.0
            if self.config.ephemeral_cache:
                self.radio.delete_cache_file(song)
        self.radio.track_start_time = None
        audio_source.cleanup()

    async def _playback_monitor_loop(self, voice: discord.VoiceClient, song: Song, done: asyncio.Event):
        """Listens for user actions and triggers pre-buffering while a track is playing."""
        while not done.is_set():
            try:
                if await self.voice_manager.check_solitary_timeout(voice):
                    break
                
                # Delayed History Recording (after 10% or 15s)
                if not self.history_recorded and not self.radio.is_navigating and song:
                    elapsed_total = self.radio.track_start_offset
                    if self.radio.track_start_time:
                        elapsed_total += (asyncio.get_event_loop().time() - self.radio.track_start_time)
                    threshold = min(15.0, (song.duration * 0.1) if song.duration > 0 else 15.0)
                    if elapsed_total >= threshold:
                        log.info(f"[HISTORY] Recording track after threshold: {song.title}")
                        self.radio.history_manager.add(song)
                        self.history_recorded = True

                # Gapless Pre-buffering trigger
                if song and not self.prefetcher.prefetched_song and (self.radio.future_queue or self.radio.queue):
                    elapsed_current = self.radio.track_start_offset
                    if self.radio.track_start_time:
                        elapsed_current += (asyncio.get_event_loop().time() - self.radio.track_start_time)
                    
                    remaining = (song.duration - elapsed_current) if song.duration > 0 else 0
                    if song.duration == 0 or remaining <= 25.0 or elapsed_current >= 10.0:
                        next_song = self.radio.future_queue[0] if self.radio.future_queue else self.radio.queue[0]
                        if next_song and next_song != song:
                            self.prefetcher.trigger_prefetch(next_song)

                action_task = asyncio.create_task(self.radio.action_queue.get())
                done_task = asyncio.create_task(done.wait())
                
                finished, pending = await asyncio.wait(
                    [action_task, done_task],
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=self.config.action_timeout
                )
                for task in pending:
                    task.cancel()

                if action_task in finished:
                    action, data = action_task.result()
                    if await self.action_handler.handle_playback_action(action, data, voice, song):
                        break
                
                if done_task in finished:
                    break
            except asyncio.TimeoutError:
                continue
