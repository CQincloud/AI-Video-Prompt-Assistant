"""Application logging configuration."""

import re
import sys

from loguru import logger

from app.config import config


SECRET_PATTERNS = [
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?key(?:[_-]?secret)?|secret|token|password|credential)\b\s*[:=]\s*[^,\s;]+"
    ),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b1[3-9]\d{9}\b"),
    re.compile(r"(?i)\b(code|sms[_-]?code|verification[_-]?code|otp)\b\s*[:=]\s*\d{4,8}"),
]


def _redact_message(message: str) -> str:
    redacted = message
    redacted = SECRET_PATTERNS[0].sub(lambda match: f"{match.group(1)}=<redacted>", redacted)
    redacted = SECRET_PATTERNS[1].sub("sk-<redacted>", redacted)
    redacted = SECRET_PATTERNS[2].sub(
        lambda match: f"{match.group(0)[:3]}****{match.group(0)[-4:]}",
        redacted,
    )
    redacted = SECRET_PATTERNS[3].sub(lambda match: f"{match.group(1)}=<redacted>", redacted)
    return redacted


def _prepare_record(record) -> str:
    record["extra"]["redacted_message"] = _redact_message(record["message"])
    record["extra"]["redacted_exception"] = ""

    if record["exception"] and not config.debug:
        record["extra"]["redacted_exception"] = (
            f"\n{record['exception'].type.__name__}: <redacted>"
        )
        return "{extra[redacted_exception]}"

    if record["exception"]:
        return "\n{exception}"

    return "\n"


def _console_format(record):
    exception_format = _prepare_record(record)
    return (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{module}</cyan>.<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{extra[redacted_message]}</level>"
        f"{exception_format}"
    )


def _file_format(record):
    exception_format = _prepare_record(record)
    return (
        "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
        "{module}.{function}:{line} | {extra[redacted_message]}"
        f"{exception_format}"
    )


def setup_logger():
    """Configure console and rotating file logs."""
    logger.remove()

    logger.add(
        sys.stdout,
        format=_console_format,
        level="DEBUG" if config.debug else "INFO",
        colorize=True,
        backtrace=config.debug,
        diagnose=config.debug,
    )

    logger.add(
        "logs/app_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="7 days",
        compression="zip",
        encoding="utf-8",
        enqueue=True,
        backtrace=config.debug,
        diagnose=config.debug,
        level="INFO",
        format=_file_format,
    )


setup_logger()
