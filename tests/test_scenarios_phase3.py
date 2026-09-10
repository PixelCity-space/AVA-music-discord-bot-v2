"""
Phase 3 Stress Test Suite: 35 Brand New Scenarios.
Targeting Prefix Commands, Embed State, Database, YT-DLP Probing, Voice Management,
FFmpeg Audio Sources, Progress Bar Boundaries, Action Dispatching, and Modal Inputs.
"""

import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from cogs.prefix_commands import handle_prefix_commands
from core.actions import RadioAction, RadioState
from core.database import Database
from core.embed_state import EmbedStateManager
from core.models import Song
from core.state import RadioManager
from providers.ytdlp_provider import YTDLPProvider
from services.player.audio_source import AudioSourceFactory
from services.player.voice_manager import VoiceManager
from tests.conftest import MockMember
from ui.components.progress_bar import create_progress_bar
from ui.icons import Icons
from ui.modals.seek import SeekModal
from ui.modals.volume import VolumeModal


# =====================================================================
# Feature 1: Prefix Commands (cogs/prefix_commands.py)
# =====================================================================

@pytest.mark.asyncio
async def test_scenario_01_prefix_trailing_spaces_and_casing(mock_config, test_db):
    """Scenario 01: Prefix command with leading/trailing spaces and mixed casing."""
    radio = RadioManager(mock_config, test_db)
    mock_channel = AsyncMock()
    mock_channel.id = mock_config.radio_text_channel_id
    author = MockMember()
    msg = AsyncMock()
    msg.author = author
    msg.author.bot = False
    msg.channel = mock_channel
    msg.content = "   !pLaY   https://youtube.com/watch?v=abc   "
    radio.command_service.play = MagicMock(return_value=MagicMock(feedback="Playing"))

    await handle_prefix_commands(msg, radio)
    # Stress test: Command with leading whitespace should be parsed, not discarded
    assert radio.command_service.play.called, "Prefix command with leading whitespace was discarded!"
    radio.command_service.play.assert_called_once_with(author, "https://youtube.com/watch?v=abc")


@pytest.mark.asyncio
async def test_scenario_02_prefix_seek_without_arguments(mock_config, test_db):
    """Scenario 02: Prefix !seek invoked with no arguments."""
    radio = RadioManager(mock_config, test_db)
    mock_channel = AsyncMock()
    mock_channel.id = mock_config.radio_text_channel_id
    author = MockMember()
    msg = AsyncMock()
    msg.author = author
    msg.author.bot = False
    msg.channel = mock_channel
    msg.content = "!seek"
    radio.command_service.seek = MagicMock()

    await handle_prefix_commands(msg, radio)
    # Stress test: Running !seek without arguments should provide feedback rather than silently returning
    assert mock_channel.send.called, "!seek without arguments gave no feedback to the user!"


@pytest.mark.asyncio
async def test_scenario_03_prefix_volume_invalid_text(mock_config, test_db):
    """Scenario 03: Prefix !volume invoked with invalid text ('50%' or 'loud')."""
    radio = RadioManager(mock_config, test_db)
    mock_channel = AsyncMock()
    mock_channel.id = mock_config.radio_text_channel_id
    author = MockMember()
    msg = AsyncMock()
    msg.author = author
    msg.author.bot = False
    msg.channel = mock_channel
    msg.content = "!volume 50%"

    await handle_prefix_commands(msg, radio)
    mock_channel.send.assert_called_once()
    call_content = mock_channel.send.call_args[0][0]
    assert "50%" not in call_content


@pytest.mark.asyncio
async def test_scenario_04_prefix_wrong_channel_ignored(mock_config, test_db):
    """Scenario 04: Prefix command sent in an unassigned channel is ignored."""
    radio = RadioManager(mock_config, test_db)
    mock_channel = AsyncMock()
    mock_channel.id = 999999  # Not radio_text_channel_id
    msg = AsyncMock()
    msg.author = MockMember()
    msg.author.bot = False
    msg.channel = mock_channel
    msg.content = "!play something"
    radio.command_service.play = MagicMock()

    await handle_prefix_commands(msg, radio)
    radio.command_service.play.assert_not_called()


