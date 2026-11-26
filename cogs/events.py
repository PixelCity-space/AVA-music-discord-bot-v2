"""
Discord gateway event listener cog handling ready initialization, voice state updates, and messages.
"""

import asyncio
import discord
import random
from discord.ext import commands
from core.actions import RadioState
from ui.views.player import NowPlayingView
from ui.views.station import FrequencyStationView, WelcomeLayout
from cogs.prefix_commands import handle_prefix_commands
from utils.logger import log

class EventsCog(commands.Cog):
    """Cog listening to lifecycle and voice gateway events (on_ready, on_voice_state_update, on_message)."""
    def __init__(self, bot):
        self.bot = bot
        self.radio = bot.radio
        self.config = bot.config
        self.ui_manager = bot.ui_manager
        self._ready_once = False

    @commands.Cog.listener()
    async def on_ready(self):
        instance_label = self.bot.instance_name if self.bot.instance_name else 'Default'
        providers = getattr(self.radio, "providers", []) or []
        ytdlp_mode = next(
            ("subprocess" if getattr(p, "_use_subprocess", False) else "in-process" for p in providers if hasattr(p, "_use_subprocess")),
            "unknown",
        )
        log.info("--- RADIO BOT ONLINE ---")
        log.info(f"Identity: {self.bot.user} (ID: {self.bot.user.id})")
        log.info(f"Instance: {instance_label}")
        log.info(
            f"[ENV] guild={self.config.guild_id}, text_ch={self.config.radio_text_channel_id}, "
            f"ephemeral_cache={self.config.ephemeral_cache}, voice_status={self.config.update_voice_status}, "
            f"opus_loaded={discord.opus.is_loaded()}, ffmpeg={self.config.ffmpeg_path}, ytdlp_mode={ytdlp_mode}"
        )
        log.info("------------------------")

        if self._ready_once:
            log.info("[GATEWAY] Reconnected (on_ready); skipping duplicate view/command sync.")
            return
        self._ready_once = True

        try:
            ctx = self.ui_manager.context
            self.bot.add_view(WelcomeLayout(self.radio, context=ctx))
            self.bot.add_view(FrequencyStationView(self.radio, context=ctx))
            self.bot.add_view(NowPlayingView(self.radio, context=ctx))
            await self.ui_manager.force_new_embed()
        except Exception as e:
            log.error(f"Error during on_ready view registration: {e}", exc_info=True)

        # Slash command sync
        try:
            guild_id = self.config.guild_id
            if guild_id and guild_id > 0:
                target_guild = discord.Object(id=guild_id)
                self.bot.tree.copy_global_to(guild=target_guild)
                if self.bot.instance_name:
                    await asyncio.sleep(random.uniform(1.0, 5.0))
                await self.bot.tree.sync(guild=target_guild)
                log.info(f"Slash commands synced to guild: {guild_id}")
            else:
                if self.bot.instance_name:
                    await asyncio.sleep(random.uniform(1.0, 5.0))
                await self.bot.tree.sync()
                log.info("Slash commands synced globally!")
        except Exception as e:
            log.error(f"Failed to sync commands: {e}", exc_info=True)
            
        # Optional Auto-Join
        if self.config.auto_join_channel_id > 0:
            try:
                channel = self.bot.get_channel(self.config.auto_join_channel_id)
                if not channel:
                    channel = await self.bot.fetch_channel(self.config.auto_join_channel_id)
                
                if channel and isinstance(channel, discord.VoiceChannel):
                    if not channel.guild.voice_client:
                        log.info(f"Auto-joining channel: {channel.name}")
                        if self.bot.instance_name:
                            await asyncio.sleep(random.uniform(0.5, 3.0))
                        await channel.connect(reconnect=True, timeout=20.0, self_deaf=True)
                        self.radio.voice_channel_id = channel.id
                        self.radio.voice = channel.guild.voice_client
                        self.radio.status = RadioState.IDLE
                    else:
                        log.debug("[VOICE] Auto-join skipped; guild already has an active voice client.")
                else:
                    log.warning(f"[VOICE] Auto-join channel {self.config.auto_join_channel_id} not found or not a VoiceChannel.")
            except Exception as e:
                log.error(f"Auto-join failed: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.id == self.bot.user.id:
            target_channel = after.channel
            old_channel = before.channel
            
            guild = member.guild
            voice_client = guild.voice_client
            
            if target_channel:
                if old_channel and old_channel.id != target_channel.id:
                    log.info(f"[VOICE] Bot moved from #{old_channel.name} to #{target_channel.name}")
                    await self.ui_manager.clear_voice_status(old_channel.id)
                elif not old_channel:
                    log.info(f"[VOICE] Bot connected to #{target_channel.name}")
                    
                if not old_channel or old_channel.id != target_channel.id:
                    self.radio.voice_channel_id = target_channel.id
                    self.radio.voice = voice_client
                    await self.ui_manager.update_now_playing(self.radio.current_song)
            else:
                if not voice_client or not voice_client.is_connected():
                    await asyncio.sleep(1.5)
                    voice_client = member.guild.voice_client 
                    
                    if not voice_client or not voice_client.is_connected():
                        log.info(f"[VOICE] Confirmed disconnect for {member.guild.name}. Cleaning up state.")
                        prev_channel_id = old_channel.id if old_channel else self.radio.voice_channel_id
                        self.radio.voice_channel_id = None
                        self.radio.voice = None
                        self.radio.status = RadioState.IDLE
                        self.radio.current_song = None
                        await self.ui_manager.update_now_playing(None)
                        
                        if prev_channel_id:
                            await self.ui_manager.clear_voice_status(prev_channel_id)
                    else:
                        log.info(f"[VOICE] Disconnect event was transient. Bot is still connected to {voice_client.channel.name}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Delegates traditional prefix command handling."""
        await handle_prefix_commands(message, self.radio)

async def setup(bot):
    await bot.add_cog(EventsCog(bot))
