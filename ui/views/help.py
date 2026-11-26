import discord

from ui.feedback import get_feedback
from ui.i18n import t
from ui.theme import Theme


class HelpView:
    """Builds the help embed listing available slash and prefix commands."""

    def __init__(self, radio):
        self.radio = radio
        self.config = radio.config

    def get_embed(self) -> discord.Embed:
        prefix = self.config.command_prefix
        embed = discord.Embed(
            title=get_feedback("help_title"),
            description=t("help_description"),
            color=Theme.PRIMARY,
        )

        commands = [
            ("play [url/search]", t("help_play_desc")),
            ("pause", t("help_pause_desc")),
            ("stop", t("help_stop_desc")),
            ("skip", t("help_skip_desc")),
            ("back", t("help_back_desc")),
            ("volume [0-100]", t("help_vol_desc")),
            ("seek [time]", t("help_seek_desc")),
            ("queue", t("help_queue_desc")),
            ("join", t("help_join_desc")),
            ("disconnect", t("help_leave_desc")),
            ("loop", t("help_loop_desc")),
            ("loopq", t("help_loopq_desc")),
            ("shuffle", t("help_shuffle_desc")),
        ]

        for cmd, desc in commands:
            embed.add_field(name=f"`/{cmd}` vagy `{prefix}{cmd}`", value=desc, inline=False)

        return embed

