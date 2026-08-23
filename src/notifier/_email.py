"""Email notification channel via SMTP."""

import logging
import smtplib
from email.mime.text import MIMEText

from config import (
    SMTP_HOST,
    SMTP_PORT,
    SMTP_FROM,
    SMTP_TO,
    SMTP_USERNAME,
    SMTP_PASSWORD,
    SMTP_TIMEOUT,
)
from notifier._types import Level, NotificationContext, format_context_inline

_LEVEL_PREFIX: dict[Level, str] = {
    Level.INFO: "[INFO]",
    Level.WARNING: "[WARNING]",
    Level.CRITICAL: "[CRITICAL]",
}


def is_configured() -> bool:
    return bool(SMTP_HOST and SMTP_TO)


def send(
    message: str,
    level: Level,
    context: NotificationContext | None,
    hostname: str,
    timestamp: str,
) -> bool:
    """Send an email notification via SMTP. Never raises."""
    prefix = _LEVEL_PREFIX.get(level, "")
    subject = f"{prefix} Vigil -- {hostname}"

    body = f"{message}\n\n{hostname} -- {timestamp}"
    if context is not None:
        ctx_str = format_context_inline(context)
        if ctx_str:
            body += f"\n{ctx_str}"

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM or f"vigil@{hostname}"
    msg["To"] = SMTP_TO

    try:
        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT)
            server.starttls()

        if SMTP_USERNAME:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)

        server.send_message(msg)
        server.quit()
        logging.debug("Email: notification envoyee a %s", SMTP_TO)
        return True
    except smtplib.SMTPAuthenticationError:
        logging.warning("Email: authentification echouee")
    except (smtplib.SMTPException, ConnectionError, TimeoutError) as e:
        logging.warning("Email: erreur -- %s", e)
    except Exception as e:
        logging.warning("Email: erreur inattendue -- %s", e)
    return False
