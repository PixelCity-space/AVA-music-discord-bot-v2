"""
Phase 2 Stress Test Suite: 32 Brand New Scenarios.
Targeting CacheService, Song Model, Permissions, Queue Manipulation, i18n, Seeking/Audio, Theme, and Icons.
"""

import asyncio
import os
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from core.actions import RadioAction, RadioState
from core.database import Database
from core.models import Song
from core.state import RadioManager
from providers.ytdlp_provider import YTDLPProvider
from services.cache_service import CacheService
from services.command_service import CommandService
from services.permissions import PermissionService
from services.player import AudioSourceFactory
from tests.conftest import MockMember, MockVoiceChannel
from ui.i18n import t, init_translate
from ui.icons import Icons
from ui.theme import Theme
from ui.utils import truncate, delayed_delete


# =====================================================================
# Feature 1: Local Cache Lifecycle & Disk Eviction
# =====================================================================

def test_scenario_01_cache_lru_size_eviction(test_db):
    """Scenario 1: Cache size limit exceeded triggers LRU file eviction."""
    temp_dir = tempfile.TemporaryDirectory()
    mock_config = MagicMock()
    mock_config.max_cache_size_mb = 1  # 1 MB limit
    mock_config.cache_expiry_days = 30

    cs = CacheService(mock_config, test_db)
    cs.cache_dir = temp_dir.name

    # Create 3 files of 600 KB each (total 1.8 MB > 1 MB)
    p1 = os.path.join(temp_dir.name, "old_track.mp3")
    p2 = os.path.join(temp_dir.name, "mid_track.mp3")
    p3 = os.path.join(temp_dir.name, "new_track.mp3")

    with open(p1, "wb") as f: f.write(b"0" * 600 * 1024)
    with open(p2, "wb") as f: f.write(b"0" * 600 * 1024)
    with open(p3, "wb") as f: f.write(b"0" * 600 * 1024)

    # Set access times: p1 oldest, p3 newest
    now = time.time()
    os.utime(p1, (now - 300, now - 300))
    os.utime(p2, (now - 200, now - 200))
    os.utime(p3, (now - 100, now - 100))

    cs.cleanup_cache()

    remaining = os.listdir(temp_dir.name)
    # Oldest file must have been evicted to satisfy 1 MB quota
    assert "old_track.mp3" not in remaining
    assert "new_track.mp3" in remaining
    temp_dir.cleanup()


def test_scenario_02_cache_expiry_purge(test_db):
    """Scenario 2: Expired audio files purged based on cache_expiry_days."""
    temp_dir = tempfile.TemporaryDirectory()
    mock_config = MagicMock()
    mock_config.max_cache_size_mb = 100
    mock_config.cache_expiry_days = 10  # 10 days expiry

    cs = CacheService(mock_config, test_db)
    cs.cache_dir = temp_dir.name

    p_expired = os.path.join(temp_dir.name, "expired.mp3")
    p_fresh = os.path.join(temp_dir.name, "fresh.mp3")

    with open(p_expired, "wb") as f: f.write(b"data")
    with open(p_fresh, "wb") as f: f.write(b"data")

    now = time.time()
    # 15 days ago (> 10 days limit)
    os.utime(p_expired, (now - 15 * 86400, now - 15 * 86400))
    # 2 days ago (< 10 days limit)
    os.utime(p_fresh, (now - 2 * 86400, now - 2 * 86400))

    cs.cleanup_cache()

    remaining = os.listdir(temp_dir.name)
    assert "expired.mp3" not in remaining
    assert "fresh.mp3" in remaining
    temp_dir.cleanup()


