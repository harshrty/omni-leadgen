"""
Waterfall Enricher: Find decision makers using multiple sources.

Priority order:
  1. Scrapling - scrape company website (FREE, unlimited)
  2. Snov.io API (50 free credits/month)
  3. Hunter.io API (25 free credits/month)
  4. Groq LLM guess (free, unlimited - last resort)
"""
import re
import time
import json
import random
import requests
from config import (
    GROQ_API_KEY, GROQ_MODEL,
    SNOV_USER_ID, SNOV_API_SECRET,
    HUNTER_API_KEY, TARGET_TITLES,
)
from db import get_leads_by_status, update_lead, get_stats


# ============================================================
#  CREDIT TRACKER - tracks remaining credits per provider
# ============================================================
class CreditTracker:
    def __init__(self):
        self.limits = {
            "snov": 50,
            "hunter": 25,
        }
        self.used = {
            "snov": 0,
            "hunter": 0,
        }

    def can_use(self, provider):
        return self.used[provider] < self.limits[provider]

    def use(self, provider):
        self.used[provider] += 1

    def remaining(self, provider):
        return self.limits[provider] - self.used[provider]

    def summary(self):
        print("  --- Credit Usage ---")
        for p in self.limits:
            r = self.remaining(p)
            u = self.used[p]
            print("    " + p + ": " + str(u) + " used, " + str(r) + " remaining")


credits = CreditTracker()


# ============================================================
#  LAYER 1: SCRAPLING - Find website + scrape contact info
# ============================================================
def extract_emails_from_text(text):
    pattern = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
    emails = re.findall(pattern, text)
    skip = [
        "example.com", "email.com", "domain.com", "yourcompany",
        "sentry.io", "webpack", "babel", ".png", ".jpg", ".gif",
        "wixpress", "schema.org", "noreply", "no-reply",
        "unsubscribe", "mailer-daemon", "postmaster",
    ]
    cleaned = []
    for e in emails:
        e_lower = e.lower()
        if not any(s in e_lower for s in skip) and len(e) < 60:
            cleaned.append(e)
    return list(set(cleaned))


def extract_phones_from_text(text):
    patterns = [
        r"\+?1?[\s.\-]?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}",
        r"\+\d{1,3}[\s.\-]?\d{2,4}[\s.\-]?\d{3,4}[\s.\-]?\d{3,4}",
    ]
    phones = []
    for p in patterns:
        found = re.findall(p, text)
        phones.extend(found)
    return list(set(phones))[:3]


def extract_domain_from_url(url):
    """Get clean domain from URL (e.g. 'https://www.pepsico.com/about' -> 'pepsico.com')"""
    if not url:
        return ""
    url = url.lower().strip()
    # Remove protocol
    for prefix in ["https://", "http://", "www."]:
        if url.startswith(prefix):
            url = url[len(prefix):]
    # Get just the domain
    domain = url.split("/")[0].split("?")[0]
    return domain


def find_company_website(company_name):
    """Use DuckDuckGo HTML to find company website."""
    from scrapling.fetchers import StealthyFetcher
    from urllib.parse import unquote, quote_plus

    try:
        query = quote_plus(company_name + " official website")
        url = "https://html.duckduckgo.com/html/?q=" + query
        response = StealthyFetcher.fetch(url, headless=True, disable_resources=True)

        if response.status != 200:
            return ""

        # DuckDuckGo result links have class "result__a"
        links = response.css("a.result__a")

        skip_domains = [
            "google.", "linkedin.", "facebook.",
            "twitter.", "youtube.", "wikipedia.",
            "instagram.", "glassdoor.", "indeed.",
            "yelp.", "bloomberg.", "crunchbase.",
            "x.com", "tiktok.", "duckduckgo.",
            "amazon.", "reddit.", "github.",
        ]

        for link in links[:5]:
            try:
                href = link.attrib.get("href", "")
                # DuckDuckGo wraps URLs: //duckduckgo.com/l/?uddg=https%3A%2F%2Fsite.com&...
                if "uddg=" in href:
                    encoded = href.split("uddg=")[1].split("&")[0]
                    actual = unquote(encoded)
                elif href.startswith("http"):
                    actual = href
                else:
                    continue

                actual_lower = actual.lower()
                if not any(s in actual_lower for s in skip_domains):
                    return actual
            except Exception:
                continue

        return ""

    except Exception as e:
        print(" DDG error: " + str(e)[:60])
        return ""


