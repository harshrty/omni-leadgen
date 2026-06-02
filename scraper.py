"""
LinkedIn Job Scraper - USA + Europe, past 72 hours only.

Two modes:
  - Logged-in  (recommended): set LINKEDIN_EMAIL + LINKEDIN_PASS in .env
    Uses a real LinkedIn session via Playwright. More data, fewer blocks.
  - Anonymous fallback: uses Scrapling StealthyFetcher (no credentials needed).
"""
import random
import re
import time
from urllib.parse import quote_plus

from config import (
    SEARCH_QUERIES, SEARCH_LOCATIONS, TIME_FILTER,
    MAX_PAGES_PER_QUERY, MIN_DELAY, MAX_DELAY, MAX_LEADS_PER_RUN,
    MAX_DESC_PER_RUN,
    LINKEDIN_EMAIL, LINKEDIN_PASS,
)
from db import insert_lead, get_stats, get_existing_companies

# Pre-warm scrapling's lazy imports before any threads start.
# scrapling.fetchers uses lazy imports — concurrent first-access from threads
# races the curl_cffi C-extension init and crashes with "No module named 'curl_cffi'".
try:
    from scrapling.fetchers import StealthyFetcher as _StealthyFetcher  # noqa: F401
    del _StealthyFetcher
except Exception:
    pass


# ---------------------------------------------------------------------------
#  JOB RELEVANCE FILTER
# ---------------------------------------------------------------------------
_JAVA_RE = re.compile(r'\bjava\b', re.IGNORECASE)

# Job title must match at least one of these (word-boundary regex to avoid
# false positives like "spain" matching "ai" or "email" matching "ml")
_AI_TITLE_PATTERNS = re.compile(
    r'\b('
    r'ai|a\.i\.|artificial intelligence'
    r'|machine learning|ml engineer|ml researcher'
    r'|deep learning|nlp|natural language'
    r'|computer vision|llm|large language'
    r'|genai|generative ai|gen ai'
    r'|neural|mlops|llmops|agentic'
    r'|data scientist|data science'
    r'|prompt engineer|ai research'
    r')\b',
    re.IGNORECASE,
)


def is_relevant_job(title):
    """
    Return True only if the job title is genuinely AI/ML related
    AND does not reference Java (the language).
    Uses word-boundary matching to avoid false positives like 'spain' → 'ai'.
    Also rejects titles that are too long (likely scraped descriptions, not titles).
    """
    if not title or len(title) > 120:
        return False
    t = title.lower()
    # Hard-drop Java developer / Java engineer roles
    # But do NOT drop roles that mention JavaScript (a valid AI stack skill)
    if _JAVA_RE.search(t) and "javascript" not in t:
        return False
    return bool(_AI_TITLE_PATTERNS.search(title))


def human_delay(min_s=None, max_s=None):
    min_s = min_s if min_s is not None else MIN_DELAY
    max_s = max_s if max_s is not None else MAX_DELAY
    time.sleep(random.uniform(min_s, max_s))


def build_linkedin_url(query, location="", start=0, time_filter=""):
    base = "https://www.linkedin.com/jobs/search/"
    q = quote_plus(query)
    url = base + "?keywords=" + q + "&position=1&pageNum=0&start=" + str(start)
    if location:
        url += "&location=" + quote_plus(location)
    if time_filter:
        url += "&f_TPR=" + time_filter
    return url


def css_first(element, selector):
    results = element.css(selector)
    if results and len(results) > 0:
        return results[0]
    return None


def get_text(element, selector):
    el = css_first(element, selector)
    if el is not None:
        try:
            t = el.text
            if t:
                return t.strip()
        except Exception:
            pass
    return ""


def get_attr(element, selector, attr):
    el = css_first(element, selector)
    if el is not None:
        try:
            return el.attrib.get(attr, "")
        except Exception:
            pass
    return ""


