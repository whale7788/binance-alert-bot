from logging.handlers import TimedRotatingFileHandler

from binance_alert_bot.main import setup_logging


def test_setup_logging_uses_daily_rotating_file_handler(tmp_path) -> None:
    log_file = tmp_path / "monitor.log"

    setup_logging(log_file, "INFO")

    handlers = __import__("logging").getLogger().handlers
    rotating_handlers = [handler for handler in handlers if isinstance(handler, TimedRotatingFileHandler)]

    assert rotating_handlers
    file_handler = rotating_handlers[0]
    assert file_handler.backupCount == 14
    assert file_handler.when == "MIDNIGHT"
