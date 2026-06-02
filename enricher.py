"""
Enricher - find one decision maker email per company.

Waterfall per company:
  1. Hunter.io domain-search (executive first, then any named contact)
  2. Email guessing (pattern generation + SMTP RCPT-TO verify) — fallback when Hunter finds nothing
  3. Mark no_match if both fail

Parallel execution: ThreadPoolExecutor(max_workers=4) — 4x throughput vs sequential.
HunterRotator is thread-safe via a Lock.
"""
import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from config import HUNTER_API_KEYS
from db import get_all_leads, update_lead, get_stats

logger = logging.getLogger(__name__)
_print_lock = threading.Lock()


def _log(msg):
    with _print_lock:
        print(msg)


# ============================================================
#  HUNTER KEY ROTATOR  (thread-safe)
# ============================================================
class HunterRotator:
    def __init__(self, keys):
        self.keys = list(keys)
        self.exhausted = set()
        self.used = {k: 0 for k in keys}
        self._lock = threading.Lock()

    def get_key(self):
        with self._lock:
            for k in self.keys:
                if k not in self.exhausted:
                    return k
        return None

    def mark_used(self, key):
        with self._lock:
            self.used[key] = self.used.get(key, 0) + 1

    def mark_exhausted(self, key):
        with self._lock:
            self.exhausted.add(key)

    def has_credits(self):
        with self._lock:
            return bool(self.keys) and len(self.exhausted) < len(self.keys)

    def summary(self):
        if not self.keys:
            return
        total = sum(self.used.values())
        print("  Hunter credits used this run: " + str(total))
        for i, k in enumerate(self.keys):
            label = k[:8] + "..." + k[-4:]
            status = "EXHAUSTED" if k in self.exhausted else "active"
            print("    Key " + str(i + 1) + " (" + label + "): " + str(self.used.get(k, 0)) + " used [" + status + "]")


hunter = HunterRotator(HUNTER_API_KEYS)


# ============================================================
#  DOMAIN HELPERS
# ============================================================
_SKIP_DOMAINS = {
    "google.", "linkedin.", "facebook.", "twitter.", "youtube.",
    "wikipedia.", "instagram.", "glassdoor.", "indeed.", "yelp.",
    "bloomberg.", "crunchbase.", "x.com", "tiktok.", "duckduckgo.",
    "amazon.", "reddit.", "github.", "lever.co", "greenhouse.io",
    "workday.com", "ashbyhq.com", "jobs.",
}


def extract_domain(url):
    if not url:
        return ""
    url = url.lower().strip()
    for prefix in ("https://", "http://", "www."):
        if url.startswith(prefix):
            url = url[len(prefix):]
    return url.split("/")[0].split("?")[0]


def find_domain(company_name, retries=3):
    """DDG text search with exponential backoff retry."""
    from ddgs import DDGS
    for attempt in range(retries):
        try:
            results = DDGS().text(company_name + " official website", max_results=6)
            for r in results:
                domain = extract_domain(r.get("href", ""))
                if domain and not any(s in domain for s in _SKIP_DOMAINS):
                    return domain
            return ""
        except Exception as e:
            if attempt < retries - 1:
                wait = (2 ** attempt) + random.uniform(0.5, 1.5)
                logger.warning("DDG retry %d/%d for '%s': %s — waiting %.1fs",
                               attempt + 1, retries, company_name, str(e)[:50], wait)
                time.sleep(wait)
            else:
                logger.error("DDG failed for '%s': %s", company_name, str(e)[:60])
    return ""


# ============================================================
#  HUNTER SEARCH
# ============================================================
def hunter_search(domain):
    """
    1 credit per company. Returns best available contact dict or None.
    Priority: Hunter-tagged executive → any named personal email.
    """
    key = hunter.get_key()
    if not key:
        return None

    def _fetch(api_key):
        return requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": api_key, "limit": 10},
            timeout=30,
        )

    try:
        resp = _fetch(key)
        if resp.status_code in (402, 429):
            hunter.mark_exhausted(key)
            key = hunter.get_key()
            if not key:
                return None
            resp = _fetch(key)
            if resp.status_code in (402, 429):
                hunter.mark_exhausted(key)
                return None

        if resp.status_code != 200:
            return None

        hunter.mark_used(key)
        emails = resp.json().get("data", {}).get("emails", [])

        executive = None
        fallback = None

        for person in emails:
            email = (person.get("value") or "").strip()
            if not email or person.get("type") == "generic":
                continue
            first = (person.get("first_name") or "").strip()
            last = (person.get("last_name") or "").strip()
            name = (first + " " + last).strip() or first
            if not name:
                continue

            result = {
                "name":     name,
                "first":    first,
                "last":     last,
                "title":    (person.get("position") or "").strip(),
                "email":    email,
                "linkedin": person.get("linkedin") or "",
            }

            if executive is None and (person.get("seniority") or "").lower() == "executive":
                executive = result
            if fallback is None:
                fallback = result

        return executive or fallback

    except Exception as e:
        logger.error("Hunter error for %s: %s", domain, str(e)[:60])
        return None


