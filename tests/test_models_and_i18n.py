from core.models import Song
from ui.i18n import init_translate, load_locales_for_instance, t


def test_song_model_creation():
    s = Song(title="My Song", path="http://example.com/audio.mp3", uploader="Artist", duration=210)
    assert s.title == "My Song"
    assert s.path == "http://example.com/audio.mp3"
    assert s.uploader == "Artist"
    assert s.duration == 210
    assert s.is_resolving is False

def test_song_from_dict_and_to_dict():
    raw_data = {
        "title": "Song Title",
        "url": "http://audio.mp3",
        "uploader": "Uploader Name",
        "duration": 180,
        "thumbnail": "http://thumb.jpg",
        "is_external": True,
        "requested_by": "User1"
    }
    song = Song.from_dict(raw_data)
    assert song.title == "Song Title"
    assert song.path == "http://audio.mp3"
    assert song.uploader == "Uploader Name"
    assert song.duration == 180
    assert song.thumbnail_url == "http://thumb.jpg"
    assert song.is_external is True

    d = song.to_dict()
    assert d["title"] == "Song Title"
    assert d["path"] == "http://audio.mp3"
    assert "_resolve_event" not in d

def test_song_resolve_event():
    s = Song(path="http://sample.mp3", is_resolving=False)
    # Since not resolving, resolve_event should immediately be set
    assert s.resolve_event.is_set()

    s_resolving = Song(path="http://sample2.mp3", is_resolving=True)
    assert not s_resolving.resolve_event.is_set()
    s_resolving.resolve_event.set()
    assert s_resolving.resolve_event.is_set()

def test_song_update_metadata():
    s = Song(path="", title="[Initial]", duration=0, uploader="...")
    _ = s.resolve_event # Initialize _resolve_event while is_resolving is False
    s.update({
        "title": "Resolved Title",
        "duration": 300,
        "artist": "New Artist",
        "url": "http://updated.mp3",
        "stream_url": "http://stream.mp3"
    })
    assert s.title == "Resolved Title"
    assert s.duration == 300
    assert s.uploader == "New Artist"
    assert s.path == "http://updated.mp3"
    assert s.stream_url == "http://stream.mp3"

def test_song_cache_to_db(test_db):
    s = Song(path="http://sample_cache.mp3", title="Cached Song", uploader="Cached Artist", duration=250)
    s.cache_to_db(test_db, local_path="data/cache/cached.mp3")

    cached = test_db.get_cache("http://sample_cache.mp3")
    assert cached is not None
    assert cached["title"] == "Cached Song"
    assert cached["local_path"] == "data/cache/cached.mp3"

    # None path or none db returns gracefully
    s_empty = Song(path="")
    s_empty.cache_to_db(test_db)
    s.cache_to_db(None)

def test_i18n_locales_load():
    locales = load_locales_for_instance()
    assert "en" in locales
    assert "hu" in locales
    assert "now_playing" in locales["en"]
    assert "now_playing" in locales["hu"]

def test_i18n_translate_key(test_radio):
    init_translate(test_radio)
    test_radio.language = "en"
    text_en = t("now_playing", radio=test_radio)
    assert text_en != ""
    assert "now_playing" not in text_en.lower() # Should be translated

    test_radio.language = "hu"
    text_hu = t("now_playing", radio=test_radio)
    assert text_hu != ""
    assert text_hu != text_en
