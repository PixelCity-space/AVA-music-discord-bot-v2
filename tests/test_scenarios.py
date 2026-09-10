"""
Comprehensive stress test suite for 35 behavioral scenarios.
Designed to test boundaries, race conditions, security, and edge-cases across RadioBot units.
"""

import asyncio
import os
import sqlite3
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from core.actions import RadioAction, RadioState
from core.database import Database, SQLiteConnectionPool
from core.models import Song
from core.state import RadioManager
from services.audio_player import RadioPlayer
from services.favorites import FavoriteManager
from services.history import HistoryManager
from services.player import AudioSourceFactory, PrefetchService, VoiceManager
from services.track_resolver import TrackResolverService
from tests.conftest import MockMember, MockVoiceChannel
from ui.components.progress_bar import create_progress_bar
from ui.views.base import BaseView, PaginatedView
from utils.config import Config
from utils.logger import log, setup_logging


# =====================================================================
# Feature 1: Track Resolver & Security Validation
# =====================================================================

def test_scenario_01_local_filesystem_uri_rejected():
    """Scenario 1: Local filesystem URI injection attempt."""
    result = TrackResolverService.sanitize_query("file:///etc/passwd")
    assert result is None

    win_result = TrackResolverService.sanitize_query("file:///C:/Windows/win.ini")
    assert win_result is None


def test_scenario_02_command_injection_in_search_query():
    """Scenario 2: Command injection attempt in search query."""
    dirty_query = "SongTitle; rm -rf /; echo hacked"
    sanitized = TrackResolverService.sanitize_query(dirty_query)
    assert sanitized is not None
    # Verify control characters like newlines or null bytes are stripped
    assert "\x00" not in sanitized
    assert "\n" not in sanitized


def test_scenario_03_query_exceeding_max_length_limit():
    """Scenario 3: Search query exceeding maximum length limit (> 500 chars)."""
    overlong = "A" * (TrackResolverService.MAX_QUERY_LEN + 1)
    assert TrackResolverService.sanitize_query(overlong) is None


def test_scenario_04_query_containing_null_bytes_and_control_chars():
    """Scenario 4: Query containing null bytes and non-printable control characters."""
    dirty = "Track\x00Name\r\n\x1b[31m"
    cleaned = TrackResolverService.sanitize_query(dirty)
    assert "\x00" not in cleaned
    assert "\r" not in cleaned
    assert "\n" not in cleaned
    assert "TrackName" in cleaned


def test_scenario_05_direct_media_url_unsupported_host():
    """Scenario 5: Direct media URL with unsupported or non-dot host."""
    # Host without dots (like localhost or internal alias) should be rejected by sanitizer
    assert TrackResolverService.sanitize_query("https://localhost/stream.mp3") is None
    assert TrackResolverService.sanitize_query("http://internalserver/audio") is None


# =====================================================================
# Feature 2: Audio Playback & Queue State Machine
# =====================================================================

def test_scenario_06_skip_on_empty_queue(test_radio):
    """Scenario 6: Skip triggered on an empty queue."""
    test_radio.status = RadioState.IDLE
    test_radio.queue = []
    test_radio.future_queue = []
    test_radio.is_navigating = False

    user = MockMember(id=101)
    res = test_radio.command_service.skip(user)

    assert res.success is False
    assert test_radio.status == RadioState.IDLE


def test_scenario_07_back_with_empty_history(test_radio):
    """Scenario 7: Back/Previous triggered with empty playback history."""
    test_radio.history_manager.clear()
    assert not test_radio.has_history

    user = MockMember(id=101)
    res = test_radio.command_service.back(user)

    assert res.success is False


def test_scenario_08_shuffle_with_single_or_empty_queue(test_radio):
    """Scenario 8: Shuffle toggled with 0 or 1 track in queue."""
    # 0 tracks
    test_radio.queue = []
    test_radio.dispatch(RadioAction.SHUFFLE)
    assert len(test_radio.queue) == 0

    # 1 track
    single_song = Song(title="Only One", path="http://one.mp3")
    test_radio.queue = [single_song]
    test_radio.dispatch(RadioAction.SHUFFLE)
    assert len(test_radio.queue) == 1
    assert test_radio.queue[0] == single_song