def test_scenario_03_cache_cleanup_locked_file_handled(test_db):
    """Scenario 3: Deleting a cached file currently locked on Windows."""
    temp_dir = tempfile.TemporaryDirectory()
    mock_config = MagicMock()
    mock_config.max_cache_size_mb = 0.001  # Trigger size cleanup
    mock_config.cache_expiry_days = 30

    cs = CacheService(mock_config, test_db)
    cs.cache_dir = temp_dir.name

    p = os.path.join(temp_dir.name, "locked.mp3")
    with open(p, "wb") as f: f.write(b"0" * 5000)

    with patch("os.remove", side_effect=PermissionError("File locked by process")):
        # Must catch PermissionError and continue without raising
        try:
            cs.cleanup_cache()
        except PermissionError:
            pytest.fail("CacheService.cleanup_cache crashed on PermissionError instead of catching gracefully!")

    temp_dir.cleanup()


def test_scenario_04_ephemeral_cache_clear_on_startup(test_db):
    """Scenario 4: Startup cleanup when ephemeral cache is enabled."""
    temp_dir = tempfile.TemporaryDirectory()
    mock_config = MagicMock()
    cs = CacheService(mock_config, test_db)
    cs.cache_dir = temp_dir.name

    p = os.path.join(temp_dir.name, "song.mp3")
    with open(p, "wb") as f: f.write(b"audio")

    test_db.set_cache("http://song.mp3", "Song", "Artist", 120, "", local_path=p)

    deleted_count = cs.clear_cache()
    assert deleted_count == 1
    assert not os.path.exists(p)

    # Verify db reset
    cached = test_db.get_cache("http://song.mp3")
    assert cached["local_path"] is None
    temp_dir.cleanup()


@pytest.mark.asyncio
async def test_scenario_05_concurrent_cache_download_lock(test_db):
    """Scenario 5: Concurrent duplicate track download attempt (Cache stampede)."""
    temp_dir = tempfile.TemporaryDirectory()
    mock_config = MagicMock()
    cs = CacheService(mock_config, test_db)
    cs.cache_dir = temp_dir.name
    song = Song(title="Stampede Track", path="http://stampede.mp3")

    executed_count = 0
    real_file = os.path.join(temp_dir.name, "downloaded.mp3")

    async def fake_ytdlp(*args, **kwargs):
        nonlocal executed_count
        executed_count += 1
        await asyncio.sleep(0.05)
        with open(real_file, "wb") as f: f.write(b"audio")
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=fake_ytdlp):
        with patch.object(cs, "get_cache_path", return_value=real_file):
            # Launch two parallel downloads for the exact same song
            task1 = asyncio.create_task(cs._download_task(song))
            task2 = asyncio.create_task(cs._download_task(song))
            await asyncio.gather(task1, task2)

    # Thanks to download_lock and is_cached check inside lock, second download is skipped
    assert executed_count == 1
    temp_dir.cleanup()


# =====================================================================
# Feature 2: Data Model Integrity & Serialization
# =====================================================================

def test_scenario_06_song_from_dict_with_none_duration():
    """Scenario 6: Instantiating Song from dictionary with duration as explicit None."""
    payload = {
        "title": "Valid Title",
        "path": "https://youtube.com/watch?v=xyz",
        "duration": None  # Some providers return None for livestreams or unprobed files
    }
    # Stress test: int(data.get("duration", 0)) will raise TypeError: int() argument must be... not 'NoneType'
    try:
        song = Song.from_dict(payload)
        assert song.duration == 0
    except TypeError as e:
        pytest.fail(f"Song.from_dict crashed with TypeError on duration=None: {e}")


def test_scenario_07_song_from_dict_negative_duration():
    """Scenario 7: Instantiating Song with negative duration integer."""
    payload = {
        "title": "Negative Duration Track",
        "path": "http://neg.mp3",
        "duration": -120
    }
    song = Song.from_dict(payload)
    # Check whether negative duration is accepted or clamped
    assert song.duration >= 0, f"Song duration allowed negative value: {song.duration}"


