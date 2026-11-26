import asyncio

from core.actions import RadioAction, RadioState
from core.models import Song
from tests.conftest import MockMember


async def test_radio_queue_management(test_radio):
    assert len(test_radio.queue) == 0

    s1 = Song(title="Song 1", path="http://s1.mp3", duration=100)
    s2 = Song(title="Song 2", path="http://s2.mp3", duration=150)

    # Dispatch ADD_SONGS (handled via async task)
    test_radio.dispatch(RadioAction.ADD_SONGS, [s1, s2])
    await asyncio.sleep(0.02)
    assert len(test_radio.queue) == 2
    assert test_radio.queue[0].title == "Song 1"

    # Dispatch REMOVE_FROM_QUEUE (synchronous state handling)
    test_radio.dispatch(RadioAction.REMOVE_FROM_QUEUE, s1)
    assert len(test_radio.queue) == 1
    assert test_radio.queue[0].title == "Song 2"

    # Dispatch CLEAR_QUEUE
    test_radio.dispatch(RadioAction.CLEAR_QUEUE)
    assert len(test_radio.queue) == 0

async def test_radio_modes_toggle(test_radio):
    assert test_radio.loop_mode is False
    assert test_radio.loop_queue_mode is False

    # Toggle loop mode
    test_radio.dispatch(RadioAction.LOOP)
    assert test_radio.loop_mode

    # Toggle loop queue mode (should disable single loop)
    test_radio.dispatch(RadioAction.LOOP_QUEUE)
    assert test_radio.loop_queue_mode
    assert not test_radio.loop_mode

async def test_background_task_tracking_and_close(test_radio):
    executed = []
    async def sample_task():
        await asyncio.sleep(0.02)
        executed.append(True)

    task = test_radio.create_task(sample_task(), name="sample_test_task")
    assert task in test_radio._background_tasks
    await asyncio.sleep(0.05)
    assert len(executed) == 1
    # Task automatically discarded from set after completion
    assert task not in test_radio._background_tasks

    # Verify close drains and cleans up tasks
    hanging_task = test_radio.create_task(asyncio.sleep(10), name="hanging_task")
    assert hanging_task in test_radio._background_tasks
    await test_radio.close()
    assert len(test_radio._background_tasks) == 0
    assert hanging_task.cancelled() or hanging_task.done()

async def test_radio_additional_actions(test_radio):
    s1 = Song(title="A", path="http://a.mp3")
    s2 = Song(title="B", path="http://b.mp3")
    s3 = Song(title="C", path="http://c.mp3")

    test_radio.queue = [s1, s2, s3]

    # MOVE_SONG
    test_radio.dispatch(RadioAction.MOVE_SONG, (s1, 1))
    assert test_radio.queue[1].title == "A"
    assert test_radio.queue[0].title == "B"

    # SHUFFLE
    test_radio.dispatch(RadioAction.SHUFFLE)
    assert len(test_radio.queue) == 3

    # TOGGLE_FAVORITE
    test_radio.dispatch(RadioAction.TOGGLE_FAVORITE, ("user_10", s1))
    assert test_radio.fav_manager.is_favorite("user_10", s1) is True

    # CLEAR_FAVORITES
    test_radio.dispatch(RadioAction.CLEAR_FAVORITES, "user_10")
    assert test_radio.fav_manager.is_favorite("user_10", s1) is False

    # CLEAR_HISTORY
    test_radio.db.add_history(s1)
    assert test_radio.has_history is True
    test_radio.dispatch(RadioAction.CLEAR_HISTORY)
    assert not test_radio.has_history
    assert len(test_radio.history) == 0

    # HistoryManager methods directly
    hm = test_radio.history_manager
    hm.add(None)
    hm.add(Song(path=""))
    hm.add(s1)
    assert hm.has_items() is True
    assert hm.get_latest(offset=0).title == "A"
    assert len(hm.get_all(limit=5)) == 1
    popped = hm.pop_latest()
    assert popped.title == "A"
    assert hm.has_items() is False

    # CLEAR_CACHE
    test_radio.dispatch(RadioAction.CLEAR_CACHE)

    # State change callback notification
    notified = []
    async def state_cb(song=None): notified.append(True)
    test_radio.on_state_change = state_cb
    test_radio._notify_state_change()
    await asyncio.sleep(0.01)
    assert len(notified) == 1

