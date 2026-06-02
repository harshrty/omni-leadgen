"""
Alternative job scrapers — HN Who's Hiring + builtin.com + Indeed.

Feeds the same DB as the LinkedIn scraper.
Run standalone:
    python alt_scraper.py                  # all sources
    python alt_scraper.py --hn-only
    python alt_scraper.py --builtin-only
    python alt_scraper.py --indeed-only
"""
import re
import random
import time
import requests
from urllib.parse import quote_plus

from config import SEARCH_QUERIES
from db import insert_lead, get_stats, get_existing_companies
from scraper import is_relevant_job, human_delay, extract_salary_from_text


# ── HELPERS ──────────────────────────────────────────────────────────────────

def _get_text(el):
    if el is None:
        return ""
    try:
        t = el.text
        if t:
            return t.strip()
    except Exception:
        pass
    try:
        t = el.get_all_text()
        if t:
            return t.strip()
    except Exception:
        pass
    return ""


def _clean_company(name):
    """Strip URLs, domain extensions, and junk from a scraped company name."""
    if not name:
        return ""
    name = re.sub(r"\s*\(\s*https?://[^\)]*\)\s*|\s*https?://\S+", "", name).strip()
    name = re.sub(r"\s*(Inc\.?|LLC|Ltd\.?|Corp\.?)$", "", name, flags=re.I).strip()
    # If the whole name is a bare domain (no spaces, has TLD), drop the extension
    if re.search(r"\.[a-z]{2,4}$", name, re.I) and " " not in name:
        name = re.sub(r"\.[a-z]{2,4}$", "", name, flags=re.I).strip()
    return name.strip()


def _get_attr(el, attr):
    if el is None:
        return ""
    try:
        return (el.attrib.get(attr) or "").strip()
    except Exception:
        return ""


def _css_first(el, selector):
    """css_first on an element (Scrapling elements only have .css(), not .css_first())."""
    if el is None:
        return None
    try:
        results = el.css(selector)
        return results[0] if results else None
    except Exception:
        return None


def _strip_html(text):
    import html
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ── SOURCE 1: HN WHO'S HIRING ─────────────────────────────────────────────────
# HN posts a "Who is Hiring?" thread monthly. We find the latest one via
# Algolia's HN search API and pull AI/ML comments from it.

def _find_hn_hiring_thread():
    """Return the HN item ID of the latest 'Who is Hiring?' thread."""
    try:
        resp = requests.get(
            "https://hn.algolia.com/api/v1/search_by_date"
            "?query=Ask+HN+Who+is+hiring&tags=ask_hn&hitsPerPage=10",
            timeout=15,
        )
        hits = resp.json().get("hits", [])
        for hit in hits:
            title = hit.get("title", "")
            if "who is hiring" in title.lower():
                item_id = hit.get("objectID")
                print("    Thread: " + title + " (id=" + str(item_id) + ")")
                return str(item_id)
    except Exception as e:
        print("    Error finding thread: " + str(e)[:60])
    return ""


_AI_KEYWORDS = [
    "machine learning", "ml engineer", "ai engineer", "llm", "deep learning",
    "nlp", "natural language", "computer vision", "mlops", "data scientist",
    "generative ai", "gen ai", "genai", "artificial intelligence",
    "large language model", "neural", "pytorch", "tensorflow", "hugging face",
]


def _is_ai_comment(text):
    t = text.lower()
    return any(kw in t for kw in _AI_KEYWORDS)


# Pre-compiled: skip entries whose "company" is actually a role posting
_NOT_COMPANY_RE = re.compile(
    r'^(senior|junior|lead|staff|principal|founding\s+(?:engineer|dev)|'
    r'software|backend|frontend|full.?stack|cs\s+phd|phd\s+position|'
    r'hiring|looking\s+for|we\s+are)',
    re.IGNORECASE,
)

