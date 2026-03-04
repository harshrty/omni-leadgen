"""
Omnithrive Lead Generation Pipeline.

Usage:
  python run.py              Full pipeline (scrape + enrich + draft)
  python run.py scrape       Scrape LinkedIn jobs only
  python run.py enrich       Find websites + decision makers
  python run.py draft        Draft emails only
  python run.py stats        Pipeline statistics
  python run.py review       Review all drafted emails
  python run.py export       Export all leads to CSV
"""
import sys
import csv
import os
from db import get_stats, get_leads_by_status, get_all_leads
from scraper import run_scraper
from enricher import run_enricher
from drafter import run_drafter


def review_drafts():
    drafts = get_leads_by_status("drafted")
    if not drafts:
        print("No drafted emails to review.")
        return
    print("")
    print("=" * 70)
    print("  DRAFTED EMAILS (" + str(len(drafts)) + " total)")
    print("=" * 70)
    for i, lead in enumerate(drafts, 1):
        print("")
        print("--- Lead #" + str(i) + " (ID: " + str(lead["id"]) + ") ---")
        print("Company:    " + str(lead["company_name"]))
        print("Website:    " + str(lead.get("company_website", "")))
        print("Job:        " + str(lead["job_title"]))
        print("Location:   " + str(lead.get("job_location", "")))
        print("Posted:     " + str(lead.get("job_posted_date", "")))
        dm = str(lead.get("decision_maker_name", ""))
        dt = str(lead.get("decision_maker_title", ""))
        print("Contact:    " + dm + " (" + dt + ")")
        print("Email:      " + str(lead.get("decision_maker_email", "")))
        print("LinkedIn:   " + str(lead.get("decision_maker_linkedin", "")))
        ce = str(lead.get("company_contact_email", ""))
        if ce:
            print("Co. Emails: " + ce)
        cp = str(lead.get("company_phone", ""))
        if cp:
            print("Co. Phone:  " + cp)
        print("")
        print("Subject:    " + str(lead.get("draft_subject", "")))
        print("")
        print(str(lead.get("draft_email", "")))
        print("")
        ln = str(lead.get("draft_linkedin_note", ""))
        if ln:
            print("LinkedIn Note: " + ln)
        print("_" * 70)


def export_to_csv():
    leads = get_all_leads()
    if not leads:
        print("No leads to export.")
        return

    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(script_dir, "leads_export.csv")
    fieldnames = [
        "id", "company_name", "company_website", "company_contact_email",
        "company_phone", "job_title", "job_description", "job_url",
        "job_location", "job_posted_date",
        "decision_maker_name", "decision_maker_title",
        "decision_maker_email", "decision_maker_linkedin",
        "draft_subject", "draft_email", "draft_linkedin_note",
        "status", "created_at",
    ]

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for lead in leads:
            writer.writerow(lead)

    print("Exported " + str(len(leads)) + " leads to: " + out_path)


def run_full_pipeline():
    print("=" * 60)
    print("  OMNITHRIVE LEAD GENERATION PIPELINE v2")
    print("  USA + Europe | AI Roles | Past 72 Hours")
    print("=" * 60)

    # Phase 1: Scrape LinkedIn for AI jobs
    run_scraper()

    # Phase 2: Find websites + decision makers
    run_enricher()

    # Phase 3: Draft personalized emails
    run_drafter()

    print("")
    print("=" * 60)
    print("  PIPELINE COMPLETE")
    print("=" * 60)
    get_stats()
    print("Next steps:")
    print("  python run.py review   - See drafted emails")
    print("  python run.py export   - Export leads to CSV")
    print("")


COMMANDS = {
    "scrape": run_scraper,
    "enrich": run_enricher,
    "draft": run_drafter,
    "stats": get_stats,
    "review": review_drafts,
    "export": export_to_csv,
}

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd in COMMANDS:
            COMMANDS[cmd]()
        else:
            print("Unknown command: " + cmd)
            print("Available: " + ", ".join(COMMANDS.keys()))
    else:
        run_full_pipeline()