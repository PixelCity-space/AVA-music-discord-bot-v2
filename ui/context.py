from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import discord


@dataclass(frozen=True)
class UIContext:
    """
    Immutable Context Object for the UI layer (Dependency Injection).
    Encapsulates Discord client, configuration, and UI update callbacks
    without relying on mutable module-level state.
    """
    bot: discord.Client | None = None
    config: Any | None = None
    update_callback: Callable | None = None

    def get_guild(self) -> discord.Guild | None:
        """Safely fetches the configured guild from the bot client if available."""
        if not self.bot or not self.config:
            return None
        guild_id = getattr(self.config, "guild_id", None)
        if not guild_id:
            return None
        return self.bot.get_guild(guild_id)

    @property
    def bot_user(self) -> discord.ClientUser | None:
        """Returns the client's User representation if logged in."""
        if self.bot and hasattr(self.bot, "user"):
            return self.bot.user
        return None
