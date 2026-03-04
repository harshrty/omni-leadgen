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
    print("=" * 60)
    print("  DRAFTED EMAILS (" + str(len(drafts)) + " total)")
    print("=" * 60)
    for i, lead in enumerate(drafts, 1):
        print("")
        print("--- Lead #" + str(i) + " (ID: " + str(lead["id"]) + ") ---")
        print("Company:  " + str(lead["company_name"]))
        print("Job:      " + str(lead["job_title"]))
        print("Location: " + str(lead.get("job_location", "")))
        ci = str(lead["contact_name"]) + " (" + str(lead["contact_title"]) + ")"
        print("Contact:  " + ci)
        print("Email:    " + str(lead["contact_email"]))
        print("LinkedIn: " + str(lead.get("linkedin_url", "")))
        print("")
        print("Subject:  " + str(lead["draft_subject"]))
        print("")
        print(str(lead["draft_email"]))
        print("")
        print("LinkedIn Note: " + str(lead.get("draft_linkedin_note", "")))
        print("_" * 60)


def export_to_csv():
    leads = get_all_leads()
    if not leads:
        print("No leads to export.")
        return
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(script_dir, "leads_export.csv")
    fieldnames = [
        "id", "company_name", "job_title", "job_location",
        "contact_name", "contact_title", "contact_email",
        "linkedin_url", "draft_subject", "draft_email",
        "draft_linkedin_note", "status", "created_at",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for lead in leads:
            writer.writerow(lead)
    print("Exported " + str(len(leads)) + " leads to: " + out_path)


def run_full_pipeline():
    print("=" * 50)
    print("  OMNITHRIVE LEAD GENERATION PIPELINE")
    print("=" * 50)
    run_scraper()
    run_enricher()
    run_drafter()
    print("")
    print("=" * 50)
    print("  PIPELINE COMPLETE")
    print("=" * 50)
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