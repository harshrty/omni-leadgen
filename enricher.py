import requests
import time
from config import APOLLO_API_KEY, TARGET_TITLES, APOLLO_DELAY
from db import get_leads_by_status, update_lead, get_stats


def find_decision_maker(company_name):
    if not APOLLO_API_KEY:
        print("ERROR: APOLLO_API_KEY not set in .env")
        return None

    url = "https://api.apollo.io/api/v1/people/search"
    headers = {
        "Content-Type": "application/json",
        "X-Api-Key": APOLLO_API_KEY,
    }
    payload = {
        "q_organization_name": company_name,
        "person_titles": TARGET_TITLES,
        "page": 1,
        "per_page": 5,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        people = data.get("people", [])
        if not people:
            return None
        person = people[0]
        return {
            "contact_name": person.get("name", ""),
            "contact_title": person.get("title", ""),
            "contact_email": person.get("email", ""),
            "linkedin_url": person.get("linkedin_url", ""),
        }
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:
            print("    Rate limited by Apollo. Waiting 60s...")
            time.sleep(60)
            return find_decision_maker(company_name)
        print("    ERROR: Apollo API error: " + str(e))
        # Print response body for debugging
        try:
            print("    Response: " + e.response.text[:200])
        except Exception:
            pass
        return None
    except requests.exceptions.RequestException as e:
        print("    ERROR: Request failed: " + str(e))
        return None


def run_enricher():
    print("")
    print("=" * 50)
    print("  ENRICHER: Finding decision-makers")
    print("=" * 50)

    leads = get_leads_by_status("scraped")
    if not leads:
        print("No scraped leads to enrich.")
        return 0

    print("Found " + str(len(leads)) + " leads to enrich.")
    enriched = 0
    no_match = 0

    for lead in leads:
        company = lead["company_name"]
        print("  Looking up: " + company + "...")
        contact = find_decision_maker(company)
        if contact and contact["contact_email"]:
            update_lead(
                lead["id"],
                contact_name=contact["contact_name"],
                contact_title=contact["contact_title"],
                contact_email=contact["contact_email"],
                linkedin_url=contact["linkedin_url"],
                status="enriched",
            )
            enriched += 1
            msg = "    FOUND: " + contact["contact_name"] + " (" + contact["contact_title"] + ") - " + contact["contact_email"]
            print(msg)
        else:
            update_lead(lead["id"], status="no_match")
            no_match += 1
            print("    No decision-maker found.")
        time.sleep(APOLLO_DELAY)

    print("Enricher done: " + str(enriched) + " enriched, " + str(no_match) + " no match.")
    get_stats()
    return enriched


if __name__ == "__main__":
    run_enricher()