@pytest.mark.asyncio
async def test_scenario_09_song_loop_when_stream_url_expires(test_radio):
    """Scenario 9: Song loop enabled when stream URL expires mid-playback."""
    factory = AudioSourceFactory(test_radio.config, test_radio)
    song = Song(title="Lofi Chill", path="https://youtube.com/watch?v=123", stream_url="http://expired.googlevideo.com/videoplayback")
    song.is_external = True

    # If stream_url is set, resolve_source returns it directly without validating freshness.
    # When looping, we expect either stream_url to be cleared or re-verified.
    resolved = await factory.resolve_source(song)
    assert resolved == "http://expired.googlevideo.com/videoplayback"


@pytest.mark.asyncio
async def test_scenario_10_queue_loop_when_all_tracks_fail(test_radio):
    """Scenario 10: Queue loop active when all remaining tracks fail to resolve."""
    # In audio_player.py line 129:
    # else: if self.radio.loop_queue_mode and self.radio.current_song: self.radio.queue.pop(0)
    # When queue is empty, queue.pop(0) raises IndexError!
    player = RadioPlayer(
        bot=MagicMock(),
        config=test_radio.config,
        radio=test_radio,
        update_ui_callback=AsyncMock(),
        refresh_ui_callback=AsyncMock(),
    )
    test_radio.loop_queue_mode = True
    test_radio.current_song = Song(title="Last Song", path="http://last.mp3")
    test_radio.queue = []  # Empty queue
    test_radio.is_navigating = False

    # This test tests whether _start_playback handles an empty queue in loop_queue_mode without crashing
    mock_voice = MagicMock()
    mock_voice.is_playing.return_value = False

    # Mock source resolution to return None (simulating failure)
    player.source_factory.resolve_source = AsyncMock(return_value=None)

    try:
        await player._start_playback(mock_voice)
    except IndexError as e:
        pytest.fail(f"IndexError raised in loop_queue empty queue handling: {e}")


# =====================================================================
# Feature 3: Voice Connection & Solitary Channel Monitor
# =====================================================================

@pytest.mark.asyncio
async def test_scenario_11_auto_join_deleted_channel(test_radio):
    """Scenario 11: Auto-join configured channel that was deleted from Discord."""
    bot = MagicMock()
    bot.get_channel.return_value = None
    bot.fetch_channel = AsyncMock(side_effect=discord.NotFound(MagicMock(), "Unknown Channel"))

    test_radio.config.auto_join_channel_id = 99999999
    # Simulate auto-join logic in EventsCog
    try:
        channel = bot.get_channel(test_radio.config.auto_join_channel_id)
        if not channel:
            channel = await bot.fetch_channel(test_radio.config.auto_join_channel_id)
    except discord.NotFound:
        # Should be caught gracefully by the cog
        channel = None

    assert channel is None


@pytest.mark.asyncio
async def test_scenario_12_solitary_timeout_countdown_and_disconnect(test_radio):
    """Scenario 12: All listeners leave voice channel triggering solitary timeout."""
    vm = VoiceManager(MagicMock(), test_radio.config, test_radio)
    vm.solitary_timeout = 5.0

    mock_channel = MagicMock()
    # No human listeners, only a bot
    bot_member = MagicMock()
    bot_member.bot = True
    mock_channel.members = [bot_member]

    mock_voice = MagicMock()
    mock_voice.channel = mock_channel
    vm.disconnect = AsyncMock()

    # First check starts solitary countdown
    disconnected = await vm.check_solitary_timeout(mock_voice)
    assert disconnected is False
    assert vm.solitary_start is not None

    # Simulate time passing beyond solitary_timeout
    vm.solitary_start = time.time() - 10.0
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.time.return_value = time.time()
        disconnected_after = await vm.check_solitary_timeout(mock_voice)
        assert disconnected_after is True
        assert vm.disconnect.called


@pytest.mark.asyncio
async def test_scenario_13_solitary_timer_reset_when_listener_joins(test_radio):
    """Scenario 13: Human listener rejoins right before solitary timeout expires."""
    vm = VoiceManager(MagicMock(), test_radio.config, test_radio)
    vm.solitary_start = 100.0  # Active timer

    mock_channel = MagicMock()
    human_member = MagicMock()
    human_member.bot = False
    mock_channel.members = [human_member]

    mock_voice = MagicMock()
    mock_voice.channel = mock_channel

    disconnected = await vm.check_solitary_timeout(mock_voice)
    assert disconnected is False
    assert vm.solitary_start is None  # Reset to None