# ============================================================
#  MAIN ENRICHER — single lead
# ============================================================
def enrich_lead(lead):
    """
    Process one lead. Returns: 'enriched' | 'no_domain' | 'no_exec' | 'no_credits'
    """
    company = (lead.get("company_name") or "").strip()
    if not company:
        update_lead(lead["id"], status="no_match")
        return "no_domain"

    # ── Domain resolution ──────────────────────────────────────
    domain = (lead.get("company_domain") or "").strip()
    if not domain:
        website = (lead.get("company_website") or "").strip()
        if website:
            domain = extract_domain(website)
    if not domain:
        domain = find_domain(company)

    if not domain:
        _log("    [" + company + "] no domain found → no_match")
        update_lead(lead["id"], status="no_match")
        return "no_domain"

    # ── Hunter ────────────────────────────────────────────────
    if not hunter.has_credits():
        return "no_credits"

    result = hunter_search(domain)

    if result:
        _log("    [" + company + "] Hunter → " + result["name"] + " <" + result["email"] + ">")
        update_lead(
            lead["id"],
            company_domain=domain,
            decision_maker_name=result["name"],
            decision_maker_title=result["title"],
            decision_maker_email=result["email"],
            decision_maker_linkedin=result["linkedin"],
            status="enriched",
        )
        return "enriched"

    # ── Email guessing fallback ───────────────────────────────
    # Hunter returned nothing — try pattern generation + SMTP verify
    # We need a name to guess patterns. Use existing DM name in DB if set.
    dm_name = (lead.get("decision_maker_name") or "").strip()
    first, last = "", ""
    if dm_name:
        parts = dm_name.split()
        first = parts[0] if parts else ""
        last = parts[-1] if len(parts) > 1 else ""

    if first and domain:
        try:
            from email_guesser import guess_and_verify
            guessed_email, method = guess_and_verify(first, last, domain)
            if guessed_email:
                _log("    [" + company + "] Guessed (" + method + ") → " + guessed_email)
                update_lead(
                    lead["id"],
                    company_domain=domain,
                    decision_maker_email=guessed_email,
                    status="enriched",
                )
                return "enriched"
        except Exception as e:
            logger.warning("Email guesser failed for %s: %s", company, str(e)[:60])

    _log("    [" + company + "] no contact found → no_match")
    update_lead(lead["id"], company_domain=domain, status="no_match")
    return "no_exec"


# ============================================================
#  RUN ENRICHER  (parallel)
# ============================================================
def run_enricher(max_workers=4):
    print("")
    print("=" * 60)
    print("  ENRICHER — Hunter + email guessing | workers=" + str(max_workers))
    print("=" * 60)
    print("")

    if not HUNTER_API_KEYS:
        print("  WARNING: No HUNTER_API_KEY in .env — skipping Hunter, using email guessing only")

    all_leads = get_all_leads()
    needs_email = [
        l for l in all_leads
        if not (l.get("decision_maker_email") or "").strip()
        and (l.get("status") or "") not in ("sent", "opened", "replied")
    ]

    # One representative lead per company
    seen = {}
    to_enrich = []
    for l in needs_email:
        key = (l.get("company_name") or "").lower().strip()
        if key not in seen:
            seen[key] = True
            to_enrich.append(l)

    total = len(to_enrich)
    print("  Leads needing email: " + str(len(needs_email)))
    print("  Unique companies:    " + str(total))
    print("")

    if not to_enrich:
        print("  Nothing to do.")
        get_stats()
        return 0

    enriched = 0
    no_domain = 0
    no_exec = 0
    counter = [0]
    counter_lock = threading.Lock()
    stop_flag = threading.Event()

    def _process(lead):
        if stop_flag.is_set():
            return "skipped"
        result = enrich_lead(lead)
        with counter_lock:
            counter[0] += 1
            n = counter[0]
        company = (lead.get("company_name") or "")[:40]
        _log("[" + str(n) + "/" + str(total) + "] " + company + " → " + result)
        if result == "no_credits":
            stop_flag.set()
        time.sleep(random.uniform(0.8, 2.0))
        return result

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_process, lead): lead for lead in to_enrich}
            for fut in as_completed(futures):
                try:
                    res = fut.result()
                    if res == "enriched":
                        enriched += 1
                    elif res == "no_domain":
                        no_domain += 1
                    elif res == "no_exec":
                        no_exec += 1
                    elif res == "no_credits":
                        pass  # stop_flag already set
                except Exception as e:
                    logger.error("Enricher worker error: %s", e)
    except KeyboardInterrupt:
        print("\n  Stopped by user — all saved data is safe.")

    print("")
    print("=" * 60)
    print("  DONE:")
    print("    Enriched (email found): " + str(enriched))
    print("    No domain found:        " + str(no_domain))
    print("    No contact found:       " + str(no_exec))
    hunter.summary()
    print("=" * 60)
    get_stats()
    return enriched


if __name__ == "__main__":
    run_enricher()