def test_scenario_08_song_update_preserves_valid_metadata_against_none():
    """Scenario 8: Metadata update payload attempting to overwrite valid fields with None."""
    song = Song(title="Known Song", uploader="Original Artist", path="http://valid.mp3", duration=180)
    # Incoming payload with None values
    song.update({"title": None, "uploader": None, "duration": None})

    assert song.title == "Known Song"
    assert song.uploader == "Original Artist"
    assert song.duration == 180


@pytest.mark.asyncio
async def test_scenario_09_multiple_waiters_on_song_resolve_event():
    """Scenario 9: Multiple concurrent coroutines awaiting a single song resolve_event."""
    song = Song(title="Resolving Track", path="http://resolving.mp3", is_resolving=True)
    unblocked = []

    async def waiter(idx):
        await song.resolve_event.wait()
        unblocked.append(idx)

    tasks = [asyncio.create_task(waiter(i)) for i in range(3)]
    await asyncio.sleep(0.01)
    assert len(unblocked) == 0

    # Resolve finishes
    song.is_resolving = False
    song.resolve_event.set()

    await asyncio.gather(*tasks)
    assert unblocked == [0, 1, 2]


def test_scenario_10_song_cache_to_db_with_blank_or_whitespace_path(test_db):
    """Scenario 10: Song caching to database with whitespace-only or empty path."""
    blank_song = Song(title="Blank", path="   ")
    blank_song.cache_to_db(test_db)

    # Stress test: ensure whitespace path was not stored in database as a valid URL
    entry = test_db.get_cache("   ")
    assert entry is None, "Database permitted caching a blank/whitespace-only track path!"


# =====================================================================
# Feature 3: Permission Matrix & Role Hierarchy
# =====================================================================

def test_scenario_11_non_admin_cannot_clear_cache(test_radio):
    """Scenario 11: Non-admin user attempts admin-only clear cache command."""
    user = MockMember(id=2001, is_admin=False)
    res = test_radio.command_service.clear_cache(user)
    assert res.success is False
    assert "admin_only" in res.feedback or "❌" in res.feedback


def test_scenario_12_non_admin_cannot_restart_bot(test_radio):
    """Scenario 12: Non-admin user attempts admin-only restart command."""
    user = MockMember(id=2002, is_admin=False)
    res = test_radio.command_service.restart(user)
    assert res.success is False
    assert os.getenv("BOT_RESTART") != "1"


def test_scenario_13_server_owner_not_in_voice_rejected(test_radio):
    """Scenario 13: Server owner not in voice channel tries to control playback."""
    owner = MockMember(id=test_radio.config.guild_id, is_admin=True, voice_channel=None)
    owner.guild.owner_id = owner.id

    res = test_radio.command_service.play(owner, "some query")
    assert res.success is False


def test_scenario_14_listener_in_different_voice_channel_rejected(test_radio):
    """Scenario 14: Listener in a different voice channel attempts to modify volume."""
    vc1 = MockVoiceChannel(id=111, name="Room A")
    vc2 = MockVoiceChannel(id=222, name="Room B")

    test_radio.status = RadioState.PLAYING
    test_radio.voice = type("MockVoice", (), {"channel": vc1})()

    user_in_vc2 = MockMember(id=3001, voice_channel=vc2, is_admin=False)
    res = test_radio.command_service.volume(user_in_vc2, 80)
    assert res.success is False


def test_scenario_15_command_in_direct_message_context_safe(test_radio):
    """Scenario 15: Command invoked in Direct Message (DM) context by raw discord.User."""
    dm_user = type("PlainUser", (), {"name": "dm_user", "id": 4001})()
    res = test_radio.command_service.play(dm_user, "song query")
    assert res.success is False


# =====================================================================
# Feature 4: Queue Navigation & List Reordering
# =====================================================================

def test_scenario_16_move_song_index_zero_up(test_radio):
    """Scenario 16: Move the first song up beyond index 0."""
    s1 = Song(title="S1", path="http://s1.mp3")
    s2 = Song(title="S2", path="http://s2.mp3")
    test_radio.queue = [s1, s2]

    # Move first song UP (-1)
    test_radio.dispatch(RadioAction.MOVE_SONG, (s1, -1))
    assert test_radio.queue == [s1, s2]


