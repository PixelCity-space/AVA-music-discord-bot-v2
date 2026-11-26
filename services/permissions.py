import discord

from core.actions import RadioState


class PermissionService:
    def __init__(self, config):
        self.config = config

    def is_admin(self, user: discord.Member | discord.User) -> bool:
        guild_perms = getattr(user, "guild_permissions", None)
        if guild_perms and getattr(guild_perms, "administrator", False):
            return True

        guild = getattr(user, "guild", None)
        if guild and getattr(user, "id", None) == getattr(guild, "owner_id", None):
            return True

        user_roles = getattr(user, "roles", [])
        user_role_ids = [getattr(r, "id", r) for r in user_roles]
        if self.config.admin_role_id > 0 and self.config.admin_role_id in user_role_ids:
            return True
        return self.config.sysadmin_role_id > 0 and self.config.sysadmin_role_id in user_role_ids

    def can_interact(self, user: discord.Member | discord.User, radio) -> bool:
        """
        Checks if the user has permission to interact with the bot.
        Admins can always interact.
        The voice channel restriction ONLY applies if the bot is:
        - PLAYING
        - PAUSED
        - STOPPED
        If the bot is IDLE, anyone can interact (e.g. to make it join their channel).
        """
        if self.is_admin(user):
            return True

        # If IDLE, we don't restrict by channel
        if radio.status == RadioState.IDLE:
            return True

        if not radio.voice or not radio.voice.channel:
            # If not in voice despite status, allow interaction
            return True

        user_voice = getattr(user, "voice", None)
        if not user_voice or not getattr(user_voice, "channel", None):
            return False

        # Must be in the same voice channel if the bot is active
        return user_voice.channel.id == radio.voice.channel.id
