import os
import logging
import tempfile
import pytest
from utils.logger import setup_logging, log, ColoredFormatter

@pytest.fixture
def temp_log_dir():
    temp_dir = tempfile.TemporaryDirectory()
    yield temp_dir.name
    # Clean up handlers before deleting temp directory
    logging.shutdown()
    temp_dir.cleanup()

def test_setup_logging_basic(temp_log_dir, monkeypatch):
    log_file = os.path.join(temp_log_dir, "test.log")
    monkeypatch.setattr("utils.logger.os.path.abspath", lambda p: log_file)

    setup_logging(level_name="DEBUG", instance_name="test_inst")
    assert log.level == logging.DEBUG
    assert not log.propagate

    # Verify handlers
    file_handlers = [h for h in log.handlers if isinstance(h, logging.FileHandler)]
    console_handlers = [h for h in log.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)]
    assert len(file_handlers) == 1
    assert len(console_handlers) == 1

def test_setup_logging_reentrancy_no_handler_leak_or_order_flip(temp_log_dir, monkeypatch):
    log_file = os.path.join(temp_log_dir, "reentrant.log")
    monkeypatch.setattr("utils.logger.os.path.abspath", lambda p: log_file)

    # Call setup_logging multiple times
    setup_logging(level_name="INFO", instance_name="reentrant")
    setup_logging(level_name="WARNING", instance_name="reentrant")
    setup_logging(level_name="DEBUG", instance_name="reentrant")

    assert log.level == logging.DEBUG
    # Handler count should stay exactly 2 (1 file, 1 console)
    assert len(log.handlers) == 2
    assert isinstance(log.handlers[0], logging.FileHandler)
    assert isinstance(log.handlers[1], logging.StreamHandler)

def test_no_ansi_in_file_handler_even_after_console_formatting(temp_log_dir, monkeypatch):
    log_file = os.path.join(temp_log_dir, "clean.log")
    # Point target_log_file to temporary path
    monkeypatch.setattr("utils.logger.os.path.abspath", lambda p: log_file)

    setup_logging(level_name="DEBUG", instance_name="clean")

    # Log at various levels
    log.debug("Debug message without color")
    log.info("Info message")
    log.warning("Warning message with bright style")
    log.error("Error message with red color: %s", "details")
    log.critical("Critical error occurred")

    # Flush all handlers
    for h in log.handlers:
        h.flush()

    with open(log_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Content must NOT contain ANSI escape sequences
    assert "\x1b" not in content
    assert "[DEBUG] Debug message without color" in content
    assert "[INFO] Info message" in content
    assert "[WARNING] Warning message with bright style" in content
    assert "[ERROR] Error message with red color: details" in content
    assert "[CRITICAL] Critical error occurred" in content

def test_unicode_and_emojis_logging(temp_log_dir, monkeypatch):
    log_file = os.path.join(temp_log_dir, "unicode.log")
    monkeypatch.setattr("utils.logger.os.path.abspath", lambda p: log_file)

    setup_logging(level_name="INFO", instance_name="unicode")

    # Emojis and Hungarian accented characters that normally trigger charmap errors
    unicode_msg = "Zene lejátszása: 🎵 Lofi Hip Hop Radio 🎧 - árvíztűrő fúrótükör 🎶"
    log.info(unicode_msg)

    for h in log.handlers:
        h.flush()

    with open(log_file, "r", encoding="utf-8") as f:
        content = f.read()

    assert unicode_msg in content

def test_non_string_and_exception_messages(temp_log_dir, monkeypatch):
    log_file = os.path.join(temp_log_dir, "exceptions.log")
    monkeypatch.setattr("utils.logger.os.path.abspath", lambda p: log_file)

    setup_logging(level_name="INFO", instance_name="exceptions")

    # Pass Exception object directly as msg
    err = RuntimeError("Direct exception object")
    log.error(err)

    # Pass dict or integer
    log.warning({"status": "failed", "code": 500})
    log.warning(404)

    for h in log.handlers:
        h.flush()

    with open(log_file, "r", encoding="utf-8") as f:
        content = f.read()

    assert "Direct exception object" in content
    assert "{'status': 'failed', 'code': 500}" in content
    assert "404" in content
    assert "\x1b" not in content

def test_discord_logger_integration(temp_log_dir, monkeypatch):
    log_file = os.path.join(temp_log_dir, "discord.log")
    monkeypatch.setattr("utils.logger.os.path.abspath", lambda p: log_file)

    setup_logging(level_name="INFO", instance_name="discord")

    discord_log = logging.getLogger("discord")
    assert not discord_log.propagate
    assert discord_log.level == logging.INFO

    discord_log.info("Shard 0 connected to Gateway")
    discord_log.warning("Gateway connection dropped, reconnecting in 5s...")

    for h in discord_log.handlers:
        h.flush()

    with open(log_file, "r", encoding="utf-8") as f:
        content = f.read()

    assert "Shard 0 connected to Gateway" in content
    assert "Gateway connection dropped, reconnecting in 5s..." in content
    assert "\x1b" not in content