def test_scenario_17_move_song_last_index_down(test_radio):
    """Scenario 17: Move the last song down beyond queue length."""
    s1 = Song(title="S1", path="http://s1.mp3")
    s2 = Song(title="S2", path="http://s2.mp3")
    test_radio.queue = [s1, s2]

    # Move second song DOWN (+1)
    test_radio.dispatch(RadioAction.MOVE_SONG, (s2, 1))
    assert test_radio.queue == [s1, s2]


def test_scenario_18_move_phantom_song_not_in_queue(test_radio):
    """Scenario 18: Attempting to move a song that does not exist in the queue."""
    s1 = Song(title="S1", path="http://s1.mp3")
    phantom = Song(title="Phantom", path="http://phantom.mp3")
    test_radio.queue = [s1]

    # Must not raise ValueError
    test_radio.dispatch(RadioAction.MOVE_SONG, (phantom, -1))
    assert test_radio.queue == [s1]


def test_scenario_19_remove_already_deleted_song(test_radio):
    """Scenario 19: Removing a song that is already deleted from the queue."""
    s1 = Song(title="S1", path="http://s1.mp3")
    test_radio.queue = [s1]

    # Remove once
    test_radio.dispatch(RadioAction.REMOVE_FROM_QUEUE, s1)
    assert len(test_radio.queue) == 0

    # Remove again (already deleted) - must not raise ValueError
    test_radio.dispatch(RadioAction.REMOVE_FROM_QUEUE, s1)
    assert len(test_radio.queue) == 0


def test_scenario_20_loop_mode_clears_loop_queue(test_radio):
    """Scenario 20: Activating single song loop immediately disables queue loop."""
    test_radio.loop_queue_mode = True
    test_radio.loop_mode = False

    test_radio.dispatch(RadioAction.LOOP)
    assert test_radio.loop_mode is True
    assert test_radio.loop_queue_mode is False


# =====================================================================
# Feature 5: Internationalization (i18n) & String Formatting
# =====================================================================

def test_scenario_21_translation_missing_key_fallback(test_radio):
    """Scenario 21: Translation requested for non-existent key returns key string without crashing."""
    init_translate(test_radio)
    result = t("non_existent_key_xyz_123")
    assert result == "non_existent_key_xyz_123"


def test_scenario_22_translation_template_missing_kwargs(test_radio):
    """Scenario 22: Translation template contains placeholders but kwargs are omitted."""
    init_translate(test_radio)
    # vol_set template contains {percent}%
    result = t("vol_set")
    assert "{percent}" in result or "Hangerő" in result or "Volume" in result


def test_scenario_23_unregistered_locale_code_fallback(test_radio):
    """Scenario 23: Radio language switched dynamically to an unregistered locale code."""
    test_radio.language = "unregistered_lang_code"
    init_translate(test_radio)
    # Should fall back to "en" or raw key without crash
    result = t("now_playing", radio=test_radio)
    assert result is not None
    assert len(result) > 0


def test_scenario_24_translation_uppercase_icon_replacement(test_radio):
    """Scenario 24: Translation string contains uppercase icon tokens."""
    init_translate(test_radio)
    rendered = t("resuming")
    # {PLAY} token inside resuming must be replaced by actual icon value
    assert "{PLAY}" not in rendered


# =====================================================================
# Feature 6: Audio Stream Resolution & Seek Bounds
# =====================================================================

def test_scenario_25_seek_negative_offset_validation(test_radio):
    """Scenario 25: User attempts to seek to a negative timestamp."""
    test_radio.status = RadioState.PLAYING
    test_radio.current_song = Song(title="Song", path="http://s.mp3", duration=180)
    user = MockMember(id=999, is_admin=True)

    res = test_radio.command_service.seek(user, "-30")
    # Stress test: seek should reject negative offsets or clamp to 0, not send negative -ss
    assert res.success is False, "CommandService.seek accepted negative timestamp -30!"