@pytest.mark.asyncio
async def test_scenario_05_prefix_bot_author_ignored(mock_config, test_db):
    """Scenario 05: Prefix command sent by a bot author is ignored."""
    radio = RadioManager(mock_config, test_db)
    mock_channel = AsyncMock()
    mock_channel.id = mock_config.radio_text_channel_id
    msg = AsyncMock()
    msg.author = MockMember()
    msg.author.bot = True  # Bot sender
    msg.channel = mock_channel
    msg.content = "!skip"
    radio.command_service.skip = MagicMock()

    await handle_prefix_commands(msg, radio)
    radio.command_service.skip.assert_not_called()


@pytest.mark.asyncio
async def test_scenario_06_prefix_rapid_spam_delayed_delete_tasks(mock_config, test_db):
    """Scenario 06: Rapid spam of prefix commands schedules deletion tasks safely."""
    radio = RadioManager(mock_config, test_db)
    mock_channel = AsyncMock()
    mock_channel.id = mock_config.radio_text_channel_id
    radio.command_service.skip = MagicMock(return_value=MagicMock(feedback="Skipped"))

    msgs = []
    for _ in range(5):
        m = AsyncMock()
        m.author = MockMember()
        m.author.bot = False
        m.channel = mock_channel
        m.content = "!skip"
        msgs.append(m)
        await handle_prefix_commands(m, radio)

    await asyncio.sleep(0.15)
    for m in msgs:
        m.delete.assert_called_once()


# =====================================================================
# Feature 2: Embed State Persistence (core/embed_state.py)
# =====================================================================

def test_scenario_07_embed_state_corrupt_json(tmp_path):
    """Scenario 07: Loading from a corrupt or truncated JSON file."""
    corrupt_file = tmp_path / "corrupt_embed_state.json"
    corrupt_file.write_text("{ incomplete json: ", encoding="utf-8")
    mgr = EmbedStateManager(str(corrupt_file))
    assert mgr.state == {}


def test_scenario_08_embed_state_non_serializable_object(tmp_path):
    """Scenario 08: Saving a non-serializable object into embed state."""
    state_file = tmp_path / "state.json"
    mgr = EmbedStateManager(str(state_file))

    class UnserializableObject:
        pass

    try:
        mgr.save_value("bad_key", UnserializableObject())
    except TypeError:
        pytest.fail("EmbedStateManager.save_value raised unhandled TypeError on non-serializable value!")


def test_scenario_09_embed_state_invalid_or_negative_message_id(tmp_path):
    """Scenario 09: Saving a negative message ID into embed state."""
    state_file = tmp_path / "state.json"
    mgr = EmbedStateManager(str(state_file))
    mgr.save_message_id("station", -1)
    loaded = mgr.load_message_id("station")
    # Stress test: Discord message snowflakes cannot be negative
    assert loaded is None or loaded > 0, f"EmbedStateManager accepted negative Discord snowflake ID: {loaded}!"


def test_scenario_10_embed_state_missing_parent_directory(tmp_path):
    """Scenario 10: Initializing with a deeply nested non-existent directory."""
    nested_file = tmp_path / "dir1" / "dir2" / "dir3" / "embed_state.json"
    mgr = EmbedStateManager(str(nested_file))
    mgr.save_value("hello", "world")
    assert nested_file.exists()


# =====================================================================
# Feature 3: Database Operations (core/database.py)
# =====================================================================

def test_scenario_11_db_get_history_latest_negative_offset(test_db):
    """Scenario 11: get_history_latest with negative offset value."""
    song = Song(title="Track 1", path="http://track1")
    test_db.add_history(song)
    # Calling get_history_latest with offset=-1 should not crash SQLite with syntax error
    res = test_db.get_history_latest(offset=-1)
    assert res is None


def test_scenario_12_db_set_cache_batch_malformed_entries(test_db):
    """Scenario 12: set_cache_batch containing an entry with duration: None."""
    batch = [
        {"url": "http://song_valid_1", "title": "Song 1", "duration": None},
        {"url": "http://song_valid_2", "title": "Song 2", "duration": 150}
    ]
    # Stress test: duration: None should not crash the entire transaction with TypeError
    test_db.set_cache_batch(batch)
    cached = test_db.get_cache("http://song_valid_2")
    assert cached is not None, "Valid song was not cached because duration: None broke set_cache_batch!"