def scrape_company_contacts(website_url):
    """Scrape company website for contact info and team details."""
    from scrapling.fetchers import StealthyFetcher

    all_text = ""
    all_emails = []
    all_phones = []

    base = website_url.rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base

    pages = [
        base,
        base + "/about",
        base + "/about-us",
        base + "/contact",
        base + "/contact-us",
        base + "/team",
        base + "/our-team",
        base + "/leadership",
    ]

    for page_url in pages:
        try:
            response = StealthyFetcher.fetch(
                page_url, headless=True, disable_resources=True,
            )
            if response.status == 200:
                try:
                    page_text = response.get_all_text() or ""
                except Exception:
                    page_text = ""
                if page_text:
                    all_text += page_text + "\n"
                    all_emails.extend(extract_emails_from_text(page_text))
                    all_phones.extend(extract_phones_from_text(page_text))
            time.sleep(random.uniform(1.5, 3))
        except Exception:
            continue

    return {
        "text": all_text[:3000],
        "emails": list(set(all_emails))[:10],
        "phones": list(set(all_phones))[:5],
    }


def classify_email(email, company_domain):
    """Check if an email looks like a personal email or a generic one."""
    generic_prefixes = [
        "info@", "contact@", "hello@", "support@", "admin@",
        "sales@", "help@", "team@", "office@", "enquiries@",
        "hr@", "jobs@", "careers@", "press@", "media@",
    ]
    e_lower = email.lower()
    for prefix in generic_prefixes:
        if e_lower.startswith(prefix):
            return "generic"
    return "personal"


def pick_best_email(emails, company_domain):
    """Pick the best email: prefer personal emails on company domain."""
    personal = []
    generic = []
    other = []

    for email in emails:
        domain = email.split("@")[1].lower() if "@" in email else ""
        etype = classify_email(email, company_domain)

        if company_domain and company_domain in domain:
            if etype == "personal":
                personal.append(email)
            else:
                generic.append(email)
        else:
            other.append(email)

    # Priority: personal on company domain > generic on domain > any other
    if personal:
        return personal[0], "personal"
    if generic:
        return generic[0], "generic"
    if other:
        return other[0], "other"
    return "", "none"


def scrapling_enrich(company_name):
    """Layer 1: Use Scrapling to find website and scrape contacts."""
    print("    [Scrapling] Finding website...", end="")
    website = find_company_website(company_name)
    if not website:
        print(" not found")
        return None

    domain = extract_domain_from_url(website)
    print(" " + domain)

    print("    [Scrapling] Scraping contacts...", end="")
    contacts = scrape_company_contacts(website)
    email_count = len(contacts.get("emails", []))
    phone_count = len(contacts.get("phones", []))
    print(" " + str(email_count) + " emails, " + str(phone_count) + " phones")

    best_email, email_type = pick_best_email(
        contacts.get("emails", []), domain
    )

    return {
        "website": website,
        "domain": domain,
        "emails": contacts.get("emails", []),
        "phones": contacts.get("phones", []),
        "text": contacts.get("text", ""),
        "best_email": best_email,
        "email_type": email_type,
    }


