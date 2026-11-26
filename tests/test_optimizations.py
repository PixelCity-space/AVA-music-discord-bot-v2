import asyncio
import hashlib
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.events import EventsCog
from core.actions import RadioAction, RadioState
from core.embed_state import EmbedStateManager
from core.models import Song
from core.queue_manager import QueueManager
from providers.ytdlp_provider import YTDLPProvider
from services.audio_player import RadioPlayer
from services.cache_service import CacheService
from ui.manager import UIManager
from ui.views.favorites import FavoritesView
from ui.views.history import HistoryView


def test_embed_state_skips_redundant_writes_and_supports_none(tmp_path):
    state_file = tmp_path / "embed_state.json"
    mgr = EmbedStateManager(str(state_file))

    with patch.object(mgr, "save", wraps=mgr.save) as save_spy:
        mgr.save_message_id("player", 123456)
        assert save_spy.call_count == 1

        # Saving identical ID should not write to disk again
        mgr.save_message_id("player", 123456)
        assert save_spy.call_count == 1

        # Saving None clears the stored ID
        mgr.save_message_id("player", None)
        assert mgr.load_message_id("player") is None
        assert save_spy.call_count == 2

        # Clearing an already-absent ID does not write
        mgr.save_message_id("player", None)
        assert save_spy.call_count == 2


def test_database_in_memory_history_and_favorite_caches(test_db):
    song = Song(title="Cached Track", path="http://cached.mp3", duration=120)

    assert test_db.has_history() is False
    with patch.object(test_db, "_get_connection", wraps=test_db._get_connection) as conn_spy:
        # Second call served from cache with 0 DB connections
        assert test_db.has_history() is False
        assert conn_spy.call_count == 0

    test_db.add_history(song)
    with patch.object(test_db, "_get_connection", wraps=test_db._get_connection) as conn_spy:
        assert test_db.has_history() is True
        assert conn_spy.call_count == 0

    test_db.clear_history()
    assert test_db.has_history() is False

    # Favorites cache
    test_db.add_favorite("u1", song)
    assert test_db.is_favorite("u1", song.path) is True
    with patch.object(test_db, "_get_connection", wraps=test_db._get_connection) as conn_spy:
        assert test_db.is_favorite("u1", song.path) is True
        assert conn_spy.call_count == 0

    test_db.remove_favorite("u1", song.path)
    assert test_db.is_favorite("u1", song.path) is False

    # Song metadata in-memory cache
    test_db.set_cache("http://memcache.mp3", "Mem", "Art", 100, "", local_path="data/cache/m.mp3")
    with patch.object(test_db, "_get_connection", wraps=test_db._get_connection) as conn_spy:
        cached = test_db.get_cache("http://memcache.mp3")
        assert cached is not None
        assert cached["local_path"] == "data/cache/m.mp3"
        assert conn_spy.call_count == 0
    test_db.clear_cache()
    assert test_db.get_cache("http://memcache.mp3")["local_path"] is None


@pytest.mark.asyncio
async def test_ytdlp_in_process_resolve_and_timeout():
    provider = YTDLPProvider()

    mock_info = {
        "title": "Test Video",
        "uploader": "Test Channel",
        "duration": 95,
        "url": "https://cdn.example.com/audio.webm",
        "thumbnail": "https://img.example.com/1.jpg",
        "webpage_url": "https://youtube.com/watch?v=123",
    }
    with patch.object(provider, "_extract_info_sync", return_value=mock_info):
        res = await provider.resolve("https://youtube.com/watch?v=123")
        assert res is not None
        assert res["title"] == "Test Video"
        assert res["stream_url"] == "https://cdn.example.com/audio.webm"

    with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
        res_timeout = await provider.resolve("https://youtube.com/watch?v=slow")
        assert res_timeout is None
    provider.close()


