import random
import discord
from core.actions import RadioState
from core.models import Song
from ui.i18n import t
from utils.logger import log


class PresenceManager:
    """Synchronizes bot presence activity and voice channel status with playback state."""

    def __init__(self, bot: discord.Client, config, radio):
        self.bot = bot
        self.config = config
        self.radio = radio
        self._last_presence_sig = None
        self._last_voice_status = None

    def reset_voice_status_cache(self):
        """Clears cached voice channel status signature so the next sync updates unconditionally."""
        self._last_voice_status = None

    async def update(self, song: Song | None, force_channel_id: int | None = None):
        """Updates both bot presence and voice channel status with deduplication."""
        await self.update_presence(song)
        await self.update_channel_status(song, force_channel_id=force_channel_id)

    async def update_presence(self, song: Song | None):
        """Updates the Discord bot's presence activity based on current RadioState."""
        try:
            if self.radio.status == RadioState.PLAYING and song:
                current_sig = f"PLAYING:{song.title}"
                if current_sig != self._last_presence_sig:
                    activity = discord.Activity(
                        type=discord.ActivityType.listening,
                        name=song.title or t("unknown"),
                    )
                    await self.bot.change_presence(activity=activity)
                    self._last_presence_sig = current_sig
                return

            if self.radio.status == RadioState.PAUSED:
                msg_src = t("holding_rhythm")
            elif self.radio.status == RadioState.IDLE:
                msg_src = t("waiting_melody")
            else:
                msg_src = t("at_command")

            final_msg = random.choice(msg_src) if isinstance(msg_src, list) else msg_src
            current_sig = f"{self.radio.status.name}:{final_msg}"
            if current_sig != self._last_presence_sig:
                await self.bot.change_presence(activity=discord.Game(name=final_msg))
                self._last_presence_sig = current_sig
        except Exception as e:
            log.debug(f"Presence update failed: {e}")

    async def update_channel_status(self, song: Song | None, force_channel_id: int | None = None):
        """Updates the connected Voice Channel's status text when enabled in config."""
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
                status_text = t("channel_status_playing", TITLE=song.title)
            else:
                status_text = None

            status_sig = (target_id, status_text)
            if status_sig == self._last_voice_status:
                return

            current_status = getattr(channel, "status", "UNKNOWN_ATTR")
            if current_status == "UNKNOWN_ATTR" or current_status != status_text:
                await channel.edit(status=status_text)
            self._last_voice_status = status_sig
        except Exception as e:
            log.debug(f"Voice channel status update failed: {e}")