_TITLE_KEYWORDS = re.compile(
    r'\b(engineer|scientist|researcher|developer|lead|head|manager|'
    r'architect|analyst|specialist|director|vp|founder|intern|cto|ceo)\b',
    re.IGNORECASE,
)
_LOCATION_HINTS = re.compile(
    r'\b(remote|onsite|hybrid|usa|uk|eu|us|nyc|sf|berlin|london|'
    r'paris|amsterdam|toronto|singapore|australia|canada|germany|'
    r'france|spain|italy|ireland|netherlands|israel)\b'
    r'|,\s*[A-Z]{2}\b',  # ", NY" ", CA" etc.
    re.IGNORECASE,
)


def _parse_hn_comment(text):
    """
    Extract company name, job title, location, URL, salary from a raw HN comment.
    HN comments are freeform but follow loose conventions.
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return None

    # First line is usually "Company | Role | Location | Remote/Onsite"
    header = lines[0]
    parts = [p.strip() for p in re.split(r"\s*\|\s*", header)]

    company = parts[0] if parts else ""
    # Strip URLs embedded in company name e.g. "Acme (https://acme.com)" or "Acme ( https://acme.com )"
    company = re.sub(r"\s*\(\s*https?://[^\)]*\)\s*|\s*https?://\S+", "", company).strip()
    # Strip common suffixes like "(YC W24)", "Inc.", "Inc", etc.
    company = re.sub(r"\s*\(YC\s+\w+\)", "", company).strip()
    company = re.sub(r"\s*(Inc\.?|LLC|Ltd\.?|Corp\.?)$", "", company, flags=re.I).strip()
    # Strip trailing domain extension if the whole name looks like a bare domain
    company = re.sub(r"\.(com|io|ai|co|net|org|app|dev|tech|xyz|de|fr|uk)$", "", company, flags=re.I).strip()

    if not company or len(company) > 80:
        return None

    if _NOT_COMPANY_RE.match(company):
        return None

    # Skip if still looks like a domain (contains dot with short TLD, e.g. "hurra.com")
    if re.search(r"\.[a-z]{2,4}$", company, re.I) and " " not in company:
        return None

    # Job title — parts[1] is title ONLY if it looks like a role, not a location
    title = ""
    location = ""
    for part in parts[1:]:
        part = part[:100]
        if not title and _TITLE_KEYWORDS.search(part) and not _LOCATION_HINTS.search(part):
            title = part
        elif not location and _LOCATION_HINTS.search(part):
            location = part[:60]

    # If no title found in pipe-parts, scan first few lines of the comment body
    if not title:
        for line in lines[1:6]:
            if len(line) > 120:
                continue  # skip long paragraphs
            if _TITLE_KEYWORDS.search(line) and not _LOCATION_HINTS.search(line):
                title = line[:80]
                break

    if not title:
        title = "AI/ML Engineer"  # fallback — we already know this is an AI company

    # Clean up location — strip trailing company-description text.
    # Find the EARLIEST marker so we cut as soon as the description starts.
    if location:
        cut = len(location)
        for marker in (". ", "! ", " We\u2019", " we\u2019", " We're", " we're",
                       " I'm", " I\u2019m", " Our ", " our ", " They ", " Hiring"):
            idx = location.find(marker)
            if 0 < idx < cut:
                cut = idx
        location = location[:cut].strip()[:60]

    # URL — first http link in the comment
    url_match = re.search(r"https?://[^\s\)\]\"<>]+", text)
    job_url = url_match.group(0).rstrip(".,;") if url_match else ""

    # Salary
    salary = extract_salary_from_text(text)

    return {
        "company_name": company,
        "job_title": title,
        "job_url": job_url,
        "job_location": location,
        "job_posted_date": "",
        "job_description": "\n".join(lines[:10])[:1000],
        "salary": salary,
        "source": "hn_hiring",
    }


def scrape_hn_hiring():
    """
    Scrape HN 'Who is Hiring?' thread via Algolia API.
    Filters to AI/ML posts only. Returns job dicts.
    """
    jobs = []
    thread_id = _find_hn_hiring_thread()
    if not thread_id:
        print("    Could not find HN hiring thread.")
        return jobs

    page = 0
    seen_companies = set()

    while True:
        try:
            url = (
                "https://hn.algolia.com/api/v1/search_by_date"
                "?tags=comment,story_" + thread_id +
                "&hitsPerPage=200&page=" + str(page)
            )
            resp = requests.get(url, timeout=20)
            data = resp.json()
            hits = data.get("hits", [])
            if not hits:
                break

            for hit in hits:
                text = _strip_html(hit.get("comment_text") or "")
                if not text or len(text) < 50:
                    continue
                if not _is_ai_comment(text):
                    continue

                parsed = _parse_hn_comment(text)
                if not parsed:
                    continue

                company_key = parsed["company_name"].lower()
                if company_key in seen_companies:
                    continue
                seen_companies.add(company_key)

                if is_relevant_job(parsed["job_title"]):
                    jobs.append(parsed)

            total_pages = (data.get("nbHits", 0) // 200) + 1
            if page >= total_pages - 1:
                break
            page += 1
            time.sleep(0.5)

        except Exception as e:
            print("    HN page " + str(page) + " error: " + str(e)[:60])
            break

    return jobs


# ── SOURCE 2: BUILTIN.COM ─────────────────────────────────────────────────────
# builtin.com is a tech-focused job board with clean HTML and no aggressive
# bot detection. Covers US cities + remote well.

BUILTIN_URLS = [
    "https://builtin.com/jobs/machine-learning",
    "https://builtin.com/jobs/artificial-intelligence",
    "https://builtin.com/jobs/data-science",
    "https://builtin.com/jobs/machine-learning?remote=true",
    "https://builtin.com/jobs/artificial-intelligence?remote=true",
]


def scrape_builtin():
    from scrapling.fetchers import StealthyFetcher
    jobs = []
    seen = set()

    for base_url in BUILTIN_URLS:
        for page in range(1, 4):  # up to 3 pages per category
            url = base_url + ("&" if "?" in base_url else "?") + "page=" + str(page)
            print("    " + url[:80] + "...")

            try:
                response = StealthyFetcher.fetch(url, headless=True, disable_resources=True)
                if response.status != 200:
                    print("      HTTP " + str(response.status))
                    break

                sample = (response.get_all_text() or "")[:2000].lower()
                if "access denied" in sample or "captcha" in sample:
                    print("      Blocked.")
                    break

                # builtin.com job card selectors
                cards = response.css("div[data-id='job-card']")
                if not cards:
                    cards = response.css("div[class*='job-bounded']")
                if not cards:
                    cards = response.css("div[id^='job-card-']")

                if not cards:
                    print("      No cards found.")
                    break

                print("      " + str(len(cards)) + " cards.")
                found_on_page = 0

                for card in cards:
                    try:
                        # Title: <a data-id="job-card-title">
                        title_el = _css_first(card, "a[data-id='job-card-title']")
                        title = _get_text(title_el)

                        # Company: <a data-id="company-title"> span
                        co_el = _css_first(card, "a[data-id='company-title']")
                        company = _get_text(_css_first(co_el, "span"))
                        if not company:
                            company = _get_text(co_el)

                        # Location: look for text after icon spans
                        loc = ""
                        for span in card.css("span"):
                            t = _get_text(span)
                            if t and any(w in t.lower() for w in ["remote", "hybrid", "onsite", ", "]):
                                if len(t) < 80 and not any(c.isdigit() for c in t[:3]):
                                    loc = t
                                    break

                        # URL
                        job_url = ""
                        if title_el:
                            href = _get_attr(title_el, "href")
                            if href.startswith("/"):
                                job_url = "https://builtin.com" + href
                            elif href.startswith("http"):
                                job_url = href

                        # Salary (not always present)
                        salary = _get_text(_css_first(card, "[class*='salary']"))

                        if not company or not title:
                            continue
                        if not is_relevant_job(title):
                            continue

                        key = company.lower() + "|" + title.lower()
                        if key in seen:
                            continue
                        seen.add(key)

                        jobs.append({
                            "company_name": company,
                            "job_title": title,
                            "job_url": job_url,
                            "job_location": loc,
                            "job_posted_date": "",
                            "job_description": "",
                            "salary": salary,
                            "source": "builtin",
                        })
                        found_on_page += 1

                    except Exception:
                        continue

                if found_on_page == 0:
                    break  # no new jobs on this page, stop paginating

            except Exception as e:
                print("      ERROR: " + str(e)[:100])
                break

            time.sleep(random.uniform(1.0, 2.5))

    return jobs


# ── SOURCE 3: INDEED ─────────────────────────────────────────────────────────

INDEED_LOCATIONS = [
    "United States",
    "United Kingdom",
    "Germany",
    "Netherlands",
    "France",
    "Ireland",
    "Switzerland",
    "Sweden",
]


def _indeed_url(query, location, start=0):
    q = quote_plus(query)
    l = quote_plus(location)
    return (
        "https://www.indeed.com/jobs"
        "?q=" + q + "&l=" + l + "&fromage=3&sort=date&start=" + str(start)
    )


def scrape_indeed(query, location, max_pages=2):
    from scrapling.fetchers import StealthyFetcher
    jobs = []

    for page in range(max_pages):
        start = page * 10
        url = _indeed_url(query, location, start)
        print("    Page " + str(page + 1) + ": " + url[:90] + "...")

        try:
            response = StealthyFetcher.fetch(url, headless=True, disable_resources=True)
            if response.status != 200:
                print("      HTTP " + str(response.status) + ", stopping.")
                break

            sample = (response.get_all_text() or "")[:3000].lower()
            if any(kw in sample for kw in [
                "verify you are human", "captcha", "access denied",
                "robot check", "unusual traffic",
            ]):
                print("      Blocked by Indeed. Stopping.")
                break

            cards = response.css("div.job_seen_beacon")
            if not cards:
                cards = response.css("div.tapItem")
            if not cards:
                cards = response.css("div[data-jk]")

            if not cards:
                print("      No cards found.")
                break

            print("      Found " + str(len(cards)) + " cards.")

            for card in cards:
                try:
                    title = _get_attr(_css_first(card, "h2.jobTitle span[title]"), "title")
                    if not title:
                        title = _get_text(_css_first(card, "h2.jobTitle span"))
                    if not title:
                        title = _get_text(_css_first(card, "h2.jobTitle"))

                    company = _get_text(_css_first(card, "span.companyName"))
                    if not company:
                        company = _get_text(_css_first(card, "[data-testid='company-name']"))

                    loc = _get_text(_css_first(card, "div.companyLocation"))
                    if not loc:
                        loc = _get_text(_css_first(card, "[data-testid='text-location']"))

                    job_url = ""
                    link = (_css_first(card, "h2.jobTitle a")
                            or _css_first(card, "a.jcs-JobTitle")
                            or _css_first(card, "a[data-jk]"))
                    if link:
                        href = _get_attr(link, "href")
                        if href.startswith("/"):
                            job_url = "https://www.indeed.com" + href.split("?")[0]
                        elif href.startswith("http"):
                            job_url = href.split("?")[0]

                    salary = _get_text(_css_first(card, ".salary-snippet-container"))

                    if company and title and is_relevant_job(title):
                        jobs.append({
                            "company_name": company,
                            "job_title": title,
                            "job_url": job_url,
                            "job_location": loc or location,
                            "job_posted_date": "",
                            "job_description": "",
                            "salary": salary,
                            "source": "indeed",
                        })

                except Exception:
                    continue

        except Exception as e:
            print("      ERROR: " + str(e)[:100])

        human_delay()

    return jobs


# ── MAIN ─────────────────────────────────────────────────────────────────────

def run_alt_scraper(use_hn=True, use_builtin=True, use_indeed=True):
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    print("")
    print("=" * 60)
    print("  ALT SCRAPER: HN Hiring + builtin.com + Indeed (parallel)")
    print("=" * 60)
    print("")

    existing_companies = get_existing_companies()
    print("Companies already in DB (will skip): " + str(len(existing_companies)))
    print("")

    total_new = 0
    total_skip = 0
    source_counts = {}
    _lock = threading.Lock()

    def _save(jobs):
        """Thread-safe: insert jobs immediately as each source finishes."""
        nonlocal total_new, total_skip
        for job in jobs:
            company = _clean_company(job["company_name"])
            if not company:
                continue
            with _lock:
                if company.lower() in existing_companies:
                    total_skip += 1
                    continue
            inserted = insert_lead(
                company_name=company,
                job_title=job["job_title"],
                job_description=job.get("job_description", ""),
                job_url=job.get("job_url", ""),
                job_location=job.get("job_location", ""),
                job_posted_date=job.get("job_posted_date", ""),
                salary=job.get("salary", ""),
            )
            with _lock:
                if inserted:
                    total_new += 1
                    existing_companies.add(company.lower())
                    src = job.get("source", "unknown")
                    source_counts[src] = source_counts.get(src, 0) + 1
                    msg = "  + " + company + " -- " + job["job_title"]
                    if job.get("job_location"):
                        msg += " (" + job["job_location"][:40] + ")"
                    if job.get("salary"):
                        msg += " [" + job["salary"] + "]"
                    print(msg)
                else:
                    total_skip += 1

    def _run_hn():
        print("[HN  ] Starting...")
        jobs = scrape_hn_hiring()
        _save(jobs)
        print("[HN  ] Done — " + str(len(jobs)) + " found")
        return "hn_hiring", len(jobs)

    def _run_builtin():
        print("[BLT ] Starting...")
        jobs = scrape_builtin()
        _save(jobs)
        print("[BLT ] Done — " + str(len(jobs)) + " found")
        return "builtin", len(jobs)

    def _run_indeed():
        print("[INDX] Starting...")
        queries = SEARCH_QUERIES[:5]
        locations = INDEED_LOCATIONS[:4]
        combos = [(q, loc) for q in queries for loc in locations]
        random.shuffle(combos)
        all_indeed = []
        for i, (query, loc) in enumerate(combos):
            idx = str(i + 1) + "/" + str(len(combos))
            print("[INDX] [" + idx + "] " + query + " in " + loc)
            jobs = scrape_indeed(query, loc)
            _save(jobs)
            all_indeed.extend(jobs)
            if i < len(combos) - 1:
                wait = random.uniform(8, 14)
                print("[INDX] Waiting " + str(int(wait)) + "s...")
                time.sleep(wait)
        print("[INDX] Done — " + str(len(all_indeed)) + " found")
        return "indeed", len(all_indeed)

    # Run all enabled sources in parallel
    tasks = []
    if use_hn:
        tasks.append(_run_hn)
    if use_builtin:
        tasks.append(_run_builtin)
    if use_indeed:
        tasks.append(_run_indeed)

    print("Running " + str(len(tasks)) + " source(s) in parallel...")
    print("")

    try:
        with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
            futures = [pool.submit(fn) for fn in tasks]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print("  Source error: " + str(e)[:80])
    except KeyboardInterrupt:
        print("")
        print("Stopped by user. All leads saved so far have been written to DB.")

    print("")
    print("=" * 60)
    print("  DONE: " + str(total_new) + " new, " + str(total_skip) + " skipped")
    for src, cnt in sorted(source_counts.items()):
        print("    " + src + ": " + str(cnt) + " new leads")
    print("=" * 60)

    get_stats()
    return total_new


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if "--hn-only" in args:
        run_alt_scraper(use_hn=True, use_builtin=False, use_indeed=False)
    elif "--builtin-only" in args:
        run_alt_scraper(use_hn=False, use_builtin=True, use_indeed=False)
    elif "--indeed-only" in args:
        run_alt_scraper(use_hn=False, use_builtin=False, use_indeed=True)
    else:
        run_alt_scraper()
