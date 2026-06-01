"""
Deliverability-Optimised Email Sender for Omnithrive.

Strategy:
- multipart/alternative with plain text as the primary part
- Ghost HTML part: zero CSS, zero styling — raw text + invisible 1x1 tracking pixel
- Plain-text signature only: "Omnithrive"
- Message-ID stored to enable reply tracking
"""
import smtplib
import ssl
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid

from config import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS,
    FROM_EMAIL, FROM_NAME, BASE_URL,
)
from db import mark_sent


SIGNATURE = ""


def _build_ghost_html(plain_body: str, lead_id: int) -> str:
    """
    Minimal ghost HTML: no CSS, no styling — just raw text and tracking pixel.
    The pixel URL triggers the open-tracking endpoint when loaded.
    """
    pixel_url = BASE_URL.rstrip("/") + "/api/track/open/" + str(lead_id)
    escaped = plain_body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    lines = escaped.split("\n")
    html_lines = "<br>\n".join(lines)
    return (
        "<html><body>"
        + html_lines
        + '<img src="' + pixel_url + '" width="1" height="1" alt="" '
        + 'style="display:none;width:1px;height:1px;border:0;" />'
        + "</body></html>"
    )


def send_email(lead: dict) -> str:
    """
    Send the drafted email for a lead via SMTP.
    Returns the Message-ID string on success, raises on failure.
    """
    to_email = (lead.get("decision_maker_email") or "").strip()
    subject = (lead.get("draft_subject") or "").strip()
    body = (lead.get("draft_email") or "").strip()

    if not to_email:
        raise ValueError("No recipient email for lead id=" + str(lead["id"]))
    if not subject or not body:
        raise ValueError("Missing subject or body for lead id=" + str(lead["id"]))
    if not SMTP_USER or not SMTP_PASS:
        raise RuntimeError("SMTP credentials not configured (SMTP_USER / SMTP_PASS missing)")

    plain_body = body + SIGNATURE

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = FROM_NAME + " <" + FROM_EMAIL + ">"
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=True)

    message_id = make_msgid(domain=FROM_EMAIL.split("@")[-1] if "@" in FROM_EMAIL else "localhost")
    msg["Message-ID"] = message_id

    # Order matters: email clients prefer the LAST alternative they can render.
    # We attach plain first, HTML second so HTML-capable clients render the ghost
    # HTML (which looks identical to the plain text) and load the tracking pixel.
    part_plain = MIMEText(plain_body, "plain", "utf-8")
    part_html = MIMEText(_build_ghost_html(plain_body, lead["id"]), "html", "utf-8")

    msg.attach(part_plain)
    msg.attach(part_html)

    context = ssl.create_default_context()
    last_err = None
    for attempt in range(1, 4):
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.ehlo()
                server.starttls(context=context)
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(FROM_EMAIL, [to_email], msg.as_string())
            break
        except (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused,
                smtplib.SMTPSenderRefused, smtplib.SMTPDataError) as e:
            # Non-retryable — auth/recipient errors won't resolve on retry
            raise RuntimeError("SMTP permanent error: " + str(e)) from e
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError,
                ConnectionError, OSError) as e:
            last_err = e
            if attempt < 3:
                time.sleep(2 ** attempt)
    else:
        raise RuntimeError("SMTP failed after 3 attempts: " + str(last_err))

    try:
        mark_sent(lead["id"], message_id)
    except Exception as db_err:
        # Email already sent — log the DB failure but don't raise,
        # otherwise the caller sees a failure and may retry sending.
        import logging
        logging.getLogger(__name__).error(
            "mark_sent failed for lead_id=%s (email WAS sent): %s",
            lead.get("id"), db_err
        )
    return message_id