def extract_salary_from_text(text):
    """Extract salary/compensation info from job description text."""
    if not text:
        return ""

    patterns = [
        # up to $150K / up to £80,000
        r'up\s+to\s+[\$£€][\d,]+[kK]?',
        # $120,000 - $180,000 / $120K - $180K
        r'[\$£€][\d,]+[kK]?\s*[-–to]+\s*[\$£€][\d,]+[kK]?\s*(?:per\s+(?:year|annum|hr|hour))?',
        # between $120k and $180k
        r'between\s+[\$£€][\d,]+[kK]?\s+and\s+[\$£€][\d,]+[kK]?',
        # $120,000/year or $120K/yr
        r'[\$£€][\d,]+[kK]?\s*/?\s*(?:year|yr|annum|annually|per\s+year|per\s+annum|hour|hr|per\s+hour)',
        # salary/compensation: $120K - $180K
        r'(?:salary|compensation|pay|range|base|OTE)[:\s]*[\$£€][\d,]+[kK]?\s*[-–to]+\s*[\$£€][\d,]+[kK]?',
        # 120k-150k (no currency, with k)
        r'\b\d{2,3}[kK]\s*[-–]\s*\d{2,3}[kK]\b',
        # 120,000 - 180,000 USD/EUR/GBP/CHF
        r'[\d,]+[kK]?\s*[-–to]+\s*[\d,]+[kK]?\s*(?:USD|EUR|GBP|CHF)',
        # standalone $150K or £80,000
        r'[\$£€][\d,]+[kK]?\b',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            salary = match.group(0).strip()
            salary = re.sub(r'\s+', ' ', salary)
            return salary

    return ""


def _parse_html(html: str, url: str = ""):
    """Wrap raw HTML string in a Scrapling Adaptor for CSS selector use."""
    from scrapling.parser import Adaptor
    return Adaptor(html, url=url, auto_match=False)


def scrape_job_description(job_url, session=None):
    """Fetch the full job description from a LinkedIn job detail page."""
    if not job_url:
        return ""

    try:
        if session:
            html = session.fetch(job_url, wait_ms=3000)
            if not html:
                return ""
            response = _parse_html(html, job_url)
        else:
            from scrapling.fetchers import StealthyFetcher
            response = StealthyFetcher.fetch(
                job_url,
                headless=True,
                disable_resources=False,
            )
            if response.status != 200:
                return ""

        # Try multiple selectors for job description
        for selector in [
            "div.show-more-less-html__markup",
            "div.description__text",
            "section.description",
            "div.decorated-job-posting__details",
            "article.jobs-description__container",
            "div.jobs-description-content__text",
            "div.jobs-box__html-content",
        ]:
            text = get_text(response, selector)
            if text and len(text) > 50:
                return text[:1500]

        # Fallback: grab all visible text and look for description-like content
        try:
            full_text = response.get_all_text() or ""
            if len(full_text) > 200:
                # Extract middle portion (skip nav/header, stop before footer)
                lines = full_text.split("\n")
                content_lines = []
                started = False
                for line in lines:
                    line = line.strip()
                    if not line or len(line) < 10:
                        continue
                    # Start capturing after job title indicators
                    lower = line.lower()
                    if any(w in lower for w in ["about the role", "about this role",
                            "job description", "what you'll do", "responsibilities",
                            "about the job", "the role", "overview",
                            "what we're looking for", "requirements"]):
                        started = True
                    if started:
                        content_lines.append(line)
                    if len(content_lines) > 30:
                        break
                if content_lines:
                    return "\n".join(content_lines)[:1500]
        except Exception:
            pass

        return ""

    except Exception as e:
        print("      Desc fetch error: " + str(e)[:80])
        return ""


def scrape_linkedin_jobs(query, location, session=None):
    """
    Generator: yields one job dict per relevant card found across all pages.
    Yields immediately so callers can save each job to DB as it arrives —
    stopping mid-run won't lose already-yielded jobs.
    """
    for page in range(MAX_PAGES_PER_QUERY):
        start = page * 25
        url = build_linkedin_url(query, location, start, TIME_FILTER)
        print("    Page " + str(page + 1) + ": " + url[:90] + "...")

        try:
            if session:
                html = session.fetch(url, wait_ms=3000)
                if not html:
                    print("      Empty response, skipping.")
                    human_delay()
                    continue
                response = _parse_html(html, url)
            else:
                from scrapling.fetchers import StealthyFetcher
                response = StealthyFetcher.fetch(url, headless=True, disable_resources=True)
                if response.status != 200:
                    print("      Got status " + str(response.status) + ", skipping.")
                    human_delay()
                    continue
                # Detect CAPTCHA / authwall (LinkedIn returns 200 for these)
                page_text = response.get_all_text() or ""
                if any(kw in page_text[:2000].lower() for kw in ["join now to see", "sign in to view", "authwall", "verify you're human"]):
                    print("      Blocked by LinkedIn (authwall/CAPTCHA). Skipping.")
                    human_delay()
                    continue

            # Logged-in LinkedIn uses different card selectors than public view
            job_cards = response.css("li.jobs-search-results__list-item")
            if not job_cards:
                job_cards = response.css("li[data-occludable-job-id]")
            if not job_cards:
                job_cards = response.css("li.scaffold-layout__list-item")
            if not job_cards:
                job_cards = response.css("div.base-card")
            if not job_cards:
                job_cards = response.css("div.job-search-card")

            if not job_cards:
                print("      No job cards found.")
                continue  # try next page — LinkedIn sometimes returns empty mid-pagination

            print("      Found " + str(len(job_cards)) + " cards.")

            for card in job_cards:
                try:
                    # Company — logged-in view uses artdeco entity lockup
                    company = get_text(card, ".artdeco-entity-lockup__subtitle span")
                    if not company:
                        company = get_text(card, ".job-card-container__company-name")
                    if not company:
                        company = get_text(card, "a.hidden-nested-link")
                    if not company:
                        company = get_text(card, "h4.base-search-card__subtitle")
                    if not company:
                        company = get_text(card, ".base-search-card__subtitle")

                    # Title — logged-in view uses job-card-list__title--link
                    title = get_attr(card, "a.job-card-list__title--link", "aria-label")
                    if not title:
                        title = get_text(card, "a.job-card-list__title--link strong")
                    if not title:
                        title = get_text(card, "a.job-card-list__title--link")
                    if not title:
                        title = get_text(card, ".job-card-list__title")
                    if not title:
                        title = get_text(card, "h3.base-search-card__title")
                    if not title:
                        title = get_text(card, "h3")

                    # URL — logged-in anchor has relative href, make absolute
                    job_url = get_attr(card, "a.job-card-list__title--link", "href")
                    if not job_url:
                        job_url = get_attr(card, "a.job-card-list__title", "href")
                    if not job_url:
                        job_url = get_attr(card, "a.base-card__full-link", "href")
                    if not job_url:
                        job_url = get_attr(card, "a", "href")
                    # Make relative URLs absolute, strip tracking params
                    if job_url and job_url.startswith("/"):
                        job_url = "https://www.linkedin.com" + job_url
                    if job_url and "?" in job_url:
                        job_url = job_url.split("?")[0]

                    # Location
                    job_loc = get_text(card, "ul.job-card-container__metadata-wrapper li span")
                    if not job_loc:
                        job_loc = get_text(card, ".job-card-container__metadata-item")
                    if not job_loc:
                        job_loc = get_text(card, "span.job-search-card__location")
                    if not job_loc:
                        job_loc = get_text(card, ".base-search-card__metadata")

                    # Posted date
                    posted = get_attr(card, "time", "datetime")

                    # Salary
                    salary = get_text(card, ".job-card-container__salary-info")
                    if not salary:
                        salary = get_text(card, "span.job-search-card__salary-info")
                    if not salary:
                        salary = get_text(card, ".base-search-card__salary")

                    if company and title and is_relevant_job(title):
                        yield {
                            "company_name": company,
                            "job_title": title,
                            "job_url": job_url,
                            "job_location": job_loc,
                            "job_posted_date": posted,
                            "job_description": "",
                            "salary": salary,
                        }
                except Exception:
                    continue

        except Exception as e:
            print("      ERROR: " + str(e)[:100])

        human_delay()


def run_scraper(force_anon=True):
    print("")
    print("=" * 60)
    print("  SCRAPER: AI jobs in USA + Europe (past 72 hours)")
    print("=" * 60)
    print("")

    # --- Session setup ---
    # Anonymous by default. Pass --login flag to use LinkedIn credentials.
    use_session = bool(LINKEDIN_EMAIL and LINKEDIN_PASS) and not force_anon
    if use_session:
        from linkedin_session import ensure_session, LinkedInSession
        ok = ensure_session(LINKEDIN_EMAIL, LINKEDIN_PASS)
        if not ok:
            print("  ⚠ LinkedIn login failed. Falling back to anonymous mode.")
            use_session = False
        else:
            print("  Mode: Logged-in (LinkedIn session active)")
    if not use_session:
        print("  Mode: Anonymous web scraping (no LinkedIn login)")
    print("")

    # Build all query+location combos and shuffle
    combos = []
    for q in SEARCH_QUERIES:
        for loc in SEARCH_LOCATIONS:
            combos.append((q, loc))
    random.shuffle(combos)

    total_combos = len(combos)
    print("Total search combos: " + str(total_combos))
    print("(Will stop at " + str(MAX_LEADS_PER_RUN) + " leads or when done)")
    print("")

    existing_companies = get_existing_companies()
    print("Companies already in DB (will skip): " + str(len(existing_companies)))
    print("")

    total_new = 0
    total_skip = 0

    # Open ONE browser session for the entire run (if logged in)
    session_ctx = None
    session = None
    if use_session:
        try:
            session_ctx = LinkedInSession()
            session = session_ctx.__enter__()
        except Exception as e:
            print("  ⚠ Failed to open browser session: " + str(e)[:60])
            print("  Falling back to anonymous mode.")
            session_ctx = None
            session = None

    try:
        for i, (query, location) in enumerate(combos):
            idx = str(i + 1) + "/" + str(total_combos)
            print("[" + idx + "] " + query + " in " + location)
            print("-" * 50)

            # scrape_linkedin_jobs is a generator — each job is yielded and
            # inserted immediately, so stopping mid-run never loses saved leads.
            for job in scrape_linkedin_jobs(query, location, session=session):
                if job["company_name"].strip().lower() in existing_companies:
                    total_skip += 1
                    continue
                inserted = insert_lead(
                    company_name=job["company_name"],
                    job_title=job["job_title"],
                    job_description=job["job_description"],
                    job_url=job["job_url"],
                    job_location=job["job_location"],
                    job_posted_date=job["job_posted_date"],
                    salary=job.get("salary", ""),
                )
                if inserted:
                    total_new += 1
                    existing_companies.add(job["company_name"].strip().lower())
                    msg = "  + " + job["company_name"] + " -- " + job["job_title"]
                    if job["job_location"]:
                        msg += " (" + job["job_location"] + ")"
                    sal = job.get("salary", "")
                    if sal:
                        msg += " [" + sal + "]"
                    print(msg)
                else:
                    total_skip += 1

            if total_new >= MAX_LEADS_PER_RUN:
                print("Hit max leads limit (" + str(MAX_LEADS_PER_RUN) + "). Stopping.")
                break

            if i < len(combos) - 1:
                wait = random.uniform(3, 7)
                print("  Waiting " + str(int(wait)) + "s...")
                time.sleep(wait)

    except KeyboardInterrupt:
        print("")
        print("Stopped by user. All leads scraped so far have been saved to DB.")

    finally:
        if session_ctx:
            try:
                session_ctx.__exit__(None, None, None)
            except Exception:
                pass

    print("")
    print("Scraping complete: " + str(total_new) + " new, " + str(total_skip) + " skipped")

    # Phase 2: Fetch job descriptions (limited batch, sequential to avoid LinkedIn bans)
    from db import get_leads_by_status, update_lead
    scraped = get_leads_by_status("scraped")
    leads_needing_desc = [l for l in scraped if not l.get("job_description") and l.get("job_url")]

    if leads_needing_desc:
        batch = leads_needing_desc[:MAX_DESC_PER_RUN]
        remaining = len(leads_needing_desc) - len(batch)
        print("")
        print("Fetching job descriptions for " + str(len(batch)) + " leads"
              + (" (" + str(remaining) + " remaining for next run)" if remaining > 0 else "")
              + "...")
        desc_count = 0

        for lead in batch:
            desc = None
            for attempt in range(2):  # 1 retry on transient failure
                try:
                    desc = scrape_job_description(lead["job_url"])
                    break
                except Exception as e:
                    if attempt == 0:
                        time.sleep(3)
                    else:
                        print("  desc error: " + str(e)[:60])
            if desc:
                fields = {"job_description": desc}
                sal = ""
                if not (lead.get("salary") or "").strip():
                    sal = extract_salary_from_text(desc)
                if sal:
                    fields["salary"] = sal
                    print("  " + lead["company_name"] + ": OK (" + str(len(desc)) + " chars) [" + sal + "]")
                else:
                    print("  " + lead["company_name"] + ": OK (" + str(len(desc)) + " chars)")
                update_lead(lead["id"], **fields)
                desc_count += 1
            else:
                print("  " + lead["company_name"] + ": no description")
            time.sleep(random.uniform(2, 4))  # rate limit

        print("Got descriptions for " + str(desc_count) + " leads.")

    get_stats()
    return total_new


if __name__ == "__main__":
    import sys
    # Default: anonymous mode. Pass --login to use LinkedIn credentials.
    use_login = "--login" in sys.argv
    run_scraper(force_anon=not use_login)