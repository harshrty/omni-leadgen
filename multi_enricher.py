"""
Email enricher — Hunter.io only (other providers paused).

Usage:
  python multi_enricher.py                 # enrich all scraped leads
  python multi_enricher.py --limit 50      # enrich 50 leads max
  python multi_enricher.py --status        # show credit status

Add API key to .env:
  HUNTER_API_KEY=xxx
"""
import os
import sys
import time
import random
import requests
from dotenv import load_dotenv

from db import get_leads_by_status, update_lead, get_stats, get_all_leads

load_dotenv()

# ── TARGET TITLES ───────────────────────────────────────────────────────────
_TARGET_TITLES = [
    "cto", "ceo", "coo", "cfo", "cpo", "cmo", "ciso",
    "chief", "founder", "co-founder", "president",
    "vp", "vice president", "head of", "director", "partner", "owner",
    "general manager", "managing director", "managing partner",
]
_EXACT_TITLES = {"cto", "ceo", "coo", "cfo", "cpo", "cmo", "ciso", "vp", "svp", "evp"}


def _title_is_target(position):
    pos = (position or "").lower().strip()
    if not pos:
        return False
    words = set(pos.replace(",", " ").replace("-", " ").split())
    if words & _EXACT_TITLES:
        return True
    return any(t in pos for t in _TARGET_TITLES)


# ── PROVIDER BASE ───────────────────────────────────────────────────────────

class Provider:
    """Base class for email finder providers."""
    name = "base"
    exhausted = False

    def search(self, domain, company_name=""):
        """Search for decision maker. Returns dict or None."""
        raise NotImplementedError

    def is_available(self):
        return not self.exhausted

    def status(self):
        return "exhausted" if self.exhausted else "active"


# ── HUNTER.IO ───────────────────────────────────────────────────────────────

class HunterProvider(Provider):
    name = "Hunter.io"

    def __init__(self):
        self.keys = []
        # Support multiple keys
        for i in range(1, 21):
            k = os.getenv("HUNTER_API_KEY_" + str(i), "")
            if k:
                self.keys.append(k)
        single = os.getenv("HUNTER_API_KEY", "")
        if single and single not in self.keys:
            self.keys.insert(0, single)
        self.exhausted_keys = set()
        self.used = 0

    def is_available(self):
        return bool(self.keys) and len(self.exhausted_keys) < len(self.keys)

    def _get_key(self):
        for k in self.keys:
            if k not in self.exhausted_keys:
                return k
        return None

    def search(self, domain, company_name=""):
        key = self._get_key()
        if not key:
            self.exhausted = True
            return None
        try:
            resp = requests.get(
                "https://api.hunter.io/v2/domain-search",
                params={"domain": domain, "api_key": key, "limit": 10},
                timeout=15,
            )
            if resp.status_code in (402, 429):
                self.exhausted_keys.add(key)
                if not self._get_key():
                    self.exhausted = True
                return None
            if resp.status_code != 200:
                return None
            self.used += 1

            title_match = None
            seniority_match = None

            for person in resp.json().get("data", {}).get("emails", []):
                email = (person.get("value") or "").strip()
                if not email or person.get("type") == "generic":
                    continue
                first = (person.get("first_name") or "").strip()
                last = (person.get("last_name") or "").strip()
                name = (first + " " + last).strip() or first
                if not name:
                    continue
                position = (person.get("position") or "").strip()
                seniority = (person.get("seniority") or "").strip().lower()

                result = {"name": name, "title": position, "email": email}
                if title_match is None and _title_is_target(position):
                    title_match = result
                if seniority_match is None and seniority == "executive":
                    seniority_match = result

            return title_match or seniority_match
        except Exception:
            pass
        return None

    def status(self):
        if not self.keys:
            return "no keys"
        return f"{len(self.keys) - len(self.exhausted_keys)}/{len(self.keys)} keys active, {self.used} used"


# ── SNOV.IO ─────────────────────────────────────────────────────────────────