def test_scenario_13_db_add_favorite_sql_injection_title(test_db):
    """Scenario 13: SQL injection string inside song title."""
    song = Song(title="Cool Song'; DROP TABLE favorites;--", path="http://injected")
    test_db.add_favorite("user_sql", song)
    favs = test_db.get_favorites("user_sql")
    assert len(favs) == 1
    assert favs[0].title == "Cool Song'; DROP TABLE favorites;--"


def test_scenario_14_db_is_favorite_empty_or_none(test_db):
    """Scenario 14: is_favorite called with empty user_id or None path."""
    assert test_db.is_favorite("", None) is False
    assert test_db.is_favorite(None, "http://path") is False


def test_scenario_15_db_clear_favorites_nonexistent_user(test_db):
    """Scenario 15: clear_favorites for a non-existent user."""
    test_db.clear_favorites("ghost_user_9999")
    assert test_db.get_favorite_count("ghost_user_9999") == 0


# =====================================================================
# Feature 4: YT-DLP Provider Probing (providers/ytdlp_provider.py)
# =====================================================================

@pytest.mark.asyncio
async def test_scenario_16_ytdlp_resolve_livestream_none_duration():
    """Scenario 16: Resolving a livestream probe where yt-dlp returns duration: null."""
    provider = YTDLPProvider()
    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_json = '{"title": "Live Stream", "url": "https://live.m3u8", "duration": null}'
    mock_process.communicate.return_value = (mock_json.encode("utf-8"), b"")

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        res = await provider.resolve("https://youtube.com/watch?v=live123")
        # Stress test: duration: null in JSON should resolve cleanly with duration=0 instead of throwing TypeError
        assert res is not None, "Livestream resolution failed because duration was None!"
        assert res["duration"] == 0


@pytest.mark.asyncio
async def test_scenario_17_ytdlp_resolve_playlist_entry_with_none_duration():
    """Scenario 17: Playlist resolving containing an entry with duration: null."""
    provider = YTDLPProvider()
    mock_process = AsyncMock()
    mock_process.returncode = 0
    lines = [
        '{"title": "Track 1", "url": "http://track1", "duration": 120}',
        '{"title": "Live Premiere 2", "url": "http://track2", "duration": null}'
    ]
    mock_process.communicate.return_value = ("\n".join(lines).encode("utf-8"), b"")

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        results = await provider.resolve_playlist("http://playlist_url")
        # Stress test: The live premiere should not be silently dropped from the playlist
        assert len(results) == 2, f"Expected 2 tracks from playlist, but got {len(results)}! Track with duration=None was dropped."


@pytest.mark.asyncio
async def test_scenario_18_ytdlp_search_result_with_none_duration():
    """Scenario 18: Search result containing an entry with duration: null."""
    provider = YTDLPProvider()
    mock_process = AsyncMock()
    mock_process.returncode = 0
    lines = [
        '{"title": "Live Broadcast", "url": "http://live", "duration": null}'
    ]
    mock_process.communicate.return_value = ("\n".join(lines).encode("utf-8"), b"")

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        results = await provider.search("live concert")
        # Stress test: Search result with duration: null should not be discarded
        assert len(results) == 1, f"Expected 1 search result, but got {len(results)}! Result was dropped."


@pytest.mark.asyncio
async def test_scenario_19_ytdlp_error_probing_binary_undecodable_stderr():
    """Scenario 19: Non-zero exit code with non-UTF8 binary stderr output."""
    provider = YTDLPProvider()
    mock_process = AsyncMock()
    mock_process.returncode = 1
    mock_process.communicate.return_value = (b"", b"\xff\xfe\xfd Error message")

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        res = await provider.resolve("https://youtube.com/watch?v=bad")
        assert res is None


@pytest.mark.asyncio
async def test_scenario_20_ytdlp_timeout_kills_process():
    """Scenario 20: Subprocess resolution timeout kills the hung process."""
    provider = YTDLPProvider()
    mock_process = AsyncMock()
    mock_process.communicate.side_effect = asyncio.TimeoutError()

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        res = await provider.resolve("https://youtube.com/watch?v=hang")
        assert res is None
        mock_process.kill.assert_called_once()


# =====================================================================
# Feature 5: Voice Manager (services/player/voice_manager.py)
# =====================================================================

