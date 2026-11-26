import discord
from discord.ui import Modal, TextInput

from ui.feedback import get_feedback
from ui.i18n import t
from ui.icons import Icons
from ui.utils import respond
from ui.views.base import handle_ui_error


class VolumeButton(discord.ui.Button):
    def __init__(self, radio):
        super().__init__(
            label=None if radio.is_compact else t('vol_label'),
            emoji=Icons.VOLUME,
            style=discord.ButtonStyle.secondary,
            custom_id="volume_button"
        )
        self.radio = radio

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        modal = VolumeModal(self.radio)
        await interaction.response.send_modal(modal)

class VolumeModal(Modal):
    def __init__(self, radio):
        super().__init__(title=t("vol_modal_title"))
        self.radio = radio
        self.volume_input = TextInput(
            label=t("vol_input_label"),
            placeholder="50",
            style=discord.TextStyle.short,
            required=True,
            max_length=3
        )
        self.add_item(self.volume_input)

    @handle_ui_error
    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = int(self.volume_input.value)
        except ValueError:
            await respond(interaction, get_feedback("invalid_number"), delete_after=self.radio.config.notification_timeout)
            return

        res = self.radio.command_service.volume(interaction.user, value)
        await respond(interaction, res.feedback, delete_after=self.radio.config.notification_timeout)