class SnovProvider(Provider):
    name = "Snov.io"

    def __init__(self):
        self.client_id = os.getenv("SNOV_CLIENT_ID", "")
        self.client_secret = os.getenv("SNOV_CLIENT_SECRET", "")
        self.token = ""
        self.used = 0

    def is_available(self):
        return bool(self.client_id and self.client_secret) and not self.exhausted

    def _get_token(self):
        if self.token:
            return self.token
        try:
            resp = requests.post(
                "https://api.snov.io/v1/oauth/access_token",
                json={"grant_type": "client_credentials",
                      "client_id": self.client_id,
                      "client_secret": self.client_secret},
                timeout=15,
            )
            self.token = resp.json().get("access_token", "")
            return self.token
        except Exception:
            return ""

    def search(self, domain, company_name=""):
        token = self._get_token()
        if not token:
            return None
        try:
            resp = requests.post(
                "https://api.snov.io/v2/domain-emails-with-info",
                json={"domain": domain, "type": "all", "limit": 5},
                headers={"Authorization": "Bearer " + token},
                timeout=15,
            )
            if resp.status_code in (402, 429):
                self.exhausted = True
                return None
            if resp.status_code != 200:
                return None
            self.used += 1
            for person in resp.json().get("data", []):
                email = (person.get("email") or "").strip()
                if not email:
                    continue
                position = (person.get("position") or "").strip()
                first = (person.get("firstName") or "").strip()
                last = (person.get("lastName") or "").strip()
                name = (first + " " + last).strip()
                if _title_is_target(position) and name and email:
                    return {"name": name, "title": position, "email": email}
        except Exception:
            pass
        return None

    def status(self):
        if not self.client_id:
            return "no keys"
        return f"{'exhausted' if self.exhausted else 'active'}, {self.used} used"


# ── SKRAPP.IO ───────────────────────────────────────────────────────────────

class SkrappProvider(Provider):
    name = "Skrapp.io"

    def __init__(self):
        self.api_key = os.getenv("SKRAPP_API_KEY", "")
        self.used = 0

    def is_available(self):
        return bool(self.api_key) and not self.exhausted

    def search(self, domain, company_name=""):
        if not self.api_key:
            return None
        try:
            resp = requests.get(
                "https://api.skrapp.io/api/v2/find",
                params={"domain": domain},
                headers={"X-Access-Key": self.api_key, "Content-Type": "application/json"},
                timeout=15,
            )
            if resp.status_code in (402, 429, 403):
                self.exhausted = True
                return None
            if resp.status_code != 200:
                return None
            self.used += 1
            for person in resp.json().get("results", []):
                email = (person.get("email") or "").strip()
                if not email:
                    continue
                position = (person.get("title") or person.get("position") or "").strip()
                name = (person.get("name") or "").strip()
                if not name:
                    first = (person.get("first_name") or "").strip()
                    last = (person.get("last_name") or "").strip()
                    name = (first + " " + last).strip()
                if _title_is_target(position) and name and email:
                    return {"name": name, "title": position, "email": email}
        except Exception:
            pass
        return None

    def status(self):
        if not self.api_key:
            return "no keys"
        return f"{'exhausted' if self.exhausted else 'active'}, {self.used} used"


# ── GETPROSPECT ─────────────────────────────────────────────────────────────

class GetProspectProvider(Provider):
    name = "GetProspect"

    def __init__(self):
        self.api_key = os.getenv("GETPROSPECT_API_KEY", "")
        self.used = 0

    def is_available(self):
        return bool(self.api_key) and not self.exhausted

    def search(self, domain, company_name=""):
        if not self.api_key:
            return None
        try:
            resp = requests.post(
                "https://api.getprospect.com/public/v1/email/find",
                json={"domain": domain},
                headers={"apiKey": self.api_key, "Content-Type": "application/json"},
                timeout=15,
            )
            if resp.status_code in (402, 429, 403):
                self.exhausted = True
                return None
            if resp.status_code != 200:
                return None
            self.used += 1
            data = resp.json()
            email = (data.get("email") or "").strip()
            name = (data.get("name") or "").strip()
            position = (data.get("position") or "").strip()
            if email and name:
                return {"name": name, "title": position, "email": email}
        except Exception:
            pass
        return None

    def status(self):
        if not self.api_key:
            return "no keys"
        return f"{'exhausted' if self.exhausted else 'active'}, {self.used} used"


# ── TOMBA.IO ────────────────────────────────────────────────────────────────

class TombaProvider(Provider):
    name = "Tomba.io"

    def __init__(self):
        self.api_key = os.getenv("TOMBA_API_KEY", "")
        self.secret = os.getenv("TOMBA_SECRET", "")
        self.used = 0

    def is_available(self):
        return bool(self.api_key and self.secret) and not self.exhausted

    def search(self, domain, company_name=""):
        if not self.api_key:
            return None
        try:
            resp = requests.get(
                "https://api.tomba.io/v1/domain-search",
                params={"domain": domain},
                headers={"X-Tomba-Key": self.api_key, "X-Tomba-Secret": self.secret},
                timeout=15,
            )
            if resp.status_code in (402, 429, 403):
                self.exhausted = True
                return None
            if resp.status_code != 200:
                return None
            self.used += 1
            for person in resp.json().get("data", {}).get("emails", []):
                email = (person.get("email") or "").strip()
                if not email:
                    continue
                position = (person.get("position") or "").strip()
                first = (person.get("first_name") or "").strip()
                last = (person.get("last_name") or "").strip()
                name = (first + " " + last).strip()
                if _title_is_target(position) and name and email:
                    return {"name": name, "title": position, "email": email}
        except Exception:
            pass
        return None

    def status(self):
        if not self.api_key:
            return "no keys"
        return f"{'exhausted' if self.exhausted else 'active'}, {self.used} used"