# ============================================================
#  LAYER 2: SNOV.IO API
# ============================================================
def get_snov_token():
    """Get OAuth token from Snov.io."""
    if not SNOV_USER_ID or not SNOV_API_SECRET:
        return None
    try:
        resp = requests.post(
            "https://api.snov.io/v1/oauth/access_token",
            json={
                "grant_type": "client_credentials",
                "client_id": SNOV_USER_ID,
                "client_secret": SNOV_API_SECRET,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json().get("access_token")
    except Exception:
        pass
    return None


def snov_enrich(domain):
    """Layer 2: Use Snov.io to find decision makers by domain.
    Uses the v2 async Domain Search API (start -> poll result)."""
    if not credits.can_use("snov"):
        return None
    if not SNOV_USER_ID or not SNOV_API_SECRET:
        return None

    token = get_snov_token()
    if not token:
        print("    [Snov.io] Auth failed")
        return None

    print("    [Snov.io] Searching " + domain + "...", end="")

    try:
        headers = {"Authorization": "Bearer " + token}

        # Step 1: Start domain search
        resp = requests.post(
            "https://api.snov.io/v2/domain-search/start",
            data={"domain": domain},
            headers=headers,
            timeout=30,
        )
        if resp.status_code != 200:
            print(" error " + str(resp.status_code))
            # If 403, API not available on free plan
            if resp.status_code == 403:
                print("    [Snov.io] API not available on free plan - disabling")
                credits.remaining["snov"] = 0
            return None

        data = resp.json()
        task_hash = data.get("meta", {}).get("task_hash", "")
        if not task_hash:
            print(" no task_hash")
            return None

        credits.use("snov")

        # Step 2: Poll for results (may need a moment)
        time.sleep(3)
        resp2 = requests.get(
            "https://api.snov.io/v2/domain-search/result/" + task_hash,
            headers=headers,
            timeout=30,
        )
        if resp2.status_code != 200:
            print(" result error " + str(resp2.status_code))
            return None

        result_data = resp2.json()
        if result_data.get("status") == "in_progress":
            # Wait and retry
            time.sleep(5)
            resp2 = requests.get(
                "https://api.snov.io/v2/domain-search/result/" + task_hash,
                headers=headers,
                timeout=30,
            )
            result_data = resp2.json()

        # Step 3: Get prospects URL from result
        prospects_url = result_data.get("links", {}).get("prospects")
        if not prospects_url:
            print(" no prospects link")
            return None

        # Step 4: Search prospects filtered by titles
        resp3 = requests.post(
            prospects_url,
            json={"positions": TARGET_TITLES[:6], "page": 1},
            headers=headers,
            timeout=30,
        )
        if resp3.status_code != 200:
            print(" prospects error")
            return None

        prospects_data = resp3.json()
        prospects = prospects_data.get("data", [])

        for person in prospects:
            email = ""
            emails = person.get("emails", [])
            if emails:
                for em in emails:
                    if em.get("smtp_status") == "valid":
                        email = em.get("email", "")
                        break
                if not email:
                    email = emails[0].get("email", "")

            if email:
                name = (
                    (person.get("first_name", "") or "")
                    + " "
                    + (person.get("last_name", "") or "")
                ).strip()
                title = person.get("position", "") or ""
                li = person.get("social", {}).get("linkedin", "") or ""
                print(" FOUND: " + name)
                return {
                    "name": name,
                    "title": title,
                    "email": email,
                    "linkedin": li,
                    "source": "snov.io",
                }

        print(" no decision maker found")
        return None

    except Exception as e:
        print(" error: " + str(e)[:60])
        return None


# ============================================================
#  LAYER 3: HUNTER.IO API
# ============================================================
def hunter_enrich(domain):
    """Layer 3: Use Hunter.io Domain Search to find contacts."""
    if not credits.can_use("hunter"):
        return None
    if not HUNTER_API_KEY:
        return None

    print("    [Hunter] Searching " + domain + "...", end="")

    try:
        resp = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={
                "domain": domain,
                "api_key": HUNTER_API_KEY,
                "limit": 10,
            },
            timeout=30,
        )

        if resp.status_code == 401:
            print(" invalid API key")
            return None
        if resp.status_code == 429:
            print(" rate limited")
            return None
        if resp.status_code != 200:
            print(" error " + str(resp.status_code))
            return None

        credits.use("hunter")
        data = resp.json()
        emails = data.get("data", {}).get("emails", [])

        if not emails:
            print(" no results")
            return None

        # Look for senior people first
        senior_keywords = [
            "cto", "ceo", "founder", "co-founder", "chief",
            "vp", "vice president", "head", "director",
            "president", "partner", "owner",
        ]

        best_senior = None
        best_personal = None

        for person in emails:
            pos = (person.get("position") or "").lower()
            seniority = (person.get("seniority") or "").lower()
            email = person.get("value", "")
            ptype = person.get("type", "")

            if ptype == "generic":
                continue

            is_senior = seniority in ["executive", "senior", "c-level"]
            has_senior_title = any(kw in pos for kw in senior_keywords)

            first = person.get("first_name", "")
            last = person.get("last_name", "")
            name = (first + " " + last).strip()
            position = person.get("position", "")
            li = person.get("linkedin") or ""

            if (is_senior or has_senior_title) and email and not best_senior:
                best_senior = {
                    "name": name,
                    "title": position,
                    "email": email,
                    "linkedin": li,
                    "source": "hunter.io",
                }

            if ptype == "personal" and email and not best_personal:
                best_personal = {
                    "name": name,
                    "title": position,
                    "email": email,
                    "linkedin": li,
                    "source": "hunter.io",
                }

        result = best_senior or best_personal
        if result:
            print(" FOUND: " + result["name"])
        else:
            print(" no decision maker")
        return result

    except Exception as e:
        print(" error: " + str(e)[:60])
        return None


# ============================================================
#  LAYER 4: GROQ LLM GUESS (last resort)
# ============================================================
def groq_enrich(company_name, domain, scraped_data):
    """Layer 4: Use Groq to guess decision maker from scraped data."""
    if not GROQ_API_KEY:
        return None

    from groq import Groq

    print("    [Groq] Analyzing scraped data...", end="")

    emails_str = ", ".join(scraped_data.get("emails", [])[:5])
    site_text = scraped_data.get("text", "")[:1500]

    prompt = (
        "I am researching " + company_name + " (domain: " + domain + ") "
        "to find the best decision maker to contact about AI services.\n\n"
        "Website text:\n" + (site_text if site_text else "(none)") + "\n\n"
        "Emails found: " + (emails_str if emails_str else "none") + "\n\n"
        "Based on this, identify the most likely CTO/VP/Founder.\n"
        "If you can see names on the website, use them.\n"
        "If not, pick the best email from the list.\n\n"
        "Respond ONLY in JSON, no markdown:\n"
        '{"name": "Name", "title": "Title", "email": "email@domain.com", '
        '"linkedin": ""}'
    )

    try:
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You identify decision makers at companies. "
                        "Respond with valid JSON only, no markdown."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=200,
        )

        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()

        result = json.loads(raw)
        result["source"] = "groq"
        if result.get("email"):
            print(" FOUND: " + result.get("name", "?"))
        else:
            print(" no result")
        return result if result.get("email") else None

    except Exception as e:
        print(" error: " + str(e)[:60])
        return None


