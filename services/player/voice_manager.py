import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

import discord

from core.actions import RadioState
from utils.logger import log

if TYPE_CHECKING:
    from core.state import RadioManager

class VoiceManager:
    """Manages voice channel connections, movements, forbidden bot checks, and solitary timeouts."""
    
    def __init__(self, bot: discord.Client, config, radio: 'RadioManager', cleanup_ui_callback: Callable | None = None):
        self.bot = bot
        self.config = config
        self.radio = radio
        self.cleanup_ui = cleanup_ui_callback
        
        self.solitary_timeout = self.config.solitary_timeout_seconds
        self.solitary_start: float | None = None
        self._voice_lock = asyncio.Lock()

    async def ensure_voice(self) -> discord.VoiceClient | None:
        """Ensures the bot is connected to the correct voice channel."""
        async with self._voice_lock:
            guild = self.bot.get_guild(self.config.guild_id)
            if not guild or not self.radio.voice_channel_id:
                return None
                
            channel = cast(discord.VoiceChannel | None, guild.get_channel(self.radio.voice_channel_id))
            if not channel:
                log.warning(f"[VOICE] Target channel {self.radio.voice_channel_id} not found in guild {guild.name}")
                return None

            vc = cast(discord.VoiceClient | None, guild.voice_client)
            if vc:
                if vc.is_connected():
                    self.radio.voice = vc
                    if not vc.channel or vc.channel.id != channel.id:
                        from_name = vc.channel.name if vc.channel else "unknown"
                        log.info(f"[VOICE] Moving from {from_name} to {channel.name}")
                        await vc.move_to(channel)
                    return self.radio.voice
                log.warning(f"[VOICE] Dead voice client found for guild {guild.name}. Cleaning up.")
                try:
                    await vc.disconnect(force=True)
                except Exception as e:
                    log.warning(f"[VOICE] Error disconnecting dead voice client: {e}")
                self.radio.voice = None

            # Check for forbidden bots
            for member in channel.members:
                if member.bot and member.id in self.config.forbidden_bot_ids:
                    log.warning(f"[VOICE] Forbidden bot {member.name} ({member.id}) detected in {channel.name}. Aborting join.")
                    return None
            
            try:
                log.info(f"[VOICE] Connecting to {channel.name} in guild {guild.name}...")
                self.radio.voice = await channel.connect(reconnect=True, timeout=30.0, self_deaf=True)
                log.info(f"[VOICE] Successfully connected to {channel.name}")
            except Exception as e:
                log.warning(f"[VOICE] Connection attempt failed: {type(e).__name__}: {e}")
                self.radio.voice = None
                return None

            return self.radio.voice

    async def switch_channel(self, target_channel_id: int, voice: discord.VoiceClient | None = None) -> bool:
        """Switches voice channel safely."""
        if self.radio.voice_channel_id == target_channel_id:
            log.debug(f"[VOICE] Already targeting channel {target_channel_id}; skipping switch.")
            return False

        guild = self.bot.get_guild(self.config.guild_id)
        target_channel = cast(discord.VoiceChannel | None, guild.get_channel(target_channel_id) if guild else None)
        if not target_channel:
            try:
                target_channel = cast(discord.VoiceChannel | None, await self.bot.fetch_channel(target_channel_id))
            except Exception as e:
                log.warning(f"[VOICE] Failed to fetch target channel {target_channel_id}: {e}")
                return False

        if target_channel:
            # Check for forbidden bots
            for member in target_channel.members:
                if member.bot and member.id in self.config.forbidden_bot_ids:
                    log.warning(f"[VOICE] Forbidden bot {member.name} ({member.id}) detected in {target_channel.name}. Aborting switch.")
                    return False

        self.radio.voice_channel_id = target_channel_id
        if target_channel and voice and voice.is_connected():
            log.info(f"[VOICE] Moving voice client to {target_channel.name}")
            await voice.move_to(target_channel)
            return True
        return False

    async def check_solitary_timeout(self, voice: discord.VoiceClient) -> bool:
        """Returns True if the bot disconnected due to being alone in the voice channel."""
        if not voice or not voice.channel:
            return False
            
        real_members = [m for m in voice.channel.members if not m.bot]
        if len(real_members) == 0:
            if self.solitary_start is None:
                log.info(f"[SOLITARY] Bot is alone. Starting {self.solitary_timeout}s countdown.")
                self.solitary_start = asyncio.get_event_loop().time()
            elif asyncio.get_event_loop().time() - self.solitary_start >= self.solitary_timeout:
                log.info(f"Auto-disconnecting: Bot was alone for {self.solitary_timeout}s.")
                self.solitary_start = None
                await self.disconnect(voice)
                return True
        else:
            if self.solitary_start is not None:
                log.info("[SOLITARY] Member joined or present. Resetting countdown.")
            self.solitary_start = None
        return False

    async def disconnect(self, voice: discord.VoiceClient | None = None):
        """Cleanly disconnects the bot from voice and resets voice connection state."""
        self.radio.voice_channel_id = None
        self.radio.status = RadioState.IDLE
        self.radio.current_song = None
        self.solitary_start = None
        
        if voice:
            try:
                await voice.disconnect()
            except Exception as e:
                log.warning(f"[VOICE] Error during voice client disconnect: {e}")
        self.radio.voice = None
        
        if self.cleanup_ui:
            await self.cleanup_ui()