def test_scenario_26_seek_beyond_track_duration(test_radio):
    """Scenario 26: User attempts to seek beyond the total track duration."""
    test_radio.status = RadioState.PLAYING
    test_radio.current_song = Song(title="Short Track", path="http://short.mp3", duration=120)
    user = MockMember(id=999, is_admin=True)

    res = test_radio.command_service.seek(user, "300")
    # Stress test: seeking 300s on 120s song should be rejected or clamped
    assert res.success is False, "CommandService.seek allowed seeking to 300s on a 120s song!"


def test_scenario_27_ffmpeg_reconnect_options_only_for_urls(test_radio):
    """Scenario 27: FFmpeg reconnect options generated for HTTP stream vs local file."""
    factory = AudioSourceFactory(test_radio.config, test_radio)

    with patch("discord.FFmpegOpusAudio") as mock_audio:
        # Local file
        factory.create_ffmpeg_source("data/cache/track.mp3")
        _, kwargs_local = mock_audio.call_args
        assert "-reconnect 1" not in kwargs_local.get("before_options", "")

        # HTTP URL
        factory.create_ffmpeg_source("https://audio.stream/live.mp3")
        _, kwargs_http = mock_audio.call_args
        assert "-reconnect 1" in kwargs_http.get("before_options", "")


@pytest.mark.asyncio
async def test_scenario_28_ytdlp_malformed_json_handled():
    """Scenario 28: yt-dlp probe returns corrupted or unparseable JSON on stdout."""
    provider = YTDLPProvider()

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        proc = AsyncMock()
        proc.communicate.return_value = (b"MALFORMED_NON_JSON_TEXT", b"")
        proc.returncode = 0
        mock_exec.return_value = proc

        result = await provider.resolve("https://youtube.com/watch?v=corrupted")
        assert result is None


# =====================================================================
# Feature 7: UI Interaction, Theming & Icon Fallbacks
# =====================================================================

def test_scenario_29_theme_init_invalid_hex_string():
    """Scenario 29: Theme color initialized with invalid hex string."""
    mock_config = MagicMock()
    mock_config.ui_settings = {
        "theme": {
            "primary": "not_a_valid_hex"
        }
    }
    # Stress test: int("not_a_valid_hex", 16) raises ValueError
    try:
        Theme.init_theme(mock_config)
        assert isinstance(Theme.PRIMARY, int)
    except ValueError as e:
        pytest.fail(f"Theme.init_theme crashed with ValueError on invalid hex: {e}")


def test_scenario_30_icons_setup_empty_emojis_dict():
    """Scenario 30: Config emojis dictionary is completely empty."""
    mock_config = MagicMock()
    mock_config.emojis = {}

    Icons.setup(mock_config)
    # Check that default emojis are retained and not None
    assert Icons.PLAY is not None
    assert Icons.PAUSE is not None
    assert Icons.STOP is not None


def test_scenario_31_truncate_negative_or_small_length():
    """Scenario 31: Title truncation called with max_len <= 3."""
    title = "Hello World"
    res = truncate(title, max_len=2)
    # Stress test: truncate(title, max_len=2) should NOT produce longer text than max_len
    assert len(res) <= 2, f"truncate('Hello World', max_len=2) returned '{res}' with length {len(res)} > 2!"


@pytest.mark.asyncio
async def test_scenario_32_delayed_delete_already_deleted_message():
    """Scenario 32: Delayed delete invoked on a message already deleted by a user."""
    mock_message = AsyncMock()
    mock_message.delete.side_effect = discord.NotFound(MagicMock(), "Unknown Message")

    # Must catch discord.NotFound cleanly
    try:
        await delayed_delete(mock_message, delay=0.01)
    except discord.NotFound:
        pytest.fail("delayed_delete failed to handle discord.NotFound cleanly!")
