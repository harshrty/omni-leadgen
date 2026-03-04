"""
LinkedIn Job Scraper - USA + Europe, past 72 hours only.
Uses Scrapling StealthyFetcher for anti-detection.
Pulls full job descriptions from detail pages.
"""
import random
import time
from urllib.parse import quote_plus

from config import (
    SEARCH_QUERIES, SEARCH_LOCATIONS, TIME_FILTER,
    MAX_PAGES_PER_QUERY, MIN_DELAY, MAX_DELAY, MAX_LEADS_PER_RUN,
)
from db import insert_lead, get_stats


def human_delay(min_s=None, max_s=None):
    min_s = min_s or MIN_DELAY
    max_s = max_s or MAX_DELAY
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


def scrape_job_description(job_url):
    """Fetch the full job description from a LinkedIn job detail page."""
    if not job_url:
        return ""

    from scrapling.fetchers import StealthyFetcher

    try:
        response = StealthyFetcher.fetch(
            job_url,
            headless=True,
            disable_resources=True,
        )

        if response.status != 200:
            return ""

        # Try multiple selectors for job description
        for selector in [
            "div.show-more-less-html__markup",
            "div.description__text",
            "section.description",
            "div.decorated-job-posting__details",
        ]:
            text = get_text(response, selector)
            if text and len(text) > 50:
                # Return first 1500 chars for LLM context
                return text[:1500]

        return ""

    except Exception as e:
        print("      Desc fetch error: " + str(e)[:80])
        return ""


def scrape_linkedin_jobs(query, location):
    """Scrape LinkedIn public job listings for a query+location combo."""
    from scrapling.fetchers import StealthyFetcher

    jobs = []

    for page in range(MAX_PAGES_PER_QUERY):
        start = page * 25
        url = build_linkedin_url(query, location, start, TIME_FILTER)
        print("    Page " + str(page + 1) + ": " + url[:90] + "...")

        try:
            response = StealthyFetcher.fetch(
                url,
                headless=True,
                disable_resources=True,
            )

            if response.status != 200:
                print("      Got status " + str(response.status) + ", skipping.")
                human_delay()
                continue

            job_cards = response.css("div.base-card")
            if not job_cards:
                job_cards = response.css("div.job-search-card")

            if not job_cards:
                print("      No job cards found.")
                break

            print("      Found " + str(len(job_cards)) + " cards.")

            for card in job_cards:
                try:
                    company = get_text(card, "a.hidden-nested-link")
                    if not company:
                        company = get_text(card, "h4.base-search-card__subtitle")
                    if not company:
                        company = get_text(card, ".base-search-card__subtitle")

                    title = get_text(card, "h3.base-search-card__title")
                    if not title:
                        title = get_text(card, "h3")

                    job_url = get_attr(card, "a.base-card__full-link", "href")
                    if not job_url:
                        job_url = get_attr(card, "a", "href")

                    job_loc = get_text(card, "span.job-search-card__location")
                    if not job_loc:
                        job_loc = get_text(card, ".base-search-card__metadata")

                    # Get posted date from time element
                    posted = get_attr(card, "time", "datetime")

                    if company and title:
                        jobs.append({
                            "company_name": company,
                            "job_title": title,
                            "job_url": job_url,
                            "job_location": job_loc,
                            "job_posted_date": posted,
                            "job_description": "",
                        })
                except Exception:
                    continue

        except Exception as e:
            print("      ERROR: " + str(e)[:100])

        human_delay()

    return jobs


def run_scraper():
    print("")
    print("=" * 60)
    print("  SCRAPER: AI jobs in USA + Europe (past 72 hours)")
    print("=" * 60)
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

    total_new = 0
    total_skip = 0

    for i, (query, location) in enumerate(combos):
        idx = str(i + 1) + "/" + str(total_combos)
        print("[" + idx + "] " + query + " in " + location)
        print("-" * 50)

        jobs = scrape_linkedin_jobs(query, location)

        for job in jobs:
            inserted = insert_lead(
                company_name=job["company_name"],
                job_title=job["job_title"],
                job_description=job["job_description"],
                job_url=job["job_url"],
                job_location=job["job_location"],
                job_posted_date=job["job_posted_date"],
            )
            if inserted:
                total_new += 1
                msg = "  + " + job["company_name"] + " -- " + job["job_title"]
                if job["job_location"]:
                    msg += " (" + job["job_location"] + ")"
                print(msg)
            else:
                total_skip += 1

        if total_new >= MAX_LEADS_PER_RUN:
            print("Hit max leads limit (" + str(MAX_LEADS_PER_RUN) + "). Stopping.")
            break

        # Longer delay between different combos
        if i < len(combos) - 1:
            wait = random.uniform(6, 12)
            print("  Waiting " + str(int(wait)) + "s...")
            time.sleep(wait)

    print("")
    print("Scraping complete: " + str(total_new) + " new, " + str(total_skip) + " skipped")

    # Phase 2: Fetch job descriptions for new leads
    from db import get_leads_by_status, update_lead
    scraped = get_leads_by_status("scraped")
    leads_needing_desc = [l for l in scraped if not l.get("job_description")]

    if leads_needing_desc:
        print("")
        print("Fetching job descriptions for " + str(len(leads_needing_desc)) + " leads...")
        desc_count = 0
        # Limit to 50 descriptions per run to avoid detection
        for lead in leads_needing_desc[:50]:
            url = lead.get("job_url", "")
            if url:
                print("  Fetching desc: " + lead["company_name"] + "...", end="")
                desc = scrape_job_description(url)
                if desc:
                    update_lead(lead["id"], job_description=desc)
                    desc_count += 1
                    print(" OK (" + str(len(desc)) + " chars)")
                else:
                    print(" no description found")
                human_delay(3, 7)
        print("Got descriptions for " + str(desc_count) + " leads.")

    get_stats()
    return total_new


if __name__ == "__main__":
    run_scraper()