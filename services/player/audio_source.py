import os
import asyncio
import discord
from typing import Optional, Callable, TYPE_CHECKING
from core.models import Song
from utils.logger import log

if TYPE_CHECKING:
    from core.state import RadioManager

class AudioSourceFactory:
    """Handles audio stream resolution, local cache retrieval, and FFmpeg audio source generation."""
    
    def __init__(self, config, radio: 'RadioManager'):
        self.config = config
        self.radio = radio

    async def resolve_source(self, song: Song, update_ui_callback: Optional[Callable] = None) -> Optional[str]:
        """Resolves the audio source path or stream URL for a given song."""
        if os.path.exists(song.path):
            return song.path

        if self.radio.is_cached(song):
            return self.radio.get_cache_path(song)

        if song.stream_url and not song.is_resolving:
            log.info(f"[PLAYER] Using pre-buffered stream URL for: {song.title}")
            return song.stream_url

        if song.is_resolving:
            log.info(f"[PLAYER] Waiting for background resolution: {song.title}")
            try:
                await asyncio.wait_for(song.resolve_event.wait(), timeout=15.0)
            except asyncio.TimeoutError:
                log.warning(f"[PLAYER] Resolution timed out for: {song.title}")

        if self.radio.is_cached(song):
            return self.radio.get_cache_path(song)

        source_path = song.path
        if song.is_external:
            if not song.stream_url or song.is_resolving:
                if update_ui_callback:
                    await update_ui_callback(song)
                from providers import resolve_any
                resolved = await resolve_any(source_path, self.radio.providers)
                if resolved:
                    song.update(resolved)
                    song.cache_to_db(self.radio.db)
            
            if song.stream_url:
                return song.stream_url
            return None
        return source_path

    def create_ffmpeg_source(self, source_path: str, song: Optional[Song] = None, 
                             track_start_offset: float = 0.0, volume: float = 0.5) -> discord.FFmpegOpusAudio:
        """Creates a configured FFmpegOpusAudio source with headers and options."""
        is_url = source_path.startswith("http")
        reconnect_opts = self.config.ffmpeg_reconnect_options if is_url else ""
        user_agent = self.config.user_agent if is_url else ""
        
        before_opts_list = ["-nostdin"]
        if track_start_offset > 0:
            before_opts_list.append(f"-ss {track_start_offset}")
             
        if is_url:
            ua = None
            if song and song.http_headers and "User-Agent" in song.http_headers:
                ua = song.http_headers["User-Agent"]
            elif user_agent:
                ua = user_agent

            if ua:
                safe_ua = str(ua).replace('"', '')
                before_opts_list.append(f'-user_agent "{safe_ua}"')
            if reconnect_opts:
                before_opts_list.append(reconnect_opts)
            
            is_soundcloud = "soundcloud.com" in source_path or (song and song.webpage_url and "soundcloud.com" in song.webpage_url)
            if is_soundcloud:
                before_opts_list.append("-headers \"Referer: https://soundcloud.com/\"")
                before_opts_list.append("-allowed_extensions ALL")
                
            before_opts_list.extend(["-analyzeduration 0", "-probesize 32k"])
        
        before_opts = " ".join(before_opts_list)
        safe_volume = max(0.0, float(volume if volume is not None else 0.5))
        filter_chain = f"volume={safe_volume}"
        options = f'-vn -filter:a "{filter_chain}" -c:a libopus -b:a {self.config.audio_bitrate} -ar 48000 -ac 2 -f opus -threads 2'
        
        return discord.FFmpegOpusAudio(
            source_path,
            executable=self.config.ffmpeg_path,
            before_options=before_opts,
            options=options
        )