async def test_radio_delegates_and_async_add(test_radio):
    song = Song(title="Track Ext", path="http://track.mp3", duration=120)
    assert test_radio.is_cached(song) is False
    assert test_radio.get_cache_path(song) is None

    test_radio.cleanup_cache()
    test_radio.clear_cache()
    test_radio.delete_cache_file(song)

    # Test _add_songs directly
    user = MockMember(id=777, name="User777", display_name="UserSeven")
    test_radio.voice_channel_id = 999
    test_radio.status = RadioState.IDLE

    await test_radio._add_songs([song], user=user)
    assert len(test_radio.queue) > 0
    assert song.requested_by == "UserSeven"
    assert song.user_id == "777"
    assert test_radio.status == RadioState.PLAYING

async def test_radio_remaining_branches(test_radio):
    # 1. Unhandled exception in background task triggers logging
    async def failing_task():
        raise RuntimeError("Intentional task failure for test")
    
    task = test_radio.create_task(failing_task(), name="failing_test_task")
    await asyncio.sleep(0.02)
    assert task.done()

    # 2. Synchronous on_state_change callback (line 148)
    sync_called = []
    def sync_cb(song=None):
        sync_called.append(True)
    test_radio.on_state_change = sync_cb
    test_radio._notify_state_change()
    assert len(sync_called) == 1

    # 3. start_cache_download delegate
    await test_radio.start_cache_download(Song(path="http://sample.mp3"))

    # 4. _add_external_link with invalid query
    test_radio.resolver.sanitize_query = lambda q: None
    await test_radio._add_external_link("invalid://path")

    # 5. Non-state action forwarded to action_queue
    test_radio.dispatch(RadioAction.PAUSE)
    action, data = test_radio.action_queue.get_nowait()
    assert action == RadioAction.PAUSE

async def test_radio_resolver_tasks(test_radio):
    user = MockMember(id=888, name="User888")

    # 1. Single resolving song task
    s_resolving = Song(title="Resolving Song", path="http://resolving.mp3", is_resolving=True)
    async def mock_prepare(q, user=None):
        return s_resolving
    async def mock_resolve(s):
        s.is_resolving = False
        s.duration = 180

    test_radio.resolver.prepare_external_song = mock_prepare
    test_radio.resolver.resolve_song = mock_resolve
    test_radio.resolver.is_matching_provider = lambda q: None

    await test_radio._add_external_link("http://resolving.mp3", user=user)
    await asyncio.sleep(0.05)
    assert s_resolving.duration == 180

    # 2. Playlist task
    mock_prov = type("MockProv", (), {"is_playlist": lambda self, u: True})()
    test_radio.resolver.is_matching_provider = lambda q: mock_prov
    s_p1 = Song(title="P1", path="http://p1.mp3")
    async def mock_playlist(u, user=None):
        return [s_p1]
    test_radio.resolver.resolve_playlist = mock_playlist

    await test_radio._add_external_link("http://playlist.url", user=user)
    await asyncio.sleep(0.05)
    assert any(s.title == "P1" for s in test_radio.queue)

    # 3. Action dispatch with user string formatting
    test_radio.dispatch(RadioAction.SHUFFLE, user=user)
    assert test_radio.last_user == user
    assert test_radio.is_admin(user) is False
    assert test_radio.can_interact(user) is True

    # 4. Dispatch ADD_EXT_LINK
    test_radio.dispatch(RadioAction.ADD_EXT_LINK, "http://playlist.url", user=user)
    await asyncio.sleep(0.05)

    # 5. MOVE_SONG with non-existent song triggers ValueError branch
    untracked_song = Song(path="http://ghost.mp3")
    test_radio.dispatch(RadioAction.MOVE_SONG, (untracked_song, 1))

    # 6. prepare_external_song returning None (line 247)
    async def mock_prepare_none(q, user=None):
        return None
    test_radio.resolver.is_matching_provider = lambda q: None
    test_radio.resolver.prepare_external_song = mock_prepare_none
    await test_radio._add_external_link("http://empty.song", user=user)

    # 7. Single song with IDLE and active voice channel sets PLAYING (line 256)
    test_radio.status = RadioState.IDLE
    test_radio.voice_channel_id = 9999
    s_single = Song(title="Single", path="http://single.mp3", is_resolving=False)
    async def mock_prepare_single(q, user=None):
        return s_single
    test_radio.resolver.prepare_external_song = mock_prepare_single
    await test_radio._add_external_link("http://single.song", user=user)
    assert test_radio.status == RadioState.PLAYING

    # 8. Playlist task with active voice channel sets PLAYING (line 279)
    test_radio.status = RadioState.IDLE
    test_radio.voice_channel_id = 1111
    await test_radio._resolve_playlist_task("http://playlist.url", user=user)
    assert test_radio.status == RadioState.PLAYING
