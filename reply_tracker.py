"""
IMAP Reply Tracker for Omnithrive.

Polls the Omnithrive inbox every N minutes, finds replies to sent emails,
and marks the corresponding lead as "replied" in the database.

Matching strategy (in order of priority):
1. In-Reply-To / References header matches a stored Message-ID
2. Sender email matches decision_maker_email for a lead with status="sent"

Run standalone: python reply_tracker.py
Or imported and started as a background thread by server.py.
"""
import email
import imaplib
import logging
import threading
import time

from config import IMAP_HOST, IMAP_PORT, IMAP_USER, IMAP_PASS
from db import get_lead_by_message_id, get_lead_by_email, mark_replied

POLL_INTERVAL = 300  # seconds between inbox checks
logger = logging.getLogger(__name__)


def _get_header(msg, name: str) -> str:
    val = msg.get(name, "")
    return val.strip() if val else ""


def _extract_message_ids(header_value: str) -> list:
    """Extract all <msgid> tokens from an In-Reply-To or References header."""
    import re
    return re.findall(r"<[^>]+>", header_value)


def check_inbox_once():
    """Connect to IMAP, scan UNSEEN messages, and mark any replies."""
    if not IMAP_USER or not IMAP_PASS:
        logger.warning("IMAP credentials not configured — skipping reply check.")
        return

    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        mail.login(IMAP_USER, IMAP_PASS)
        mail.select("INBOX")

        # Search all unseen messages
        status, data = mail.search(None, "UNSEEN")
        if status != "OK" or not data or not data[0]:
            mail.logout()
            return

        msg_ids = data[0].split()
        logger.info("Reply tracker: %d unseen message(s) to check.", len(msg_ids))

        for num in msg_ids:
            try:
                status, msg_data = mail.fetch(num, "(RFC822)")
                if status != "OK":
                    continue

                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                in_reply_to = _get_header(msg, "In-Reply-To")
                references = _get_header(msg, "References")
                from_header = _get_header(msg, "From")

                lead = None

                # Strategy 1: match by In-Reply-To or References
                candidate_ids = _extract_message_ids(in_reply_to)
                candidate_ids += _extract_message_ids(references)
                for mid in candidate_ids:
                    lead = get_lead_by_message_id(mid)
                    if lead:
                        break

                # Strategy 2: match by sender email address
                if not lead:
                    import re
                    match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", from_header)
                    if match:
                        sender_email = match.group(0).lower()
                        lead = get_lead_by_email(sender_email)

                if lead and lead["status"] != "replied":
                    mark_replied(lead["id"])
                    logger.info(
                        "Reply detected: lead_id=%d company=%s",
                        lead["id"], lead.get("company_name", "")
                    )

            except Exception as e:
                logger.error("Error processing message %s: %s", num, e)

        mail.logout()

    except imaplib.IMAP4.error as e:
        logger.error("IMAP error: %s", e)
    except Exception as e:
        logger.error("Unexpected error in reply tracker: %s", e)


def _run_loop():
    logger.info("Reply tracker loop started (interval=%ds).", POLL_INTERVAL)
    while True:
        try:
            check_inbox_once()
        except Exception as e:
            logger.error("Reply tracker loop error: %s", e)
        time.sleep(POLL_INTERVAL)


def start_background_thread():
    """Start the IMAP poll loop as a daemon thread."""
    t = threading.Thread(target=_run_loop, daemon=True, name="ReplyTracker")
    t.start()
    return t


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
    logger.info("Running one-shot inbox check...")
    check_inbox_once()
    logger.info("Done.")
