"""
Fast company scraper — finds companies from free job APIs, exports clean CSV for Apollo.io.

NO BROWSER. NO HUNTER. Just fast API scraping → clean CSV with company names + domains.
Upload the CSV to Apollo.io to get decision-maker emails manually.

Sources:
  - HN Who's Hiring (Algolia API)
  - Remotive API (remote tech jobs)
  - The Muse API (US companies)
  - Arbeitnow API (EU tech jobs)

Usage:
  python fast_scraper.py              # all sources
  python fast_scraper.py --hn-only
  python fast_scraper.py --limit 100
"""
import re
import csv
import sys
import time
import random
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus, unquote

from db import get_existing_companies, get_stats

# ── CONFIG ──────────────────────────────────────────────────────────────────
MAX_WORKERS_DOMAIN = 8      # parallel DDG lookups
_lock = threading.Lock()


# ── PHASE 1: SCRAPE COMPANY NAMES ──────────────────────────────────────────

def _scrape_hn_hiring():
    """HN Who's Hiring via Algolia API. Fast, no browser."""
    print("  [HN] Fetching latest hiring thread...")
    companies = []
    try:
        resp = requests.get(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={"query": "Ask HN Who is hiring", "tags": "ask_hn", "hitsPerPage": 5},
            timeout=15,
        )
        hits = resp.json().get("hits", [])
        thread_id = ""
        for hit in hits:
            if "who is hiring" in hit.get("title", "").lower():
                thread_id = str(hit.get("objectID", ""))
                print("    Thread: " + hit["title"])
                break
        if not thread_id:
            print("    No thread found")
            return companies

        # Fetch all comments
        page = 0
        while page < 5:
            resp = requests.get(
                "https://hn.algolia.com/api/v1/search_by_date",
                params={"tags": "comment,story_" + thread_id, "hitsPerPage": 200, "page": page},
                timeout=20,
            )
            data = resp.json()
            hits = data.get("hits", [])
            if not hits:
                break

            for hit in hits:
                text = re.sub(r"<[^>]+>", " ", hit.get("comment_text") or "")
                text = re.sub(r"\s+", " ", text).strip()
                if len(text) < 30:
                    continue
                # First line: "Company | Role | Location"
                first_line = text.split(".")[0] if "." in text[:100] else text[:100]
                parts = [p.strip() for p in first_line.split("|")]
                company = parts[0] if parts else ""
                company = re.sub(r"\s*\(YC\s+\w+\)", "", company).strip()
                company = re.sub(r"\s*(Inc\.?|LLC|Ltd\.?|Corp\.?)$", "", company, flags=re.I).strip()
                if company and 2 < len(company) < 60:
                    # Extract URL if present
                    url_match = re.search(r"https?://[^\s\)\]\"<>]+", text)
                    job_url = url_match.group(0).rstrip(".,;") if url_match else ""
                    companies.append({"company_name": company, "job_url": job_url, "source": "hn"})

            total_pages = (data.get("nbHits", 0) // 200) + 1
            if page >= total_pages - 1:
                break
            page += 1
            time.sleep(0.3)

    except Exception as e:
        print("    HN error: " + str(e)[:60])
    print(f"    Found {len(companies)} companies")
    return companies


def _scrape_remotive():
    """Remotive API — remote tech jobs."""
    print("  [Remotive] Fetching remote jobs...")
    companies = []
    try:
        resp = requests.get("https://remotive.com/api/remote-jobs?limit=200", timeout=15)
        jobs = resp.json().get("jobs", [])
        for job in jobs:
            company = (job.get("company_name") or "").strip()
            if company and 2 < len(company) < 60:
                companies.append({
                    "company_name": company,
                    "job_url": job.get("url", ""),
                    "source": "remotive",
                })
    except Exception as e:
        print("    Remotive error: " + str(e)[:60])
    print(f"    Found {len(companies)} companies")
    return companies


def _scrape_arbeitnow():
    """Arbeitnow API — EU tech jobs."""
    print("  [Arbeitnow] Fetching EU jobs...")
    companies = []
    try:
        for page in range(1, 6):
            resp = requests.get(
                "https://www.arbeitnow.com/api/job-board-api",
                params={"page": page},
                timeout=15,
            )
            data = resp.json()
            jobs = data.get("data", [])
            if not jobs:
                break
            for job in jobs:
                company = (job.get("company_name") or "").strip()
                if company and 2 < len(company) < 60:
                    companies.append({
                        "company_name": company,
                        "job_url": job.get("url", ""),
                        "source": "arbeitnow",
                    })
            time.sleep(0.3)
    except Exception as e:
        print("    Arbeitnow error: " + str(e)[:60])
    print(f"    Found {len(companies)} companies")
    return companies


def _scrape_themuse():
    """The Muse API — US companies."""
    print("  [TheMuse] Fetching US companies...")
    companies = []
    try:
        for page in range(0, 10):
            resp = requests.get(
                "https://www.themuse.com/api/public/jobs",
                params={"page": page, "descending": "true"},
                timeout=15,
            )
            data = resp.json()
            results = data.get("results", [])
            if not results:
                break
            for job in results:
                company_obj = job.get("company") or {}
                company = (company_obj.get("name") or "").strip()
                if company and 2 < len(company) < 60:
                    refs = job.get("refs", {})
                    companies.append({
                        "company_name": company,
                        "job_url": refs.get("landing_page", ""),
                        "source": "themuse",
                    })
            time.sleep(0.3)
    except Exception as e:
        print("    TheMuse error: " + str(e)[:60])
    print(f"    Found {len(companies)} companies")
    return companies


# ── PHASE 2: FIND DOMAINS (no browser, requests only) ──────────────────────

_SKIP_DOMAINS = {
    "google.", "linkedin.", "facebook.", "twitter.", "youtube.",
    "wikipedia.", "instagram.", "glassdoor.", "indeed.", "yelp.",
    "bloomberg.", "crunchbase.", "x.com", "tiktok.", "amazon.",
    "reddit.", "github.", "duckduckgo.", "remotive.", "themuse.",
    "arbeitnow.", "wellfound.", "ziprecruiter.", "monster.",
}


def _find_domain_ddg(company_name):
    """Find company domain via DuckDuckGo search. No browser needed."""
    try:
        from ddgs import DDGS
        results = DDGS().text(company_name + " official website", max_results=5)
        for r in results:
            url = r.get("href", "")
            if not any(s in url.lower() for s in _SKIP_DOMAINS):
                domain = url.lower().strip()
                for prefix in ["https://", "http://", "www."]:
                    if domain.startswith(prefix):
                        domain = domain[len(prefix):]
                domain = domain.split("/")[0].split("?")[0]
                if "." in domain and len(domain) > 3:
                    return domain
    except Exception:
        pass
    return ""


def _find_domains_parallel(companies):
    """Find domains for all companies in parallel."""
    print(f"\n  Finding domains for {len(companies)} companies ({MAX_WORKERS_DOMAIN} workers)...")
    results = {}  # company_name -> domain
    done = 0

    def _worker(company_name):
        nonlocal done
        domain = _find_domain_ddg(company_name)
        with _lock:
            done += 1
            if done % 20 == 0:
                print(f"    {done}/{len(companies)} domains found...")
        return company_name, domain

    with ThreadPoolExecutor(max_workers=MAX_WORKERS_DOMAIN) as pool:
        futures = {pool.submit(_worker, c): c for c in companies}
        for future in as_completed(futures):
            try:
                name, domain = future.result()
                if domain:
                    results[name] = domain
            except Exception:
                continue
            # Small delay to avoid DDG rate limiting
            time.sleep(random.uniform(0.1, 0.3))

    found = len(results)
    print(f"    Done: {found}/{len(companies)} domains found")
    return results


# ── MAIN ────────────────────────────────────────────────────────────────────

CSV_PATH = "apollo_leads.csv"


def _clean_name(name):
    """Return True if name looks like a real company."""
    name = name.strip()
    if len(name) < 3 or len(name) > 60:
        return False
    if not re.match(r'^[A-Za-z]', name):
        return False
    junk = ['points by', 'hours ago', 'open source', 'you need', 'hedge fund',
            'help us', 'hiring', 'looking for', 'we are', 'remote only',
            'no remote', 'apply here', 'click here', 'job board']
    if any(w in name.lower() for w in junk):
        return False
    return True


def run_fast_scraper(use_hn=True, use_remotive=True, use_arbeitnow=True,
                     use_themuse=True, limit=500):
    print("")
    print("=" * 60)
    print("  FAST SCRAPER → Apollo CSV (no browser, all parallel)")
    print("=" * 60)
    print("")

    existing = get_existing_companies()
    print(f"  Companies already in DB: {len(existing)}")
    print("")

    # ── PHASE 1: Scrape company names from free APIs ──
    print("── PHASE 1: Finding companies ──")
    all_companies = []
    sources = []
    if use_hn:
        sources.append(("hn", _scrape_hn_hiring))
    if use_remotive:
        sources.append(("remotive", _scrape_remotive))
    if use_arbeitnow:
        sources.append(("arbeitnow", _scrape_arbeitnow))
    if use_themuse:
        sources.append(("themuse", _scrape_themuse))

    # Run sources in parallel
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        futures = {pool.submit(fn): name for name, fn in sources}
        for future in as_completed(futures):
            try:
                all_companies.extend(future.result())
            except Exception as e:
                print(f"    Source error: {str(e)[:60]}")

    # Deduplicate + clean names
    seen = set()
    unique = []
    for c in all_companies:
        name = c["company_name"].strip()
        key = name.lower()
        if key in seen or key in existing:
            continue
        if not _clean_name(name):
            continue
        seen.add(key)
        unique.append(c)

    print(f"\n  Total unique new companies: {len(unique)}")

    if not unique:
        print("  No new companies found.")
        return 0

    if len(unique) > limit:
        unique = unique[:limit]
        print(f"  Limited to {limit} companies")

    # ── PHASE 2: Find domains (DDG, no browser) ──
    print("\n── PHASE 2: Finding company domains ──")
    company_names = [c["company_name"] for c in unique]
    domains = _find_domains_parallel(company_names)

    # ── PHASE 3: Export CSV for Apollo ──
    print(f"\n── PHASE 3: Exporting to {CSV_PATH} ──")
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Company Name", "Website URL", "Source"])
        for c in unique:
            name = c["company_name"]
            domain = domains.get(name, "")
            url = "https://" + domain if domain else ""
            w.writerow([name, url, c.get("source", "")])

    with_domain = sum(1 for c in unique if domains.get(c["company_name"]))

    print(f"\n{'=' * 60}")
    print(f"  DONE:")
    print(f"    Companies found:     {len(unique)}")
    print(f"    With website/domain: {with_domain}")
    print(f"    CSV saved to:        {CSV_PATH}")
    print(f"{'=' * 60}")
    print(f"\n  Next: Upload {CSV_PATH} to Apollo.io → People → filter CTO/CEO → reveal emails")

    return len(unique)


if __name__ == "__main__":
    args = sys.argv[1:]
    limit = 500
    for i, a in enumerate(args):
        if a == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])

    if "--hn-only" in args:
        run_fast_scraper(use_hn=True, use_remotive=False, use_arbeitnow=False, use_themuse=False, limit=limit)
    elif "--remotive-only" in args:
        run_fast_scraper(use_hn=False, use_remotive=True, use_arbeitnow=False, use_themuse=False, limit=limit)
    else:
        run_fast_scraper(limit=limit)
