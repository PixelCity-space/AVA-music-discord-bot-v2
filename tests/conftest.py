import os
import tempfile
from dataclasses import dataclass

import pytest

from core.database import Database
from core.state import RadioManager
from utils.config import Config


@dataclass
class MockVoiceState:
    channel: object | None = None

@dataclass
class MockRole:
    id: int
    name: str = "Member"

class MockGuildPermissions:
    def __init__(self, administrator: bool = False):
        self.administrator = administrator

class MockGuild:
    def __init__(self, id: int = 12345, owner_id: int = 99999):
        self.id = id
        self.owner_id = owner_id

class MockVoiceChannel:
    def __init__(self, id: int = 200, name: str = "Music Room"):
        self.id = id
        self.name = name

class MockTextChannel:
    def __init__(self, id: int = 100, name: str = "radio-chat"):
        self.id = id
        self.name = name
        self.sent_messages: list[str] = []

    async def send(self, content=None, *args, **kwargs):
        self.sent_messages.append("" if content is None else str(content))
        return self

class MockMember:
    def __init__(self, id: int = 1001, name: str = "TestUser", display_name: str = "TestDisplay",
                 is_admin: bool = False, voice_channel: MockVoiceChannel | None = None, bot: bool = False):
        self.id = id
        self.name = name
        self.display_name = display_name
        self.mention = f"<@{id}>"
        self.guild = MockGuild()
        self.guild_permissions = MockGuildPermissions(administrator=is_admin)
        self.roles = [MockRole(id=1)]
        self.voice = MockVoiceState(channel=voice_channel) if voice_channel else None
        self.bot = bot

@pytest.fixture
def mock_config():
    return Config(
        token="test_mock_token_123456789",
        guild_id=12345,
        radio_text_channel_id=100,
        auto_join_channel_id=0,
        afk_channel_id=0,
        admin_role_id=888,
        sysadmin_role_id=999,
        default_language="en",
        default_ui_mode="full",
        ffmpeg_path="ffmpeg",
        ytdlp_path="yt-dlp",
        languages=[
            {"code": "en", "label": "English"},
            {"code": "hu", "label": "Magyar"}
        ],
        ui_settings={
            "search_items_per_page": 5,
            "queue_items_per_page": 5,
            "list_max_title_len": 60
        },
        timings={
            "progress_update_seconds": 15,
            "notification_timeout": 5.0,
            "view_timeout": 60,
            "command_delete_delay": 0.1
        },
        defaults={
            "volume": 0.5,
            "prefix": "!",
            "history_limit": 50,
            "search_limit": 20,
            "database_path": "data/test.db",
            "log_level": "INFO",
            "max_cache_size_mb": 1024
        }
    )

@pytest.fixture
def test_db():
    temp_dir = tempfile.TemporaryDirectory()
    db_file = os.path.join(temp_dir.name, "test_radio.db")
    db = Database(db_file, pool_size=3)
    yield db
    db.close()
    temp_dir.cleanup()

@pytest.fixture
def test_radio(mock_config, test_db):
    radio = RadioManager(mock_config)
    # Use isolated test database
    radio.db.close()
    radio.db = test_db
    radio.history_manager.db = test_db
    radio.fav_manager.db = test_db
    radio.resolver.db = test_db
    return radio
