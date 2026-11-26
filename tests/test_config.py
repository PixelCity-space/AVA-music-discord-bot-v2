import json
import os
import tempfile

import pytest

from utils.config import Config, load_config


def test_config_valid(mock_config):
    assert mock_config.token == "test_mock_token_123456789"
    assert mock_config.default_volume == 0.5
    assert mock_config.default_language == "en"
    assert mock_config.default_ui_mode == "full"

def test_config_token_placeholder_rejected(mock_config):
    with pytest.raises(ValueError, match="placeholder"):
        Config(
            token="your_bot_token_here",
            guild_id=mock_config.guild_id,
            radio_text_channel_id=mock_config.radio_text_channel_id,
            auto_join_channel_id=0,
            afk_channel_id=0,
            admin_role_id=0,
            sysadmin_role_id=0,
            default_language="en",
            default_ui_mode="full",
            ffmpeg_path="ffmpeg",
            ytdlp_path="yt-dlp",
            languages=mock_config.languages,
            ui_settings={},
            timings={},
            defaults={}
        )

def test_config_invalid_ui_mode(mock_config):
    with pytest.raises(ValueError, match="default_ui_mode"):
        Config(
            token=mock_config.token,
            guild_id=mock_config.guild_id,
            radio_text_channel_id=mock_config.radio_text_channel_id,
            auto_join_channel_id=0,
            afk_channel_id=0,
            admin_role_id=0,
            sysadmin_role_id=0,
            default_language="en",
            default_ui_mode="ultra_mode",
            ffmpeg_path="ffmpeg",
            ytdlp_path="yt-dlp",
            languages=mock_config.languages,
            ui_settings={},
            timings={},
            defaults={}
        )

def test_config_unregistered_language(mock_config):
    with pytest.raises(ValueError, match="default_language"):
        Config(
            token=mock_config.token,
            guild_id=mock_config.guild_id,
            radio_text_channel_id=mock_config.radio_text_channel_id,
            auto_join_channel_id=0,
            afk_channel_id=0,
            admin_role_id=0,
            sysadmin_role_id=0,
            default_language="de",
            default_ui_mode="full",
            ffmpeg_path="ffmpeg",
            ytdlp_path="yt-dlp",
            languages=mock_config.languages,
            ui_settings={},
            timings={},
            defaults={}
        )

def test_config_negative_id(mock_config):
    with pytest.raises(ValueError, match="guild_id"):
        Config(
            token=mock_config.token,
            guild_id=-1,
            radio_text_channel_id=mock_config.radio_text_channel_id,
            auto_join_channel_id=0,
            afk_channel_id=0,
            admin_role_id=0,
            sysadmin_role_id=0,
            default_language="en",
            default_ui_mode="full",
            ffmpeg_path="ffmpeg",
            ytdlp_path="yt-dlp",
            languages=mock_config.languages,
            ui_settings={},
            timings={},
            defaults={}
        )

def test_load_config_rejects_token_in_json():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
        json.dump({"token": "leaked_secret_token"}, tf)
        tf_path = tf.name

    try:
        with pytest.raises(ValueError, match="Security violation"):
            load_config(tf_path)
    finally:
        os.remove(tf_path)

def test_load_config_missing_token_raised(monkeypatch):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    with pytest.raises(ValueError, match="Missing required environment variable: 'DISCORD_TOKEN'"):
        load_config("configs/config.json", instance_name="unconfigured_instance_xyz")

def test_load_config_missing_file():
    with pytest.raises(FileNotFoundError, match="Configuration file not found"):
        load_config("nonexistent_path_xyz_123.json")

def test_load_config_root_env_fallback(monkeypatch, tmp_path):
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    test_root_env = os.path.join(root_dir, "test_fallback.env")
    with open(test_root_env, "w", encoding="utf-8") as f:
        f.write("DISCORD_TOKEN=root_env_token_val\n")
    try:
        cfg = load_config("configs/config.json", instance_name="test_fallback")
        assert cfg.token == "root_env_token_val"
    finally:
        if os.path.exists(test_root_env):
            os.remove(test_root_env)

