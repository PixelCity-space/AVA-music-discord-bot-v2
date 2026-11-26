import asyncio
import os
from collections.abc import Callable
from typing import TYPE_CHECKING

import discord

from core.actions import RadioAction, RadioActionData, RadioState
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
        if action == RadioAction.JOIN and isinstance(data, int):
            log.info(f"[PLAYER] Joining voice channel from disconnected state: {data}")
            self.radio.voice_channel_id = data
            self.radio.status = RadioState.PLAYING
            return True
        if action == RadioAction.DISCONNECT:
            log.debug("[PLAYER] Disconnect requested while already disconnected; cleaning up state.")
            await self.voice_manager.disconnect(None)
            return True
        if action == RadioAction.RESTART:
            await self.handle_restart()
            return True
        log.debug(f"[PLAYER] Ignored action {action.name} while disconnected.")
        return False

    async def handle_idle_action(self, action: RadioAction, data: RadioActionData, voice: discord.VoiceClient | None) -> bool:
        """Handles actions when voice is connected but in IDLE, PAUSED, or STOPPED state."""
        if action == RadioAction.SET_VOLUME and isinstance(data, (int, float)):
            vol = float(data)
            log.info(f"[PLAYER] Idle volume set to: {int(vol * 100)}%")
            self.radio.volume = vol
            return True
        if action == RadioAction.JOIN and isinstance(data, (int, str)):
            await self.voice_manager.switch_channel(int(data), voice)
            await self.update_ui(self.radio.current_song)
            return True
        if action == RadioAction.DISCONNECT:
            log.info("[PLAYER] Disconnecting from idle state.")
            await self.voice_manager.disconnect(voice)
            return True
        if action == RadioAction.REPLAY:
            if self.radio.status == RadioState.STOPPED and self.radio.current_song:
                log.info(f"[PLAYER] Replaying stopped track: {self.radio.current_song.title}")
                self.radio.is_seeking = True
                self.radio.seek_position = 0
            elif self.radio.status == RadioState.PAUSED and self.radio.current_song:
                log.info(f"[PLAYER] Resuming paused track via replay: {self.radio.current_song.title}")
                self.radio.is_seeking = True
                self.radio.seek_position = None
            else:
                log.debug(f"[PLAYER] Replay in {self.radio.status.name} state (current_song={self.radio.current_song}).")
        elif action == RadioAction.SKIP:
            if self.radio.queue_manager.has_next():
                log.info("[PLAYER] Advancing to next track from idle state.")
                self.radio.status = RadioState.PLAYING
                return False
            log.debug("[PLAYER] Skip ignored in idle state: no next track.")
            return True
        elif action == RadioAction.BACK:
            back_song = self.radio.queue_manager.step_back(
                self.radio.history_manager, self.radio.current_song, during_playback=False
            )
            if back_song:
                log.info(f"[PLAYER] Stepping back from idle state to: {back_song.title}")
                self.radio.current_song = back_song
                self.radio.is_seeking = True
                self.radio.status = RadioState.PLAYING
                return False
            log.debug("[PLAYER] Back ignored in idle state: no history item found.")
            return True
        elif action == RadioAction.SEEK and isinstance(data, (int, float)):
            pos = float(data)
            log.info(f"[PLAYER] Idle Seeking to: {pos}s")
            self.radio.seek_position = pos
            self.radio.track_start_offset = pos
            self.radio.is_seeking = True
            await self.update_ui(self.radio.current_song)
            return True
        elif action == RadioAction.RESTART:
            await self.handle_restart()
            return True
        else:
            log.debug(f"[PLAYER] Ignored action {action.name} in {self.radio.status.name} state.")
            return True

        self.radio.status = RadioState.PLAYING
        return False

    async def handle_playback_action(self, action: RadioAction, data: RadioActionData, 
                                     voice: discord.VoiceClient, song: Song | None) -> bool:
        """Handles actions received while audio is actively streaming."""
        if action == RadioAction.SKIP:
            log.info("[PLAYER] Skipping current track.")
            self.radio.is_navigating = True
            self.radio.is_seeking = False
            voice.stop()
            return True
        if action == RadioAction.SEEK and isinstance(data, (int, float)):
            pos = float(data)
            log.info(f"[PLAYER] Seeking to: {pos}s")
            self.radio.seek_position = pos
            self.radio.is_seeking = True
            if self.radio.status == RadioState.PAUSED:
                self.radio.track_start_offset = pos
            voice.stop()
            if self.radio.status == RadioState.PAUSED:
                await self.update_ui(song)
            return True
        if action == RadioAction.SET_VOLUME and isinstance(data, (int, float)):
            new_vol = float(data)
            if abs(new_vol - float(self.radio.volume)) < 1e-6:
                log.debug(f"[PLAYER] Volume unchanged ({int(new_vol * 100)}%); skipping FFmpeg restart.")
                return False
            log.info(f"[PLAYER] Volume changed to: {int(new_vol * 100)}%")
            self.radio.volume = new_vol
            source = getattr(voice, "source", None)
            if isinstance(source, discord.PCMVolumeTransformer):
                source.volume = new_vol
                return False
            if self.radio.status == RadioState.PAUSED:
                log.debug("[PLAYER] Deferring FFmpeg volume restart while paused.")
                self.radio.seek_position = self.radio.elapsed_seconds
                self.radio.is_seeking = True
                return False
            self.radio.seek_position = self.radio.elapsed_seconds
            self.radio.is_seeking = True
            voice.stop()
            return True
        if action == RadioAction.PAUSE:
            if voice.is_playing():
                log.info("[PLAYER] Pausing playback.")
                voice.pause()
                self.radio.track_start_offset = self.radio.elapsed_seconds
                self.radio.track_start_time = None
                self.radio.status = RadioState.PAUSED
                await self.update_ui(song)
            return False
        if action == RadioAction.REPLAY:
            if self.radio.status == RadioState.PAUSED:
                log.info("[PLAYER] Resuming playback.")
                voice.resume()
                self.radio.track_start_time = asyncio.get_event_loop().time()
                self.radio.status = RadioState.PLAYING
                await self.update_ui(song)
                return False
            log.info("[PLAYER] Replaying track from start.")
            self.radio.seek_position = 0
            self.radio.is_seeking = True
            voice.stop()
            return True
        if action == RadioAction.BACK:
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
        if action == RadioAction.STOP:
            log.info("[PLAYER] Stopping playback.")
            self.radio.status = RadioState.STOPPED
            self.radio.track_start_offset = 0.0
            self.radio.track_start_time = None
            voice.stop()
            await self.update_ui(song)
            return True
        if action == RadioAction.JOIN and isinstance(data, (int, str)):
            await self.voice_manager.switch_channel(int(data), voice)
            await self.update_ui(song)
            return False
        if action == RadioAction.DISCONNECT:
            await self.voice_manager.disconnect(voice)
            return True
        if action == RadioAction.RESTART:
            await self.handle_restart()
            return True
        return False
