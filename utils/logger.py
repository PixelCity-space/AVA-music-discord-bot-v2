import copy
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
from colorama import init, Fore, Style

# Ensure standard console streams handle UTF-8 cleanly on Windows without charmap encoding errors
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

init(autoreset=True)

class ColoredFormatter(logging.Formatter):
    LEVEL_COLORS = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.RED + Style.BRIGHT,
    }

    def format(self, record):
        # Create a shallow copy so mutations do not leak to other handlers (e.g. RotatingFileHandler)
        record_copy = copy.copy(record)
        color = self.LEVEL_COLORS.get(record_copy.levelno, Fore.WHITE)
        record_copy.levelname = f"{color}{record_copy.levelname}{Style.RESET_ALL}"
        if record_copy.levelno >= logging.WARNING:
            msg = record_copy.getMessage()
            record_copy.msg = f"{Style.BRIGHT}{msg}{Style.RESET_ALL}"
            record_copy.args = ()
        return super().format(record_copy)

log = logging.getLogger("RadioBot")

def setup_logging(
    level_name: str = "INFO", 
    instance_name: str = "", 
    max_bytes: int = 10 * 1024 * 1024, 
    backup_count: int = 5
):
    level = getattr(logging, level_name.upper(), logging.INFO)
    log.setLevel(level)
    log.propagate = False

    inst = instance_name or os.getenv("INSTANCE_NAME", "")
    target_log_file = f"data/{inst}_radio.log" if inst else "data/radio.log"
    os.makedirs(os.path.dirname(os.path.abspath(target_log_file)), exist_ok=True)

    discord_log = logging.getLogger("discord")
    discord_log.propagate = False
    discord_level = logging.INFO if level <= logging.INFO else level
    discord_log.setLevel(discord_level)

    # Cleanly remove and close existing handlers to avoid duplicates or leaks
    for logger in (log, discord_log):
        for h in list(logger.handlers):
            logger.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass

    # Rotating File Handler
    if not os.getenv("MANAGED_LOGGING"):
        file_handler = RotatingFileHandler(
            target_log_file, 
            maxBytes=max_bytes, 
            backupCount=backup_count, 
            encoding="utf-8"
        )
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        log.addHandler(file_handler)

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ColoredFormatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
    log.addHandler(console_handler)

    # Route discord logger events to the same handlers
    for h in log.handlers:
        discord_log.addHandler(h)

