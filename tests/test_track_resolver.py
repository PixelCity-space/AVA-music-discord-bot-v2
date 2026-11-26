from services.track_resolver import TrackResolverService


def test_sanitize_valid_urls():
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert TrackResolverService.sanitize_query(url) == url

    sc_url = "https://soundcloud.com/artist/track"
    assert TrackResolverService.sanitize_query(sc_url) == sc_url

def test_sanitize_valid_search_query():
    query = "classical piano mozart sonata"
    assert TrackResolverService.sanitize_query(query) == query

def test_sanitize_rejects_disallowed_schemes():
    assert TrackResolverService.sanitize_query("file:///etc/passwd") is None
    assert TrackResolverService.sanitize_query("ftp://ftp.example.com/audio.mp3") is None
    assert TrackResolverService.sanitize_query("gopher://example.com") is None

def test_sanitize_rejects_overlong_query():
    overlong = "a" * (TrackResolverService.MAX_QUERY_LEN + 1)
    assert TrackResolverService.sanitize_query(overlong) is None

def test_sanitize_strips_control_characters():
    dirty = "https://youtube.com/watch?v=123\x00\r\n; rm -rf /"
    cleaned = TrackResolverService.sanitize_query(dirty)
    assert cleaned is not None
    assert "\x00" not in cleaned
    assert "\r" not in cleaned
    assert "\n" not in cleaned
    assert cleaned == "https://youtube.com/watch?v=123; rm -rf /"

def test_sanitize_empty_query():
    assert TrackResolverService.sanitize_query("") is None
    assert TrackResolverService.sanitize_query("   \n\t  ") is None
    assert TrackResolverService.sanitize_query(None) is None
