import discord
from discord.ui import Modal, TextInput

from core.actions import RadioState
from ui.feedback import get_feedback
from ui.i18n import t
from ui.icons import Icons
from ui.utils import respond
from ui.views.base import handle_ui_error


class SeekButton(discord.ui.Button):
    def __init__(self, radio):
        super().__init__(
            label=None if radio.is_compact else t('seek_label'),
            emoji=Icons.SEEK,
            style=discord.ButtonStyle.secondary,
            custom_id="seek_button",
            disabled=(radio.status in [RadioState.STOPPED, RadioState.IDLE])
        )
        self.radio = radio

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        if self.radio.status in [RadioState.IDLE, RadioState.STOPPED]:
            await respond(interaction, get_feedback("cannot_seek_stopped"), delete_after=self.radio.config.notification_timeout)
            return
        modal = SeekModal(self.radio)
        await interaction.response.send_modal(modal)

class SeekModal(Modal):
    def __init__(self, radio):
        super().__init__(title=t("jump_modal_title"))
        self.radio = radio
        self.timestamp_input = TextInput(
            label=t("timestamp_input_label"),
            placeholder="01:30",
            style=discord.TextStyle.short,
            required=True,
            max_length=5
        )
        self.add_item(self.timestamp_input)

    @handle_ui_error
    async def on_submit(self, interaction: discord.Interaction):
        res = self.radio.command_service.seek(interaction.user, self.timestamp_input.value)
        await respond(interaction, res.feedback, delete_after=self.radio.config.notification_timeout)
