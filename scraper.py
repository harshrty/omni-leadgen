"""
LinkedIn Job Scraper using Scrapling StealthyFetcher.

Targets LinkedIn PUBLIC job search pages (no login required).
Uses stealth browser fingerprinting to bypass bot detection.
"""
import random
import time
from urllib.parse import quote_plus

from config import (
    SEARCH_QUERIES, SEARCH_LOCATION, MAX_PAGES_PER_QUERY,
    MIN_DELAY, MAX_DELAY, MAX_LEADS_PER_RUN,
)
from db import insert_lead, get_stats


def human_delay(min_s=None, max_s=None):
    min_s = min_s or MIN_DELAY
    max_s = max_s or MAX_DELAY
    delay = random.uniform(min_s, max_s)
    time.sleep(delay)


def build_linkedin_url(query, location="", start=0):
    base = "https://www.linkedin.com/jobs/search/"
    q = quote_plus(query)
    url = base + "?keywords=" + q + "&position=1&pageNum=0&start=" + str(start)
    if location:
        url += "&location=" + quote_plus(location)
    return url


def css_first(element, selector):
    """Safely get the first match from a CSS selector, or None."""
    results = element.css(selector)
    if results and len(results) > 0:
        return results[0]
    return None


def get_text(element, selector):
    """Get stripped text from the first match of a CSS selector."""
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
    """Get an attribute from the first match of a CSS selector."""
    el = css_first(element, selector)
    if el is not None:
        try:
            return el.attrib.get(attr, "")
        except Exception:
            pass
    return ""


def scrape_linkedin_jobs(query, location=""):
    from scrapling.fetchers import StealthyFetcher

    jobs = []

    for page in range(MAX_PAGES_PER_QUERY):
        start = page * 25
        url = build_linkedin_url(query, location, start)
        print("  Page " + str(page + 1) + ": " + url[:80] + "...")

        try:
            response = StealthyFetcher.fetch(
                url,
                headless=True,
                disable_resources=True,
            )

            if response.status != 200:
                print("    Got status " + str(response.status) + ", skipping.")
                human_delay()
                continue

            # Get all job cards
            job_cards = response.css("div.base-card")
            if not job_cards:
                job_cards = response.css("div.job-search-card")

            if not job_cards:
                print("    No job cards found.")
                break

            print("    Found " + str(len(job_cards)) + " job cards.")

            for card in job_cards:
                try:
                    # Company name: inside h4 > a.hidden-nested-link
                    company = get_text(card, "a.hidden-nested-link")
                    if not company:
                        company = get_text(card, "h4.base-search-card__subtitle")
                    if not company:
                        company = get_text(card, ".base-search-card__subtitle")

                    # Job title: inside h3.base-search-card__title
                    title = get_text(card, "h3.base-search-card__title")
                    if not title:
                        title = get_text(card, "h3")

                    # Job URL: from the main link
                    job_url = get_attr(card, "a.base-card__full-link", "href")
                    if not job_url:
                        job_url = get_attr(card, "a", "href")

                    # Location
                    job_loc = get_text(card, "span.job-search-card__location")
                    if not job_loc:
                        job_loc = get_text(card, ".base-search-card__metadata")

                    if company and title:
                        jobs.append({
                            "company_name": company,
                            "job_title": title,
                            "job_url": job_url,
                            "job_location": job_loc,
                            "job_description": "",
                        })
                except Exception:
                    continue

        except Exception as e:
            print("    ERROR fetching page: " + str(e))

        human_delay()

    return jobs


def run_scraper():
    print("")
    print("=" * 50)
    print("  SCRAPER: Finding companies hiring for AI roles")
    print("=" * 50)
    print("")

    queries = SEARCH_QUERIES.copy()
    random.shuffle(queries)

    total_new = 0
    total_skip = 0

    for i, query in enumerate(queries):
        idx = str(i + 1) + "/" + str(len(queries))
        print("[" + idx + "] Searching: " + query)
        print("-" * 40)

        jobs = scrape_linkedin_jobs(query, SEARCH_LOCATION)

        for job in jobs:
            inserted = insert_lead(
                company_name=job["company_name"],
                job_title=job["job_title"],
                job_description=job["job_description"],
                job_url=job["job_url"],
                job_location=job["job_location"],
            )
            if inserted:
                total_new += 1
                print("  + NEW: " + job["company_name"] + " -- " + job["job_title"])
            else:
                total_skip += 1

        if total_new >= MAX_LEADS_PER_RUN:
            print("Hit max leads limit. Stopping.")
            break

        if i < len(queries) - 1:
            wait = random.uniform(8, 15)
            print("  Waiting " + str(int(wait)) + "s before next query...")
            time.sleep(wait)

    print("Scraper done: " + str(total_new) + " new, " + str(total_skip) + " skipped")
    get_stats()
    return total_new


if __name__ == "__main__":
    run_scraper()