# ── MINELEAD.IO ─────────────────────────────────────────────────────────────

class MineleadProvider(Provider):
    name = "Minelead.io"

    def __init__(self):
        self.api_key = os.getenv("MINELEAD_API_KEY", "")
        self.used = 0

    def is_available(self):
        return bool(self.api_key) and not self.exhausted

    def search(self, domain, company_name=""):
        if not self.api_key:
            return None
        try:
            resp = requests.get(
                "https://api.minelead.io/v1/search/" + domain,
                params={"key": self.api_key},
                timeout=15,
            )
            if resp.status_code in (402, 429, 403):
                self.exhausted = True
                return None
            if resp.status_code != 200:
                return None
            self.used += 1
            for person in resp.json().get("data", []):
                email = (person.get("email") or "").strip()
                if not email:
                    continue
                position = (person.get("position") or person.get("title") or "").strip()
                name = (person.get("name") or "").strip()
                if not name:
                    first = (person.get("first_name") or "").strip()
                    last = (person.get("last_name") or "").strip()
                    name = (first + " " + last).strip()
                if _title_is_target(position) and name and email:
                    return {"name": name, "title": position, "email": email}
        except Exception:
            pass
        return None

    def status(self):
        if not self.api_key:
            return "no keys"
        return f"{'exhausted' if self.exhausted else 'active'}, {self.used} used"


# ── VOILANORBERT ────────────────────────────────────────────────────────────

class VoilaNorbertProvider(Provider):
    name = "VoilaNorbert"

    def __init__(self):
        self.api_key = os.getenv("VOILANORBERT_API_KEY", "")
        self.used = 0

    def is_available(self):
        return bool(self.api_key) and not self.exhausted

    def search(self, domain, company_name=""):
        if not self.api_key:
            return None
        try:
            resp = requests.post(
                "https://api.voilanorbert.com/2018-01-08/search/new",
                auth=("", self.api_key),
                data={"domain": domain, "company": company_name},
                timeout=15,
            )
            if resp.status_code in (402, 429, 403):
                self.exhausted = True
                return None
            if resp.status_code != 200:
                return None
            self.used += 1
            data = resp.json()
            email = (data.get("email", {}).get("email") or "").strip()
            name = (data.get("email", {}).get("name") or "").strip()
            if email and name:
                return {"name": name, "title": "Executive", "email": email}
        except Exception:
            pass
        return None

    def status(self):
        if not self.api_key:
            return "no keys"
        return f"{'exhausted' if self.exhausted else 'active'}, {self.used} used"


# ── ANYMAIL FINDER ──────────────────────────────────────────────────────────

class AnymailProvider(Provider):
    name = "Anymail Finder"

    def __init__(self):
        self.api_key = os.getenv("ANYMAIL_API_KEY", "")
        self.used = 0

    def is_available(self):
        return bool(self.api_key) and not self.exhausted

    def search(self, domain, company_name=""):
        if not self.api_key:
            return None
        try:
            resp = requests.post(
                "https://api.anymailfinder.com/v5.0/search/company.json",
                headers={"Authorization": "Bearer " + self.api_key,
                         "Content-Type": "application/json"},
                json={"domain": domain},
                timeout=15,
            )
            if resp.status_code in (402, 429, 403):
                self.exhausted = True
                return None
            if resp.status_code != 200:
                return None
            self.used += 1
            for person in resp.json().get("results", []):
                email = (person.get("email") or "").strip()
                if not email:
                    continue
                position = (person.get("title") or "").strip()
                name = (person.get("name") or "").strip()
                if _title_is_target(position) and name and email:
                    return {"name": name, "title": position, "email": email}
        except Exception:
            pass
        return None

    def status(self):
        if not self.api_key:
            return "no keys"
        return f"{'exhausted' if self.exhausted else 'active'}, {self.used} used"


# ── PROVIDER CHAIN ──────────────────────────────────────────────────────────

def _build_providers():
    """Hunter-only. Other providers paused."""
    return [
        HunterProvider(),
    ]


def search_all_providers(providers, domain, company_name=""):
    """Try each provider in order until one returns a result."""
    for p in providers:
        if not p.is_available():
            continue
        result = p.search(domain, company_name)
        if result:
            return result, p.name
        time.sleep(random.uniform(0.3, 0.8))
    return None, ""


