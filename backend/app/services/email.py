"""Outgoing e-mail. SMTP when configured; otherwise messages are only logged (development) and kept in OUTBOX (tests)."""
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings

log = logging.getLogger("recall.email")
OUTBOX: list[dict] = []  # inspected by tests; capped so it cannot grow without bound
settings = get_settings()


def send_email(to: str, subject: str, body: str) -> None:
    OUTBOX.append({"to": to, "subject": subject, "body": body})
    del OUTBOX[:-200]
    if not settings.smtp_host:
        # No mail server: in development the body (which contains the link) is logged so you can click it.
        log.info("EMAIL (not sent, SMTP not configured) to=%s subject=%s%s", to, subject, "" if settings.is_production else f"\n{body}")
        return
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.email_from, to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
            s.starttls()
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
    except Exception:  # a mail outage must not break the request (responses never reveal whether mail was sent)
        log.exception("failed to send e-mail to %s", to)
