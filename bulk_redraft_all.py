"""
Bulk Redraft All Leads
----------------------
Redrafts emails for leads that HAVE an email address and have NOT been sent yet.

Usage:
    python bulk_redraft_all.py           # redraft all unsent leads with email
    python bulk_redraft_all.py --skip    # skip leads already drafted without cal.com link
"""
import sys
import time
import anthropic
from config import ANTHROPIC_API_KEY
from db import get_all_leads, update_lead
from draft_emails import generate_email

SKIP_CLEAN = "--skip" in sys.argv


def run():
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set in .env")
        return

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    leads = get_all_leads()

    # Only leads with an email address, not yet sent
    candidates = [
        l for l in leads
        if (l.get("decision_maker_email") or "").strip()
        and (l.get("status") or "scraped") not in ("sent", "opened", "replied")
    ]

    if SKIP_CLEAN:
        # Skip leads that are already drafted AND don't have the cal.com link
        to_redraft = [
            l for l in candidates
            if "cal.com" in (l.get("draft_email") or "")
            or not (l.get("draft_email") or "").strip()
        ]
        skipped = len(candidates) - len(to_redraft)
        print(f"--skip mode: skipping {skipped} already-clean leads\n")
    else:
        to_redraft = candidates

    total = len(to_redraft)
    if not total:
        print("No leads to redraft.")
        return

    print(f"Redrafting {total} leads (only those with email addresses)...\n")
    done = 0
    failed = 0

    for i, lead in enumerate(to_redraft):
        company = lead.get("company_name", "")
        dm_name = (lead.get("decision_maker_name") or "").strip()
        email = lead.get("decision_maker_email", "")
        has_cal = "cal.com" in (lead.get("draft_email") or "")
        prefix = f"[{i+1}/{total}] {company} <{email}>"
        if has_cal:
            prefix += " [HAS CAL LINK - redrafting]"

        try:
            subject, body = generate_email(client, lead)
            if subject and body:
                update_lead(lead["id"], draft_subject=subject, draft_email=body, status="drafted")
                done += 1
                dm_label = f" -> {dm_name}" if dm_name else " -> (no DM name)"
                print(f"{prefix}{dm_label} -> OK")
            else:
                failed += 1
                print(f"{prefix} FAILED (empty AI response)")
        except Exception as e:
            failed += 1
            print(f"{prefix} ERROR: {str(e)[:80]}")

        time.sleep(0.4)

    print(f"\nDone. Redrafted: {done} | Failed: {failed}")


if __name__ == "__main__":
    run()