def test_load_config_env_overrides(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "valid_override_token")
    monkeypatch.setenv("GUILD_ID", "98765")
    monkeypatch.setenv("RADIO_CHANNEL_ID", "12345")
    monkeypatch.setenv("AUTO_JOIN_ID", "54321")

    cfg = load_config("configs/config.json", instance_name="test_override_inst")
    assert cfg.token == "valid_override_token"
    assert cfg.guild_id == 98765
    assert cfg.radio_text_channel_id == 12345
    assert cfg.auto_join_channel_id == 54321

def test_config_empty_token():
    with pytest.raises(ValueError, match="'token' must be a non-empty string"):
        Config(
            token="",
            guild_id=0,
            radio_text_channel_id=0,
            auto_join_channel_id=0,
            afk_channel_id=0,
            admin_role_id=0,
            sysadmin_role_id=0,
            default_language="en",
            default_ui_mode="full",
            ffmpeg_path="ffmpeg",
            ytdlp_path="yt-dlp",
            languages=[],
            ui_settings={},
            timings={},
            defaults={}
        )

def test_config_bounds_validations(mock_config):
    # Invalid volume (< 0 or > 1)
    with pytest.raises(ValueError, match="default volume"):
        Config(
            token=mock_config.token,
            guild_id=0,
            radio_text_channel_id=0,
            auto_join_channel_id=0,
            afk_channel_id=0,
            admin_role_id=0,
            sysadmin_role_id=0,
            default_language="en",
            default_ui_mode="full",
            ffmpeg_path="ffmpeg",
            ytdlp_path="yt-dlp",
            languages=mock_config.languages,
            ui_settings={},
            timings={},
            defaults={"volume": 1.5}
        )

    # Invalid progress_update_seconds (< 1)
    with pytest.raises(ValueError, match="progress_update_seconds"):
        Config(
            token=mock_config.token,
            guild_id=0,
            radio_text_channel_id=0,
            auto_join_channel_id=0,
            afk_channel_id=0,
            admin_role_id=0,
            sysadmin_role_id=0,
            default_language="en",
            default_ui_mode="full",
            ffmpeg_path="ffmpeg",
            ytdlp_path="yt-dlp",
            languages=mock_config.languages,
            ui_settings={},
            timings={"progress_update_seconds": 0},
            defaults={}
        )

    # Invalid max_cache_size_mb (<= 0)
    with pytest.raises(ValueError, match="max_cache_size_mb"):
        Config(
            token=mock_config.token,
            guild_id=0,
            radio_text_channel_id=0,
            auto_join_channel_id=0,
            afk_channel_id=0,
            admin_role_id=0,
            sysadmin_role_id=0,
            default_language="en",
            default_ui_mode="full",
            ffmpeg_path="ffmpeg",
            ytdlp_path="yt-dlp",
            languages=mock_config.languages,
            ui_settings={},
            timings={},
            defaults={"max_cache_size_mb": 0}
        )

def test_config_property_accessors(mock_config):
    assert mock_config.embed_refresh_minutes == 58
    assert mock_config.error_retry_seconds == 5
    assert mock_config.afk_retry_seconds == 5
    assert mock_config.solitary_timeout_seconds == 300
    assert mock_config.progress_bar_width == 18
    assert mock_config.thumbnail_size == 40
    assert mock_config.max_title_len == 45
    assert mock_config.list_max_title_len == 60
    assert mock_config.max_uploader_len == 35
    assert mock_config.database_path == "data/test.db"
    assert mock_config.log_level == "INFO"
    assert mock_config.log_max_bytes == 10 * 1024 * 1024
    assert mock_config.log_backup_count == 5
    assert "-reconnect" in mock_config.ffmpeg_reconnect_options
    assert mock_config.search_items_per_page == 5
    assert mock_config.queue_items_per_page == 5
    assert mock_config.action_timeout == 5.0
    assert mock_config.notification_timeout == 5.0
    assert mock_config.view_timeout == 60
    assert mock_config.command_delete_delay == 0.1
    assert mock_config.command_prefix == "!"
    assert mock_config.history_limit == 50
    assert mock_config.search_limit == 20
    assert mock_config.max_cache_size_mb == 1024
    assert "Chrome" in mock_config.user_agent