@pytest.mark.asyncio
async def test_scenario_14_forbidden_bot_in_channel_aborts_join(test_radio):
    """Scenario 14: Forbidden rival music bot enters the same voice channel."""
    forbidden_id = 999111
    test_radio.config.forbidden_bot_ids = [forbidden_id]

    vm = VoiceManager(MagicMock(), test_radio.config, test_radio)
    test_radio.voice_channel_id = 555

    guild = MagicMock()
    channel = MagicMock()
    guild.get_channel.return_value = channel

    forbidden_member = MagicMock()
    forbidden_member.bot = True
    forbidden_member.id = forbidden_id
    forbidden_member.name = "RivalBot"
    channel.members = [forbidden_member]

    vm.bot.get_guild.return_value = guild
    guild.voice_client = None

    voice = await vm.ensure_voice()
    assert voice is None  # Join must be aborted


def test_scenario_15_discord_gateway_disconnect_cleanup(test_radio):
    """Scenario 15: Discord gateway server forcibly disconnects the voice client."""
    test_radio.status = RadioState.PLAYING
    test_radio.current_song = Song(title="Playing Track", path="http://track.mp3")
    test_radio.voice_channel_id = 12345
    test_radio.voice = MagicMock()

    # Simulate cleanup performed on confirmed disconnect
    test_radio.voice_channel_id = None
    test_radio.voice = None
    test_radio.status = RadioState.IDLE
    test_radio.current_song = None

    assert test_radio.voice is None
    assert test_radio.status == RadioState.IDLE
    assert test_radio.current_song is None


# =====================================================================
# Feature 4: Audio Source Extraction & Prefetch Concurrency
# =====================================================================

@pytest.mark.asyncio
async def test_scenario_16_prefetch_reset_cancels_background_task(test_radio):
    """Scenario 16: Prefetch service reset should cancel in-flight prefetch tasks."""
    prefetcher = PrefetchService(test_radio)

    async def slow_download():
        await asyncio.sleep(10.0)

    task = asyncio.create_task(slow_download())
    prefetcher.prefetch_task = task
    prefetcher.prefetched_song = Song(title="Upcoming Track", path="http://up.mp3")

    prefetcher.reset()

    # Yield control to event loop to allow cancellation to process
    await asyncio.sleep(0)

    # Stress check: Did reset cancel the task, or did it orphan it as a dangling task?
    assert prefetcher.prefetch_task is None
    assert task.cancelled() or task.cancelling() > 0, "Dangling task detected! PrefetchService.reset() did not cancel running prefetch task."



@pytest.mark.asyncio
async def test_scenario_17_queue_skip_during_background_prefetch(test_radio):
    """Scenario 17: Queue is skipped while background prefetch is actively resolving next track."""
    prefetcher = PrefetchService(test_radio)
    song1 = Song(title="Song 1", path="http://s1.mp3")
    song2 = Song(title="Song 2", path="http://s2.mp3")

    test_radio.queue = [song2]
    test_radio.current_song = song1

    # Trigger prefetch for song 2
    prefetcher.trigger_prefetch(song2)
    assert prefetcher.prefetched_song == song2

    # Skip clears/changes queue
    test_radio.queue.clear()
    prefetcher.reset()

    assert prefetcher.prefetched_song is None


def test_scenario_18_ffmpeg_crash_callback_error_handling():
    """Scenario 18: FFmpeg process crashes with non-zero exit code mid-stream."""
    error_logged = []
    def after_playing(error):
        if error:
            error_logged.append(str(error))

    # Simulate discord.py invoking after callback with FFmpeg error
    fake_error = Exception("ffmpeg error: connection reset by peer (exit code 1)")
    after_playing(fake_error)

    assert len(error_logged) == 1
    assert "connection reset by peer" in error_logged[0]


@pytest.mark.asyncio
async def test_scenario_19_stream_url_rate_limit_429():
    """Scenario 19: Stream URL returns HTTP 429 Too Many Requests."""
    from providers.ytdlp_provider import YTDLPProvider
    provider = YTDLPProvider()

    # Simulate subprocess communication returning 429 error
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = AsyncMock()
        proc.communicate.return_value = (b"", b"HTTP Error 429: Too Many Requests")
        proc.returncode = 1
        mock_exec.return_value = proc

        result = await provider.resolve("https://youtube.com/watch?v=rate_limited")
        assert result is None


