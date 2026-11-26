from core.models import Song


def test_connection_pool_reuse(test_db):
    conns = []
    for _ in range(3):
        with test_db._get_connection() as c:
            conns.append(c)
    assert len(conns) == 3
    # Borrowing again reuses existing pooled connection objects
    with test_db._get_connection() as c_reused:
        assert c_reused in conns

def test_cache_crud(test_db):
    test_db.set_cache(
        url="https://youtube.com/watch?v=123",
        title="Test Song",
        uploader="Test Artist",
        duration=240,
        thumbnail_url="https://thumb.jpg",
        local_path="data/cache/123.mp3"
    )
    cached = test_db.get_cache("https://youtube.com/watch?v=123")
    assert cached is not None
    assert cached["title"] == "Test Song"
    assert cached["duration"] == 240
    assert cached["local_path"] == "data/cache/123.mp3"

    # Batch cache
    test_db.set_cache_batch([
        {"url": "https://youtube.com/watch?v=456", "title": "Batch Song 1", "duration": 180},
        {"url": "https://youtube.com/watch?v=789", "title": "Batch Song 2", "duration": 200}
    ])
    assert test_db.get_cache("https://youtube.com/watch?v=456")["title"] == "Batch Song 1"

    # Clear cache resets local_path
    test_db.clear_cache()
    assert test_db.get_cache("https://youtube.com/watch?v=123")["local_path"] is None

def test_history_o1_and_bounds(test_db):
    assert test_db.has_history() is False
    assert test_db.get_history_count() == 0

    # Add song to history
    song = Song(title="Track 1", path="https://test.com/1", uploader="Artist 1", duration=120)
    test_db.add_history(song)

    assert test_db.has_history() is True
    assert test_db.get_history_count() == 1

    latest = test_db.get_history_latest(offset=0)
    assert latest is not None
    assert latest.title == "Track 1"

    # Test clear history
    test_db.clear_history()
    assert test_db.has_history() is False
    assert test_db.get_history_count() == 0

def test_favorites_crud_and_count(test_db):
    user_id = "user_42"
    song = Song(title="Fav 1", path="https://test.com/fav1", uploader="Artist", duration=300)

    assert test_db.is_favorite(user_id, song.path) is False
    assert test_db.get_favorite_count(user_id) == 0

    test_db.add_favorite(user_id, song)
    assert test_db.is_favorite(user_id, song.path) is True
    assert test_db.get_favorite_count(user_id) == 1

    favs = test_db.get_favorites(user_id)
    assert len(favs) == 1
    assert favs[0].title == "Fav 1"

    test_db.remove_favorite(user_id, song.path)
    assert test_db.is_favorite(user_id, song.path) is False
    assert test_db.get_favorite_count(user_id) == 0

def test_database_cache_extended(test_db):
    song = Song(title="Ext Song", path="http://ext.mp3", uploader="Ext Artist", duration=150)
    test_db.cache_song(song, local_path="data/cache/ext.mp3")

    cached_urls = test_db.get_all_cached_urls()
    assert "http://ext.mp3" in cached_urls

    test_db.update_cache_path("http://ext.mp3", "data/cache/ext_new.mp3")
    cached = test_db.get_cache("http://ext.mp3")
    assert cached["local_path"] == "data/cache/ext_new.mp3"

    test_db.clear_cache_metadata()
    assert test_db.get_cache("http://ext.mp3") is None

def test_database_history_and_stats_extended(test_db):
    # Test increment_stat
    test_db.increment_stat("tracks_played")
    test_db.increment_stat("tracks_played")

    # Test history insertion, get_history, and pop_history_latest
    s1 = Song(title="H1", path="http://h1.mp3", duration=100)
    s2 = Song(title="H2", path="http://h2.mp3", duration=200)
    test_db.add_history(s1)
    test_db.add_history(s2)

    hist_all = test_db.get_history()
    assert len(hist_all) == 2
    assert hist_all[0].title == "H2"

    hist_limited = test_db.get_history(limit=1)
    assert len(hist_limited) == 1
    assert hist_limited[0].title == "H2"

    popped = test_db.pop_history_latest()
    assert popped is not None
    assert popped.title == "H2"
    assert test_db.get_history_count() == 1

    # Clear favorites test
    test_db.add_favorite("user_99", s1)
    assert test_db.get_favorite_count("user_99") == 1
    test_db.clear_favorites("user_99")
    assert test_db.get_favorite_count("user_99") == 0

def test_database_closed_pool_exception_branches(test_db):
    test_db.close()
    s = Song(title="T", path="P")

    assert test_db.get_cache("p") is None
    test_db.clear_cache()
    test_db.set_cache("p", "t", "u", 10, "th")
    test_db.update_cache_path("p", "lp")
    test_db.clear_cache_metadata()
    assert test_db.get_all_cached_urls() == []
    test_db.set_cache_batch([{"url": "p"}])
    test_db.add_history(s)
    assert test_db.has_history() is False
    assert test_db.get_history_count() == 0
    test_db.increment_stat("stat")
    assert test_db.get_history_latest() is None
    assert test_db.pop_history_latest() is None
    assert test_db.get_history() == []
    test_db.clear_history()
    test_db.add_favorite("u", s)
    test_db.remove_favorite("u", "p")
    assert test_db.is_favorite("u", "p") is False
    assert test_db.get_favorites("u") == []
    assert test_db.get_favorite_count("u") == 0
    test_db.clear_favorites("u")

def test_database_edge_cases(test_db):
    # Empty batch returns immediately without db query
    test_db.set_cache_batch([])

    # History offset beyond range returns None
    assert test_db.get_history_latest(offset=999) is None

    # Pop on empty history returns None
    assert test_db.pop_history_latest() is None

    # None song or empty path in add_favorite
    test_db.add_favorite("u", None)
    test_db.add_favorite("u", Song(path=""))
