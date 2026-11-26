import asyncio
import discord
from discord.ext import commands
from core.state import RadioManager
from core.actions import RadioState
from services.audio_player import RadioPlayer
from ui.manager import UIManager
from ui.theme import Theme
from ui.icons import Icons
from cogs import COGS
from utils.logger import log

class RadioBot(commands.Bot):
    def __init__(self, config, instance_name: str = ""):
        self.config = config
        self.instance_name = instance_name
        
        # Setup UI Icons and Theme
        Icons.setup(config)
        Theme.init_theme(config)

        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix=config.command_prefix,
            intents=intents,
            help_command=None,
            max_messages=100,
            member_cache_flags=discord.MemberCacheFlags.voice()
        )

        # Core State & Services
        self.radio = RadioManager(config, instance_name=instance_name)
        
        # Clear ephemeral cache on startup if enabled
        if config.ephemeral_cache:
            log.info("[CACHE] Ephemeral cache enabled. Performing startup cleanup...")
            self.radio.clear_cache()
            
        self.ui_manager = UIManager(self, config, self.radio)
        self.player = RadioPlayer(
            self, config, self.radio,
            update_ui_callback=self.ui_manager.update_now_playing,
            refresh_ui_callback=self.ui_manager.refresh_all_uis,
            cleanup_ui_callback=self.ui_manager.force_new_embed
        )

        self.bg_tasks: list[asyncio.Task] = []

    async def setup_hook(self):
        """Called automatically when bot initializes before connecting to gateway."""
        # 1. Clear old global commands from tree to avoid duplication/leakage across instances
        self.tree.clear_commands(guild=None)

        # 2. Load all Cogs
        for cog_ext in COGS:
            try:
                await self.load_extension(cog_ext)
                log.info(f"[EXTENSION] Loaded {cog_ext}")
            except Exception as e:
                log.error(f"[EXTENSION] Failed to load {cog_ext}: {e}")

        # 3. Start background monitoring tasks
        if not self.radio.task:
            self.radio.task = asyncio.create_task(self.player.run_loop())
            self.bg_tasks.append(self.radio.task)
            
        self.bg_tasks.append(asyncio.create_task(self._embed_refresh_loop()))
        self.bg_tasks.append(asyncio.create_task(self._progress_update_loop()))
        self.bg_tasks.append(asyncio.create_task(self._cache_cleanup_loop()))

    async def _cache_cleanup_loop(self):
        await self.wait_until_ready()
        while not self.is_closed():
            await asyncio.sleep(3600)
            try:
                await self.radio.cleanup_cache_async()
            except Exception as e:
                log.debug(f"[CACHE] Periodic cleanup failed: {e}")

    async def _embed_refresh_loop(self):
        await self.wait_until_ready()
        while not self.is_closed():
            await asyncio.sleep(self.config.embed_refresh_minutes * 60)
            await self.ui_manager.force_new_embed()

    async def _progress_update_loop(self):
        await self.wait_until_ready()
        while not self.is_closed():
            await asyncio.sleep(self.config.progress_update_seconds)
            # Only trigger progress UI update when actually playing
            if self.radio.status == RadioState.PLAYING and self.radio.now_playing_message:
                try:
                    await self.ui_manager.update_now_playing(self.radio.current_song)
                except Exception as e:
                    log.debug(f"[UI] Progress update failed: {e}")

    async def close(self):
        """Graceful shutdown logic."""
        log.info(f"Cleaning up {len(self.bg_tasks)} background tasks...")
        for task in self.bg_tasks:
            if not task.done():
                task.cancel()
        
        if self.bg_tasks:
            await asyncio.gather(*self.bg_tasks, return_exceptions=True)

        if hasattr(self.radio, 'close'):
            await self.radio.close()
            
        await super().close()
