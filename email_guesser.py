"""
Email guesser — generates B2B email patterns for a known name+domain and
verifies them via SMTP RCPT-TO. Used as a Hunter.io fallback in enricher.py.
"""
import dns.resolver
import logging
import random
import re
import smtplib
import socket
import time

logger = logging.getLogger(__name__)

_SMTP_TIMEOUT = 10
_FROM_EMAIL = "verify@leadcheck.local"
_SMTP_DELAY = (0.4, 1.2)
_mx_cache = {}


# ── Pattern generation ───────────────────────────────────────────────────────

def _generate_patterns(first_name: str, last_name: str, domain: str) -> list:
    first = re.sub(r"[^a-z]", "", first_name.lower())
    last = re.sub(r"[^a-z]", "", last_name.lower())
    if not first or not domain:
        return []
    if not last:
        return [first + "@" + domain]
    i = first[0]
    return [
        first + "." + last + "@" + domain,   # john.smith@
        i + last + "@" + domain,              # jsmith@
        first + "@" + domain,                 # john@
        first + last + "@" + domain,          # johnsmith@
        last + "." + first + "@" + domain,   # smith.john@
        first + "_" + last + "@" + domain,   # john_smith@
        i + "." + last + "@" + domain,        # j.smith@
        first + last[0] + "@" + domain,       # johns@
    ]


# ── MX lookup ────────────────────────────────────────────────────────────────

def _get_mx_host(domain: str) -> str:
    if domain in _mx_cache:
        return _mx_cache[domain]
    try:
        answers = dns.resolver.resolve(domain, "MX")
        mx = str(sorted(answers, key=lambda r: r.preference)[0].exchange).rstrip(".")
        _mx_cache[domain] = mx
        return mx
    except Exception:
        _mx_cache[domain] = ""
        return ""


# ── SMTP RCPT-TO check ───────────────────────────────────────────────────────

def _smtp_check(email: str, mx_host: str):
    """Returns True (valid), False (rejected), None (inconclusive)."""
    if not mx_host:
        return None
    try:
        with smtplib.SMTP(timeout=_SMTP_TIMEOUT) as s:
            s.connect(mx_host, 25)
            s.helo(socket.getfqdn())
            s.mail(_FROM_EMAIL)
            code, _ = s.rcpt(email)
            s.quit()
            if code == 250:
                return True
            if code in (550, 551, 552, 553, 554):
                return False
            return None
    except Exception:
        return None


# ── Public API ───────────────────────────────────────────────────────────────

def guess_and_verify(first_name: str, last_name: str, domain: str) -> tuple:
    """
    Generate email patterns for first+last@domain and verify via SMTP.

    Returns (email, method) where method is:
        "guessed_verified"  — SMTP returned 250 OK
        "guessed_catchall"  — SMTP inconclusive (catch-all), best-guess pattern returned
        "no_guess"          — all patterns rejected, no MX, or missing inputs
    """
    domain = (domain or "").strip().lower()
    if domain.startswith("www."):
        domain = domain[4:]

    patterns = _generate_patterns(first_name or "", last_name or "", domain)
    if not patterns:
        return "", "no_guess"

    mx = _get_mx_host(domain)
    if not mx:
        logger.debug("No MX for %s — returning best-guess without SMTP", domain)
        return patterns[0], "guessed_catchall"

    inconclusive = []
    for email in patterns:
        result = _smtp_check(email, mx)
        if result is True:
            logger.info("Email guessed+verified: %s", email)
            return email, "guessed_verified"
        if result is False:
            pass  # rejected — try next
        else:
            inconclusive.append(email)
        time.sleep(random.uniform(*_SMTP_DELAY))

    if inconclusive:
        best = inconclusive[0]
        logger.info("Email guessed (catch-all domain): %s", best)
        return best, "guessed_catchall"

    return "", "no_guess"