# ============================================================
#  MAIN WATERFALL ENRICHER
# ============================================================
def enrich_lead(lead, seen_companies):
    """Run the waterfall enrichment for a single lead."""
    company = lead["company_name"]
    company_key = company.lower().strip()

    # Check cache
    if company_key in seen_companies:
        cached = seen_companies[company_key]
        if cached:
            update_lead(lead["id"], **cached, status="enriched")
            return "cached_hit"
        else:
            update_lead(lead["id"], status="no_match")
            return "cached_miss"

    print("  --- " + company + " ---")

    # ---- LAYER 1: Scrapling ----
    scraped = scrapling_enrich(company)

    website = ""
    domain = ""
    all_emails = []
    all_phones = []
    site_text = ""

    if scraped:
        website = scraped.get("website", "")
        domain = scraped.get("domain", "")
        all_emails = scraped.get("emails", [])
        all_phones = scraped.get("phones", [])
        site_text = scraped.get("text", "")

        # If we found a personal email on company domain, that might be enough
        if scraped["email_type"] == "personal" and scraped["best_email"]:
            fields = {
                "company_website": website,
                "company_domain": domain,
                "company_contact_email": ", ".join(all_emails[:3]),
                "company_phone": ", ".join(all_phones[:2]),
                "decision_maker_email": scraped["best_email"],
                "decision_maker_name": "",
                "decision_maker_title": "",
                "decision_maker_linkedin": "",
            }
            # Still try to get name/title from APIs if available
            # but mark as enriched with what we have
            dm = None

            # Try Snov.io
            if domain:
                dm = snov_enrich(domain)

            # Try Hunter
            if not dm and domain:
                dm = hunter_enrich(domain)

            if dm:
                fields["decision_maker_name"] = dm.get("name", "")
                fields["decision_maker_title"] = dm.get("title", "")
                fields["decision_maker_email"] = dm.get("email", "") or fields["decision_maker_email"]
                fields["decision_maker_linkedin"] = dm.get("linkedin", "")

            update_lead(lead["id"], **fields, status="enriched")
            seen_companies[company_key] = fields
            return "enriched"

    # ---- LAYER 2: Snov.io ----
    dm = None
    if domain:
        dm = snov_enrich(domain)

    # ---- LAYER 3: Hunter.io ----
    if not dm and domain:
        dm = hunter_enrich(domain)

    # ---- LAYER 4: Groq guess ----
    if not dm and GROQ_API_KEY and scraped:
        dm = groq_enrich(company, domain, {
            "emails": all_emails,
            "text": site_text,
        })

    # Save whatever we found
    if dm and dm.get("email"):
        fields = {
            "company_website": website,
            "company_domain": domain,
            "company_contact_email": ", ".join(all_emails[:3]),
            "company_phone": ", ".join(all_phones[:2]),
            "decision_maker_name": dm.get("name", ""),
            "decision_maker_title": dm.get("title", ""),
            "decision_maker_email": dm.get("email", ""),
            "decision_maker_linkedin": dm.get("linkedin", ""),
        }
        update_lead(lead["id"], **fields, status="enriched")
        seen_companies[company_key] = fields
        return "enriched"
    elif website:
        # Save website info even without decision maker
        fields = {
            "company_website": website,
            "company_domain": domain,
            "company_contact_email": ", ".join(all_emails[:3]),
            "company_phone": ", ".join(all_phones[:2]),
        }
        update_lead(lead["id"], **fields, status="no_match")
        seen_companies[company_key] = None
        return "partial"
    else:
        update_lead(lead["id"], status="no_match")
        seen_companies[company_key] = None
        return "no_match"