@pytest.mark.asyncio
async def test_scenario_21_voice_manager_switch_channel_to_forbidden_bot(mock_config, test_db):
    """Scenario 21: switch_channel target channel contains a forbidden bot."""
    mock_config.forbidden_bot_ids = [9999]
    radio = RadioManager(mock_config, test_db)
    bot = MagicMock()
    guild = MagicMock()
    bot.get_guild.return_value = guild

    target_channel = MagicMock()
    target_channel.id = 5555
    target_channel.name = "Forbidden Room"
    bot_member = MagicMock()
    bot_member.bot = True
    bot_member.id = 9999  # Forbidden bot
    target_channel.members = [bot_member]
    guild.get_channel.return_value = target_channel

    voice_client = AsyncMock()
    voice_client.is_connected.return_value = True

    vm = VoiceManager(bot, mock_config, radio)
    switched = await vm.switch_channel(5555, voice_client)
    # Stress test: switch_channel should enforce the forbidden bot policy
    assert switched is False, "switch_channel allowed moving into a channel containing a forbidden bot!"
    voice_client.move_to.assert_not_called()


@pytest.mark.asyncio
async def test_scenario_22_voice_manager_switch_channel_same_channel(mock_config, test_db):
    """Scenario 22: switch_channel called with the channel the bot is already in."""
    radio = RadioManager(mock_config, test_db)
    radio.voice_channel_id = 1234
    vm = VoiceManager(MagicMock(), mock_config, radio)
    voice_client = AsyncMock()
    res = await vm.switch_channel(1234, voice_client)
    assert res is False
    voice_client.move_to.assert_not_called()


@pytest.mark.asyncio
async def test_scenario_23_voice_manager_connect_forbidden_permission(mock_config, test_db):
    """Scenario 23: Channel connection raises discord.Forbidden."""
    radio = RadioManager(mock_config, test_db)
    radio.voice_channel_id = 1234
    bot = MagicMock()
    guild = MagicMock()
    guild.voice_client = None
    channel = AsyncMock()
    channel.members = []
    channel.connect.side_effect = discord.Forbidden(MagicMock(), "Missing Connect Permission")
    guild.get_channel.return_value = channel
    bot.get_guild.return_value = guild

    vm = VoiceManager(bot, mock_config, radio)
    vc = await vm.ensure_voice()
    assert vc is None
    assert radio.voice is None


@pytest.mark.asyncio
async def test_scenario_24_voice_manager_solitary_timeout_all_members_are_bots(mock_config, test_db):
    """Scenario 24: Solitary countdown starts when all other channel members are bots."""
    radio = RadioManager(mock_config, test_db)
    vm = VoiceManager(MagicMock(), mock_config, radio)
    voice = MagicMock()
    b1 = MagicMock(bot=True)
    b2 = MagicMock(bot=True)
    voice.channel.members = [b1, b2]

    await vm.check_solitary_timeout(voice)
    assert vm.solitary_start is not None, "Solitary countdown should start when only bots are present!"


# =====================================================================
# Feature 6: Audio Source Factory (services/player/audio_source.py)
# =====================================================================

def test_scenario_25_audio_source_volume_bounds_clamped(mock_config, test_db):
    """Scenario 25: Negative volume parameter in create_ffmpeg_source."""
    radio = RadioManager(mock_config, test_db)
    factory = AudioSourceFactory(mock_config, radio)
    with patch("discord.FFmpegOpusAudio") as mock_ffmpeg:
        factory.create_ffmpeg_source("http://stream.mp3", volume=-0.5)
        options = mock_ffmpeg.call_args[1]["options"]
        # Stress test: Volume must be clamped to >= 0.0 to prevent FFmpeg filter failure
        assert "volume=0" in options or "volume=0.0" in options, f"Negative volume was not clamped: {options}"


def test_scenario_26_audio_source_user_agent_with_quotes(mock_config, test_db):
    """Scenario 26: User-Agent header with unescaped double quotes."""
    radio = RadioManager(mock_config, test_db)
    factory = AudioSourceFactory(mock_config, radio)
    song = Song(title="Track", path="http://stream.mp3", is_external=True)
    song.http_headers = {"User-Agent": 'Evil" -malicious_opt'}
    with patch("discord.FFmpegOpusAudio") as mock_ffmpeg:
        factory.create_ffmpeg_source("http://stream.mp3", song=song)
        before_opts = mock_ffmpeg.call_args[1]["before_options"]
        # Stress test: Unescaped quotes break the FFmpeg command line string
        assert 'Evil" -malicious_opt"' not in before_opts, f"Unescaped quotes found in user-agent: {before_opts}"


