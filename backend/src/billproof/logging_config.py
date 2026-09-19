import logging

from billproof.config import get_settings

_SENSITIVE_KEYS = {
    "token",
    "access_token",
    "authorization",
    "body",
    "extracted_text",
    "raw_text",
    "protected_args",
}


class RedactingFilter(logging.Filter):
    """Drops log records that carry a sensitive field name in their message args.

    Belt-and-suspenders: the real control is that services never pass this data
    to the logger at all (invariant 9). This filter is the backstop.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage().lower()
        return not any(key in msg for key in _SENSITIVE_KEYS)


def configure_logging() -> None:
    settings = get_settings()
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    logging.basicConfig(level=settings.log_level, handlers=[handler], force=True)