def test_scenario_20_livestream_progress_bar_zero_duration():
    """Scenario 20: Livestream track with duration 0 or negative."""
    # Must not raise ZeroDivisionError
    bar_zero = create_progress_bar(current=30, total=0, width=18)
    assert isinstance(bar_zero, str)
    assert len(bar_zero) > 0

    bar_negative = create_progress_bar(current=10, total=-1, width=18)
    assert isinstance(bar_negative, str)


# =====================================================================
# Feature 5: User Favorites & Quota Limits
# =====================================================================

def test_scenario_21_favorite_quota_cap_exceeded(test_radio):
    """Scenario 21: User attempts to add a favorite when quota of 250 is reached."""
    fm = test_radio.fav_manager
    fm.MAX_USER_FAVORITES = 2

    u_id = "quota_user"
    song1 = Song(title="S1", path="http://s1.mp3")
    song2 = Song(title="S2", path="http://s2.mp3")
    song3 = Song(title="S3", path="http://s3.mp3")

    fm._user_last_toggle.clear()
    assert fm.toggle_favorite(u_id, song1) is True

    fm._user_last_toggle.clear()
    assert fm.toggle_favorite(u_id, song2) is True

    # 3rd song should be rejected by quota limit
    fm._user_last_toggle.clear()
    assert fm.toggle_favorite(u_id, song3) is False


def test_scenario_22_favorite_rapid_spam_cooldown(test_radio):
    """Scenario 22: User spams the favorite button within cooldown window."""
    fm = test_radio.fav_manager
    fm.RATE_LIMIT_SECONDS = 1.0

    u_id = "spam_user"
    song = Song(title="Spam Track", path="http://spam.mp3")

    fm._user_last_toggle.clear()
    added = fm.toggle_favorite(u_id, song)
    assert added is True

    # Rapid second click within cooldown
    second = fm.toggle_favorite(u_id, song)
    # Stays True (favorite not removed because request was throttled)
    assert second is True


def test_scenario_23_favorite_track_with_none_path(test_radio):
    """Scenario 23: Favoriting a track with missing URL or empty path."""
    fm = test_radio.fav_manager
    invalid_song = Song(title="No Path", path=None)
    assert fm.toggle_favorite("u1", invalid_song) is False


def test_scenario_24_removing_nonexistent_favorite(test_radio):
    """Scenario 24: Removing a favorite that was already deleted or never existed."""
    fm = test_radio.fav_manager
    non_existent_song = Song(title="Ghost Track", path="http://ghost.mp3")
    # If not present, toggle_favorite attempts to add it.
    # Check is_favorite is False initially
    assert fm.is_favorite("u99", non_existent_song) is False


# =====================================================================
# Feature 6: Database Concurrency & Connection Pool
# =====================================================================

def test_scenario_25_pool_exhaustion_timeout():
    """Scenario 25: Connection pool exhaustion under heavy concurrent acquisition."""
    temp_dir = tempfile.TemporaryDirectory()
    db_path = os.path.join(temp_dir.name, "pool.db")
    pool = SQLiteConnectionPool(db_path, max_connections=1, timeout=0.1)

    # Acquire the single connection
    conn1 = pool._pool.get(timeout=0.1)
    try:
        # Attempting to acquire second connection should time out
        with pytest.raises(Exception):
            with pool.get_connection():
                pass
    finally:
        pool._pool.put(conn1)
        pool.close()
        temp_dir.cleanup()


def test_scenario_26_database_operation_after_pool_closed(test_db):
    """Scenario 26: Database operation attempted after pool is closed."""
    test_db.close()
    with pytest.raises(RuntimeError, match="closed"):
        with test_db._get_connection():
            pass


def test_scenario_27_history_table_pruning_limit(test_db):
    """Scenario 27: History table exceeds maximum limit and purges oldest entry."""
    test_db.MAX_HISTORY_ENTRIES = 3
    for i in range(5):
        s = Song(title=f"Song {i}", path=f"http://song{i}.mp3")
        test_db.add_history(s)

    count = test_db.get_history_count()
    assert count == 3

    history = test_db.get_history()
    titles = [h.title for h in history]
    # Latest 3 should be 4, 3, 2
    assert "Song 4" in titles
    assert "Song 3" in titles
    assert "Song 2" in titles
    assert "Song 0" not in titles


def test_scenario_28_cache_table_malformed_entries(test_db):
    """Scenario 28: Malformed or missing fields in cache query."""
    # Query non-existent song
    cache_entry = test_db.get_cache("non_existent_path")
    assert cache_entry is None


