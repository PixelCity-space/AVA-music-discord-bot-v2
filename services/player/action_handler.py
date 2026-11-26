import os
import asyncio
import discord
from typing import Optional, Callable, TYPE_CHECKING
from core.actions import RadioAction, RadioState, RadioActionData
from core.models import Song
from utils.logger import log

if TYPE_CHECKING:
    from core.state import RadioManager
    from .voice_manager import VoiceManager

class PlaybackActionHandler:
    """Processes user and system actions in disconnected, idle, and playing states."""
    
    def __init__(self, bot: discord.Client, radio: 'RadioManager', 
                 voice_manager: 'VoiceManager', update_ui_callback: Callable):
        self.bot = bot
        self.radio = radio
        self.voice_manager = voice_manager
        self.update_ui = update_ui_callback

    async def handle_restart(self):
        """Triggers bot process restart."""
        log.info("[PLAYER] Restart triggered. Closing bot connection...")
        os.environ["BOT_RESTART"] = "1"
        await self.bot.close()

    async def handle_disconnected_action(self, action: RadioAction, data: RadioActionData) -> bool:
        """Handles actions when voice is disconnected."""
        if action == RadioAction.JOIN:
            self.radio.voice_channel_id = data
            self.radio.status = RadioState.PLAYING
            return True
        elif action == RadioAction.DISCONNECT:
            await self.voice_manager.disconnect(None)
            return True
        elif action == RadioAction.RESTART:
            await self.handle_restart()
            return True
        return False

    async def handle_idle_action(self, action: RadioAction, data: RadioActionData, voice: Optional[discord.VoiceClient]) -> bool:
        """Handles actions when voice is connected but in IDLE, PAUSED, or STOPPED state."""
        if action == RadioAction.SET_VOLUME:
            self.radio.volume = data
            return True
        elif action == RadioAction.JOIN:
            await self.voice_manager.switch_channel(int(data), voice)
            await self.update_ui(self.radio.current_song)
            return True
        elif action == RadioAction.DISCONNECT:
            await self.voice_manager.disconnect(voice)
            return True
        elif action == RadioAction.REPLAY:
            if self.radio.status == RadioState.STOPPED and self.radio.current_song:
                self.radio.is_seeking = True
                self.radio.seek_position = 0
            elif self.radio.status == RadioState.PAUSED and self.radio.current_song:
                self.radio.is_seeking = True
                self.radio.seek_position = None
        elif action == RadioAction.SKIP:
            if self.radio.queue_manager.has_next():
                self.radio.status = RadioState.PLAYING
                return False
            return True
        elif action == RadioAction.BACK:
            back_song = self.radio.queue_manager.step_back(
                self.radio.history_manager, self.radio.current_song, during_playback=False
            )
            if back_song:
                self.radio.current_song = back_song
                self.radio.is_seeking = True
                self.radio.status = RadioState.PLAYING
                return False
            return True
        elif action == RadioAction.SEEK:
            log.info(f"[PLAYER] Idle Seeking to: {data}s")
            self.radio.seek_position = data
            self.radio.track_start_offset = data
            self.radio.is_seeking = True
            await self.update_ui(self.radio.current_song)
            return True
        elif action == RadioAction.RESTART:
            await self.handle_restart()
            return True
        else:
            return True
            
        self.radio.status = RadioState.PLAYING
        return False

    async def handle_playback_action(self, action: RadioAction, data: RadioActionData, 
                                     voice: discord.VoiceClient, song: Optional[Song]) -> bool:
        """Handles actions received while audio is actively streaming."""
        if action == RadioAction.SKIP:
            log.info("[PLAYER] Skipping current track.")
            self.radio.is_navigating = True
            self.radio.is_seeking = False
            voice.stop()
            return True
        elif action == RadioAction.SEEK:
            log.info(f"[PLAYER] Seeking to: {data}s")
            self.radio.seek_position = data
            self.radio.is_seeking = True
            if self.radio.status == RadioState.PAUSED:
                self.radio.track_start_offset = data
            voice.stop()
            if self.radio.status == RadioState.PAUSED:
                await self.update_ui(song)
            return True
        elif action == RadioAction.SET_VOLUME:
            log.info(f"[PLAYER] Volume changed to: {int(data*100)}%")
            self.radio.volume = data
            self.radio.seek_position = self.radio.elapsed_seconds
            self.radio.is_seeking = True
            voice.stop()
            return True
        elif action == RadioAction.PAUSE:
            if voice.is_playing():
                log.info("[PLAYER] Pausing playback.")
                voice.pause()
                self.radio.track_start_offset = self.radio.elapsed_seconds
                self.radio.track_start_time = None
                self.radio.status = RadioState.PAUSED
                await self.update_ui(song)
            return False
        elif action == RadioAction.REPLAY:
            if self.radio.status == RadioState.PAUSED:
                log.info("[PLAYER] Resuming playback.")
                voice.resume()
                self.radio.track_start_time = asyncio.get_event_loop().time()
                self.radio.status = RadioState.PLAYING
                await self.update_ui(song)
                return False
            else:
                log.info("[PLAYER] Replaying track from start.")
                self.radio.seek_position = 0
                self.radio.is_seeking = True
                voice.stop()
                return True
        elif action == RadioAction.BACK:
            elapsed = self.radio.elapsed_seconds

            if elapsed > 10.0:
                log.info(f"[PLAYER] Restarting current track (elapsed: {int(elapsed)}s)")
                self.radio.seek_position = 0
                self.radio.is_seeking = True
                voice.stop()
                return True

            log.info(f"[PLAYER] Navigating to previous track in history (elapsed: {int(elapsed)}s)")
            back_song = self.radio.queue_manager.step_back(
                self.radio.history_manager, self.radio.current_song, during_playback=True
            )

            if back_song:
                self.radio.current_song = back_song
                self.radio.is_seeking = True
                voice.stop()
                return True
            
            self.radio.seek_position = 0
            self.radio.is_seeking = True
            voice.stop()
            return True
        elif action == RadioAction.STOP:
            log.info("[PLAYER] Stopping playback.")
            self.radio.status = RadioState.STOPPED
            self.radio.track_start_offset = 0.0
            self.radio.track_start_time = None
            voice.stop()
            await self.update_ui(song)
            return True
        elif action == RadioAction.JOIN:
            await self.voice_manager.switch_channel(int(data), voice)
            await self.update_ui(song)
            return False
        elif action == RadioAction.DISCONNECT:
            await self.voice_manager.disconnect(voice)
            return True
        elif action == RadioAction.RESTART:
            await self.handle_restart()
            return True
        return False
