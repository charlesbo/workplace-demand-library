"""Logging module with loguru backend and rich terminal output.

Provides structured logging to both terminal (with rich formatting)
and rotating log files. Designed to be configured once via setup_logging()
and then used throughout the application via get_logger().

Usage::

    from src.utils.logger import get_logger, setup_logging
    setup_logging(log_level="DEBUG", log_dir="logs")
    logger = get_logger(__name__)
    logger.info("Starting scraper...")
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from loguru import logger as _loguru_logger
from rich.console import Console
from rich.text import Text

_console = Console(stderr=True)
_initialized = False

_LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {extra[module_name]} | {message}"


def _rich_sink(message: Any) -> None:
    """Write a log record to the terminal using rich formatting.

    Args:
        message: The loguru message object containing the log record.
    """
    record = message.record
    level = record["level"].name
    style_map = {
        "TRACE": "dim",
        "DEBUG": "dim cyan",
        "INFO": "green",
        "SUCCESS": "bold green",
        "WARNING": "bold yellow",
        "ERROR": "bold red",
        "CRITICAL": "bold white on red",
    }
    style = style_map.get(level, "")

    text = Text.from_ansi(str(message).rstrip())
    text.stylize(style)
    _console.print(text)


def highlight_important(message: str, importance: int = 0) -> str:
    """Highlight a notification message for high-importance demands.

    Prints a rich-formatted panel to the terminal when importance > 8,
    and returns the message unchanged for normal loguru logging.

    Args:
        message: The notification message to highlight.
        importance: Importance score (0-10). Values > 8 trigger rich highlighting.

    Returns:
        The original message string (unmodified).
    """
    if importance > 8:
        from rich.panel import Panel

        _console.print(
            Panel(
                f"[bold red]⚠ HIGH IMPORTANCE ({importance})[/bold red]\n{message}",
                border_style="red",
                title="🔔 Important Notification",
            )
        )
    return message


def setup_logging(log_level: str = "INFO", log_dir: str = "logs") -> None:
    """Initialize the logging system with terminal and file sinks.

    Removes any previously configured loguru handlers and sets up:
    - A rich-formatted terminal sink on stderr.
    - A rotating file sink at ``<log_dir>/scraper.log``.

    This function is idempotent; calling it multiple times simply
    reconfigures the handlers.

    Args:
        log_level: Minimum log level (e.g. ``"DEBUG"``, ``"INFO"``).
        log_dir: Directory for log files. Created if it does not exist.
    """
    global _initialized

    _loguru_logger.remove()

    # Terminal sink via rich
    _loguru_logger.add(
        _rich_sink,
        level=log_level.upper(),
        format=_LOG_FORMAT,
        colorize=False,
    )

    # Rotating file sink
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    _loguru_logger.add(
        str(log_path / "scraper.log"),
        level=log_level.upper(),
        format=_LOG_FORMAT,
        rotation="10 MB",
        retention=5,
        encoding="utf-8",
    )

    _initialized = True
    _loguru_logger.bind(module_name="logger").debug(
        "Logging initialised (level={}, dir={})", log_level, log_dir
    )


def get_logger(name: str) -> Any:
    """Return a logger instance bound to the given module name.

    If :func:`setup_logging` has not been called yet, a default
    configuration (level ``INFO``, directory ``logs``) is applied
    automatically so that logging always works out of the box.

    Args:
        name: Typically ``__name__`` of the calling module.

    Returns:
        A loguru logger instance with the *module_name* extra field set.
    """
    if not _initialized:
        setup_logging()
    return _loguru_logger.bind(module_name=name)