@pytest.mark.asyncio
async def test_scenario_27_audio_source_resolve_external_missing_stream_url(mock_config, test_db):
    """Scenario 27: Resolving external song where provider returns None stream_url."""
    radio = RadioManager(mock_config, test_db)
    factory = AudioSourceFactory(mock_config, radio)
    song = Song(title="No Stream", path="http://external.url", is_external=True)
    with patch("providers.resolve_any", return_value={"title": "No Stream", "stream_url": None}):
        res = await factory.resolve_source(song)
        assert res is None


# =====================================================================
# Feature 7: Progress Bar Component (ui/components/progress_bar.py)
# =====================================================================

def test_scenario_28_progress_bar_zero_or_one_width():
    """Scenario 28: Progress bar rendered with width=1."""
    bar = create_progress_bar(current=0, total=0, width=1)
    # Stress test: Progress bar with width=1 must not exceed length 1
    assert len(bar) <= 1, f"Progress bar with width=1 generated '{bar}' with length {len(bar)} > 1!"


def test_scenario_29_progress_bar_current_exceeds_total():
    """Scenario 29: Current position exceeding total duration (150%)."""
    bar = create_progress_bar(current=150, total=100, width=18)
    assert bar.endswith(str(Icons.PB_END))


def test_scenario_30_progress_bar_zero_total_custom_width():
    """Scenario 30: Zero total duration with custom width."""
    width = 25
    bar = create_progress_bar(current=0, total=0, width=width)
    assert len(bar) == width


# =====================================================================
# Feature 8: Radio State Action Dispatching (core/state.py)
# =====================================================================

@pytest.mark.asyncio
async def test_scenario_31_state_add_songs_none_payload(mock_config, test_db):
    """Scenario 31: ADD_SONGS action with None payload."""
    radio = RadioManager(mock_config, test_db)
    try:
        await radio._add_songs(None)
    except TypeError as e:
        pytest.fail(f"_add_songs(None) crashed with TypeError: {e}")


def test_scenario_32_state_move_song_direction_out_of_bounds(mock_config, test_db):
    """Scenario 32: MOVE_SONG action with large offset."""
    radio = RadioManager(mock_config, test_db)
    s1 = Song(title="1", path="1")
    s2 = Song(title="2", path="2")
    s3 = Song(title="3", path="3")
    radio.queue = [s1, s2, s3]

    radio.dispatch(RadioAction.MOVE_SONG, (s1, 10))
    # Queue should remain unaffected or safely clamped
    assert radio.queue == [s1, s2, s3]


def test_scenario_33_state_toggle_favorite_empty_path(mock_config, test_db):
    """Scenario 33: TOGGLE_FAVORITE for a song with empty path."""
    radio = RadioManager(mock_config, test_db)
    empty_song = Song(title="Empty Path", path="")
    radio.dispatch(RadioAction.TOGGLE_FAVORITE, ("user_1", empty_song))
    assert test_db.get_favorite_count("user_1") == 0


# =====================================================================
# Feature 9: Modals Input Parsing (ui/modals/volume.py & seek.py)
# =====================================================================

@pytest.mark.asyncio
async def test_scenario_34_volume_modal_submit_percentage(mock_config, test_db):
    """Scenario 34: Volume modal submitted with '50%'."""
    radio = RadioManager(mock_config, test_db)
    modal = VolumeModal(radio)
    modal.volume_input = MagicMock()
    modal.volume_input.value = "50%"
    interaction = AsyncMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.user = MockMember()
    await modal.on_submit(interaction)
    interaction.response.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_scenario_35_seek_modal_submit_negative_timestamp(mock_config, test_db):
    """Scenario 35: Seek modal submitted with negative timestamp '-01:30'."""
    radio = RadioManager(mock_config, test_db)
    radio.current_song = Song(title="Song", path="http://s", duration=180)
    radio.dispatch = MagicMock()
    modal = SeekModal(radio)
    modal.timestamp_input = MagicMock()
    modal.timestamp_input.value = "-01:30"
    interaction = AsyncMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.user = MockMember()
    await modal.on_submit(interaction)

    # Stress test: Negative seek position should be rejected before dispatching
    if radio.dispatch.called:
        dispatched_seconds = radio.dispatch.call_args[0][1]
        assert dispatched_seconds >= 0, f"SeekModal dispatched negative timestamp {dispatched_seconds}s to player!"