def print_provider_status(providers):
    """Print credit status for all providers."""
    print("")
    print("  --- Provider Status ---")
    active = 0
    for p in providers:
        available = p.is_available()
        marker = "✓" if available else "✗"
        print(f"    {marker} {p.name:20s} {p.status()}")
        if available:
            active += 1
    print(f"  Active providers: {active}/{len(providers)}")
    print("")
    return active


# ── DOMAIN FINDER ───────────────────────────────────────────────────────────

def _extract_domain(url):
    if not url:
        return ""
    url = url.lower().strip()
    for prefix in ["https://", "http://", "www."]:
        if url.startswith(prefix):
            url = url[len(prefix):]
    return url.split("/")[0].split("?")[0]


def _find_domain_ddg(company_name):
    """Find domain via DDG search. No browser."""
    skip = {"google.", "linkedin.", "facebook.", "twitter.", "youtube.",
            "wikipedia.", "instagram.", "glassdoor.", "indeed.", "crunchbase.",
            "amazon.", "reddit.", "github."}
    try:
        from ddgs import DDGS
        results = DDGS().text(company_name + " official website", max_results=5)
        for r in results:
            url = r.get("href", "")
            domain = _extract_domain(url)
            if domain and not any(s in domain for s in skip):
                return domain
    except Exception:
        pass
    return ""


# ── MAIN ────────────────────────────────────────────────────────────────────

def run_multi_enricher(limit=200, status_only=False):
    print("")
    print("=" * 65)
    print("  ENRICHER (Hunter.io only)")
    print("=" * 65)
    print("")

    providers = _build_providers()
    active = print_provider_status(providers)

    if status_only:
        return 0

    if active == 0:
        print("  No API keys configured! Add keys to .env file.")
        print("  See top of multi_enricher.py for the full list.")
        return 0

    # Get leads that need enrichment
    all_leads = get_all_leads()
    needs_email = [
        l for l in all_leads
        if not (l.get("decision_maker_email") or "").strip()
        and l.get("status") not in ("no_match",)
    ]

    # Sort: leads with domains first (faster — skip DDG lookup)
    needs_email.sort(key=lambda l: 0 if (l.get("company_domain") or "").strip() else 1)

    if not needs_email:
        print("  All leads already have emails or are no_match!")
        get_stats()
        return 0

    if len(needs_email) > limit:
        needs_email = needs_email[:limit]

    print(f"  Leads to enrich: {len(needs_email)}")
    print("")

    enriched = 0
    no_domain = 0
    no_match = 0
    domain_cache = {}

    for i, lead in enumerate(needs_email):
        company = lead["company_name"]
        company_key = company.lower().strip()

        # Check if any provider still has credits
        if not any(p.is_available() for p in providers):
            print("")
            print("  All providers exhausted! Stopping.")
            break

        print(f"[{i+1}/{len(needs_email)}] {company}")

        # 1. Find domain
        domain = (lead.get("company_domain") or "").strip()
        if not domain:
            website = (lead.get("company_website") or "").strip()
            if website:
                domain = _extract_domain(website)

        if not domain:
            if company_key in domain_cache:
                domain = domain_cache[company_key]
            else:
                domain = _find_domain_ddg(company)
                domain_cache[company_key] = domain
                time.sleep(random.uniform(0.5, 1.0))

        if not domain:
            print(f"  → no domain found")
            update_lead(lead["id"], status="no_match")
            no_domain += 1
            continue

        print(f"  → domain: {domain}")

        # 2. Search all providers
        result, provider_name = search_all_providers(providers, domain, company)

        if result:
            print(f"  → FOUND via {provider_name}: {result['name']} <{result['email']}>")
            update_lead(
                lead["id"],
                company_domain=domain,
                decision_maker_name=result["name"],
                decision_maker_title=result["title"],
                decision_maker_email=result["email"],
                status="enriched",
            )
            enriched += 1
        else:
            print(f"  → no exec found")
            update_lead(lead["id"], company_domain=domain, status="no_match")
            no_match += 1

        time.sleep(random.uniform(0.5, 1.5))

    # Summary
    print("")
    print("=" * 65)
    print(f"  DONE:")
    print(f"    Enriched (found email):  {enriched}")
    print(f"    No domain found:         {no_domain}")
    print(f"    No exec found:           {no_match}")
    print_provider_status(providers)
    print("=" * 65)

    get_stats()
    return enriched


if __name__ == "__main__":
    args = sys.argv[1:]

    limit = 200
    for i, a in enumerate(args):
        if a == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])

    if "--status" in args:
        run_multi_enricher(status_only=True)
    else:
        run_multi_enricher(limit=limit)
