import discord
from discord.ui import Modal, TextInput
from ui.icons import Icons
from ui.i18n import t
from ui.feedback import get_feedback
from ui.utils import respond
from ui.views.base import handle_ui_error
from core.actions import RadioAction

class WebLinkButton(discord.ui.Button):
    def __init__(self, radio, custom_id="weblink_button"):
        super().__init__(
            label=None if radio.is_compact else t('weblink_label'),
            emoji=Icons.GLOBE,
            style=discord.ButtonStyle.secondary,
            custom_id=custom_id
        )
        self.radio = radio

    @handle_ui_error
    async def callback(self, interaction: discord.Interaction):
        modal = WebLinkModal(self.radio)
        await interaction.response.send_modal(modal)

class WebLinkModal(Modal):
    def __init__(self, radio):
        super().__init__(title=t("weblink_modal_title"))
        self.radio = radio
        self.url_input = TextInput(
            label=t("weblink_input_label"),
            placeholder=t('weblink_placeholder'),
            style=discord.TextStyle.short,
            required=True,
            min_length=5
        )
        self.add_item(self.url_input)

    @handle_ui_error
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        url = self.url_input.value.strip()
        if not url:
            return
        
        self.radio.dispatch(RadioAction.ADD_EXT_LINK, url, user=interaction.user)
        await respond(interaction, get_feedback("weblink_added"), delete_after=self.radio.config.notification_timeout)