def run_enricher():
    print("")
    print("=" * 60)
    print("  WATERFALL ENRICHER")
    print("  Scrapling -> Snov.io -> Hunter.io -> Groq")
    print("=" * 60)
    print("")

    # Show which APIs are configured
    apis = []
    apis.append("Scrapling (unlimited)")
    if SNOV_USER_ID and SNOV_API_SECRET:
        apis.append("Snov.io (50 credits)")
    if HUNTER_API_KEY:
        apis.append("Hunter.io (25 credits)")
    if GROQ_API_KEY:
        apis.append("Groq LLM (unlimited)")
    print("  Active providers: " + ", ".join(apis))
    print("")

    leads = get_leads_by_status("scraped")
    if not leads:
        print("No scraped leads to enrich.")
        return 0

    print("Found " + str(len(leads)) + " leads to enrich.")
    print("")

    enriched = 0
    partial = 0
    no_match = 0
    seen_companies = {}

    for lead in leads:
        result = enrich_lead(lead, seen_companies)

        if result == "enriched" or result == "cached_hit":
            enriched += 1
        elif result == "partial":
            partial += 1
        else:
            no_match += 1

        # Delay between companies (not cached ones)
        if result not in ("cached_hit", "cached_miss"):
            time.sleep(random.uniform(2, 4))

    print("")
    print("=" * 60)
    msg = "  ENRICHER DONE: " + str(enriched) + " enriched"
    msg += ", " + str(partial) + " partial"
    msg += ", " + str(no_match) + " no match"
    print(msg)
    credits.summary()
    print("=" * 60)

    get_stats()
    return enriched


if __name__ == "__main__":
    run_enricher()