@pytest.mark.asyncio
async def test_cache_service_fast_lookup_and_parallel_different_urls(tmp_path, test_db):
    mock_config = MagicMock()
    mock_config.ytdlp_path = "yt-dlp"
    mock_config.cache_expiry_days = 30
    mock_config.max_cache_size_mb = 100

    cs = CacheService(mock_config, test_db)
    cs.cache_dir = str(tmp_path)

    s1 = Song(title="Song 1", path="http://example.com/1")
    s2 = Song(title="Song 2", path="http://example.com/2")
    h1 = hashlib.sha1(s1.path.encode()).hexdigest()
    p1 = os.path.join(cs.cache_dir, f"{h1}.opus")
    with open(p1, "wb") as f:
        f.write(b"opus")

    # Finds .opus directly without globbing
    with patch("glob.glob") as glob_mock:
        assert cs.get_cache_path(s1) == p1
        glob_mock.assert_not_called()

    # Different songs can download concurrently up to semaphore limit
    active = 0
    max_active = 0

    async def fake_exec(*args, **kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        active -= 1
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate.return_value = (b"", b"")
        return proc

    s3 = Song(title="Song 3", path="http://example.com/3")
    with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
        await asyncio.gather(cs._download_task(s2), cs._download_task(s3))
    assert max_active == 2

    await cs.cleanup_cache_async()


@pytest.mark.asyncio
async def test_ui_manager_skips_unchanged_station_edit_and_coalesces(test_radio):
    bot = MagicMock()
    bot.is_closed.return_value = False
    bot.user = MagicMock(id=999)
    bot.change_presence = AsyncMock()

    channel = MagicMock()
    station_msg = AsyncMock()
    station_msg.id = 111
    station_msg.author = bot.user
    player_msg = AsyncMock()
    player_msg.id = 222
    player_msg.author = bot.user

    channel.send = AsyncMock(side_effect=[station_msg, player_msg])

    async def empty_history(**kwargs):
        if False:
            yield None

    channel.history = empty_history
    bot.get_channel.return_value = channel
    bot.get_guild.return_value = None

    ui = UIManager(bot, test_radio.config, test_radio)
    test_radio.voice_channel_id = 333
    test_radio.status = RadioState.PLAYING
    song = Song(title="Track", path="http://track.mp3", duration=100)

    # First render sends station and player messages
    await ui.update_now_playing(song)
    assert station_msg.edit.call_count == 0
    assert player_msg.edit.call_count == 0

    # Identical state re-notification skips BOTH station and player edits
    await ui.update_now_playing(song)
    assert station_msg.edit.call_count == 0
    assert player_msg.edit.call_count == 0

    # Progress tick (elapsed changed): station_msg.edit skipped, only player_msg edited
    test_radio.track_start_offset = 15.0
    await ui.update_now_playing(song)
    assert station_msg.edit.call_count == 0
    assert player_msg.edit.call_count == 1

    # Burst coalescing: multiple concurrent calls while locked merge into one follow-up render
    render_calls = 0

    async def slow_internal(*args, **kwargs):
        nonlocal render_calls
        render_calls += 1
        await asyncio.sleep(0.03)

    with patch.object(ui, "_update_ui_internal", side_effect=slow_internal):
        await asyncio.gather(
            ui.update_now_playing(song),
            ui.update_now_playing(song),
            ui.update_now_playing(song),
            ui.update_now_playing(song),
        )
    assert render_calls == 2


@pytest.mark.asyncio
async def test_player_preserves_fresh_stream_url_and_skips_ephemeral_download(test_radio):
    test_radio.config.defaults["ephemeral_cache"] = True
    player = RadioPlayer(
        bot=MagicMock(),
        config=test_radio.config,
        radio=test_radio,
        update_ui_callback=AsyncMock(),
        refresh_ui_callback=AsyncMock(),
    )
    song = Song(
        title="Streamed",
        path="https://youtube.com/watch?v=abc",
        is_external=True,
        stream_url="https://cdn.example.com/fresh",
        stream_resolved_at=time.monotonic(),
    )
    test_radio.current_song = song
    test_radio.is_seeking = True
    test_radio.seek_position = 15.0
    test_radio.start_cache_download = AsyncMock()

    mock_voice = MagicMock()
    mock_voice.is_playing.return_value = False
    mock_voice.is_paused.return_value = False

    def immediate_play(source, after=None):
        if after:
            after(None)

    mock_voice.play.side_effect = immediate_play
    player.bot.loop = asyncio.get_running_loop()

    with patch.object(player.source_factory, "resolve_source", new=AsyncMock(return_value=song.stream_url)):
        with patch.object(player.source_factory, "create_ffmpeg_source", return_value=MagicMock()):
            await player._start_playback(mock_voice)

    # Fresh stream_url was NOT cleared during seek
    assert song.stream_url == "https://cdn.example.com/fresh"
    # Ephemeral cache skips downloading full file while streaming
    test_radio.start_cache_download.assert_not_awaited()


@pytest.mark.asyncio
async def test_playback_monitor_loop_handles_action_without_dropping_on_done(test_radio):
    player = RadioPlayer(
        bot=MagicMock(),
        config=test_radio.config,
        radio=test_radio,
        update_ui_callback=AsyncMock(),
        refresh_ui_callback=AsyncMock(),
    )
    voice = MagicMock()
    song = Song(title="S", path="http://s.mp3", duration=100)
    done = asyncio.Event()

    test_radio.dispatch(RadioAction.PAUSE)
    with patch.object(player.action_handler, "handle_playback_action", new=AsyncMock(return_value=True)) as handle_mock:
        await player._playback_monitor_loop(voice, song, done)
        handle_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_paginated_views_reuse_data_on_pagination(test_radio):
    u_id = "user_pag"
    for i in range(7):
        test_radio.db.add_favorite(u_id, Song(title=f"Fav {i}", path=f"http://fav/{i}"))
        test_radio.db.add_history(Song(title=f"Hist {i}", path=f"http://hist/{i}"))

    fav_view = FavoritesView(test_radio, u_id)
    hist_view = HistoryView(test_radio)

    interaction = AsyncMock()
    with patch.object(test_radio.fav_manager, "get_favorites") as get_fav_spy:
        fav_view.current_page = 1
        await fav_view.paginate_refresh(interaction)
        get_fav_spy.assert_not_called()

    with patch.object(test_radio.history_manager, "get_all") as get_hist_spy:
        hist_view.current_page = 1
        await hist_view.paginate_refresh(interaction)
        get_hist_spy.assert_not_called()


@pytest.mark.asyncio
async def test_events_cog_on_ready_skips_duplicate_reconnect_sync(test_radio):
    bot = MagicMock()
    bot.radio = test_radio
    bot.config = test_radio.config
    bot.config.guild_id = 123
    bot.config.auto_join_channel_id = 0
    bot.instance_name = ""
    bot.user = MagicMock(id=1)
    bot.ui_manager = MagicMock()
    bot.ui_manager.context = MagicMock()
    bot.ui_manager.force_new_embed = AsyncMock()
    bot.tree = MagicMock()
    bot.tree.sync = AsyncMock()

    cog = EventsCog(bot)
    await cog.on_ready()
    await cog.on_ready()

    assert bot.ui_manager.force_new_embed.await_count == 1
    assert bot.tree.sync.await_count == 1


@pytest.mark.asyncio
async def test_idle_player_wakes_immediately_when_songs_added(test_radio):
    test_radio.config.timings["action_timeout"] = 5.0
    test_radio.voice_channel_id = 123
    test_radio.status = RadioState.IDLE
    player = RadioPlayer(
        bot=MagicMock(),
        config=test_radio.config,
        radio=test_radio,
        update_ui_callback=AsyncMock(),
        refresh_ui_callback=AsyncMock(),
    )
    voice = MagicMock()

    async def add_soon():
        await asyncio.sleep(0.02)
        await test_radio._add_songs([Song(title="Wake Song", path="http://wake.mp3")])

    start = time.monotonic()
    _, should_continue = await asyncio.gather(
        add_soon(),
        player._handle_idle_state(voice),
    )
    elapsed = time.monotonic() - start
    assert should_continue is False
    assert elapsed < 0.5


@pytest.mark.asyncio
async def test_track_resolver_single_shot_search_and_background_notify(test_radio):
    provider = test_radio.providers[0]
    with patch.object(
        provider,
        "search_and_resolve_first",
        new=AsyncMock(return_value={
            "title": "Single Shot",
            "uploader": "Artist",
            "duration": 180,
            "path": "https://youtube.com/watch?v=single1",
            "stream_url": "https://cdn.example.com/single1.webm",
            "is_external": True,
        }),
    ) as ss_mock:
        song = await test_radio.resolver.prepare_external_song("lofi beats")
        ss_mock.assert_awaited_once_with("lofi beats")
        assert song is not None
        assert song.stream_url == "https://cdn.example.com/single1.webm"
        assert song.is_resolving is False

    # _resolve_link_task skips UI notification for non-current queue items
    test_radio.current_song = Song(title="Current", path="http://cur.mp3")
    queued_song = Song(title="Queued", path="http://queued.mp3", is_resolving=True)
    test_radio._notify_state_change = MagicMock()
    with patch.object(test_radio.resolver, "resolve_song", new=AsyncMock(return_value=True)):
        await test_radio._resolve_link_task(queued_song)
        test_radio._notify_state_change.assert_not_called()

        await test_radio._resolve_link_task(test_radio.current_song)
        test_radio._notify_state_change.assert_called_once()


def test_queue_manager_isolated_transitions_and_navigation(test_db):
    from services.history import HistoryManager

    qm = QueueManager()
    hm = HistoryManager(test_db)
    s1 = Song(title="S1", path="http://s1")
    s2 = Song(title="S2", path="http://s2")
    s3 = Song(title="S3", path="http://s3")

    qm.enqueue_many([s1, s2, s3])
    assert qm.peek_next() == s1
    assert qm.move(s1, 1) is True
    assert qm.queue == [s2, s1, s3]

    # Pop s2, then test single loop replay
    cur, replay = qm.select_next(None)
    assert cur == s2 and replay is False
    qm.toggle_loop()
    assert qm.loop_mode is True and qm.loop_queue_mode is False
    cur_loop, replay = qm.select_next(cur)
    assert cur_loop == s2 and replay is True

    # Disable loop, enable loop_queue: appends current to end when queue has items
    qm.toggle_loop_queue()
    assert qm.loop_mode is False and qm.loop_queue_mode is True
    cur2, replay = qm.select_next(s2)
    assert cur2 == s1 and replay is False
    assert qm.queue[-1] == s2

    # History back + forward navigation
    hm.add(s2)
    back_song = qm.step_back(hm, cur2, during_playback=True)
    assert back_song.path == s2.path
    assert qm.future_queue[0] == s1
    assert qm.is_navigating is True
    fwd, replay = qm.select_next(back_song)
    assert fwd == s1 and replay is False
    assert qm.is_navigating is True


def test_database_facade_exposes_repositories(test_db):
    s = Song(title="Repo", path="http://repo.mp3", duration=50)
    test_db.cache_repo.set("http://repo.mp3", "Repo", "Art", 50, "")
    assert test_db.get_cache("http://repo.mp3")["title"] == "Repo"

    test_db.history_repo.add(s)
    assert test_db.has_history() is True

    test_db.favorites_repo.add("u_repo", s)
    assert test_db.is_favorite("u_repo", s.path) is True


@pytest.mark.asyncio
async def test_command_service_unified_seek_enqueue_and_modals(test_radio):
    from tests.conftest import MockMember, MockVoiceChannel
    from ui.modals.seek import SeekModal
    from ui.modals.volume import VolumeModal

    vc = MockVoiceChannel(id=42, name="Lounge")
    user = MockMember(id=500, voice_channel=vc, is_admin=False)
    admin = MockMember(id=501, voice_channel=vc, is_admin=True)

    # CommandService.seek rejects invalid mm:ss seconds >= 60 or negative
    test_radio.status = RadioState.PLAYING
    test_radio.current_song = Song(title="Track", path="http://t", duration=200)
    assert test_radio.command_service.seek(user, "01:90").success is False
    assert test_radio.command_service.seek(user, "01:-10").success is False
    assert test_radio.command_service.seek(user, "01:30").success is True

    # SeekModal delegates to CommandService.seek
    test_radio.command_service.seek = MagicMock(return_value=MagicMock(feedback="OK"))
    seek_modal = SeekModal(test_radio)
    seek_modal.timestamp_input = MagicMock(value="01:15")
    interaction = AsyncMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.user = user
    await seek_modal.on_submit(interaction)
    test_radio.command_service.seek.assert_called_once_with(user, "01:15")

    # VolumeModal delegates valid integer to CommandService.volume
    test_radio.command_service.volume = MagicMock(return_value=MagicMock(feedback="Vol OK"))
    vol_modal = VolumeModal(test_radio)
    vol_modal.volume_input = MagicMock(value="65")
    await vol_modal.on_submit(interaction)
    test_radio.command_service.volume.assert_called_once_with(user, 65)

    # enqueue_songs joins voice if needed and enqueues cloned tracks
    test_radio.voice_channel_id = None
    res_no_voice = test_radio.command_service.enqueue_songs(MockMember(id=502, voice_channel=None), [Song(title="A", path="http://a")])
    assert res_no_voice.success is False

    songs = [Song(title="Fav", path="http://fav")]
    res_ok = test_radio.command_service.enqueue_songs(user, songs)
    assert res_ok.success is True
    await asyncio.sleep(0.02)
    assert len(test_radio.queue) == 1
    assert test_radio.queue[0] is not songs[0]

    # clear_history requires admin
    assert test_radio.command_service.clear_history(user).success is False
    assert test_radio.command_service.clear_history(admin).success is True


@pytest.mark.asyncio
async def test_cache_service_index_avoids_exists_probes_and_clears_async(tmp_path, test_db):
    mock_config = MagicMock()
    mock_config.ytdlp_path = "yt-dlp"
    mock_config.cache_expiry_days = 30
    mock_config.max_cache_size_mb = 100

    cs = CacheService(mock_config, test_db)
    cs.cache_dir = str(tmp_path)
    missing = Song(title="Missing", path="http://example.com/missing")

    # Warm index for tmp_path, then ensure misses do zero os.path.exists probes
    assert cs.get_cache_path(missing) is None
    with patch("os.path.exists") as exists_mock:
        assert cs.get_cache_path(missing) is None
        exists_mock.assert_not_called()

    # Add a cached file and verify clear_cache_async removes it
    present = Song(title="Present", path="http://example.com/present")
    h = hashlib.sha1(present.path.encode()).hexdigest()
    fp = os.path.join(cs.cache_dir, f"{h}.opus")
    with open(fp, "wb") as f:
        f.write(b"audio")
    test_db.set_cache(present.path, "Present", "Art", 60, "", local_path=fp)

    removed = await cs.clear_cache_async()
    assert removed == 1
    assert not os.path.exists(fp)
    assert test_db.get_cache(present.path)["local_path"] is None


def test_repositories_true_lru_eviction(test_db):
    from core.db.cache_repo import CacheRepository
    from core.db.favorites_repo import FavoritesRepository

    cache_repo = CacheRepository(test_db._pool, max_mem_entries=2)
    cache_repo.set("http://a", "A", "Art", 10, "")
    cache_repo.set("http://b", "B", "Art", 10, "")
    # Touch http://a so http://b becomes least-recently-used
    assert cache_repo.get("http://a") is not None
    cache_repo.set("http://c", "C", "Art", 10, "")
    assert "http://a" in cache_repo._mem_cache
    assert "http://c" in cache_repo._mem_cache
    assert "http://b" not in cache_repo._mem_cache

    fav_repo = FavoritesRepository(test_db._pool, max_cached_users=2)
    s = Song(title="F", path="http://fav")
    fav_repo.add("u1", s)
    fav_repo.add("u2", s)
    assert fav_repo.is_favorite("u1", s.path) is True
    assert fav_repo.is_favorite("u2", s.path) is True
    # Touch u1 so u2 becomes least-recently-used
    assert fav_repo.is_favorite("u1", s.path) is True
    assert fav_repo.is_favorite("u3", s.path) is False
    assert "u1" in fav_repo._fav_cache
    assert "u3" in fav_repo._fav_cache
    assert "u2" not in fav_repo._fav_cache


@pytest.mark.asyncio
async def test_ui_manager_update_progress_skips_station_presence_and_cleaner(test_radio):
    bot = MagicMock()
    bot.is_closed.return_value = False
    bot.user = MagicMock(id=999)
    channel = MagicMock()
    player_msg = AsyncMock()
    player_msg.id = 222
    player_msg.author = bot.user
    bot.get_channel.return_value = channel

    ui = UIManager(bot, test_radio.config, test_radio)
    test_radio.voice_channel_id = 333
    test_radio.status = RadioState.PLAYING
    test_radio.current_song = Song(title="Track", path="http://track.mp3", duration=100)
    test_radio.now_playing_message = player_msg

    with (
        patch.object(ui.presence, "update", new=AsyncMock()) as pres_mock,
        patch.object(ui, "_render_station_message", new=AsyncMock()) as station_mock,
        patch.object(ui.cleaner, "schedule") as cleaner_mock,
    ):
        await ui.update_progress()
        pres_mock.assert_not_awaited()
        station_mock.assert_not_awaited()
        cleaner_mock.assert_not_called()
        assert player_msg.edit.await_count == 1


@pytest.mark.asyncio
async def test_action_handler_volume_noop_and_paused_skip_restart(test_radio):
    from services.player.action_handler import PlaybackActionHandler
    from services.player.voice_manager import VoiceManager

    bot = MagicMock()
    vm = VoiceManager(bot, test_radio.config, test_radio)
    ah = PlaybackActionHandler(bot, test_radio, vm, AsyncMock())
    voice = MagicMock()
    voice.source = MagicMock()
    song = Song(title="Track", path="http://track.mp3", duration=100)

    test_radio.volume = 0.5
    test_radio.status = RadioState.PLAYING
    assert await ah.handle_playback_action(RadioAction.SET_VOLUME, 0.5, voice, song) is False
    voice.stop.assert_not_called()

    test_radio.status = RadioState.PAUSED
    assert await ah.handle_playback_action(RadioAction.SET_VOLUME, 0.8, voice, song) is False
    assert test_radio.volume == 0.8
    assert test_radio.is_seeking is True
    voice.stop.assert_not_called()


def test_embed_state_and_safe_fetch_log_failures(tmp_path, caplog):
    import logging
    import discord
    from ui.utils import safe_fetch_message

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{bad json", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="RadioBot"):
        mgr = EmbedStateManager(str(corrupt))
    assert mgr.state == {}
    assert any("EMBED_STATE" in rec.message for rec in caplog.records)

    # safe_fetch_message logs warning on Forbidden
    caplog.clear()
    channel = MagicMock()
    channel.fetch_message = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "Missing Access"))
    with caplog.at_level(logging.WARNING, logger="RadioBot"):
        res = asyncio.run(safe_fetch_message(channel, 12345))
    assert res is None
    assert any("Missing permission to fetch message 12345" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_voice_manager_switch_channel_preserves_id_and_logs_on_fetch_error(test_radio, caplog):
    import logging
    from services.player.voice_manager import VoiceManager

    bot = MagicMock()
    bot.get_guild.return_value = None
    bot.fetch_channel = AsyncMock(side_effect=RuntimeError("channel unavailable"))
    vm = VoiceManager(bot, test_radio.config, test_radio)
    test_radio.voice_channel_id = 111

    with caplog.at_level(logging.WARNING, logger="RadioBot"):
        switched = await vm.switch_channel(999, None)
    assert switched is False
    assert test_radio.voice_channel_id == 111
    assert any("Failed to fetch target channel 999" in rec.message for rec in caplog.records)


def test_radiobot_loop_exception_handler_logs_traceback(caplog):
    import logging
    from bot import RadioBot

    exc = RuntimeError("detached task boom")
    with caplog.at_level(logging.ERROR, logger="RadioBot"):
        RadioBot._handle_loop_exception(MagicMock(), {"message": "Task failed", "exception": exc})

    assert any("[ASYNCIO] Task failed: detached task boom" in rec.message for rec in caplog.records)







