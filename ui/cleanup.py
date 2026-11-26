import asyncio
from ui.utils import safe_delete_message
from utils.logger import log


class ChannelCleaner:
    """Handles rate-limited background cleanup of stray bot messages in the radio text channel."""

    def __init__(self, bot, config, radio):
        self.bot = bot
        self.config = config
        self.radio = radio
        self._last_cleanup = 0.0
        self._cleanup_task: asyncio.Task | None = None

    def schedule(self, channel, force: bool = False):
        """Schedules non-blocking stray message cleanup if interval elapsed or forced."""
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
                await self.cleanup_stray_messages(channel, force=force)
            except asyncio.CancelledError:
                pass

        self._cleanup_task = self.radio.create_task(_delayed_cleanup(), name="ui_stray_cleanup")

    async def cleanup_stray_messages(self, channel, force: bool = False):
        """Deletes old bot-authored messages that are no longer tracked as active UI embeds."""
        now = asyncio.get_running_loop().time()
        if not force and (now - self._last_cleanup < self.config.ui_cleanup_frequency):
            return
        self._last_cleanup = now

        try:
            current_station_id = self.radio.station_message.id if self.radio.station_message else None
            current_player_id = self.radio.now_playing_message.id if self.radio.now_playing_message else None
            current_search_id = self.radio.embed_manager.load_message_id("search")

            known_ids = {
                msg_id
                for msg_id in (current_station_id, current_player_id, current_search_id)
                if msg_id is not None
            }

            log.debug(f"[UI] Cleaning up. Known IDs: {known_ids}")

            to_delete = []
            async for msg in channel.history(limit=self.config.message_cleanup_limit):
                if msg.author.id == self.bot.user.id and msg.id not in known_ids:
                    to_delete.append(msg)

            if to_delete:
                if len(to_delete) > 1:
                    try:
                        await channel.delete_messages(to_delete)
                    except Exception as bulk_err:
                        log.debug(f"[UI] Bulk delete failed for {len(to_delete)} messages, falling back to single delete: {bulk_err}")
                        for msg in to_delete:
                            await safe_delete_message(msg)
                else:
                    await safe_delete_message(to_delete[0])
        except Exception as ex:
            log.warning(f"UI Cleanup sweep failed: {ex}", exc_info=True)