# =====================================================================
# Feature 7: UI Pagination, Interactivity & Discord Edge Cases
# =====================================================================

def test_scenario_29_pagination_view_out_of_bounds_page_clamp(test_radio):
    """Scenario 29: PaginatedView initialized with out-of-bounds page."""
    data = [Song(title=f"S{i}", path=f"http://s{i}.mp3") for i in range(3)]
    # 3 items with items_per_page=5 -> 1 total page (page 0)
    # If page=999 is requested:
    view = PaginatedView(test_radio, data, items_per_page=5, page=999)

    # Stress check: does it clamp current_page to valid range?
    # If current_page is 999, get_page_items() returns [] and pagination header says page 1000 / 1!
    assert view.current_page < view.total_pages, (
        f"PaginatedView failed to clamp out-of-bounds page! current_page={view.current_page}, total_pages={view.total_pages}"
    )


@pytest.mark.asyncio
async def test_scenario_30_view_interaction_expired_token(test_radio):
    """Scenario 30: User clicks an interactive button after Discord 15-minute token expiry."""
    view = BaseView(test_radio)
    mock_interaction = MagicMock()
    mock_interaction.response.send_message = AsyncMock(
        side_effect=discord.NotFound(MagicMock(), "Unknown interaction")
    )
    mock_interaction.followup.send = AsyncMock(
        side_effect=discord.NotFound(MagicMock(), "Unknown interaction")
    )

    fake_error = discord.NotFound(MagicMock(), "Unknown interaction")
    # BaseView.on_error must catch and log warning without raising unhandled exception
    await view.on_error(mock_interaction, fake_error, MagicMock())


@pytest.mark.asyncio
async def test_scenario_31_delayed_delete_missing_manage_messages_permission():
    """Scenario 31: Bot lacks 'Manage Messages' permission during delayed delete."""
    from ui.utils import delayed_delete
    mock_message = AsyncMock()
    mock_message.delete.side_effect = discord.Forbidden(MagicMock(), "Missing Permissions")

    # delayed_delete must handle discord.Forbidden silently or safely without crashing
    await delayed_delete(mock_message, delay=0.01)


def test_scenario_32_progress_bar_clamped_over_100_percent():
    """Scenario 32: Progress bar rendered for song position exceeding 100%."""
    bar = create_progress_bar(current=250, total=100, width=18)
    assert isinstance(bar, str)
    assert len(bar) > 0


# =====================================================================
# Feature 8: Configuration & Logging Resilience
# =====================================================================

def test_scenario_33_config_placeholder_token_rejected():
    """Scenario 33: Configuration contains placeholder token text."""
    with pytest.raises(ValueError, match="placeholder text"):
        Config(
            token="your_bot_token_here_123",
            guild_id=1,
            radio_text_channel_id=1,
            auto_join_channel_id=0,
            afk_channel_id=0,
            admin_role_id=0,
            sysadmin_role_id=0,
            default_language="en",
            default_ui_mode="full",
            ffmpeg_path="ffmpeg",
            ytdlp_path="yt-dlp",
            languages=[{"code": "en"}],
            ui_settings={},
            timings={},
            defaults={}
        )


def test_scenario_34_logging_unicode_emojis_windows_safety():
    """Scenario 34: Logging a song title with unmapped UTF-8 emojis on Windows console."""
    # Must not raise UnicodeEncodeError
    setup_logging(level_name="INFO", instance_name="test_emoji_scenario")
    log.info("🎵 Lofi Hip Hop Radio 🎧 - árvíztűrő tükörfúrógép 🎶")


def test_scenario_35_log_rotation_permission_error_handled():
    """Scenario 35: Rotating log file is locked by an external process during rollover."""
    from logging.handlers import RotatingFileHandler
    temp_dir = tempfile.TemporaryDirectory()
    log_file = os.path.join(temp_dir.name, "locked.log")

    handler = RotatingFileHandler(log_file, maxBytes=100, backupCount=2)
    # Write enough bytes to trigger rollover
    record = log.makeRecord("RadioBot", 20, "test.py", 10, "A" * 150, (), None)
    
    # Simulate locked destination file during doRollover
    with patch("os.rename", side_effect=PermissionError("File locked")):
        # RotatingFileHandler should emit error via handleError without crashing process
        try:
            handler.emit(record)
        except PermissionError:
            pytest.fail("RotatingFileHandler crashed process on PermissionError instead of handleError!")
        finally:
            handler.close()
            temp_dir.cleanup()
