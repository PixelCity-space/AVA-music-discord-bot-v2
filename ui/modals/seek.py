import discord
from discord.ui import Modal, TextInput
from ui.icons import Icons
from ui.i18n import t
from ui.utils import respond, get_feedback
from ui.views.base import handle_ui_error
from core.actions import RadioAction, RadioState

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
        ts = self.timestamp_input.value
        try:
            parts = ts.split(":")
            if len(parts) == 2:
                minutes, seconds = map(int, parts)
                if minutes < 0 or seconds < 0 or seconds >= 60:
                    await respond(interaction, get_feedback("format_error"), delete_after=self.radio.config.notification_timeout)
                    return
                total_seconds = minutes * 60 + seconds
            else:
                total_seconds = int(ts)
        except Exception:
            await respond(interaction, get_feedback("format_error"), delete_after=self.radio.config.notification_timeout)
            return
        
        if total_seconds < 0:
            await respond(interaction, get_feedback("format_error"), delete_after=self.radio.config.notification_timeout)
            return

        if not self.radio.current_song:
            await respond(interaction, get_feedback("no_current_track"), delete_after=self.radio.config.notification_timeout)
            return

        if self.radio.current_song.duration > 0 and total_seconds > self.radio.current_song.duration:
            await respond(interaction, get_feedback("too_long"), delete_after=self.radio.config.notification_timeout)
            return
            
        self.radio.dispatch(RadioAction.SEEK, total_seconds, user=interaction.user)
        feedback = f"{get_feedback('jumping')} {ts}"
        await respond(interaction, feedback, delete_after=self.radio.config.notification_timeout)
