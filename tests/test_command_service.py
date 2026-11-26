from core.actions import RadioState
from core.models import Song
from tests.conftest import MockMember, MockRole, MockVoiceChannel


def test_command_service_voice_permissions(test_radio):
    cs = test_radio.command_service
    vc1 = MockVoiceChannel(id=10, name="VC 1")
    vc2 = MockVoiceChannel(id=20, name="VC 2")

    # User not in voice
    user_no_voice = MockMember(id=1, voice_channel=None)
    res = cs.play(user_no_voice, "song query")
    assert res.success is False

    # User in voice channel
    user_in_vc1 = MockMember(id=2, voice_channel=vc1)
    
    # When radio is IDLE, interaction allowed
    test_radio.status = RadioState.IDLE
    assert test_radio.can_interact(user_in_vc1) is True

    # When radio is active in vc2
    test_radio.status = RadioState.PLAYING
    test_radio.voice = type("MockVoice", (), {"channel": vc2})()
    assert test_radio.can_interact(user_in_vc1) is False

    # Admin bypasses channel restrictions
    admin_user = MockMember(id=3, is_admin=True, voice_channel=vc1)
    assert test_radio.can_interact(admin_user) is True

    # Server owner is admin
    owner_user = MockMember(id=test_radio.config.guild_id, voice_channel=vc1)
    owner_user.guild.owner_id = owner_user.id
    assert test_radio.is_admin(owner_user) is True

    # Role-based admin checks
    role_admin = MockMember(id=4, is_admin=False, voice_channel=vc1)
    role_admin.roles = [MockRole(id=test_radio.config.admin_role_id)]
    assert test_radio.is_admin(role_admin) is True

    role_sysadmin = MockMember(id=5, is_admin=False, voice_channel=vc1)
    role_sysadmin.roles = [MockRole(id=test_radio.config.sysadmin_role_id)]
    assert test_radio.is_admin(role_sysadmin) is True

    # Active bot but voice client missing channel
    test_radio.voice = None
    assert test_radio.can_interact(user_in_vc1) is True

    # In same channel
    test_radio.voice = type("MockVoice", (), {"channel": vc1})()
    assert test_radio.can_interact(user_in_vc1) is True

    # Object without voice attribute
    plain_user = type("PlainUser", (), {"name": "plain"})()
    assert test_radio.can_interact(plain_user) is False

def test_command_service_volume_limits(test_radio):
    cs = test_radio.command_service
    admin_user = MockMember(id=99, is_admin=True)

    res_valid = cs.volume(admin_user, 75)
    assert res_valid.success is True

    res_invalid_high = cs.volume(admin_user, 150)
    assert res_invalid_high.success is False

    res_invalid_low = cs.volume(admin_user, -10)
    assert res_invalid_low.success is False

def test_favorite_manager_quota_and_cooldown(test_radio):
    fm = test_radio.fav_manager
    user_id = "test_fav_user"
    song = Song(title="Favorite Track", path="http://fav.mp3", duration=180)

    # Initial toggle adds to favorites
    added = fm.toggle_favorite(user_id, song)
    assert added is True

    # Immediate rapid toggle is rate-limited (stays favorite)
    rapid = fm.toggle_favorite(user_id, song)
    assert rapid is True # Remains True due to cooldown protection

    # Test quota cap
    fm.MAX_USER_FAVORITES = 1
    song2 = Song(title="Favorite Track 2", path="http://fav2.mp3", duration=200)
    fm._user_last_toggle.clear() # Reset cooldown
    added2 = fm.toggle_favorite(user_id, song2)
    assert added2 is False # Rejected by MAX_USER_FAVORITES quota

    # Test get_favorites and clear_favorites
    fav_list = fm.get_favorites(user_id)
    assert len(fav_list) == 1
    assert fav_list[0].title == "Favorite Track"

    # Toggle favorite off when already present
    fm._user_last_toggle.clear()
    toggled_off = fm.toggle_favorite(user_id, song)
    assert toggled_off is False
    assert fm.is_favorite(user_id, song) is False

    # Edge cases: empty song or None path
    assert fm.is_favorite(user_id, None) is False
    assert fm.is_favorite(user_id, Song(path="")) is False
    assert fm.toggle_favorite(user_id, None) is False
    assert fm.toggle_favorite(user_id, Song(path="")) is False

    # Clear favorites
    fm.clear_favorites(user_id)
    assert len(fm.get_favorites(user_id)) == 0
