import asyncio
import os
import sys
import re
import argparse
import logging
from utils.config import load_config
from utils.logger import log, setup_logging
from bot import RadioBot

EXIT_CODE_RESTART = 42

def parse_arguments():
    parser = argparse.ArgumentParser(description="Discord Radio Bot Instance")
    parser.add_argument("instance", nargs="?", default="", help="Name of this bot instance (e.g. 1, 2, bot1)")
    parser.add_argument("--config", help="Specific config file path")
    return parser.parse_args()

async def main() -> int:
    args = parse_arguments()
    
    instance_name = args.instance
    if not instance_name and args.config:
        m = re.search(r"config([a-zA-Z0-9_-]+)\.json", args.config)
        if m:
            instance_name = m.group(1)
    
    if instance_name:
        os.environ["INSTANCE_NAME"] = instance_name

    config_file = args.config if args.config else (f"config{instance_name}.json" if instance_name else "config.json")
    
    try:
        config = load_config(config_file, instance_name=instance_name)
        setup_logging(
            config.log_level, 
            instance_name=instance_name, 
            max_bytes=config.log_max_bytes, 
            backup_count=config.log_backup_count
        )
    except FileNotFoundError:
        print(f"Error: Configuration file '{config_file}' not found.")
        return 1

    bot = RadioBot(config, instance_name=instance_name)
    restart_requested = False
    
    try:
        async with bot:
            await bot.start(config.token)
    except (asyncio.CancelledError, KeyboardInterrupt):
        log.info("Shutdown initiated by user/signal...")
    except Exception as e:
        log.critical(f"Fatal error during bot execution: {e}", exc_info=True)
    finally:
        restart_requested = (os.getenv("BOT_RESTART") == "1")
        os.environ["BOT_RESTART"] = "0"
        
        if not bot.is_closed():
            await bot.close()
        log.info("Shutdown complete.")

    if restart_requested:
        # If running under a supervisor (Docker, systemd, supervisord, etc.)
        if os.getenv("SUPERVISOR") == "1" or os.getenv("DOCKER") == "1":
            log.info("Exiting with restart code for process manager...")
            logging.shutdown()
            return EXIT_CODE_RESTART

        # Standalone interactive restart
        log.info("Process restart initiated via execv...")
        logging.shutdown()
        try:
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            # Note: execv replaces process, so if it reaches here it failed
            print(f"os.execv failed: {e}. Exiting with code {EXIT_CODE_RESTART}", file=sys.stderr)
            return EXIT_CODE_RESTART
            
    logging.shutdown()
    return 0

if __name__ == "__main__":
    exit_code = 0
    try:
        exit_code = asyncio.run(main())
    except KeyboardInterrupt:
        exit_code = 0
    sys.exit(exit_code)
